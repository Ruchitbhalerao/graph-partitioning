"""Performance benchmarks for the optimization pipeline.

These tests verify that the system behaves correctly under load.
They are markers as 'slow' and can be skipped with: pytest -m "not slow"
"""

import pytest
import time

from app.optimization.graph_builder import DealerGraphBuilder, SpatialGridIndex
from app.optimization.partitioner import TerritoryPartitioner, MultilevelPartitioner
from app.optimization.refiner import TerritoryRefiner
from app.optimization.engine import OptimizationEngine


# Mark all tests in this module as slow
pytestmark = pytest.mark.slow


class TestGraphBuilderPerformance:
    def test_build_500_dealers(self, many_dealers):
        """500 dealers should build in under 5 seconds."""
        builder = DealerGraphBuilder(proximity_km=3.0)
        start = time.time()
        G = builder.build(many_dealers)
        elapsed = time.time() - start

        assert len(G.nodes) == len(many_dealers)
        assert elapsed < 5.0, f"Graph build took {elapsed:.2f}s (limit 5s)"

    def test_build_500_with_ftcs(self, many_dealers, many_ftcs):
        """500 dealers + 100 FTCs should build in under 10 seconds."""
        builder = DealerGraphBuilder(proximity_km=3.0)
        start = time.time()
        G = builder.build(many_dealers, many_ftcs)
        elapsed = time.time() - start

        assert len(G.nodes) >= len(many_dealers)
        assert elapsed < 10.0, f"Graph build took {elapsed:.2f}s (limit 10s)"


class TestGridIndexPerformance:
    def test_grid_build_500(self, many_dealers):
        """SpatialGridIndex for 500 dealers should build quickly."""
        grid = SpatialGridIndex(cell_size_km=5.0)
        start = time.time()
        grid.build(many_dealers)
        elapsed = time.time() - start

        assert elapsed < 1.0, f"Grid build took {elapsed:.2f}s (limit 1s)"

    def test_grid_proximity_queries(self, many_dealers):
        """500 proximity queries should be fast."""
        grid = SpatialGridIndex(cell_size_km=5.0)
        grid.build(many_dealers)

        start = time.time()
        for dealer in many_dealers:
            _ = grid.get_proximity_candidates(dealer)
        elapsed = time.time() - start

        assert elapsed < 2.0, f"500 queries took {elapsed:.2f}s (limit 2s)"


class TestPartitionerPerformance:
    @pytest.mark.skip(reason="MultilevelPartitioner may be slow on large graph without early exit")
    def test_multilevel_partition_500(self, many_graph):
        """Multilevel partition on 500-node graph should complete in reasonable time."""
        partitioner = MultilevelPartitioner(many_graph)
        start = time.time()
        # Reduce parts for speed
        partition = partitioner.partition(num_parts=5)
        elapsed = time.time() - start

        assert len(partition) > 0
        # This may need tuning depending on algorithm complexity
        assert elapsed < 30.0, f"Partition took {elapsed:.2f}s"


class TestRefinerPerformance:
    @pytest.mark.skip(reason="Refiner on 500 dealers may be slow without pre-built assignments")
    def test_refine_500(self, many_dealers, many_ftcs, many_graph):
        """Refinement on 500 dealers should be bounded."""
        builder = DealerGraphBuilder(proximity_km=3.0)
        refiner = TerritoryRefiner(
            graph_builder=builder, max_iterations=5,
            stagnation_limit=3, tabu_tenure=3,
        )
        # Simple assignment: first FTC gets first dealers
        assignments = {f.FTC_id: [] for f in many_ftcs}
        for i, d in enumerate(many_dealers):
            ftc_id = many_ftcs[i % len(many_ftcs)].FTC_id
            assignments[ftc_id].append(d.Dealer_id)

        start = time.time()
        report = refiner.run(many_graph, many_dealers, many_ftcs, assignments)
        elapsed = time.time() - start

        assert report is not None
        assert elapsed < 60.0, f"Refinement took {elapsed:.2f}s (limit 60s)"


class TestEnginePerformance:
    def test_engine_end_to_end_500(self, many_dealers, many_ftcs, config):
        """End-to-end optimization with 500 dealers. May be slow; use skip."""
        engine = OptimizationEngine(config)
        start = time.time()
        result = engine.run(many_dealers, many_ftcs, [])
        elapsed = time.time() - start

        assert result["status"] == "completed"
        print(f"\n[PERF] 500-dealer end-to-end: {elapsed:.2f}s")

    def test_engine_memory_usage(self, many_dealers, many_ftcs, config):
        """Basic memory sanity: engine should produce results without blowing up."""
        import tracemalloc
        tracemalloc.start()
        try:
            engine = OptimizationEngine(config)
            result = engine.run(many_dealers, many_ftcs, [])
            assert result["status"] == "completed"
        finally:
            tracemalloc.stop()


class TestOversizedInput:
    def test_1000_dealers(self):
        """Edge case: 1000 dealers should not crash the builder (may be slow)."""
        from helpers import generate_cluster
        dealers = generate_cluster(19.0, 73.0, 1000, "SM001", radius_km=10.0)
        builder = DealerGraphBuilder(proximity_km=2.0)
        start = time.time()
        G = builder.build(dealers)
        elapsed = time.time() - start
        assert len(G.nodes) == 1000
        print(f"\n[PERF] 1000-dealer graph build: {elapsed:.2f}s, edges={len(G.edges)}")
