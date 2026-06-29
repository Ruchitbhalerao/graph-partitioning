"""
Multilevel graph partitioner for territory optimization.

Implements a pure-NetworkX multilevel partitioning algorithm following the
METIS/KaHIP paradigm:

    1. COARSENING  — Heavy-edge matching to reduce graph size (3-5 levels)
    2. INITIAL PARTITIONING — Greedy graph growing from anchor seeds
    3. UNCOARSENING + REFINEMENT — Project + boundary Kernighan-Lin swaps

No external binaries required.  Handles 10 000+ nodes per SM region.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
import numpy as np

from ..data.processor import DataProcessor
from ..models.enums import DealerType
from ..models.schemas import DealerRecord, FTCRecord
from .graph_builder import DealerGraphBuilder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class PartitionAssignment:
    """Assignment of a single dealer to a partition (FTC)."""

    dealer_id: str
    partition_id: str
    is_anchor: bool = False
    is_static: bool = False
    distance_to_anchor: float = 0.0


@dataclass
class CoarsenedNode:
    """A coarse node stores which original dealer IDs it represents."""

    id: str
    weight: float
    members: List[str]


@dataclass
class PartitionMetrics:
    """Quality metrics for a completed partitioning solution."""

    total_edge_cut: float = 0.0
    normalized_cut: float = 0.0
    workload_balance: float = 0.0
    avg_workload_ratio: float = 0.0
    workload_variance: float = 0.0
    min_workload_ratio: float = 0.0
    max_workload_ratio: float = 0.0
    partition_count: int = 0
    contiguous_count: int = 0
    total_partitions: int = 0
    isolated_dealer_count: int = 0
    coarsening_levels: int = 0
    elapsed_sec: float = 0.0


# ---------------------------------------------------------------------------
# Multilevel graph partitioner
# ---------------------------------------------------------------------------

class MultilevelPartitioner:
    """
    Pure-NetworkX multilevel graph partitioner.

    The partitioning pipeline:

    +------------------+       +------------------+       +-------------------+
    |   COARSENING     | ----> |      INITIAL     | ----> |  UNCOARSEN +      |
    |  (heavy-edge      |       |   PARTITIONING   |       |   REFINEMENT      |
    |   matching)       |       |  (greedy grow)   |       |  (boundary KL)    |
    +------------------+       +------------------+       +-------------------+

    Parameters
    ----------
    coarsening_factor : float
        Target ratio of original-to-coarse nodes (default 0.5 → halve each level).
    max_coarsest_nodes : int
        Stop coarsening when nodes <= this value (default 30).
    imbalance_tolerance : float
        Allowed load imbalance ratio (default 0.15 = 15 %).
    refine_iterations : int
        KL sweeps per uncoarsening level (default 5).
    verbose : bool
        Emit per-step progress logs.
    """

    def __init__(
        self,
        coarsening_factor: float = 0.5,
        max_coarsest_nodes: int = 30,
        imbalance_tolerance: float = 0.15,
        refine_iterations: int = 5,
        verbose: bool = True,
    ):
        self.coarsening_factor = coarsening_factor
        self.max_coarsest_nodes = max_coarsest_nodes
        self.imbalance_tolerance = imbalance_tolerance
        self.refine_iterations = refine_iterations
        self.verbose = verbose
        self.processor = DataProcessor()
        self._metrics = PartitionMetrics()
        self._coarse_levels: List[Tuple[nx.Graph, Dict[str, CoarsenedNode]]] = []

    @property
    def metrics(self) -> PartitionMetrics:
        return self._metrics

    # ==================================================================
    # PUBLIC API
    # ==================================================================

    def partition(
        self,
        graph: nx.Graph,
        num_partitions: int,
        capacities: Dict[str, float],
        anchors: Dict[str, str],
        static_assignments: Dict[str, List[str]],
    ) -> Dict[str, List[str]]:
        """
        Run the full multilevel partitioning pipeline.

        Parameters
        ----------
        graph : nx.Graph
            Dealer proximity graph (from DealerGraphBuilder).
        num_partitions : int
            Number of FTCs (k).
        capacities : Dict[str, float]
            FTC_id → capacity score.
        anchors : Dict[str, str]
            FTC_id → anchor dealer_id.
        static_assignments : Dict[str, List[str]]
            FTC_id → [pre-assigned dealer_ids].

        Returns
        -------
        Dict[str, List[str]]
            FTC_id → list of assigned dealer_ids.
        """
        t0 = time.perf_counter()
        logger.info(
            "Multilevel partitioning: %d nodes, %d edges, k=%d",
            graph.number_of_nodes(),
            graph.number_of_edges(),
            num_partitions,
        )

        if num_partitions <= 0:
            raise ValueError(f"num_partitions must be > 0, got {num_partitions}")
        if graph.number_of_nodes() == 0:
            return {}

        partition_ids = list(capacities.keys())[:num_partitions]
        total_capacity = sum(capacities.values())
        node_weights = {
            n: max(graph.nodes[n].get("weight", 1.0), 0.01) for n in graph.nodes()
        }
        total_load = sum(node_weights.values())
        capacity_factor = total_load / max(total_capacity, 1e-6)

        target_loads: Dict[str, float] = {}
        for pid in partition_ids:
            raw = capacities[pid] * capacity_factor
            static_weight = sum(
                node_weights.get(did, 0.0)
                for did in static_assignments.get(pid, [])
            )
            target_loads[pid] = max(raw - static_weight, 0.0)

        # ---------- 1. Reserve static assignments ----------
        result: Dict[str, List[str]] = {pid: [] for pid in partition_ids}
        assigned_nodes: Set[str] = set()
        load_so_far: Dict[str, float] = {pid: 0.0 for pid in partition_ids}

        for pid, dealer_ids in static_assignments.items():
            if pid in result:
                result[pid].extend(dealer_ids)
                assigned_nodes.update(dealer_ids)
                for did in dealer_ids:
                    load_so_far[pid] += node_weights.get(did, 0.0)

        # ---------- 2. Extract subgraph of unassigned nodes ----------
        unassigned_nodes = [n for n in graph.nodes() if n not in assigned_nodes]
        if not unassigned_nodes:
            return result

        sub = graph.subgraph(unassigned_nodes).copy()

        # ---------- 3. Handle components independently ----------
        components = [sub.subgraph(c).copy() for c in nx.connected_components(sub)]
        logger.info("  %d connected components in unassigned subgraph", len(components))

        # Map anchors to their partitions and components
        anchor_in_component: Dict[str, int] = {}
        for pid, aid in anchors.items():
            for ci, comp in enumerate(components):
                if aid in comp:
                    anchor_in_component[pid] = ci
                    break

        # Determine which partitions still need nodes and which components
        # have anchors
        component_pids: Dict[int, List[str]] = defaultdict(list)
        for pid in partition_ids:
            ci = anchor_in_component.get(pid)
            if ci is not None:
                component_pids[ci].append(pid)

        # Sort components: those with the most assigned partitions first
        comp_order = sorted(
            range(len(components)),
            key=lambda ci: (
                -len(component_pids.get(ci, [])),
                -components[ci].number_of_nodes(),
            ),
        )

        # ---------- 4. Partition each component ----------
        for comp_idx in comp_order:
            component = components[comp_idx]
            comp_nodes = list(component.nodes())
            comp_weight = sum(node_weights[n] for n in comp_nodes)

            # Determine which FTCs get nodes from this component
            pids_here = component_pids.get(comp_idx, [])
            # Also consider remaining partitions that still need load
            remaining_capacity_pids = [
                p for p in partition_ids
                if p not in pids_here
                and load_so_far[p] < target_loads.get(p, float("inf")) * 0.9
            ]
            remaining_capacity_pids.sort(
                key=lambda p: target_loads.get(p, 1.0) - load_so_far[p],
                reverse=True,
            )

            # If only one partition needs nodes from this component,
            # assign all nodes to it directly
            if len(pids_here) <= 1 and comp_weight <= max(
                target_loads.get(p, float("inf")) - load_so_far[p]
                for p in (pids_here + remaining_capacity_pids[:1] or [partition_ids[0]])
            ):
                pid = (pids_here + remaining_capacity_pids[:1] or [partition_ids[0]])[0]
                for dealer_id in comp_nodes:
                    if dealer_id not in assigned_nodes:
                        result[pid].append(dealer_id)
                        assigned_nodes.add(dealer_id)
                        load_so_far[pid] += node_weights.get(dealer_id, 0.0)
                continue

            # Multi-way: determine which FTCs will share this component
            share_pids = pids_here[:]
            remaining_needed = [
                p for p in remaining_capacity_pids
                if load_so_far[p] < target_loads.get(p, float("inf"))
            ]
            # Add remaining partitions up to the number needed
            needed_partitions = max(1, len(pids_here))
            while len(share_pids) < needed_partitions + 1 and remaining_needed:
                share_pids.append(remaining_needed.pop(0))

            share_pids = share_pids[:max(1, min(len(share_pids), len(partition_ids)))]
            share_capacities = {
                p: max(target_loads.get(p, float("inf")) - load_so_far[p], 0.1)
                for p in share_pids
            }

            # Run k-way multilevel partitioning
            kway_result = self._multilevel_kway_partition(
                component,
                share_pids,
                share_capacities,
                node_weights,
                {p: anchors.get(p) for p in share_pids if anchors.get(p) in component},
            )

            # Apply results
            for pid, dealer_ids in kway_result.items():
                for dealer_id in dealer_ids:
                    if dealer_id not in assigned_nodes:
                        result[pid].append(dealer_id)
                        assigned_nodes.add(dealer_id)
                        load_so_far[pid] += node_weights.get(dealer_id, 0.0)

        # ---------- 5. Fallback: assign any remaining unassigned nodes ----------
        remaining = [n for n in sub.nodes() if n not in assigned_nodes]
        if remaining:
            logger.warning("  %d nodes remain unassigned after components", len(remaining))
            for n in remaining:
                pid = min(
                    partition_ids,
                    key=lambda p: load_so_far[p] / max(target_loads.get(p, 1.0), 1e-6),
                )
                result[pid].append(n)
                assigned_nodes.add(n)
                load_so_far[pid] += node_weights.get(n, 0.0)

        # ---------- 6. Compute and record metrics ----------
        self._metrics = self._compute_metrics(
            graph, result, partition_ids, node_weights, capacities
        )
        self._metrics.elapsed_sec = time.perf_counter() - t0
        t1 = time.perf_counter()

        if self.verbose:
            m = self._metrics
            logger.info(
                "Partition complete: %d partitions, %.1f s "
                "(cut=%.2f, balance=%.3f, contiguous=%d/%d, coarsening=%d levels)",
                m.partition_count, m.elapsed_sec,
                m.total_edge_cut, m.workload_balance,
                m.contiguous_count, m.total_partitions,
                m.coarsening_levels,
            )

        return result

    # ==================================================================
    # K-WAY MULTILEVEL PARTITIONING
    # ==================================================================

    def _multilevel_kway_partition(
        self,
        component: nx.Graph,
        partition_ids: List[str],
        capacities: Dict[str, float],
        node_weights: Dict[str, float],
        anchors: Dict[str, str],
    ) -> Dict[str, List[str]]:
        """
        Partition a single connected component across k partitions using
        multilevel coarsening + k-way greedy growing + uncoarsening refinement.

        Returns {partition_id: [dealer_id, ...]}.
        """
        k = len(partition_ids)
        if k == 0:
            return {}
        if k == 1:
            return {partition_ids[0]: list(component.nodes())}
        if component.number_of_nodes() == 0:
            return {p: [] for p in partition_ids}

        # 1. COARSEN: build coarse levels via heavy-edge matching
        coarse_levels: List[Tuple[nx.Graph, Dict[str, CoarsenedNode]]] = []
        current = component

        while current.number_of_nodes() > max(self.max_coarsest_nodes, k * 5):
            matching = self._heavy_edge_matching(current)
            if not matching:
                break
            contracted, cnodes = self._contract_keep_coarsenodes(current, matching, node_weights)
            coarse_levels.append((current, cnodes))
            current = contracted

        self._metrics.coarsening_levels = len(coarse_levels)
        if self.verbose and coarse_levels:
            logger.debug(
                "  K-way coarsening: %d levels, coarse size %d nodes for k=%d",
                len(coarse_levels), current.number_of_nodes(), k,
            )

        # 2. INITIAL PARTITION on coarsest graph (k-way)
        seeds = self._select_seeds(current, anchors, k, partition_ids)
        coarse_partition = self._greedy_kway_grow(current, seeds, capacities, node_weights)

        # 3. UNCOARSEN + REFINE
        result = dict(coarse_partition)
        for level_idx in range(len(coarse_levels) - 1, -1, -1):
            fine_graph, cnodes = coarse_levels[level_idx]

            # Project: expand all partition assignments
            result = self._project_kway_down(result, cnodes)

            # K-way boundary refinement
            result = self._kway_boundary_refine(
                fine_graph, result, capacities, node_weights,
            )

        # Assign each dealer in the component to its partition
        final: Dict[str, List[str]] = {p: [] for p in partition_ids}
        for dealer_id in component.nodes():
            pid = result.get(dealer_id, partition_ids[0])
            if pid in final:
                final[pid].append(dealer_id)

        return final

    # ---------- k-way coarsening ----------

    @staticmethod
    def _contract_keep_coarsenodes(
        graph: nx.Graph,
        matching: List[Tuple[str, str]],
        node_weights: Dict[str, float],
    ) -> Tuple[nx.Graph, Dict[str, CoarsenedNode]]:
        """Like _contract but returns the CoarsenedNode mapping."""
        coarse = nx.Graph()
        mapping: Dict[str, str] = {}
        cnodes: Dict[str, CoarsenedNode] = {}
        matched_set: Set[str] = {n for pair in matching for n in pair}

        for u, v in matching:
            cid = f"c{len(cnodes)}"
            members = [u, v]
            w = sum(node_weights.get(m, 1.0) for m in members)
            cnodes[cid] = CoarsenedNode(id=cid, weight=w, members=members)
            mapping[u] = cid
            mapping[v] = cid
            coarse.add_node(cid, weight=w, members=members)

        for n in graph.nodes():
            if n not in matched_set:
                cid = f"c{len(cnodes)}"
                w = node_weights.get(n, 1.0)
                cnodes[cid] = CoarsenedNode(id=cid, weight=w, members=[n])
                mapping[n] = cid
                coarse.add_node(cid, weight=w, members=[n])

        accum: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(
            lambda: {"weight": 0.0, "km": 0.0, "cnt": 0}
        )
        for u, v, data in graph.edges(data=True):
            cu, cv = mapping[u], mapping[v]
            if cu == cv:
                continue
            key = (cu, cv) if cu < cv else (cv, cu)
            d = accum[key]
            d["weight"] += data.get("weight", 1.0)
            d["km"] += data.get("distance_km", 0.0)
            d["cnt"] += 1

        for (cu, cv), d in accum.items():
            coarse.add_edge(cu, cv, weight=d["weight"], distance_km=d["km"] / max(d["cnt"], 1))

        return coarse, cnodes

    # ---------- k-way seed selection ----------

    def _select_seeds(
        self,
        graph: nx.Graph,
        anchors: Dict[str, str],
        k: int,
        partition_ids: List[str],
    ) -> Dict[str, str]:
        """
        Select one seed node per partition. Prefers anchor dealers, then
        highest-importance nodes. Returns {partition_id: node_id}.
        """
        seeds: Dict[str, str] = {}

        # First pass: anchors
        for pid in partition_ids:
            aid = anchors.get(pid)
            if aid and aid in graph:
                seeds[pid] = aid

        # Second pass: fill remaining slots with highest-degree unassigned nodes
        used: Set[str] = set(seeds.values())
        remaining_pids = [p for p in partition_ids if p not in seeds]
        candidates = sorted(
            [n for n in graph.nodes() if n not in used],
            key=lambda n: (
                graph.nodes[n].get("weight", 0.0)
                + graph.degree(n) * 0.1
            ),
            reverse=True,
        )

        for pid in remaining_pids:
            if candidates:
                seed = candidates.pop(0)
                seeds[pid] = seed
                used.add(seed)

        return seeds

    # ---------- k-way greedy growing ----------

    def _greedy_kway_grow(
        self,
        graph: nx.Graph,
        seeds: Dict[str, str],
        capacities: Dict[str, float],
        node_weights: Dict[str, float],
    ) -> Dict[str, str]:
        """
        Multi-source greedy growing via a priority queue.

        Maintains a max-heap of (score, node, pid) candidates.  At each
        step the globally best candidate is claimed.  Newly exposed
        nodes (neighbours of the claimed node) are added to the heap.

        The score balances:
          - Connection strength to the partition's existing nodes
          - A load-balance incentive that actively favours partitions
            below their target (not just a penalty when over target).
        """
        import heapq

        assignment: Dict[str, str] = {}
        loads: Dict[str, float] = {p: 0.0 for p in seeds}
        total_cap = sum(capacities.get(p, 1.0) for p in seeds)
        total_weight = sum(node_weights.get(n, 1.0) for n in graph.nodes())
        scale = total_weight / max(total_cap, 1e-6)
        tgt: Dict[str, float] = {p: capacities.get(p, 1.0) * scale for p in seeds}

        # Seed assignment
        for pid, seed in seeds.items():
            if seed in graph:
                assignment[seed] = pid
                loads[pid] += node_weights.get(seed, 1.0)

        all_nodes = set(graph.nodes())
        unassigned = all_nodes - set(assignment.keys())
        neighbours = {n: list(graph.neighbors(n)) for n in all_nodes}

        # ---------- Helper: compute score for (node → pid) ----------
        def compute_score(node: str, pid: str) -> float:
            conn = sum(
                graph.edges[node, nb].get("weight", 0.0)
                for nb in neighbours[node]
                if assignment.get(nb) == pid
            )
            lr = loads[pid] / max(tgt.get(pid, 1.0), 1e-6)
            # Positive incentive when below target, strong penalty when over
            balance = (1.0 - lr) * 8.0 if lr < 1.0 else (1.0 - lr) * 50.0
            return conn + balance

        # ---------- Initialise heap ----------
        heap: List[Tuple[float, str, str]] = []
        seen: Set[Tuple[str, str]] = set()

        for node in unassigned:
            for nb in neighbours[node]:
                pid = assignment.get(nb)
                if pid is not None:
                    key = (node, pid)
                    if key not in seen:
                        seen.add(key)
                        score = compute_score(node, pid)
                        heapq.heappush(heap, (-score, node, pid))

        # ---------- Main loop ----------
        while unassigned and heap:
            neg_score, node, pid = heapq.heappop(heap)

            if node not in unassigned:
                continue

            # Recompute score in case loads changed since enqueue
            score = compute_score(node, pid)

            # Only consider this node if it still has the best score
            # (lazy update strategy — we accept the first valid pop)
            if score < -neg_score * 0.9:
                heapq.heappush(heap, (-score, node, pid))
                continue

            # Check capacity
            nw = node_weights.get(node, 1.0)
            if loads[pid] + nw > tgt.get(pid, float("inf")) * (1.0 + self.imbalance_tolerance):
                continue

            # Claim
            assignment[node] = pid
            loads[pid] += nw
            unassigned.remove(node)

            # Add newly exposed candidates
            for nb in neighbours[node]:
                if nb in unassigned:
                    for npid in set(assignment.get(n) for n in neighbours[nb] if assignment.get(n)):
                        key = (nb, npid)
                        if key not in seen:
                            seen.add(key)
                            sc = compute_score(nb, npid)
                            heapq.heappush(heap, (-sc, nb, npid))

        # ---------- Fallback: round-robin leftovers ----------
        if unassigned:
            pids = list(seeds.keys())
            for i, node in enumerate(sorted(unassigned)):
                assignment[node] = pids[i % len(pids)]

        return assignment

    # ---------- k-way projection ----------

    @staticmethod
    def _project_kway_down(
        coarse_assignment: Dict[str, str],
        cnodes: Dict[str, CoarsenedNode],
    ) -> Dict[str, str]:
        """Map coarse node assignments down to their member nodes."""
        fine: Dict[str, str] = {}
        for node_id, pid in coarse_assignment.items():
            if node_id in cnodes:
                for member in cnodes[node_id].members:
                    fine[member] = pid
            else:
                fine[node_id] = pid
        return fine

    # ---------- k-way boundary refinement ----------

    def _kway_boundary_refine(
        self,
        graph: nx.Graph,
        assignment: Dict[str, str],
        capacities: Dict[str, float],
        node_weights: Dict[str, float],
    ) -> Dict[str, str]:
        """
        Multi-way Kernighan-Lin boundary refinement.

        Identifies all boundary nodes (have neighbours in a different
        partition) and evaluates gain from reassigning them.  Only
        accepts moves that improve edge cut without causing capacity
        imbalance.
        """
        if graph.number_of_nodes() < 2:
            return assignment

        result = dict(assignment)
        part_ids = list(set(result.values()))
        loads: Dict[str, float] = defaultdict(float)
        for n in graph.nodes():
            pid = result.get(n)
            if pid:
                loads[pid] += node_weights.get(n, 1.0)

        total_weight = sum(node_weights.get(n, 1.0) for n in graph.nodes())
        total_cap = sum(capacities.get(p, 1.0) for p in part_ids)
        scale = total_weight / max(total_cap, 1e-6)
        target_loads = {p: capacities.get(p, 1.0) * scale for p in part_ids}
        tolerance = self.imbalance_tolerance

        for _ in range(self.refine_iterations):
            # Find boundary nodes
            boundary: List[str] = []
            for n in graph.nodes():
                pid = result.get(n)
                if pid is None:
                    continue
                for nb in graph.neighbors(n):
                    if result.get(nb) != pid:
                        boundary.append(n)
                        break

            if not boundary:
                break

            # Evaluate moves
            moves: List[Tuple[float, str, str]] = []
            for n in boundary:
                current_pid = result.get(n)
                if current_pid is None:
                    continue

                # Compute gain for moving to each neighbouring partition
                neighbour_pids: Set[str] = set()
                for nb in graph.neighbors(n):
                    np_id = result.get(nb)
                    if np_id and np_id != current_pid:
                        neighbour_pids.add(np_id)

                for new_pid in neighbour_pids:
                    # Gain = edges cut removed - edges cut added
                    cut_removed = sum(
                        graph.edges[n, nb].get("weight", 0.0)
                        for nb in graph.neighbors(n)
                        if result.get(nb) == current_pid
                    )
                    cut_added = sum(
                        graph.edges[n, nb].get("weight", 0.0)
                        for nb in graph.neighbors(n)
                        if result.get(nb) == new_pid
                    )
                    gain = cut_removed - cut_added
                    nw = node_weights.get(n, 1.0)

                    # Check capacity constraint
                    new_load = loads[new_pid] + nw
                    max_load = target_loads.get(new_pid, float("inf")) * (1.0 + tolerance)
                    if new_load > max_load:
                        continue

                    moves.append((gain, n, new_pid))

            if not moves:
                break

            moves.sort(key=lambda x: -x[0])
            accepted = 0
            for gain, node, new_pid in moves:
                if gain <= 0 and accepted > 0:
                    break
                current_pid = result.get(node)
                if current_pid == new_pid:
                    continue
                nw = node_weights.get(node, 1.0)
                if loads[new_pid] + nw > target_loads.get(new_pid, float("inf")) * (1.0 + tolerance):
                    continue

                result[node] = new_pid
                loads[current_pid] -= nw
                loads[new_pid] += nw
                accepted += 1

            if accepted == 0:
                break

        return result

    # ==================================================================
    # COARSENING UTILITIES (shared with single-path path)
    # ==================================================================

    @staticmethod
    def _heavy_edge_matching(graph: nx.Graph) -> List[Tuple[str, str]]:
        """Greedy heavy-edge matching for maximum-weight pairings."""
        matched: Set[str] = set()
        matching: List[Tuple[str, str]] = []
        edges_sorted = sorted(
            graph.edges(data=True),
            key=lambda e: e[2].get("weight", 0.0),
            reverse=True,
        )
        for u, v, data in edges_sorted:
            if u not in matched and v not in matched:
                w = data.get("weight", 0.0)
                if w > 0:
                    matching.append((u, v))
                    matched.add(u)
                    matched.add(v)
        return matching

    @staticmethod
    def _project_down(
        coarse_partition: Set[str],
        coarse_nodes: Dict[str, CoarsenedNode],
    ) -> Set[str]:
        """Map coarse-node IDs back to their member dealer IDs."""
        fine: Set[str] = set()
        for cid in coarse_partition:
            if cid in coarse_nodes:
                fine.update(coarse_nodes[cid].members)
            else:
                fine.add(cid)
        return fine

    def _boundary_refine(
        self,
        graph: nx.Graph,
        partition: Set[str],
        node_weights: Dict[str, float],
        target_load: float,
        existing_load: float,
        iterations: int = 5,
    ) -> Set[str]:
        """
        Kernighan-Lin style boundary refinement.

        Only considers nodes on the boundary (have neighbours not in the
        partition).  Swaps improve edge cut reduction while respecting
        the load imbalance constraint.
        """
        if graph.number_of_nodes() == 0:
            return partition

        all_nodes = set(graph.nodes())
        outside = all_nodes - partition
        total_weight = sum(node_weights.get(n, 1.0) for n in all_nodes)
        allowed_max = (target_load - existing_load) * (1.0 + self.imbalance_tolerance)
        allowed_min = (target_load - existing_load) * (1.0 - self.imbalance_tolerance)

        current_load = sum(node_weights.get(n, 1.0) for n in partition)

        for iteration in range(iterations):
            # Identify boundary nodes (partition side)
            boundary_in: List[str] = []
            for n in partition:
                for nb in graph.neighbors(n):
                    if nb not in partition:
                        boundary_in.append(n)
                        break

            if not boundary_in:
                break

            # Compute gain for removing each boundary node from partition
            gains: List[Tuple[float, str, bool]] = []
            for n in boundary_in:
                cut_remove = sum(
                    graph.edges[n, nb].get("weight", 0.0)
                    for nb in graph.neighbors(n)
                    if nb in outside
                )
                cut_add = sum(
                    graph.edges[n, nb].get("weight", 0.0)
                    for nb in graph.neighbors(n)
                    if nb in partition
                )
                gain = cut_remove - cut_add
                nw = node_weights.get(n, 1.0)
                new_load = current_load - nw
                gains.append((gain, n, True))

            # Also consider adding boundary nodes from outside
            boundary_out: List[str] = []
            for n in outside:
                for nb in graph.neighbors(n):
                    if nb in partition:
                        boundary_out.append(n)
                        break

            for n in boundary_out:
                cut_add = sum(
                    graph.edges[n, nb].get("weight", 0.0)
                    for nb in graph.neighbors(n)
                    if nb in outside
                )
                cut_remove = sum(
                    graph.edges[n, nb].get("weight", 0.0)
                    for nb in graph.neighbors(n)
                    if nb in partition
                )
                gain = cut_remove - cut_add
                nw = node_weights.get(n, 1.0)
                new_load = current_load + nw
                gains.append((gain, n, False))

            if not gains:
                break

            # Sort by gain descending
            gains.sort(key=lambda x: -x[0])

            moves_made = 0
            for gain, node, remove in gains:
                nw = node_weights.get(node, 1.0)
                new_load = current_load - nw if remove else current_load + nw

                # Check balance constraint
                if new_load < allowed_min or new_load > allowed_max:
                    continue

                if gain <= 0 and moves_made > 0:
                    break

                if remove and node in partition:
                    partition.remove(node)
                    outside.add(node)
                    current_load = new_load
                    moves_made += 1
                elif not remove and node in outside:
                    partition.add(node)
                    outside.remove(node)
                    current_load = new_load
                    moves_made += 1

            if moves_made == 0:
                break

        return partition

    # ==================================================================
    # METRICS
    # ==================================================================

    def _compute_metrics(
        self,
        graph: nx.Graph,
        assignments: Dict[str, List[str]],
        partition_ids: List[str],
        node_weights: Dict[str, float],
        capacities: Dict[str, float],
    ) -> PartitionMetrics:
        m = PartitionMetrics()
        m.partition_count = len(partition_ids)
        m.total_partitions = len(partition_ids)

        # Build node → partition map once
        node_to_pid: Dict[str, str] = {}
        for pid, dealer_ids in assignments.items():
            for d in dealer_ids:
                node_to_pid[d] = pid

        # Edge cut: count each edge at most once
        total_cut = 0.0
        seen_edges: Set[Tuple[str, str]] = set()
        for u, v, data in graph.edges(data=True):
            key = (u, v) if u < v else (v, u)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            pu = node_to_pid.get(u)
            pv = node_to_pid.get(v)
            if pu is not None and pv is not None and pu != pv:
                total_cut += data.get("weight", 1.0)

        load_ratios: List[float] = []
        for pid in partition_ids:
            dealer_ids = set(assignments.get(pid, []))
            load = sum(node_weights.get(d, 0.0) for d in dealer_ids)
            cap = max(capacities.get(pid, 1.0), 0.01)
            load_ratios.append(load / cap)

            # Contiguity check — only nodes present in graph
            valid_ids = [d for d in dealer_ids if d in graph]
            if len(valid_ids) > 1:
                sub = graph.subgraph(valid_ids)
                if nx.is_connected(sub):
                    m.contiguous_count += 1
            elif len(valid_ids) == 1:
                m.contiguous_count += 1

            for d in dealer_ids:
                if d in graph and graph.degree(d) == 0:
                    m.isolated_dealer_count += 1

        m.total_edge_cut = total_cut
        m.workload_balance = (
            max(load_ratios) / max(min(load_ratios), 1e-6) if load_ratios else 0.0
        )
        m.avg_workload_ratio = float(np.mean(load_ratios)) if load_ratios else 0.0
        m.workload_variance = float(np.var(load_ratios)) if load_ratios else 0.0
        m.min_workload_ratio = float(np.min(load_ratios)) if load_ratios else 0.0
        m.max_workload_ratio = float(np.max(load_ratios)) if load_ratios else 0.0

        total_possible_edges = graph.number_of_nodes() * (graph.number_of_nodes() - 1) / 2
        if total_possible_edges > 0:
            m.normalized_cut = total_cut / max(total_possible_edges, 1.0)

        return m


# ---------------------------------------------------------------------------
# Drop-in replacement for the original TerritoryPartitioner
# ---------------------------------------------------------------------------

class TerritoryPartitioner:
    """
    High-level partitioner that wires together the multilevel algorithm
    with business-rule pre/post processing.
    """

    def __init__(self, graph_builder: DealerGraphBuilder):
        self.graph_builder = graph_builder
        self.multilevel = MultilevelPartitioner()
        self.processor = DataProcessor()

    @property
    def metrics(self) -> PartitionMetrics:
        return self.multilevel.metrics

    def partition(
        self,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        static_assignments: Dict[str, List[str]],
        anchor_map: Dict[str, DealerRecord],
    ) -> Dict[str, List[str]]:
        """
        Partition mobile dealers across FTCs within one SM region.

        Flow:
          1. Separate static (pre-assigned) dealers from mobile.
          2. Build proximity graph of mobile dealers.
          3. Compute FTC capacities.
          4. Run multilevel partitioning.
          5. Merge static assignments back.
          6. Validate and return.
        """
        if not dealers or not ftcs:
            logger.warning("No dealers or FTCs to partition")
            return {}

        mobile_dealers = [d for d in dealers if d.Dealer_type == DealerType.MOBILE]
        if not mobile_dealers:
            # All dealers are static — just return the pre-assignments
            return dict(static_assignments)

        # Pre-compute capacities
        capacities: Dict[str, float] = {}
        for f in ftcs:
            cap = self.processor.compute_ftc_capacity(f)
            capacities[f.FTC_id] = max(cap, 0.1)

        # Build the mobile-dealer proximity graph
        G = self.graph_builder.build(mobile_dealers, ftcs)

        # Extract anchor dealer IDs
        anchors: Dict[str, str] = {}
        for ftc_id, anchor_dealer in anchor_map.items():
            if anchor_dealer and anchor_dealer.Dealer_id in G:
                anchors[ftc_id] = anchor_dealer.Dealer_id

        # Run multilevel partitioning
        num_partitions = len(ftcs)
        partition_result = self.multilevel.partition(
            graph=G,
            num_partitions=num_partitions,
            capacities=capacities,
            anchors=anchors,
            static_assignments=static_assignments,
        )

        # Ensure every FTC has an assignment entry
        for f in ftcs:
            if f.FTC_id not in partition_result:
                partition_result[f.FTC_id] = []

        # Validate coverage
        all_assigned: Set[str] = set()
        for dealer_list in partition_result.values():
            all_assigned.update(dealer_list)
        for d in mobile_dealers:
            if d.Dealer_id not in all_assigned:
                # Fallback: assign to least-loaded FTC
                pid = min(
                    partition_result.keys(),
                    key=lambda p: sum(
                        self.processor.compute_dealer_importance(
                            next(dd for dd in dealers if dd.Dealer_id == did)
                        )
                        for did in partition_result[p]
                    ),
                )
                partition_result[pid].append(d.Dealer_id)

        logger.info(
            "Partition complete: %d FTCs, %d mobile dealers assigned",
            len(ftcs),
            sum(len(v) for v in partition_result.values()),
        )

        return partition_result
