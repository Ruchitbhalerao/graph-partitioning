"""Unit tests for MultilevelPartitioner and TerritoryPartitioner."""

import pytest
import networkx as nx

from app.optimization.partitioner import (
    MultilevelPartitioner, TerritoryPartitioner, PartitionMetrics, CoarsenedNode,
)
from app.optimization.graph_builder import DealerGraphBuilder
from app.models.enums import DealerType
from helpers import make_dealer


class TestMultilevelPartitioner:
    def test_empty_graph(self):
        partitioner = MultilevelPartitioner()
        result = partitioner.partition(
            nx.Graph(), 1, {}, {}, {},
        )
        assert result == {}

    def test_k_zero_raises(self, simple_graph):
        partitioner = MultilevelPartitioner()
        with pytest.raises(ValueError, match="num_partitions must be > 0"):
            partitioner.partition(simple_graph, 0, {}, {}, {})

    def test_single_partition(self, simple_graph):
        partitioner = MultilevelPartitioner()
        result = partitioner.partition(
            simple_graph, 1,
            {"FTC_1": 1.0},
            {}, {},
        )
        assert "FTC_1" in result
        assert len(result["FTC_1"]) == simple_graph.number_of_nodes()

    def test_two_partitions_small_graph(self, simple_graph, simple_ftcs):
        partitioner = MultilevelPartitioner()
        capacities = {f.FTC_id: 1.0 for f in simple_ftcs}
        anchors = {"FTC_1": "DLR_A", "FTC_2": "DLR_C"}
        result = partitioner.partition(
            simple_graph, 2, capacities, anchors, {},
        )
        assert len(result) == 2
        assert "FTC_1" in result
        assert "FTC_2" in result
        total = sum(len(v) for v in result.values())
        assert total == simple_graph.number_of_nodes()

    def test_heavy_edge_matching(self, simple_graph):
        matching = MultilevelPartitioner._heavy_edge_matching(simple_graph)
        assert isinstance(matching, list)
        for u, v in matching:
            assert simple_graph.has_edge(u, v)

    def test_contract_keep_coarsenodes(self, simple_graph):
        matching = MultilevelPartitioner._heavy_edge_matching(simple_graph)
        if matching:
            node_weights = {n: simple_graph.nodes[n].get("weight", 1.0) for n in simple_graph.nodes()}
            coarse, cnodes = MultilevelPartitioner._contract_keep_coarsenodes(
                simple_graph, matching, node_weights
            )
            assert isinstance(coarse, nx.Graph)
            assert len(cnodes) > 0

    def test_select_seeds(self, simple_graph):
        partitioner = MultilevelPartitioner()
        seeds = partitioner._select_seeds(
            simple_graph, {"FTC_1": "DLR_A"}, 2, ["FTC_1", "FTC_2"]
        )
        assert "FTC_1" in seeds
        assert seeds["FTC_1"] == "DLR_A"
        assert "FTC_2" in seeds

    def test_project_kway_down(self):
        from app.optimization.partitioner import CoarsenedNode
        cnodes = {
            "c0": CoarsenedNode(id="c0", weight=2.0, members=["A", "B"]),
            "c1": CoarsenedNode(id="c1", weight=1.0, members=["C"]),
        }
        coarse_assign = {"c0": "FTC_1", "c1": "FTC_2"}
        fine = MultilevelPartitioner._project_kway_down(coarse_assign, cnodes)
        assert fine["A"] == "FTC_1"
        assert fine["B"] == "FTC_1"
        assert fine["C"] == "FTC_2"

    def test_metrics(self, simple_graph, simple_ftcs):
        partitioner = MultilevelPartitioner()
        capacities = {f.FTC_id: 1.0 for f in simple_ftcs}
        anchors = {"FTC_1": "DLR_A", "FTC_2": "DLR_C"}
        result = partitioner.partition(
            simple_graph, 2, capacities, anchors, {},
        )
        metrics = partitioner.metrics
        assert isinstance(metrics, PartitionMetrics)
        assert metrics.partition_count == 2
        assert metrics.total_edge_cut >= 0
        assert metrics.elapsed_sec > 0

    def test_coarsening_levels_tracked(self, mixed_graph):
        """Verify coarsening is recorded for a larger graph."""
        partitioner = MultilevelPartitioner(max_coarsest_nodes=5)
        capacities = {"FTC_SM1_A": 1.0, "FTC_SM1_B": 1.0}
        # Only use SM001 subgraph for controlled test
        sm1_nodes = [n for n, a in mixed_graph.nodes(data=True) if a.get("sm_id") == "SM001"]
        sub = mixed_graph.subgraph(sm1_nodes).copy()
        if len(sm1_nodes) >= 5:
            result = partitioner.partition(
                sub, 2, capacities, {}, {},
            )
            assert partitioner.metrics.coarsening_levels >= 0


class TestTerritoryPartitioner:
    def test_empty_dealers(self, processor):
        builder = DealerGraphBuilder(proximity_km=5.0)
        partitioner = TerritoryPartitioner(builder)
        from app.models.schemas import FTCRecord
        result = partitioner.partition([], [], {}, {})
        assert result == {}

    def test_empty_ftcs(self, simple_dealers):
        builder = DealerGraphBuilder(proximity_km=5.0)
        partitioner = TerritoryPartitioner(builder)
        result = partitioner.partition(simple_dealers, [], {}, {})
        assert result == {}

    def test_all_static_dealers(self, processor):
        """When all dealers are static, assignments pass through."""
        static = [
            make_dealer("S1", dealer_type=DealerType.STATIC, lat=19.0, lng=73.0),
            make_dealer("S2", dealer_type=DealerType.STATIC, lat=19.01, lng=73.01),
        ]
        from app.models.schemas import FTCRecord
        from app.models.enums import ProductGroup
        ftcs = [
            FTCRecord(FTC_id="FTC_1", SM_id="SM001", Product_Group=ProductGroup.PRODUCT_A, Average_cases_per_day=10.0),
            FTCRecord(FTC_id="FTC_2", SM_id="SM001", Product_Group=ProductGroup.PRODUCT_A, Average_cases_per_day=10.0),
        ]
        builder = DealerGraphBuilder(proximity_km=5.0)
        partitioner = TerritoryPartitioner(builder)
        static_assign = {"FTC_1": ["S1"], "FTC_2": ["S2"]}
        result = partitioner.partition(static, ftcs, static_assign, {})
        assert result["FTC_1"] == ["S1"]
        assert result["FTC_2"] == ["S2"]

    def test_mobile_partition(self, mixed_dealers, mixed_ftcs, processor):
        """Partition mobile dealers across 2 FTCs in SM001."""
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        sm1_static = [d for d in sm1_dealers if d.Dealer_type == DealerType.STATIC]
        sm1_mobile = [d for d in sm1_dealers if d.Dealer_type == DealerType.MOBILE]
        static_assign = {"FTC_SM1_A": [d.Dealer_id for d in sm1_static]}
        builder = DealerGraphBuilder(proximity_km=5.0)
        partitioner = TerritoryPartitioner(builder)
        result = partitioner.partition(sm1_dealers, sm1_ftcs, static_assign, {})
        assert "FTC_SM1_A" in result
        assert "FTC_SM1_B" in result
        total = sum(len(v) for v in result.values())
        assert total == len(sm1_dealers)

    def test_anchor_assignment(self, mixed_dealers, mixed_ftcs, processor):
        """Anchor dealers stay fixed in their FTC."""
        from app.data.processor import DataProcessor
        proc = DataProcessor()
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        anchors = proc.select_anchor_dealers(
            [d for d in sm1_dealers if d.Dealer_type == DealerType.MOBILE],
            sm1_ftcs,
        )
        builder = DealerGraphBuilder(proximity_km=5.0)
        partitioner = TerritoryPartitioner(builder)
        result = partitioner.partition(sm1_dealers, sm1_ftcs, {}, anchors)
        # Anchor dealers should be assigned to their respective FTCs
        for ftc_id, anchor in anchors.items():
            assert anchor.Dealer_id in result.get(ftc_id, [])

    def test_metrics_recorded(self, mixed_dealers, mixed_ftcs):
        """Partition metrics are populated after a run."""
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        builder = DealerGraphBuilder(proximity_km=5.0)
        partitioner = TerritoryPartitioner(builder)
        partitioner.partition(sm1_dealers, sm1_ftcs, {}, {})
        metrics = partitioner.metrics
        assert metrics.partition_count > 0
        assert metrics.elapsed_sec >= 0
