"""
Tabu Search territory refinement.

Takes the initial k-way partitions from MultilevelPartitioner and
improves them via boundary-dealer moves and swaps coupled with a
Variable Neighbourhood Search (VNS) metaheuristic.

Key features
-----------
- Fast delta evaluation (no full re-evaluation per move).
- Three neighbourhood types cycled by VNS.
- Tabu list with aspiration-by-objective.
- Intensification (focus on promising boundaries) and
  diversification (reset-and-shake) strategies.
- Anchors and static dealers are never moved.
- Contiguity is enforced incrementally during move generation.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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
class RefinerState:
    """Fast-access state maintained incrementally across moves."""

    assignments: Dict[str, List[str]]
    node_to_ftc: Dict[str, str]

    # Per-FTC aggregates
    total_cases: Dict[str, float]
    total_weight: Dict[str, float]
    total_pairs: Dict[str, int]
    intra_edges: Dict[str, float]
    boundary_nodes: Dict[str, Set[str]]  # ftc_id → {dealer_id, ...}

    # Capacities
    ftc_capacities: Dict[str, float]
    target_loads: Dict[str, float]

    # Graph reference (for edge lookups)
    G: nx.Graph

    # Anchor / static sets (never moved)
    anchors: Set[str]
    static_dealers: Set[str]

    # Current objective components (cached)
    travel_penalty: float = 0.0
    workload_penalty: float = 0.0
    compactness_penalty: float = 0.0
    capacity_penalty: float = 0.0
    productivity_bonus: float = 0.0
    fitness: float = 0.0


@dataclass
class Move:
    """A single refinement move."""

    kind: str  # "move", "swap", "cluster"
    dealer_a: str
    ftc_from: str
    ftc_to: str
    dealer_b: Optional[str] = None  # for swaps
    cluster: Optional[List[str]] = None  # for cluster moves
    delta: float = 0.0
    feasible: bool = True


@dataclass
class SearchHistory:
    """Convergence tracking."""

    iteration: int = 0
    fitness: List[float] = field(default_factory=list)
    travel: List[float] = field(default_factory=list)
    workload: List[float] = field(default_factory=list)
    compactness: List[float] = field(default_factory=list)
    best_iteration: int = 0
    best_fitness: float = -float("inf")
    stagnation_count: int = 0
    restart_count: int = 0


@dataclass
class RefinementReport:
    """Returned metadata after refinement completes."""

    iterations_performed: int = 0
    initial_fitness: float = 0.0
    final_fitness: float = 0.0
    improvement_pct: float = 0.0
    initial_travel: float = 0.0
    final_travel: float = 0.0
    initial_workload_var: float = 0.0
    final_workload_var: float = 0.0
    moves_accepted: int = 0
    moves_rejected: int = 0
    restarts: int = 0
    elapsed_sec: float = 0.0
    history: SearchHistory = field(default_factory=SearchHistory)


# ---------------------------------------------------------------------------
# Tabu list (fixed-length ring buffer)
# ---------------------------------------------------------------------------

class TabuList:
    """Hash-based tabu list with configurable tenure."""

    def __init__(self, tenure: int = 10):
        self.tenure = tenure
        self._store: Dict[Tuple[str, str], int] = {}
        self._next_expiry: int = 0

    def add(self, key: Tuple[str, str], iteration: int):
        self._store[key] = iteration + self.tenure
        self._trim(iteration)

    def is_tabu(self, key: Tuple[str, str], iteration: int) -> bool:
        expiry = self._store.get(key)
        return expiry is not None and expiry > iteration

    def _trim(self, iteration: int):
        expired = [k for k, v in self._store.items() if v <= iteration]
        for k in expired:
            del self._store[k]


# ---------------------------------------------------------------------------
# Territory Refiner
# ---------------------------------------------------------------------------

class TerritoryRefiner:
    """
    Tabu Search / VNS territory refinement engine.

    Parameters
    ----------
    graph_builder : DealerGraphBuilder
    travel_weight : float          w1: travel-distance penalty weight
    workload_weight : float        w2: workload-variance penalty weight
    compactness_weight : float     w3: fragmentation penalty weight
    productivity_weight : float    w4: productivity bonus weight (subtracted)
    capacity_weight : float        w5: capacity violation penalty weight
    max_iterations : int           global iteration limit
    stagnation_limit : int         restart after N iterations without improvement
    tabu_tenure : int              how long a move stays tabu (iterations)
    time_limit_sec : float         wall-clock time limit (0 = unlimited)
    vns_cycle : int                neighbourhood change frequency
    verbose : bool                 log progress periodically
    """

    def __init__(
        self,
        graph_builder: DealerGraphBuilder,
        travel_weight: float = 0.35,
        workload_weight: float = 0.30,
        compactness_weight: float = 0.20,
        productivity_weight: float = 0.10,
        capacity_weight: float = 0.05,
        max_iterations: int = 200,
        stagnation_limit: int = 30,
        tabu_tenure: int = 8,
        time_limit_sec: float = 0.0,
        vns_cycle: int = 15,
        verbose: bool = True,
    ):
        self.graph_builder = graph_builder
        self.processor = DataProcessor()

        self.w_travel = travel_weight
        self.w_workload = workload_weight
        self.w_compact = compactness_weight
        self.w_productivity = productivity_weight
        self.w_capacity = capacity_weight

        self.max_iterations = max(max_iterations, 1)
        self.stagnation_limit = stagnation_limit
        self.tabu_tenure = tabu_tenure
        self.time_limit_sec = time_limit_sec
        self.vns_cycle = vns_cycle
        self.verbose = verbose

        self._progress_callback: Optional[Callable] = None
        self._report = RefinementReport()
        self._state: Optional[RefinerState] = None

    def set_progress_callback(self, cb: Callable):
        self._progress_callback = cb

    @property
    def report(self) -> RefinementReport:
        return self._report

    # ==================================================================
    # PUBLIC API
    # ==================================================================

    def refine(
        self,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        initial_assignments: Dict[str, List[str]],
    ) -> Dict[str, List[str]]:
        """
        Run Tabu Search with VNS to refine territory assignments.

        Returns refined {ftc_id: [dealer_id, ...]}.
        """
        if not initial_assignments:
            return {}

        t0 = time.perf_counter()
        logger.info(
            "Refining %d FTCs, %d dealers",
            len(initial_assignments),
            sum(len(v) for v in initial_assignments.values()),
        )

        mobile_dealers = [d for d in dealers if d.Dealer_type == DealerType.MOBILE]
        static_set = {d.Dealer_id for d in dealers if d.Dealer_type == DealerType.STATIC}

        G = self.graph_builder.build(mobile_dealers, ftcs)

        # Build incremental state
        state = self._build_state(initial_assignments, G, ftcs, static_set, dealers)
        self._state = state

        history = SearchHistory()
        tabu = TabuList(tenure=self.tabu_tenure)

        best_assignments = deepcopy(state.assignments)
        best_fitness = state.fitness
        history.best_fitness = best_fitness
        history.fitness.append(best_fitness)

        self._report.initial_fitness = best_fitness
        self._report.initial_travel = state.travel_penalty
        self._report.initial_workload_var = self._compute_workload_variance(state)

        iteration = 0
        stagnation = 0
        restarts = 0
        neighbourhood = 0  # 0 = boundary moves, 1 = swaps, 2 = cluster
        moves_accepted = 0
        moves_rejected = 0

        while iteration < self.max_iterations:
            iteration += 1
            history.iteration = iteration

            # ---- Time limit check ----
            if self.time_limit_sec > 0 and (time.perf_counter() - t0) > self.time_limit_sec:
                logger.info("Time limit reached at iteration %d", iteration)
                break

            # ---- Generate candidate moves ----
            candidates = self._generate_moves(state, neighbourhood, tabu, iteration)

            if not candidates:
                neighbourhood = (neighbourhood + 1) % 3
                continue

            # ---- Evaluate and pick best non-tabu (or aspirated) move ----
            best_move: Optional[Move] = None
            for m in candidates:
                if not m.feasible:
                    continue
                tabu_key = (m.dealer_a, m.ftc_to) if m.kind == "move" else (
                    (m.ftc_from, m.ftc_to) if m.kind == "swap" else
                    (m.cluster[0] if m.cluster else m.dealer_a, m.ftc_to)
                )
                is_tabu_move = tabu.is_tabu(tabu_key, iteration)

                if is_tabu_move:
                    aspirated = self._check_aspiration(m, best_fitness, state)
                    if not aspirated:
                        continue

                if best_move is None or m.delta > best_move.delta:
                    best_move = m

            if best_move is None:
                neighbourhood = (neighbourhood + 1) % 3
                continue

            # ---- Apply move ----
            self._apply_move(state, best_move, G)
            moves_accepted += 1

            tabu_key = (best_move.dealer_a, best_move.ftc_from)
            tabu.add(tabu_key, iteration)

            # ---- Evaluate ----
            current_fitness = state.fitness

            history.fitness.append(current_fitness)
            history.travel.append(state.travel_penalty)
            history.workload.append(state.workload_penalty)
            history.compactness.append(state.compactness_penalty)

            # ---- Best-so-far update ----
            if current_fitness > best_fitness:
                best_fitness = current_fitness
                best_assignments = deepcopy(state.assignments)
                history.best_fitness = best_fitness
                history.best_iteration = iteration
                stagnation = 0
            else:
                stagnation += 1

            # ---- VNS neighbourhood switch ----
            if iteration % self.vns_cycle == 0:
                neighbourhood = (neighbourhood + 1) % 3

            # ---- Intensification (every 50 iters) ----
            if iteration % 50 == 0 and stagnation < self.stagnation_limit // 2:
                self._intensify(state, G)

            # ---- Diversification (stagnation) ----
            if stagnation >= self.stagnation_limit:
                self._diversify(state, best_assignments, G, dealers, ftcs)
                restarts += 1
                stagnation = 0
                neighbourhood = 0
                tabu = TabuList(tenure=self.tabu_tenure)

                current_fitness = state.fitness
                if current_fitness > best_fitness:
                    best_fitness = current_fitness
                    best_assignments = deepcopy(state.assignments)

            # ---- Progress callback ----
            if self.verbose and iteration % 25 == 0:
                logger.info(
                    "  Iter %4d | fitness %.4f | best %.4f | "
                    "travel %.2f | wload %.4f | stagn %d | neigh %d",
                    iteration, current_fitness, best_fitness,
                    state.travel_penalty, state.workload_penalty,
                    stagnation, neighbourhood,
                )
                if self._progress_callback:
                    self._progress_callback({
                        "iteration": iteration,
                        "fitness": current_fitness,
                        "best_fitness": best_fitness,
                        "travel": state.travel_penalty,
                        "workload": state.workload_penalty,
                        "stagnation": stagnation,
                    })

        # ---- Build report ----
        elapsed = time.perf_counter() - t0
        final_fitness = state.fitness

        self._report.iterations_performed = iteration
        self._report.final_fitness = final_fitness
        self._report.final_travel = state.travel_penalty
        self._report.final_workload_var = self._compute_workload_variance(state)
        self._report.improvement_pct = (
            (best_fitness - self._report.initial_fitness)
            / max(abs(self._report.initial_fitness), 1e-6) * 100.0
        )
        self._report.moves_accepted = moves_accepted
        self._report.moves_rejected = moves_rejected
        self._report.restarts = restarts
        self._report.elapsed_sec = elapsed
        self._report.history = history

        logger.info(
            "Refinement complete: %d iters, %.2f s, "
            "fitness %.4f -> %.4f (%.1f%%), restarts=%d",
            iteration, elapsed,
            self._report.initial_fitness, best_fitness,
            self._report.improvement_pct, restarts,
        )

        return best_assignments

    # ==================================================================
    # STATE MANAGEMENT
    # ==================================================================

    def _build_state(
        self,
        assignments: Dict[str, List[str]],
        G: nx.Graph,
        ftcs: List[FTCRecord],
        static_set: Set[str],
        dealers: List[DealerRecord],
    ) -> RefinerState:
        """Build initial RefinerState from raw assignments."""
        node_to_ftc: Dict[str, str] = {}
        for pid, ids in assignments.items():
            for d in ids:
                node_to_ftc[d] = pid

        ftc_capacities: Dict[str, float] = {}
        for f in ftcs:
            cap = self.processor.compute_ftc_capacity(f)
            ftc_capacities[f.FTC_id] = max(cap, 0.1)

        total_weight = sum(
            G.nodes[n].get("weight", 1.0) for n in G.nodes()
        )
        total_cap = sum(ftc_capacities.values())
        scale = total_weight / max(total_cap, 1e-6)
        target_loads = {
            pid: ftc_capacities.get(pid, 1.0) * scale
            for pid in assignments
        }

        dealer_cases = {d.Dealer_id: d.Average_cases_per_day for d in dealers}

        total_cases: Dict[str, float] = {}
        total_weight_d: Dict[str, float] = {}
        total_pairs: Dict[str, int] = {}
        intra_edges: Dict[str, float] = {}
        boundary_nodes: Dict[str, Set[str]] = {}

        for pid, ids in assignments.items():
            cases = sum(dealer_cases.get(d, 0.0) for d in ids)
            wsum = sum(G.nodes[d].get("weight", 1.0)
                       for d in ids if d in G)
            total_cases[pid] = cases
            total_weight_d[pid] = wsum

            e_in = 0
            pairs = 0
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pairs += 1
                    if G.has_edge(ids[i], ids[j]):
                        e_in += G.edges[ids[i], ids[j]].get("weight", 1.0)
            total_pairs[pid] = pairs
            intra_edges[pid] = e_in

            bound: Set[str] = set()
            for d in ids:
                if d not in G:
                    continue
                for nb in G.neighbors(d):
                    if node_to_ftc.get(nb) != pid:
                        bound.add(d)
                        break
            boundary_nodes[pid] = bound

        anchors: Set[str] = set()
        for n in G.nodes():
            if G.nodes[n].get("is_anchor", False):
                anchors.add(n)

        state = RefinerState(
            assignments=deepcopy(assignments),
            node_to_ftc=node_to_ftc,
            total_cases=total_cases,
            total_weight=total_weight_d,
            total_pairs=total_pairs,
            intra_edges=intra_edges,
            boundary_nodes=boundary_nodes,
            ftc_capacities=ftc_capacities,
            target_loads=target_loads,
            G=G,
            anchors=anchors,
            static_dealers=static_set,
        )

        self._recompute_objective(state)
        return state

    def _recompute_objective(self, state: RefinerState):
        """Full objective recomputation (expensive — used rarely)."""
        state.travel_penalty = self._compute_travel_penalty(state)
        state.workload_penalty = self._compute_workload_penalty(state)
        state.compactness_penalty = self._compute_compactness_penalty(state)
        state.capacity_penalty = self._compute_capacity_penalty(state)
        state.productivity_bonus = self._compute_productivity_bonus(state)
        state.fitness = self._objective(state)

    def _objective(self, s: RefinerState) -> float:
        """Current multi-objective fitness (higher = better)."""
        return (
            -self.w_travel * s.travel_penalty
            - self.w_workload * s.workload_penalty
            - self.w_compact * s.compactness_penalty
            - self.w_capacity * s.capacity_penalty
            + self.w_productivity * s.productivity_bonus
        )

    # ==================================================================
    # OBJECTIVE COMPONENTS  (all penalties — lower is better)
    # ==================================================================

    @staticmethod
    def _compute_travel_penalty(state: RefinerState) -> float:
        total = 0.0
        for pid in state.assignments:
            total += state.intra_edges.get(pid, 0.0)
        return total

    def _compute_workload_penalty(self, state: RefinerState) -> float:
        ratios = []
        for pid in state.assignments:
            cap = state.ftc_capacities.get(pid, 1.0)
            load = state.total_cases.get(pid, 0.0)
            ratios.append(load / max(cap, 0.01))
        if not ratios:
            return 0.0
        return float(np.std(ratios))

    @staticmethod
    def _compute_compactness_penalty(state: RefinerState) -> float:
        penalties = []
        for pid in state.assignments:
            edges_in = state.intra_edges.get(pid, 0.0)
            pairs = state.total_pairs.get(pid, 0)
            if pairs > 0:
                ratio = edges_in / pairs
            else:
                ratio = 1.0
            penalties.append(1.0 - ratio)
        return float(np.mean(penalties)) if penalties else 0.0

    def _compute_capacity_penalty(self, state: RefinerState) -> float:
        total = 0.0
        for pid in state.assignments:
            cap = state.ftc_capacities.get(pid, 1.0)
            load = state.total_cases.get(pid, 0.0)
            if cap > 0 and load > cap * 1.1:
                total += (load / cap - 1.1) ** 2
        return total

    def _compute_productivity_bonus(self, state: RefinerState) -> float:
        total = 0.0
        dealer_cases = {
            n: state.G.nodes[n].get("avg_cases", 0.0)
            for n in state.G.nodes()
        }
        for pid, ids in state.assignments.items():
            cluster_cases = sum(dealer_cases.get(d, 0.0) for d in ids)
            total += cluster_cases

        all_cases = sum(dealer_cases.values())
        return total / max(all_cases, 0.01)

    # ==================================================================
    # MOVE GENERATION  (three neighbourhoods)
    # ==================================================================

    def _generate_moves(
        self,
        state: RefinerState,
        neighbourhood: int,
        tabu: TabuList,
        iteration: int,
    ) -> List[Move]:
        if neighbourhood == 0:
            return self._generate_boundary_moves(state, tabu, iteration)
        elif neighbourhood == 1:
            return self._generate_swap_moves(state, tabu, iteration)
        else:
            return self._generate_cluster_moves(state, tabu, iteration)

    def _generate_boundary_moves(
        self,
        state: RefinerState,
        tabu: TabuList,
        iteration: int,
    ) -> List[Move]:
        """Move a single boundary dealer to an adjacent FTC."""
        moves: List[Move] = []
        for ftc_a, boundary in state.boundary_nodes.items():
            for dealer in boundary:
                if dealer in state.anchors or dealer in state.static_dealers:
                    continue
                if dealer not in state.G:
                    continue

                # Determine adjacent FTCs via graph edges
                adj_ftcs: Set[str] = set()
                for nb in state.G.neighbors(dealer):
                    nb_ftc = state.node_to_ftc.get(nb)
                    if nb_ftc and nb_ftc != ftc_a:
                        adj_ftcs.add(nb_ftc)

                for ftc_b in adj_ftcs:
                    if tabu.is_tabu((dealer, ftc_a), iteration):
                        continue
                    delta = self._delta_move(state, dealer, ftc_a, ftc_b)
                    feasible = self._move_feasible(state, dealer, ftc_a, ftc_b)
                    moves.append(Move(
                        kind="move",
                        dealer_a=dealer,
                        ftc_from=ftc_a,
                        ftc_to=ftc_b,
                        delta=delta,
                        feasible=feasible,
                    ))

        moves.sort(key=lambda m: -m.delta)
        return moves[:50]

    def _generate_swap_moves(
        self,
        state: RefinerState,
        tabu: TabuList,
        iteration: int,
    ) -> List[Move]:
        """Swap two boundary dealers between adjacent FTCs."""
        moves: List[Move] = []
        ftc_ids = list(state.assignments.keys())

        for i, ftc_a in enumerate(ftc_ids):
            for ftc_b in ftc_ids[i + 1:]:
                bound_a = state.boundary_nodes.get(ftc_a, set())
                bound_b = state.boundary_nodes.get(ftc_b, set())
                if not bound_a or not bound_b:
                    continue

                for d_a in list(bound_a)[:8]:
                    if d_a in state.anchors or d_a in state.static_dealers:
                        continue
                    for d_b in list(bound_b)[:8]:
                        if d_b in state.anchors or d_b in state.static_dealers:
                            continue

                        if tabu.is_tabu((ftc_a, ftc_b), iteration):
                            continue

                        delta = self._delta_swap(state, d_a, ftc_a, d_b, ftc_b)
                        feasible = self._swap_feasible(state, d_a, ftc_a, d_b, ftc_b)
                        moves.append(Move(
                            kind="swap",
                            dealer_a=d_a,
                            ftc_from=ftc_a,
                            ftc_to=ftc_b,
                            dealer_b=d_b,
                            delta=delta,
                            feasible=feasible,
                        ))

        moves.sort(key=lambda m: -m.delta)
        return moves[:30]

    def _generate_cluster_moves(
        self,
        state: RefinerState,
        tabu: TabuList,
        iteration: int,
    ) -> List[Move]:
        """Move a small connected cluster of boundary dealers."""
        moves: List[Move] = []
        for ftc_a, boundary in state.boundary_nodes.items():
            boundary_list = [d for d in boundary
                             if d not in state.anchors
                             and d not in state.static_dealers]
            if len(boundary_list) < 2:
                continue

            # Build small connected clusters from boundary nodes
            sub = state.G.subgraph(boundary_list)
            visited: Set[str] = set()
            for comp in nx.connected_components(sub):
                cluster = list(comp)
                if len(cluster) < 2 or len(cluster) > 5:
                    continue
                key_node = cluster[0]

                adj_ftcs: Set[str] = set()
                for n in cluster:
                    for nb in state.G.neighbors(n):
                        nb_ftc = state.node_to_ftc.get(nb)
                        if nb_ftc and nb_ftc != ftc_a:
                            adj_ftcs.add(nb_ftc)

                for ftc_b in adj_ftcs:
                    if tabu.is_tabu((cluster[0], ftc_a), iteration):
                        continue
                    delta = self._delta_cluster(state, cluster, ftc_a, ftc_b)
                    feasible = self._cluster_feasible(state, cluster, ftc_a, ftc_b)
                    moves.append(Move(
                        kind="cluster",
                        dealer_a=cluster[0],
                        ftc_from=ftc_a,
                        ftc_to=ftc_b,
                        cluster=cluster,
                        delta=delta,
                        feasible=feasible,
                    ))
                # Only a few clusters per FTC
                if len(moves) >= 20:
                    break
            if len(moves) >= 20:
                break

        moves.sort(key=lambda m: -m.delta)
        return moves[:15]

    # ==================================================================
    # DELTA EVALUATION  (fast incremental computation)
    # ==================================================================

    def _delta_move(
        self,
        state: RefinerState,
        dealer: str,
        ftc_from: str,
        ftc_to: str,
    ) -> float:
        """Compute fitness change of moving `dealer` from `ftc_from` to `ftc_to`."""
        # Store current values
        old_fitness = state.fitness

        # Temporarily apply
        self._apply_move_dry(state, dealer, ftc_from, ftc_to)

        new_fitness = state.fitness
        delta = new_fitness - old_fitness

        # Roll back
        self._apply_move_dry(state, dealer, ftc_to, ftc_from)

        return delta

    def _apply_move_dry(
        self,
        state: RefinerState,
        dealer: str,
        ftc_from: str,
        ftc_to: str,
    ):
        """Apply a move temporarily to compute delta (in-place modification)."""
        ids_from = state.assignments[ftc_from]
        ids_to = state.assignments[ftc_to]

        # --- Update intra_edges and total_pairs ---
        w = state.G.nodes[dealer].get("weight", 1.0)
        cases = state.G.nodes[dealer].get("avg_cases", 0.0)

        connections_from = 0.0
        connections_to = 0.0
        for nb in state.G.neighbors(dealer):
            ew = state.G.edges[dealer, nb].get("weight", 1.0)
            nb_ftc = state.node_to_ftc.get(nb)
            if nb_ftc == ftc_from:
                connections_from += ew
            elif nb_ftc == ftc_to:
                connections_to += ew

        state.intra_edges[ftc_from] -= connections_from
        state.intra_edges[ftc_to] += connections_to

        # --- Update assignment (must happen BEFORE pair recalculation) ---
        ids_from.remove(dealer)
        ids_to.append(dealer)
        state.node_to_ftc[dealer] = ftc_to

        n_from = len(ids_from)
        n_to = len(ids_to)
        state.total_pairs[ftc_from] = max(0, n_from * (n_from - 1) // 2)
        state.total_pairs[ftc_to] = n_to * (n_to - 1) // 2

        # --- Update totals ---
        state.total_weight[ftc_from] -= w
        state.total_weight[ftc_to] += w
        state.total_cases[ftc_from] -= cases
        state.total_cases[ftc_to] += cases

        # --- Update boundary sets ---
        self._refresh_boundary(state, ftc_from)
        self._refresh_boundary(state, ftc_to)

        # --- Update affected neighbour FTCs ---
        for nb in state.G.neighbors(dealer):
            nb_ftc = state.node_to_ftc.get(nb)
            if nb_ftc and nb_ftc not in (ftc_from, ftc_to):
                self._refresh_boundary(state, nb_ftc)

        # --- Recompute objective ---
        self._recompute_objective(state)

    def _refresh_boundary(self, state: RefinerState, ftc_id: str):
        """Rebuild the boundary set for a single FTC."""
        bound: Set[str] = set()
        for d in state.assignments.get(ftc_id, []):
            if d not in state.G:
                continue
            for nb in state.G.neighbors(d):
                if state.node_to_ftc.get(nb) != ftc_id:
                    bound.add(d)
                    break
        state.boundary_nodes[ftc_id] = bound

    # ==================================================================
    # FEASIBILITY CHECKS
    # ==================================================================

    def _move_feasible(
        self,
        state: RefinerState,
        dealer: str,
        ftc_from: str,
        ftc_to: str,
    ) -> bool:
        """Check contiguity and capacity for a move."""
        if len(state.assignments[ftc_from]) <= 1:
            return False
        if not self._contiguity_after_remove(state, dealer, ftc_from):
            return False
        if not self._contiguity_after_add(state, dealer, ftc_to):
            return False

        new_load = (state.total_cases.get(ftc_to, 0.0)
                    + state.G.nodes[dealer].get("avg_cases", 0.0))
        cap = state.ftc_capacities.get(ftc_to, 1.0)
        if new_load > cap * 1.5:
            return False

        return True

    def _swap_feasible(
        self,
        state: RefinerState,
        d_a: str,
        ftc_a: str,
        d_b: str,
        ftc_b: str,
    ) -> bool:
        """Check contiguity and capacity for a swap."""
        for d, f_from, f_to in [(d_a, ftc_a, ftc_b), (d_b, ftc_b, ftc_a)]:
            if len(state.assignments[f_from]) <= 1:
                return False
            if not self._contiguity_after_remove(state, d, f_from):
                return False
            if not self._contiguity_after_add(state, d, f_to):
                return False

        new_load_a = (state.total_cases.get(ftc_a, 0.0)
                      - state.G.nodes[d_a].get("avg_cases", 0.0)
                      + state.G.nodes[d_b].get("avg_cases", 0.0))
        new_load_b = (state.total_cases.get(ftc_b, 0.0)
                      - state.G.nodes[d_b].get("avg_cases", 0.0)
                      + state.G.nodes[d_a].get("avg_cases", 0.0))
        cap_a = state.ftc_capacities.get(ftc_a, 1.0)
        cap_b = state.ftc_capacities.get(ftc_b, 1.0)
        if new_load_a > cap_a * 1.5 or new_load_b > cap_b * 1.5:
            return False

        return True

    def _cluster_feasible(
        self,
        state: RefinerState,
        cluster: List[str],
        ftc_from: str,
        ftc_to: str,
    ) -> bool:
        """Check contiguity and capacity for a cluster move."""
        if len(state.assignments[ftc_from]) <= len(cluster):
            return False
        if not self._contiguity_after_remove(state, cluster[0], ftc_from):
            return False

        added_cases = sum(
            state.G.nodes[d].get("avg_cases", 0.0) for d in cluster
        )
        new_load = state.total_cases.get(ftc_to, 0.0) + added_cases
        cap = state.ftc_capacities.get(ftc_to, 1.0)
        if new_load > cap * 1.5:
            return False

        return True

    def _contiguity_after_remove(
        self,
        state: RefinerState,
        dealer: str,
        ftc_id: str,
    ) -> bool:
        """Check if FTC remains contiguous after removing dealer."""
        ids = state.assignments[ftc_id]
        if len(ids) <= 2:
            return True
        remaining = [d for d in ids if d != dealer]
        if len(remaining) < 2:
            return True
        sub = state.G.subgraph(remaining)
        return nx.is_connected(sub)

    def _contiguity_after_add(
        self,
        state: RefinerState,
        dealer: str,
        ftc_id: str,
    ) -> bool:
        """Check if adding a dealer maintains contiguity (connects to at least one)."""
        ids = state.assignments[ftc_id]
        if not ids:
            return True
        for d in ids:
            if state.G.has_edge(dealer, d):
                return True
        return False

    # ==================================================================
    # MOVE APPLICATION
    # ==================================================================

    def _apply_move(
        self,
        state: RefinerState,
        move: Move,
        G: nx.Graph,
    ):
        """Apply a move and update the state incrementally."""
        if move.kind == "move":
            self._apply_single_move(state, move.dealer_a, move.ftc_from, move.ftc_to)
        elif move.kind == "swap":
            self._apply_swap(state, move.dealer_a, move.ftc_from,
                             move.dealer_b, move.ftc_to)
        elif move.kind == "cluster" and move.cluster:
            for d in move.cluster:
                self._apply_single_move(state, d, move.ftc_from, move.ftc_to)

    def _apply_single_move(
        self,
        state: RefinerState,
        dealer: str,
        ftc_from: str,
        ftc_to: str,
    ):
        """Apply and recompute objective."""
        ids_from = state.assignments[ftc_from]
        ids_to = state.assignments[ftc_to]

        # Edge contributions
        w_remove = 0.0
        w_add = 0.0
        for nb in state.G.neighbors(dealer):
            ew = state.G.edges[dealer, nb].get("weight", 1.0)
            nb_ftc = state.node_to_ftc.get(nb)
            if nb_ftc == ftc_from:
                w_remove += ew
            elif nb_ftc == ftc_to:
                w_add += ew

        state.intra_edges[ftc_from] -= w_remove
        state.intra_edges[ftc_to] += w_add

        n_f = len(ids_from) - 1
        n_t = len(ids_to)
        state.total_pairs[ftc_from] = max(0, n_f * (n_f - 1) // 2)
        state.total_pairs[ftc_to] = n_t * (n_t + 1) // 2

        w = state.G.nodes[dealer].get("weight", 1.0)
        cases = state.G.nodes[dealer].get("avg_cases", 0.0)
        state.total_weight[ftc_from] -= w
        state.total_weight[ftc_to] += w
        state.total_cases[ftc_from] -= cases
        state.total_cases[ftc_to] += cases

        ids_from.remove(dealer)
        ids_to.append(dealer)
        state.node_to_ftc[dealer] = ftc_to

        self._refresh_boundary(state, ftc_from)
        self._refresh_boundary(state, ftc_to)
        for nb in state.G.neighbors(dealer):
            nb_ftc = state.node_to_ftc.get(nb)
            if nb_ftc and nb_ftc not in (ftc_from, ftc_to):
                self._refresh_boundary(state, nb_ftc)

        self._recompute_objective(state)

    def _apply_swap(
        self,
        state: RefinerState,
        d_a: str,
        ftc_a: str,
        d_b: str,
        ftc_b: str,
    ):
        """Swap two dealers between territories."""
        for dealer, f_from, f_to in [(d_a, ftc_a, ftc_b), (d_b, ftc_b, ftc_a)]:
            self._apply_single_move(state, dealer, f_from, f_to)

    # ==================================================================
    # ASPIRATION CRITERIA
    # ==================================================================

    def _check_aspiration(
        self,
        move: Move,
        best_fitness: float,
        state: RefinerState,
    ) -> bool:
        """Aspiration by objective: allow tabu move if it beats best known."""
        delta = move.delta
        candidate = state.fitness + delta
        return candidate > best_fitness

    # ==================================================================
    # INTENSIFICATION / DIVERSIFICATION
    # ==================================================================

    def _intensify(self, state: RefinerState, G: nx.Graph):
        """
        Intensification: focus on high-gain boundary regions.
        Temporarily reduces neighbourhood diversity to exploit
        promising boundary areas.
        """
        if not state.boundary_nodes:
            return

        # Find the boundary with the most connections (highest potential gain)
        best_boundary: List[Tuple[str, str, float]] = []
        for ftc_id, boundary in state.boundary_nodes.items():
            for d in boundary:
                if d in state.anchors or d in state.static_dealers:
                    continue
                gain = 0.0
                for nb in G.neighbors(d):
                    nb_ftc = state.node_to_ftc.get(nb)
                    if nb_ftc and nb_ftc != ftc_id:
                        gain += G.edges[d, nb].get("weight", 0.0)
                best_boundary.append((d, ftc_id, gain))

        best_boundary.sort(key=lambda x: -x[2])
        top = best_boundary[:5]

        for dealer, ftc_from, _ in top:
            adj_ftcs: Set[str] = set()
            for nb in G.neighbors(dealer):
                nb_ftc = state.node_to_ftc.get(nb)
                if nb_ftc and nb_ftc != ftc_from:
                    adj_ftcs.add(nb_ftc)
            if adj_ftcs:
                ftc_to = max(adj_ftcs, key=lambda p: (
                    state.intra_edges.get(p, 0.0)
                ))
                if self._move_feasible(state, dealer, ftc_from, ftc_to):
                    self._apply_single_move(state, dealer, ftc_from, ftc_to)

    def _diversify(
        self,
        state: RefinerState,
        best_assignments: Dict[str, List[str]],
        G: nx.Graph,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
    ):
        """
        Diversification: reset to best solution and shake a subset of
        boundary dealers to escape local optimum.
        """
        state.assignments = deepcopy(best_assignments)

        # Rebuild state from best solution
        dealer_cases = {d.Dealer_id: d.Average_cases_per_day for d in dealers}
        new_node_to_ftc: Dict[str, str] = {}
        for pid, ids in state.assignments.items():
            for d in ids:
                new_node_to_ftc[d] = pid
        state.node_to_ftc = new_node_to_ftc

        for pid, ids in state.assignments.items():
            wsum = sum(G.nodes[d].get("weight", 1.0) for d in ids if d in G)
            cases = sum(dealer_cases.get(d, 0.0) for d in ids)
            state.total_weight[pid] = wsum
            state.total_cases[pid] = cases

            e_in = 0
            pairs = 0
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pairs += 1
                    if G.has_edge(ids[i], ids[j]):
                        e_in += G.edges[ids[i], ids[j]].get("weight", 1.0)
            state.intra_edges[pid] = e_in
            state.total_pairs[pid] = pairs

            self._refresh_boundary(state, pid)

        self._recompute_objective(state)

        # Shake: randomly move 10-20% of boundary dealers
        all_boundary = list({
            d for boundary in state.boundary_nodes.values() for d in boundary
            if d not in state.anchors and d not in state.static_dealers
        })
        np.random.shuffle(all_boundary)
        shake_count = max(1, len(all_boundary) // 8)

        for dealer in all_boundary[:shake_count]:
            ftc_from = state.node_to_ftc.get(dealer)
            if not ftc_from:
                continue

            adj_ftcs: List[str] = []
            for nb in G.neighbors(dealer):
                nb_ftc = state.node_to_ftc.get(nb)
                if nb_ftc and nb_ftc != ftc_from:
                    adj_ftcs.append(nb_ftc)
            if not adj_ftcs:
                continue

            ftc_to = np.random.choice(adj_ftcs)
            if self._move_feasible(state, dealer, ftc_from, ftc_to):
                self._apply_single_move(state, dealer, ftc_from, ftc_to)

    # ==================================================================
    # UTILITIES
    # ==================================================================

    @staticmethod
    def _compute_workload_variance(state: RefinerState) -> float:
        ratios = []
        for pid in state.assignments:
            cap = state.ftc_capacities.get(pid, 1.0)
            load = state.total_cases.get(pid, 0.0)
            ratios.append(load / max(cap, 0.01))
        return float(np.var(ratios)) if ratios else 0.0

    def _delta_swap(
        self,
        state: RefinerState,
        d_a: str,
        ftc_a: str,
        d_b: str,
        ftc_b: str,
    ) -> float:
        """Quick delta for a swap (approximate — recomputed after apply)."""
        old_obj = self._objective(state)
        self._apply_move_dry(state, d_a, ftc_a, ftc_b)
        self._apply_move_dry(state, d_b, ftc_b, ftc_a)
        new_obj = self._objective(state)

        self._apply_move_dry(state, d_b, ftc_a, ftc_b)
        self._apply_move_dry(state, d_a, ftc_b, ftc_a)

        return new_obj - old_obj

    def _delta_cluster(
        self,
        state: RefinerState,
        cluster: List[str],
        ftc_from: str,
        ftc_to: str,
    ) -> float:
        """Quick delta for a cluster move."""
        old_obj = self._objective(state)
        for d in cluster:
            self._apply_move_dry(state, d, ftc_from, ftc_to)
        new_obj = self._objective(state)
        for d in cluster:
            self._apply_move_dry(state, d, ftc_to, ftc_from)
        return new_obj - old_obj
