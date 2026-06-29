"""Edge-case and boundary-condition tests for the optimization system."""

import pytest
import networkx as nx
import math

from app.models.enums import DealerType, ProductGroup
from app.models.schemas import DealerRecord, FTCRecord, OptimizationConfig
from app.optimization.graph_builder import DealerGraphBuilder, SpatialGridIndex
from app.optimization.partitioner import TerritoryPartitioner, MultilevelPartitioner
from app.optimization.refiner import TerritoryRefiner
from app.optimization.engine import OptimizationEngine
from app.optimization.validator import BusinessRuleValidator
from helpers import make_dealer, make_ftc, generate_cluster


# ---------------------------------------------------------------------------
# Graph builder edge cases
# ---------------------------------------------------------------------------

def test_single_dealer_graph():
    dealer = make_dealer("D1", lat=19.0, lng=73.0)
    builder = DealerGraphBuilder(proximity_km=5.0)
    G = builder.build([dealer])
    assert len(G.nodes) == 1
    assert len(G.edges) == 0


def test_two_dealers_within_proximity():
    dealers = [
        make_dealer("D1", lat=19.0, lng=73.0),
        make_dealer("D2", lat=19.01, lng=73.01),
    ]
    builder = DealerGraphBuilder(proximity_km=5.0)
    G = builder.build(dealers)
    assert len(G.nodes) == 2
    assert len(G.edges) == 1


def test_two_dealers_beyond_proximity():
    dealers = [
        make_dealer("D1", lat=19.0, lng=73.0),
        make_dealer("D2", lat=28.6, lng=77.2),
    ]
    builder = DealerGraphBuilder(proximity_km=5.0)
    G = builder.build(dealers)
    assert len(G.nodes) == 2
    assert len(G.edges) == 0


def test_same_coordinates():
    dealers = [
        make_dealer("D1", lat=19.0, lng=73.0),
        make_dealer("D2", lat=19.0, lng=73.0),
    ]
    builder = DealerGraphBuilder(proximity_km=5.0)
    G = builder.build(dealers)
    assert len(G.nodes) == 2
    assert len(G.edges) >= 1


def test_zero_proximity_raises():
    with pytest.raises(ValueError, match="proximity_km must be positive"):
        DealerGraphBuilder(proximity_km=0.0)


def test_extreme_coordinates():
    dealers = [
        make_dealer("D1", lat=89.9, lng=179.9),
        make_dealer("D2", lat=-89.9, lng=-179.9),
    ]
    builder = DealerGraphBuilder(proximity_km=100.0)
    G = builder.build(dealers)
    assert len(G.nodes) == 2


def test_haversine_self_distance():
    dist = DealerGraphBuilder._haversine(19.0, 73.0, 19.0, 73.0)
    assert dist == 0.0


def test_haversine_symmetric():
    d12 = DealerGraphBuilder._haversine(19.0, 73.0, 19.01, 73.01)
    d21 = DealerGraphBuilder._haversine(19.01, 73.01, 19.0, 73.0)
    assert abs(d12 - d21) < 1e-6


def test_travel_time():
    dist = DealerGraphBuilder._haversine(19.0, 73.0, 19.01, 73.01)
    tt = DealerGraphBuilder._estimate_travel_time(dist)
    assert tt > 0
    dist2 = DealerGraphBuilder._haversine(19.0, 73.0, 19.02, 73.02)
    tt2 = DealerGraphBuilder._estimate_travel_time(dist2)
    assert tt2 > tt


# ---------------------------------------------------------------------------
# SpatialGridIndex edge cases
# ---------------------------------------------------------------------------

def test_empty_grid():
    grid = SpatialGridIndex(cell_size_km=5.0)
    grid.build([])
    assert len(grid.grid) == 0
    assert grid.dealer_ids == []


def test_single_dealer_cell():
    grid = SpatialGridIndex(cell_size_km=5.0)
    dealer = make_dealer("D1", lat=19.0, lng=73.0)
    grid.build([dealer])
    cell = grid._latlon_to_cell(19.0, 73.0)
    assert cell in grid.grid
    assert 0 in grid.grid[cell]


def test_proximity_candidates_empty():
    grid = SpatialGridIndex(cell_size_km=5.0)
    grid.build([])
    assert len(grid.coords) == 0


def test_proximity_candidates_self_exclusion():
    dealer = make_dealer("D1", lat=19.0, lng=73.0)
    grid = SpatialGridIndex(cell_size_km=5.0)
    grid.build([dealer])
    # dealer_map[Dealer_id] -> index
    idx = grid.dealer_map["D1"]
    candidates = grid.get_proximity_candidates(idx)
    assert idx not in candidates


def test_neighbor_cells():
    grid = SpatialGridIndex(cell_size_km=5.0)
    neighbors = grid.get_neighbor_cells((0, 0))
    expected = {
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),  (0, 0),  (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    }
    assert set(neighbors) == expected


# ---------------------------------------------------------------------------
# Partitioner edge cases
# ---------------------------------------------------------------------------

def test_single_dealer_single_ftc():
    dealer = make_dealer("D1", lat=19.0, lng=73.0)
    ftc = make_ftc("F1")
    builder = DealerGraphBuilder(proximity_km=5.0)
    G = builder.build([dealer], [ftc])
    partitioner = MultilevelPartitioner()
    partition = partitioner.partition(G, 1, {"F1": 1.0}, {}, {})
    assert len(partition) == 1


def test_no_ftcs():
    dealers = [
        make_dealer("D1", lat=19.0, lng=73.0),
        make_dealer("D2", lat=19.01, lng=73.01),
    ]
    builder = DealerGraphBuilder(proximity_km=5.0)
    G = builder.build(dealers)
    partitioner = TerritoryPartitioner(builder)
    assert G is not None


# ---------------------------------------------------------------------------
# Refiner edge cases
# ---------------------------------------------------------------------------

def test_refiner_empty_assignments():
    refiner = TerritoryRefiner(graph_builder=None, max_iterations=10)
    result = refiner.refine([], [], {})
    assert result == {}


def test_refiner_no_movement_possible():
    dealer = make_dealer("D1", lat=19.0, lng=73.0)
    ftc = make_ftc("F1")
    builder = DealerGraphBuilder(proximity_km=5.0)
    refiner = TerritoryRefiner(graph_builder=builder, max_iterations=10)
    assignments = {"F1": ["D1"]}
    result = refiner.refine([dealer], [ftc], assignments)
    assert result["F1"] == ["D1"]


def test_static_dealer_not_moved():
    static = make_dealer("D1", dealer_type=DealerType.STATIC, lat=19.0, lng=73.0)
    mobile = make_dealer("D2", dealer_type=DealerType.MOBILE, lat=19.01, lng=73.01)
    ftc = make_ftc("F1")
    builder = DealerGraphBuilder(proximity_km=5.0)
    refiner = TerritoryRefiner(graph_builder=builder, max_iterations=10)
    assignments = {"F1": ["D1", "D2"]}
    result = refiner.refine([static, mobile], [ftc], assignments)
    assert "D1" in result.get("F1", [])


# ---------------------------------------------------------------------------
# Validator edge cases
# ---------------------------------------------------------------------------

def test_no_assignments():
    validator = BusinessRuleValidator()
    is_valid, errors = validator.validate_all({}, [], [], nx.Graph())
    assert is_valid
    assert len(errors) == 0


def test_missing_graph():
    """Two dealers in one FTC with None graph should raise on contiguity check."""
    validator = BusinessRuleValidator()
    dealers = [make_dealer("D1"), make_dealer("D2")]
    ftcs = [make_ftc("F1")]
    with pytest.raises(Exception):
        validator.validate_all({"F1": ["D1", "D2"]}, dealers, ftcs, None)


# ---------------------------------------------------------------------------
# Engine edge cases
# ---------------------------------------------------------------------------

def test_engine_none_input():
    engine = OptimizationEngine(config=OptimizationConfig())
    with pytest.raises(Exception):
        engine.run(None, None, None)


def test_engine_single_dealer():
    config = OptimizationConfig(proximity_km=5.0)
    engine = OptimizationEngine(config)
    dealer = make_dealer("D1", lat=19.0, lng=73.0)
    ftc = make_ftc("F1")
    result = engine.run([dealer], [ftc], [])
    assert result["status"] == "completed"


def test_engine_all_static_dealers():
    """Engine raises error when all dealers are static (no mobile to build graph)."""
    config = OptimizationConfig(proximity_km=5.0)
    engine = OptimizationEngine(config)
    dealers = [
        make_dealer("D1", dealer_type=DealerType.STATIC, lat=19.0, lng=73.0),
        make_dealer("D2", dealer_type=DealerType.STATIC, lat=19.01, lng=73.01),
    ]
    ftc = make_ftc("F1")
    with pytest.raises(ValueError):
        engine.run(dealers, [ftc], [])
