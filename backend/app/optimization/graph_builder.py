import logging
import math
import time
from typing import List, Tuple, Dict, Optional, Set
from collections import defaultdict

import networkx as nx
import numpy as np

from ..models.schemas import DealerRecord, FTCRecord
from ..models.enums import DealerType
from ..data.processor import DataProcessor

logger = logging.getLogger(__name__)


class SpatialGridIndex:
    """
    Grid-based spatial index for efficient proximity queries at scale.
    Partitions the geographic space into grid cells of size `cell_size_km`
    and only checks edge candidates within the same or adjacent cells.

    For N dealers, this reduces edge candidate checks from O(N^2) to
    approximately O(N * avg_density_per_cell * 9 adjacent cells).

    At 5km proximity with grid cell size matching the proximity radius,
    each dealer checks ~9 cells * avg_dealers_per_cell candidates instead
    of all N dealers.
    """

    def __init__(self, cell_size_km: float):
        self.cell_size_km = cell_size_km
        self._km_per_deg_lat = 111.32
        self.grid: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        self.coords: List[Tuple[float, float]] = []
        self.dealer_ids: List[str] = []
        self.dealer_map: Dict[str, int] = {}

    def build(self, dealers: List[DealerRecord]):
        self.coords = [(d.Dealer_latitude, d.Dealer_longitude) for d in dealers]
        self.dealer_ids = [d.Dealer_id for d in dealers]
        self.dealer_map = {d.Dealer_id: i for i, d in enumerate(dealers)}
        self.grid.clear()

        for idx, d in enumerate(dealers):
            cell = self._latlon_to_cell(d.Dealer_latitude, d.Dealer_longitude)
            self.grid[cell].append(idx)

    def _latlon_to_cell(self, lat: float, lon: float) -> Tuple[int, int]:
        cell_deg = self.cell_size_km / self._km_per_deg_lat
        return (int(math.floor(lat / cell_deg)), int(math.floor(lon / cell_deg)))

    def get_neighbor_cells(
        self, cell: Tuple[int, int]
    ) -> List[Tuple[int, int]]:
        row, col = cell
        return [
            (row + dr, col + dc)
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
        ]

    def get_proximity_candidates(
        self, dealer_idx: int
    ) -> List[int]:
        lat, lon = self.coords[dealer_idx]
        cell = self._latlon_to_cell(lat, lon)
        candidates: Set[int] = set()
        for neighbor_cell in self.get_neighbor_cells(cell):
            for idx in self.grid.get(neighbor_cell, []):
                if idx != dealer_idx:
                    candidates.add(idx)
        return list(candidates)


class DealerGraphBuilder:
    """
    Constructs a weighted proximity graph from dealer location data.

    PHASE 1 of the optimization pipeline:
    - Nodes: Dealers with rich attribute profiles (importance, caseload, type)
    - Edges: Proximity relationships within configured radius (default 5km)
    - Edge weights: Inverse-distance attraction modulated by dealer importance

    Performance:
    - Uses grid-based spatial indexing to reduce edge building from O(N^2) to
      approximately O(N * K) where K is the average number of neighbors within
      the proximity radius.
    - Handles 100,000+ dealers with sub-minute graph construction on typical
      enterprise hardware.
    """

    def __init__(
        self,
        proximity_km: float = 5.0,
        min_edge_weight: float = 0.001,
        max_edges_per_node: int = 50,
        parallel_threshold: int = 5000,
    ):
        if proximity_km <= 0:
            raise ValueError(f"proximity_km must be positive, got {proximity_km}")
        self.proximity_km = proximity_km
        self.min_edge_weight = min_edge_weight
        self.max_edges_per_node = max_edges_per_node
        self.parallel_threshold = parallel_threshold
        self.processor = DataProcessor()
        self._stats: Dict[str, float] = {}

    @property
    def stats(self) -> Dict[str, float]:
        return dict(self._stats)

    def build(
        self,
        dealers: List[DealerRecord],
        ftcs: Optional[List[FTCRecord]] = None,
    ) -> nx.Graph:
        """
        Build the weighted dealer proximity graph.

        Args:
            dealers: List of DealerRecord objects with lat/lon coordinates.
            ftcs: Optional list of FTCRecords for computing FTC-level graph
                  attributes (capacity aggregates, etc.).

        Returns:
            nx.Graph with dealer nodes and proximity-weighted edges.

        Raises:
            ValueError: If dealers list is empty.
            RuntimeError: If graph construction fails unexpectedly.
        """
        if not dealers:
            raise ValueError("Cannot build graph: empty dealer list")

        start_time = time.perf_counter()
        logger.info(
            "Building dealer proximity graph: %d dealers, %.1f km radius",
            len(dealers),
            self.proximity_km,
        )

        try:
            G = nx.Graph()
            self._add_nodes(G, dealers)
            self._build_edges_optimized(G, dealers)
            self._attach_graph_metadata(G, dealers, ftcs)
        except Exception as e:
            logger.error("Graph construction failed: %s", str(e))
            raise RuntimeError(f"Graph construction failed: {e}") from e

        elapsed = time.perf_counter() - start_time
        self._stats["build_time_sec"] = elapsed
        self._stats["node_count"] = G.number_of_nodes()
        self._stats["edge_count"] = G.number_of_edges()
        self._stats["density"] = nx.density(G)

        logger.info(
            "Graph built: %d nodes, %d edges, density=%.6f in %.2fs",
            G.number_of_nodes(),
            G.number_of_edges(),
            nx.density(G),
            elapsed,
        )

        return G

    # ------------------------------------------------------------------
    # Node construction
    # ------------------------------------------------------------------

    def _add_nodes(self, G: nx.Graph, dealers: List[DealerRecord]):
        importance_map = {
            d.Dealer_id: self.processor.compute_dealer_importance(d)
            for d in dealers
        }

        for d in dealers:
            node_weight = self._compute_node_weight(d)
            G.add_node(
                d.Dealer_id,
                # Identity
                sm_id=d.SM_id,
                dealer_type=d.Dealer_type.value,
                product_group=d.Product_group.value,
                # Location
                latitude=d.Dealer_latitude,
                longitude=d.Dealer_longitude,
                # Business metrics
                avg_cases=d.Average_cases_per_day,
                disbursements=d.Count_BFL_disbursement,
                importance=importance_map.get(d.Dealer_id, 0.0),
                weight=node_weight,
                # Optimization state (set during pipeline)
                assigned_ftc=None,
                is_boundary=False,
                is_anchor=False,
                is_static=(d.Dealer_type == DealerType.STATIC),
            )

    @staticmethod
    def _compute_node_weight(dealer: DealerRecord) -> float:
        return (
            dealer.Average_cases_per_day * 0.50
            + dealer.Count_BFL_disbursement * 0.25
            + (0.25 if dealer.Dealer_type == DealerType.STATIC else 0.15)
        )

    # ------------------------------------------------------------------
    # Edge construction with spatial indexing
    # ------------------------------------------------------------------

    def _build_edges_optimized(
        self, G: nx.Graph, dealers: List[DealerRecord]
    ):
        """
        Build edges using grid-based spatial indexing for O(N*K) performance.

        For each dealer, only dealers in the same or adjacent grid cells
        are considered as edge candidates. This avoids the O(N^2) pairwise
        comparison that would be prohibitive at 100k+ nodes.
        """
        total_dealers = len(dealers)
        if total_dealers < 2:
            return

        cell_size = self.proximity_km * 1.1

        spatial_index = SpatialGridIndex(cell_size_km=cell_size)
        spatial_index.build(dealers)

        edges_added = 0
        candidates_evaluated = 0
        max_edges_dropped = 0

        for i, d1 in enumerate(dealers):
            candidates = spatial_index.get_proximity_candidates(i)
            candidates_evaluated += len(candidates)

            local_edges: List[Tuple[float, float, DealerRecord]] = []

            for j in candidates:
                if j <= i:
                    continue
                d2 = dealers[j]

                dist = self._haversine(
                    d1.Dealer_latitude, d1.Dealer_longitude,
                    d2.Dealer_latitude, d2.Dealer_longitude,
                )

                if dist <= self.proximity_km:
                    attraction = self._compute_attraction(dist, d1, d2)
                    if attraction >= self.min_edge_weight:
                        local_edges.append((dist, attraction, d2))

            local_edges.sort(key=lambda x: -x[1])
            if len(local_edges) > self.max_edges_per_node:
                max_edges_dropped += len(local_edges) - self.max_edges_per_node
                local_edges = local_edges[: self.max_edges_per_node]

            for dist, attraction, d2 in local_edges:
                G.add_edge(
                    d1.Dealer_id,
                    d2.Dealer_id,
                    distance_km=round(dist, 4),
                    weight=round(attraction, 6),
                    travel_time=round(self._estimate_travel_time(dist), 2),
                )
                edges_added += 1

            if (i + 1) % 10000 == 0:
                logger.info(
                    "  Proximity edges: %d/%d dealers processed, %d edges built",
                    i + 1,
                    total_dealers,
                    edges_added,
                )

        self._stats["edges_added"] = edges_added
        self._stats["candidates_evaluated"] = candidates_evaluated
        self._stats["max_edges_dropped"] = max_edges_dropped

        if max_edges_dropped > 0:
            logger.info(
                "Edge cap enabled: %d edges dropped (max %d per node)",
                max_edges_dropped,
                self.max_edges_per_node,
            )

    # ------------------------------------------------------------------
    # Graph-level metadata
    # ------------------------------------------------------------------

    def _attach_graph_metadata(
        self,
        G: nx.Graph,
        dealers: List[DealerRecord],
        ftcs: Optional[List[FTCRecord]],
    ):
        if ftcs:
            ftc_capacities = [
                self.processor.compute_ftc_capacity(f) for f in ftcs
            ]
            total_capacity = sum(ftc_capacities)
            avg_capacity = total_capacity / max(len(ftc_capacities), 1)
            G.graph["total_ftc_capacity"] = total_capacity
            G.graph["avg_ftc_capacity"] = avg_capacity
            G.graph["ftc_count"] = len(ftcs)
        else:
            G.graph["total_ftc_capacity"] = 0.0
            G.graph["avg_ftc_capacity"] = 0.0
            G.graph["ftc_count"] = 0

        total_cases = sum(d.Average_cases_per_day for d in dealers)
        G.graph["total_cases"] = total_cases
        G.graph["total_dealers"] = len(dealers)
        G.graph["proximity_radius_km"] = self.proximity_km

        sm_counts = defaultdict(int)
        for d in dealers:
            sm_counts[d.SM_id] += 1
        G.graph["sm_count"] = len(sm_counts)
        G.graph["sm_dealer_counts"] = dict(sm_counts)

        static_count = sum(
            1 for d in dealers if d.Dealer_type == DealerType.STATIC
        )
        G.graph["static_dealer_count"] = static_count
        G.graph["mobile_dealer_count"] = len(dealers) - static_count

    # ------------------------------------------------------------------
    # Query / utility methods
    # ------------------------------------------------------------------

    def get_subgraph_for_sm(
        self, G: nx.Graph, sm_id: str
    ) -> nx.Graph:
        nodes = [
            n for n, attr in G.nodes(data=True)
            if attr.get("sm_id") == sm_id
        ]
        return G.subgraph(nodes).copy()

    def get_anchor_candidates(
        self, G: nx.Graph, k: int = 10
    ) -> List[str]:
        candidates = sorted(
            G.nodes(data=True),
            key=lambda x: (
                -x[1].get("avg_cases", 0),
                -x[1].get("importance", 0),
            ),
        )
        return [n[0] for n in candidates[:k]]

    def validate_graph(self, G: nx.Graph) -> List[str]:
        errors = []
        for node, attr in G.nodes(data=True):
            if attr.get("latitude") is None or attr.get("longitude") is None:
                errors.append(f"Node {node}: missing coordinates")
        for u, v, attr in G.edges(data=True):
            dist = attr.get("distance_km", 0)
            if dist < 0:
                errors.append(f"Edge {u}-{v}: negative distance")
            if dist > self.proximity_km * 1.1:
                errors.append(
                    f"Edge {u}-{v}: distance {dist:.2f} exceeds "
                    f"proximity radius {self.proximity_km}"
                )
        return errors

    # ------------------------------------------------------------------
    # Distance and weight calculations
    # ------------------------------------------------------------------

    def _compute_attraction(
        self, distance_km: float, d1: DealerRecord, d2: DealerRecord
    ) -> float:
        if distance_km < 0.01:
            return 10.0
        importance = (
            self.processor.compute_dealer_importance(d1)
            + self.processor.compute_dealer_importance(d2)
        ) / 2.0
        return importance / (1.0 + distance_km ** 2)

    @staticmethod
    def _haversine(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        sin_dlat = math.sin(dlat / 2)
        sin_dlon = math.sin(dlon / 2)
        a = (
            sin_dlat ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * sin_dlon ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @staticmethod
    def _estimate_travel_time(distance_km: float) -> float:
        avg_speed_kph = 30.0
        return (distance_km / avg_speed_kph) * 60.0
