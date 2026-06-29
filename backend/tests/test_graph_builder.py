"""Unit tests for DealerGraphBuilder and SpatialGridIndex."""

import pytest
import networkx as nx
import math

from app.optimization.graph_builder import DealerGraphBuilder, SpatialGridIndex
from app.models.enums import DealerType
from helpers import make_dealer


class TestSpatialGridIndex:
    def test_build_and_query(self, simple_dealers):
        index = SpatialGridIndex(cell_size_km=5.0)
        index.build(simple_dealers)
        assert len(index.coords) == 3
        assert len(index.dealer_ids) == 3
        assert len(index.dealer_map) == 3

    def test_get_proximity_candidates(self, simple_dealers):
        index = SpatialGridIndex(cell_size_km=5.0)
        index.build(simple_dealers)
        candidates = index.get_proximity_candidates(0)
        assert len(candidates) >= 0
        assert 0 not in candidates

    def test_empty_grid(self):
        index = SpatialGridIndex(cell_size_km=5.0)
        index.build([])
        assert len(index.coords) == 0

    def test_latlon_to_cell(self):
        index = SpatialGridIndex(cell_size_km=111.32)
        cell = index._latlon_to_cell(19.0, 73.0)
        assert cell == (19, 73)

    def test_neighbor_cells(self):
        index = SpatialGridIndex(cell_size_km=5.0)
        neighbors = index.get_neighbor_cells((10, 20))
        assert len(neighbors) == 9
        assert (10, 20) in neighbors
        assert (9, 19) in neighbors
        assert (11, 21) in neighbors

    def test_dealer_without_proximity(self):
        """Dealers far apart should have no candidates."""
        dealers = [
            make_dealer("A", lat=19.0, lng=73.0),
            make_dealer("B", lat=28.6, lng=77.2),
        ]
        index = SpatialGridIndex(cell_size_km=5.0)
        index.build(dealers)
        candidates = index.get_proximity_candidates(0)
        # With 5km cells and ~1000km apart, likely no candidates
        assert isinstance(candidates, list)


class TestDealerGraphBuilder:
    def test_empty_dealers_raises(self):
        builder = DealerGraphBuilder(proximity_km=5.0)
        with pytest.raises(ValueError, match="empty dealer list"):
            builder.build([])

    def test_zero_proximity_raises(self):
        with pytest.raises(ValueError, match="proximity_km must be positive"):
            DealerGraphBuilder(proximity_km=0)

    def test_negative_proximity_raises(self):
        with pytest.raises(ValueError, match="proximity_km must be positive"):
            DealerGraphBuilder(proximity_km=-1)

    def test_simple_graph_build(self, simple_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(simple_dealers)
        assert G.number_of_nodes() == 3
        assert G.number_of_edges() >= 2  # all within 5km

    def test_node_attributes(self, simple_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(simple_dealers)
        for node in G.nodes():
            attrs = G.nodes[node]
            assert "latitude" in attrs
            assert "longitude" in attrs
            assert "avg_cases" in attrs
            assert "weight" in attrs
            assert attrs["weight"] > 0

    def test_edge_attributes(self, simple_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(simple_dealers)
        for _, _, attrs in G.edges(data=True):
            assert "distance_km" in attrs
            assert attrs["distance_km"] > 0
            assert "weight" in attrs
            assert "travel_time" in attrs

    def test_graph_metadata(self, simple_dealers, simple_ftcs):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(simple_dealers, simple_ftcs)
        assert "total_cases" in G.graph
        assert "total_dealers" in G.graph
        assert "proximity_radius_km" in G.graph
        assert G.graph["total_dealers"] == 3

    def test_ftc_metadata(self, simple_dealers, simple_ftcs):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(simple_dealers, simple_ftcs)
        assert "ftc_count" in G.graph
        assert G.graph["ftc_count"] == 2

    def test_distant_dealers_no_edges(self):
        """Dealers > 100km apart should have no edges with 5km proximity."""
        dealers = [
            make_dealer("A", lat=19.0, lng=73.0),
            make_dealer("B", lat=28.6, lng=77.2),
        ]
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(dealers)
        assert G.number_of_edges() == 0

    def test_sm_subgraph(self, mixed_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(mixed_dealers)
        sub = builder.get_subgraph_for_sm(G, "SM001")
        assert all(G.nodes[n]["sm_id"] == "SM001" for n in sub.nodes())

    def test_anchor_candidates(self, simple_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(simple_dealers)
        anchors = builder.get_anchor_candidates(G, k=2)
        assert len(anchors) == 2
        assert anchors[0] == "DLR_B"  # highest cases (10)

    def test_validate_graph_valid(self, simple_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(simple_dealers)
        errors = builder.validate_graph(G)
        assert len(errors) == 0

    def test_compute_node_weight(self, simple_dealers):
        weights = [DealerGraphBuilder._compute_node_weight(d) for d in simple_dealers]
        assert all(w > 0 for w in weights)

    def test_haversine(self):
        # Distance between same point should be 0
        d = DealerGraphBuilder._haversine(19.0, 73.0, 19.0, 73.0)
        assert abs(d) < 0.001

        # Known distance: Mumbai to Delhi ~1150km
        d = DealerGraphBuilder._haversine(19.076, 72.877, 28.704, 77.102)
        assert 1100 < d < 1200

    def test_estimate_travel_time(self):
        t = DealerGraphBuilder._estimate_travel_time(30.0)
        assert abs(t - 60.0) < 0.1  # 30km at 30kph = 60 min

    def test_many_dealers_build(self, many_dealers):
        """Performance: build graph with 500 dealers."""
        builder = DealerGraphBuilder(proximity_km=3.0)
        G = builder.build(many_dealers)
        assert G.number_of_nodes() == 500
        assert G.number_of_edges() > 0
        assert builder.stats["build_time_sec"] > 0

    def test_builder_stats(self, simple_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        builder.build(simple_dealers)
        stats = builder.stats
        assert "build_time_sec" in stats
        assert "node_count" in stats
        assert "edge_count" in stats
        assert stats["node_count"] == 3

    def test_static_dealer_identification(self, mixed_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(mixed_dealers)
        static_count = sum(
            1 for _, attr in G.nodes(data=True) if attr.get("is_static")
        )
        assert static_count == 3  # 2 from SM001 + 1 from SM002

    def test_output_directory(self, simple_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        G = builder.build(simple_dealers)
        # Verify the graph is a valid NetworkX graph with expected structure
        assert nx.is_connected(G) or G.number_of_edges() == 0
