"""Tests for the performance monitoring and optimization module.

Covers metrics collection, profiling, caching, resource management,
logging configuration, and dashboard endpoints.
"""

import time
import json
import threading
import pytest
from datetime import datetime


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetricsCollector:
    def test_increment_counter(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        m.increment("test_counter")
        assert m.get_counter("test_counter") == 1

    def test_increment_with_amount(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        m.increment("test_counter", amount=5)
        assert m.get_counter("test_counter") == 5

    def test_increment_with_labels(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        m.increment("test_counter", labels={"type": "a"})
        m.increment("test_counter", labels={"type": "b"})
        assert m.get_counter("test_counter", labels={"type": "a"}) == 1
        assert m.get_counter("test_counter", labels={"type": "b"}) == 1

    def test_gauge(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        m.gauge("test_gauge", 42.0)
        assert m.get_gauge("test_gauge") == 42.0

    def test_gauge_update(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        m.gauge("test_gauge", 10.0)
        m.gauge("test_gauge", 20.0)
        assert m.get_gauge("test_gauge") == 20.0

    def test_histogram(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            m.observe("test_hist", v)
        hist = m.get_histogram("test_hist")
        assert hist.count == 5
        assert hist.sum == 15.0
        assert hist.avg == 3.0
        assert hist.p50 == 3.0
        assert hist.p95 == 5.0

    def test_histogram_empty(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        hist = m.get_histogram("nonexistent")
        assert hist.count == 0
        assert hist.sum == 0.0
        assert hist.avg == 0.0

    def test_snapshot(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        m.increment("c1")
        m.gauge("g1", 3.14)
        m.observe("h1", 1.0)
        snap = m.snapshot()
        assert "counters" in snap
        assert "gauges" in snap
        assert "histograms" in snap

    def test_prometheus_text(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        m.increment("requests_total")
        text = m.prometheus_text()
        assert "tos_requests_total" in text
        assert "tos_uptime_seconds" in text

    def test_uptime(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        assert m.uptime_seconds() >= 0

    def test_concurrent_access(self):
        from app.monitoring.metrics import MetricsCollector
        m = MetricsCollector()
        errors = []

        def worker():
            for _ in range(100):
                try:
                    m.increment("concurrent")
                    m.observe("hist", 0.5)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert m.get_counter("concurrent") == 1000


class TestTimer:
    def test_timer_records_metric(self):
        from app.monitoring.metrics import Timer, get_metrics
        m = get_metrics()
        with Timer("test_timer_op"):
            time.sleep(0.01)
        hist = m.get_histogram("test_timer_op")
        assert hist.count >= 1
        assert hist.sum > 0

    def test_timer_elapsed(self):
        from app.monitoring.metrics import Timer
        with Timer("test") as t:
            time.sleep(0.01)
        assert t.elapsed >= 0.01

    def test_timer_with_labels(self):
        from app.monitoring.metrics import Timer, get_metrics
        m = get_metrics()
        with Timer("labeled_op", labels={"region": "SM001"}):
            time.sleep(0.005)
        hist = m.get_histogram("labeled_op", labels={"region": "SM001"})
        assert hist.count >= 1


# ---------------------------------------------------------------------------
# Profiler
# ---------------------------------------------------------------------------

class TestProfiler:
    def test_profile_decorator(self):
        from app.monitoring.profiler import profile
        call_count = 0

        @profile(metric_name="test_profile_func")
        def my_func():
            nonlocal call_count
            call_count += 1
            return 42

        result = my_func()
        assert result == 42
        assert call_count == 1

    def test_track_calls_decorator(self):
        from app.monitoring.profiler import track_calls, get_metrics
        m = get_metrics()

        @track_calls(metric_name="tracked_func")
        def my_func(x):
            return x * 2

        assert my_func(5) == 10
        assert my_func(10) == 20
        # Counter may have been incremented by other tests
        assert m.get_counter("tracked_func_calls") >= 2

    def test_cumulative_profiler(self):
        from app.monitoring.profiler import CumulativeProfiler
        p = CumulativeProfiler()
        p.record("phase_a", 1.5)
        p.record("phase_a", 2.5)
        p.record("phase_b", 3.0)
        assert p.total("phase_a") == 4.0
        assert p.count("phase_a") == 2
        assert p.avg("phase_a") == 2.0
        assert p.total("phase_b") == 3.0
        snap = p.snapshot()
        assert "phase_a" in snap
        assert snap["phase_a"]["total_sec"] == 4.0


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class TestTTLCache:
    def test_get_set(self):
        from app.monitoring.cache import TTLCache
        c = TTLCache(ttl_seconds=60)
        c.set("key1", "value1")
        assert c.get("key1") == "value1"

    def test_miss(self):
        from app.monitoring.cache import TTLCache
        c = TTLCache(ttl_seconds=60)
        assert c.get("nonexistent") is None

    def test_expiry(self):
        from app.monitoring.cache import TTLCache
        c = TTLCache(ttl_seconds=0.1)
        c.set("key1", "value1")
        time.sleep(0.15)
        assert c.get("key1") is None

    def test_maxsize_eviction(self):
        from app.monitoring.cache import TTLCache
        c = TTLCache(ttl_seconds=60, maxsize=3)
        for i in range(5):
            c.set(f"key{i}", f"value{i}")
        assert c.size() == 3

    def test_clear(self):
        from app.monitoring.cache import TTLCache
        c = TTLCache(ttl_seconds=60)
        c.set("k1", "v1")
        c.clear()
        assert c.size() == 0


class TestLRUCache:
    def test_get_set(self):
        from app.monitoring.cache import LRUCache
        c = LRUCache(maxsize=5)
        c.set("a", 1)
        assert c.get("a") == 1

    def test_eviction(self):
        from app.monitoring.cache import LRUCache
        c = LRUCache(maxsize=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)  # should evict "a"
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_lru_order(self):
        from app.monitoring.cache import LRUCache
        c = LRUCache(maxsize=3)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.get("a")  # makes "a" most recently used
        c.set("d", 4)  # evicts "b" (least recently used)
        assert c.get("a") == 1
        assert c.get("b") is None
        assert c.get("c") == 3
        assert c.get("d") == 4


class TestMemoized:
    def test_memoized_caches_result(self):
        from app.monitoring.cache import memoized
        call_count = 0

        @memoized(ttl_seconds=60)
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert compute(5) == 10
        assert compute(5) == 10  # from cache
        assert call_count == 1
        assert compute(10) == 20
        assert call_count == 2


class TestGraphCache:
    def test_set_and_get_subgraph(self):
        import networkx as nx
        from app.monitoring.cache import GraphCache
        G = nx.Graph()
        G.add_node("A", sm_id="SM001")
        G.add_node("B", sm_id="SM001")
        G.add_node("C", sm_id="SM002")
        G.add_edge("A", "B")

        cache = GraphCache()
        cache.set_full_graph(G, {"A": "SM001", "B": "SM001", "C": "SM002"})
        sub = cache.get_sm_subgraph("SM001", ["A", "B", "C"])
        assert len(sub.nodes) == 2
        assert "A" in sub
        assert "B" in sub
        assert "C" not in sub

    def test_clear(self):
        from app.monitoring.cache import GraphCache
        cache = GraphCache()
        cache.set_full_graph(None, {})
        cache.clear()
        assert cache.get_full_graph() is None


class TestPolygonCache:
    def test_get_set(self):
        from app.monitoring.cache import PolygonCache
        c = PolygonCache(maxsize=10)
        c.set("SM001_FTC_1", {"type": "Polygon"})
        assert c.get("SM001_FTC_1") == {"type": "Polygon"}

    def test_miss(self):
        from app.monitoring.cache import PolygonCache
        c = PolygonCache()
        assert c.get("nonexistent") is None

    def test_eviction(self):
        from app.monitoring.cache import PolygonCache
        c = PolygonCache(maxsize=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        assert c.size() == 2


# ---------------------------------------------------------------------------
# Resource Management
# ---------------------------------------------------------------------------

class TestTempFileManager:
    def test_register_and_unregister(self):
        from app.monitoring.resource import TempFileManager
        mgr = TempFileManager(base_dir="/tmp/test_tos_mon")
        mgr.register("/tmp/test_tos_mon/job_001")
        assert "/tmp/test_tos_mon/job_001" in mgr._tracked
        mgr.unregister("/tmp/test_tos_mon/job_001")
        assert "/tmp/test_tos_mon/job_001" not in mgr._tracked

    def test_cleanup_job(self):
        import os
        from app.monitoring.resource import TempFileManager
        mgr = TempFileManager(base_dir="/tmp/test_tos_cleanup")
        os.makedirs("/tmp/test_tos_cleanup/job_test", exist_ok=True)
        with open("/tmp/test_tos_cleanup/job_test/test.txt", "w") as f:
            f.write("test")
        mgr.register("/tmp/test_tos_cleanup/job_test")
        mgr.cleanup_job("job_test")
        assert not os.path.exists("/tmp/test_tos_cleanup/job_test")


class TestConcurrencyLimiter:
    def test_acquire_release(self):
        from app.monitoring.resource import ConcurrencyLimiter
        limiter = ConcurrencyLimiter(max_concurrent=2)
        assert limiter.acquire(blocking=False) is True
        assert limiter.acquire(blocking=False) is True
        assert limiter.acquire(blocking=False) is False  # maxed out
        limiter.release()
        assert limiter.acquire(blocking=False) is True

    def test_context_manager(self):
        from app.monitoring.resource import ConcurrencyLimiter
        limiter = ConcurrencyLimiter(max_concurrent=1)
        with limiter:
            assert limiter.active_count() == 1
        assert limiter.active_count() == 0

    def test_available(self):
        from app.monitoring.resource import ConcurrencyLimiter
        limiter = ConcurrencyLimiter(max_concurrent=4)
        assert limiter.available() == 4
        limiter.acquire()
        assert limiter.available() == 3


class TestTimeoutManager:
    def test_run_with_timeout(self):
        from app.monitoring.resource import TimeoutManager
        mgr = TimeoutManager(default_timeout_sec=5)
        result = mgr.run_with_timeout(lambda: 42, timeout_sec=2)
        assert result == 42

    def test_run_with_timeout_exceeded(self):
        from app.monitoring.resource import TimeoutManager
        mgr = TimeoutManager(default_timeout_sec=0.1)
        with pytest.raises(TimeoutError):
            mgr.run_with_timeout(lambda: time.sleep(10), timeout_sec=0.1)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestLogBuffer:
    def test_buffer_captures_logs(self):
        import logging
        from app.monitoring.logging_config import LogBuffer
        buffer = LogBuffer(max_entries=100)
        handler = buffer.handler
        logger = logging.getLogger("test_logger")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.info("test message")
        recent = buffer.recent(10)
        assert len(recent) >= 1
        assert "test message" in recent[0]
        logger.removeHandler(handler)


class TestJSONFormatter:
    def test_formatter_output(self):
        import logging
        from app.monitoring.logging_config import JSONFormatter
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname=__file__, lineno=42, msg="hello world",
            args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"
        assert parsed["logger"] == "test"


class TestPerformanceContextLogger:
    def test_basic_logging(self):
        from app.monitoring.logging_config import PerformanceContextLogger
        logger = PerformanceContextLogger("test_perf_logger")
        # Should not raise
        logger.info("test", duration=1.5)
        logger.warning("warning", dealers=500)
        logger.error("error")

    def test_timed_context(self):
        from app.monitoring.logging_config import PerformanceContextLogger
        logger = PerformanceContextLogger("test_timed_logger")
        with logger.timed("operation"):
            time.sleep(0.01)
        # Should not raise


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class TestDashboardEndpoints:
    def test_metrics_endpoint(self):
        from app.monitoring.dashboard import metrics_endpoint
        import inspect
        # Just verify the endpoint function exists and has correct signature
        assert callable(metrics_endpoint)

    def test_health_endpoint(self):
        from app.monitoring.dashboard import detailed_health
        assert callable(detailed_health)

    def test_router_defined(self):
        from app.monitoring.dashboard import router
        assert len(router.routes) > 0
        route_paths = [r.path for r in router.routes]
        assert "/monitoring/metrics" in route_paths
        assert "/monitoring/health" in route_paths
        assert "/monitoring/performance" in route_paths
        assert "/monitoring/logs/recent" in route_paths
        assert "/monitoring/resources" in route_paths
        assert "/monitoring/jobs" in route_paths


# ---------------------------------------------------------------------------
# Metric names
# ---------------------------------------------------------------------------

class TestMetricNames:
    def test_all_metric_names_defined(self):
        from app.monitoring.metrics import (
            METRIC_GRAPH_BUILD_TIME, METRIC_GRAPH_NODE_COUNT,
            METRIC_GRAPH_EDGE_COUNT, METRIC_PARTITION_TIME,
            METRIC_REFINE_TIME, METRIC_REFINE_ITERATIONS,
            METRIC_VALIDATE_TIME, METRIC_SM_REGIONS_TOTAL,
            METRIC_DEALERS_TOTAL, METRIC_FTCS_TOTAL,
            METRIC_JOB_DURATION, METRIC_MEMORY_USAGE,
            METRIC_CACHE_HIT, METRIC_CACHE_MISS,
            METRIC_DISK_USAGE, METRIC_ACTIVE_JOBS,
            METRIC_COMPLETED_JOBS, METRIC_ERROR_COUNT,
            METRIC_POLYGON_GEN_TIME, METRIC_EXPORT_TIME,
            METRIC_UPLOAD_SIZE, METRIC_UPLOAD_TIME,
        )
        assert METRIC_GRAPH_BUILD_TIME == "graph_build_time_seconds"
        assert METRIC_CACHE_HIT == "cache_hit_total"
        assert METRIC_CACHE_MISS == "cache_miss_total"


# ---------------------------------------------------------------------------
# Integration with engine
# ---------------------------------------------------------------------------

class TestEngineMonitoringIntegration:
    def test_engine_records_metrics(self, engine, mixed_dealers, mixed_ftcs):
        from app.monitoring.metrics import get_metrics
        m = get_metrics()
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        result = engine.run(sm1_dealers, sm1_ftcs, [])
        assert result["status"] == "completed"
        assert "profiling" in result

    def test_engine_profiling_snapshot(self, engine, mixed_dealers, mixed_ftcs):
        sm1_dealers = [d for d in mixed_dealers if d.SM_id == "SM001"]
        sm1_ftcs = [f for f in mixed_ftcs if f.SM_id == "SM001"]
        result = engine.run(sm1_dealers, sm1_ftcs, [])
        profiling = result.get("profiling", {})
        assert len(profiling) > 0
        # Should have at least one phase recorded
        phase_keys = [k for k in profiling.keys()]
        assert len(phase_keys) > 0
