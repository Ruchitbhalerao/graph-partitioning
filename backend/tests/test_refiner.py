"""Unit tests for TerritoryRefiner and Tabu Search components."""

import pytest
import networkx as nx

from app.optimization.refiner import (
    TerritoryRefiner, TabuList, RefinerState, Move, RefinementReport,
)
from app.optimization.graph_builder import DealerGraphBuilder
from app.models.enums import DealerType
from helpers import make_dealer


class TestTabuList:
    def test_add_and_check(self):
        tabu = TabuList(tenure=10)
        tabu.add(("dealer_1", "FTC_1"), iteration=0)
        assert tabu.is_tabu(("dealer_1", "FTC_1"), iteration=5)
        # After tenure expires, should not be tabu
        assert not tabu.is_tabu(("dealer_1", "FTC_1"), iteration=15)

    def test_not_tabu(self):
        tabu = TabuList(tenure=10)
        assert not tabu.is_tabu(("unknown", "FTC"), iteration=0)

    def test_multiple_entries(self):
        tabu = TabuList(tenure=5)
        tabu.add(("a", "1"), iteration=0)
        tabu.add(("b", "2"), iteration=1)
        assert tabu.is_tabu(("a", "1"), 3)
        assert tabu.is_tabu(("b", "2"), 3)
        assert not tabu.is_tabu(("a", "1"), 10)
        assert not tabu.is_tabu(("b", "2"), 10)

    def test_trim_removes_expired(self):
        tabu = TabuList(tenure=3)
        tabu.add(("a", "1"), iteration=0)
        tabu.add(("b", "2"), iteration=5)
        tabu._trim(iteration=6)
        # ("a","1"): expiry=3 ≤ 6 → removed
        # ("b","2"): expiry=8 > 6 → kept
        assert len(tabu._store) == 1
        assert ("b", "2") in tabu._store


class TestRefinerState:
    @pytest.fixture
    def sample_state(self):
        G = nx.Graph()
        G.add_node("A", weight=1.0, avg_cases=5.0)
        G.add_node("B", weight=1.0, avg_cases=10.0)
        G.add_node("C", weight=1.0, avg_cases=3.0)
        G.add_edge("A", "B", weight=0.5, distance_km=1.0)
        G.add_edge("B", "C", weight=0.3, distance_km=1.5)
        return RefinerState(
            assignments={"FTC_1": ["A", "B"], "FTC_2": ["C"]},
            node_to_ftc={"A": "FTC_1", "B": "FTC_1", "C": "FTC_2"},
            total_cases={"FTC_1": 15.0, "FTC_2": 3.0},
            total_weight={"FTC_1": 2.0, "FTC_2": 1.0},
            total_pairs={"FTC_1": 1, "FTC_2": 0},
            intra_edges={"FTC_1": 0.5, "FTC_2": 0.0},
            boundary_nodes={"FTC_1": set(), "FTC_2": set()},
            ftc_capacities={"FTC_1": 20.0, "FTC_2": 10.0},
            target_loads={"FTC_1": 12.0, "FTC_2": 6.0},
            G=G,
            anchors=set(),
            static_dealers=set(),
            travel_penalty=1.0,
            workload_penalty=0.3,
            compactness_penalty=0.25,
            capacity_penalty=0.0,
            productivity_bonus=1.0,
            fitness=-0.5,
        )

    def test_state_initialized(self, sample_state):
        assert len(sample_state.assignments) == 2
        assert sample_state.assignments["FTC_1"] == ["A", "B"]

    def test_boundary_detection(self, sample_state):
        """After refresh, boundary nodes should be detected."""
        refiner = TerritoryRefiner(graph_builder=None, max_iterations=1, verbose=False)
        # Build the boundary for FTC_1
        refiner._refresh_boundary(sample_state, "FTC_1")
        # B is connected to C in FTC_2, so B should be boundary
        assert "B" in sample_state.boundary_nodes["FTC_1"]


class TestTerritoryRefiner:
    def test_empty_assignments(self, refiner):
        result = refiner.refine([], [], {})
        assert result == {}

    def test_refine_no_movement_possible(self, simple_dealers, simple_ftcs, refiner):
        """When there's only one FTC, no moves should happen."""
        assignments = {"FTC_1": ["DLR_A", "DLR_B", "DLR_C"]}
        result = refiner.refine(simple_dealers, simple_ftcs, assignments)
        assert len(result) == 1
        assert len(result["FTC_1"]) == 3

    def test_report_populated(self, simple_dealers, simple_ftcs, refiner):
        assignments = {"FTC_1": ["DLR_A", "DLR_B"], "FTC_2": ["DLR_C"]}
        refiner.refine(simple_dealers, simple_ftcs, assignments)
        report = refiner.report
        assert isinstance(report, RefinementReport)
        assert report.initial_fitness != 0
        assert report.elapsed_sec > 0

    def test_travel_penalty(self, refiner):
        """Travel penalty should be non-negative."""
        from app.optimization.refiner import RefinerState
        G = nx.Graph()
        G.add_node("A", weight=1.0, avg_cases=5.0)
        G.add_node("B", weight=1.0, avg_cases=5.0)
        G.add_edge("A", "B", weight=0.5, distance_km=1.0)
        state = RefinerState(
            assignments={"FTC_1": ["A", "B"]},
            node_to_ftc={"A": "FTC_1", "B": "FTC_1"},
            total_cases={"FTC_1": 10.0},
            total_weight={"FTC_1": 2.0},
            total_pairs={"FTC_1": 1},
            intra_edges={"FTC_1": 0.5},
            boundary_nodes={"FTC_1": set()},
            ftc_capacities={"FTC_1": 20.0},
            target_loads={"FTC_1": 10.0},
            G=G,
            anchors=set(),
            static_dealers=set(),
        )
        penalty = refiner._compute_travel_penalty(state)
        assert penalty >= 0

    def test_workload_penalty(self, refiner):
        """Workload penalty should be 0 for perfectly balanced."""
        from app.optimization.refiner import RefinerState
        G = nx.Graph()
        state = RefinerState(
            assignments={"FTC_1": ["A"], "FTC_2": ["B"]},
            node_to_ftc={"A": "FTC_1", "B": "FTC_2"},
            total_cases={"FTC_1": 10.0, "FTC_2": 10.0},
            total_weight={"FTC_1": 1.0, "FTC_2": 1.0},
            total_pairs={"FTC_1": 0, "FTC_2": 0},
            intra_edges={"FTC_1": 0.0, "FTC_2": 0.0},
            boundary_nodes={"FTC_1": set(), "FTC_2": set()},
            ftc_capacities={"FTC_1": 10.0, "FTC_2": 10.0},
            target_loads={"FTC_1": 10.0, "FTC_2": 10.0},
            G=G,
            anchors=set(),
            static_dealers=set(),
        )
        penalty = refiner._compute_workload_penalty(state)
        assert penalty == 0.0

    def test_compactness_penalty(self, refiner):
        """Perfectly connected territory: 0 compactness penalty."""
        from app.optimization.refiner import RefinerState
        G = nx.Graph()
        G.add_node("A", weight=1.0)
        G.add_node("B", weight=1.0)
        G.add_edge("A", "B", weight=0.5)
        state = RefinerState(
            assignments={"FTC_1": ["A", "B"]},
            node_to_ftc={"A": "FTC_1", "B": "FTC_1"},
            total_cases={"FTC_1": 10.0},
            total_weight={"FTC_1": 2.0},
            total_pairs={"FTC_1": 1},
            intra_edges={"FTC_1": 0.5},
            boundary_nodes={"FTC_1": set()},
            ftc_capacities={"FTC_1": 20.0},
            target_loads={"FTC_1": 10.0},
            G=G,
            anchors=set(),
            static_dealers=set(),
        )
        penalty = refiner._compute_compactness_penalty(state)
        # penalty = mean(1 - edges_in/pairs) = 1 - 0.5/1 = 0.5
        assert round(penalty, 4) == 0.5

    def test_contiguity_after_remove(self, refiner, simple_graph):
        """Removing a non-bridge dealer preserves contiguity."""
        from app.optimization.refiner import RefinerState
        state = RefinerState(
            assignments={"FTC_1": ["DLR_A", "DLR_B", "DLR_C"]},
            node_to_ftc={"DLR_A": "FTC_1", "DLR_B": "FTC_1", "DLR_C": "FTC_1"},
            total_cases={"FTC_1": 18.0},
            total_weight={"FTC_1": 3.0},
            total_pairs={"FTC_1": 3},
            intra_edges={"FTC_1": 1.0},
            boundary_nodes={"FTC_1": set()},
            ftc_capacities={"FTC_1": 50.0},
            target_loads={"FTC_1": 18.0},
            G=simple_graph,
            anchors=set(),
            static_dealers=set(),
        )
        assert refiner._contiguity_after_remove(state, "DLR_B", "FTC_1")

    def test_objective_weights(self, refiner):
        """Verify objective function uses correct weights."""
        refiner.w_travel = 0.35
        refiner.w_workload = 0.30
        refiner.w_compact = 0.20
        refiner.w_capacity = 0.05
        refiner.w_productivity = 0.10
        from app.optimization.refiner import RefinerState
        G = nx.Graph()
        G.add_node("A", weight=1.0, avg_cases=5.0)
        state = RefinerState(
            assignments={"FTC_1": ["A"]},
            node_to_ftc={"A": "FTC_1"},
            total_cases={"FTC_1": 5.0},
            total_weight={"FTC_1": 1.0},
            total_pairs={"FTC_1": 0},
            intra_edges={"FTC_1": 0.0},
            boundary_nodes={"FTC_1": set()},
            ftc_capacities={"FTC_1": 10.0},
            target_loads={"FTC_1": 5.0},
            G=G,
            anchors=set(),
            static_dealers=set(),
            travel_penalty=1.0,
            workload_penalty=0.5,
            compactness_penalty=0.3,
            capacity_penalty=0.0,
            productivity_bonus=1.0,
            fitness=0.0,
        )
        fitness = refiner._objective(state)
        expected = -0.35*1.0 - 0.30*0.5 - 0.20*0.3 - 0.05*0.0 + 0.10*1.0
        assert abs(fitness - expected) < 0.001

    def test_anchors_never_moved(self, refiner):
        """Anchor dealers should appear in static_set and be protected."""
        G = nx.Graph()
        G.add_node("anchor", weight=1.0, avg_cases=10.0)
        G.add_node("other", weight=1.0, avg_cases=5.0)
        G.add_edge("anchor", "other", weight=0.5, distance_km=1.0)
        from app.optimization.refiner import RefinerState
        state = RefinerState(
            assignments={"FTC_1": ["anchor", "other"]},
            node_to_ftc={"anchor": "FTC_1", "other": "FTC_1"},
            total_cases={"FTC_1": 15.0},
            total_weight={"FTC_1": 2.0},
            total_pairs={"FTC_1": 1},
            intra_edges={"FTC_1": 0.5},
            boundary_nodes={"FTC_1": {"anchor", "other"}},
            ftc_capacities={"FTC_1": 20.0},
            target_loads={"FTC_1": 15.0},
            G=G,
            anchors={"anchor"},
            static_dealers=set(),
        )
        moves = refiner._generate_boundary_moves(state, TabuList(tenure=3), 0)
        for m in moves:
            assert m.dealer_a != "anchor", "Anchor dealer should not generate moves"
