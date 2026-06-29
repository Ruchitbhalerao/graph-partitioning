"""Metrics collection for performance monitoring.

Provides counters, gauges, histograms, and a Prometheus-compatible endpoint.
Operates in two modes:
  1. In-memory dict-based (default) — lightweight, no dependencies.
  2. Prometheus client — when prometheus_client is installed.
"""

import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta


@dataclass
class MetricCounter:
    value: int = 0
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricGauge:
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class MetricHistogram:
    values: List[float] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)
    _sum: float = 0.0
    _count: int = 0

    @property
    def sum(self) -> float:
        return self._sum

    @property
    def count(self) -> int:
        return self._count

    @property
    def avg(self) -> float:
        return self._sum / max(self._count, 1)

    @property
    def p50(self) -> float:
        if not self.values:
            return 0.0
        sorted_v = sorted(self.values)
        return sorted_v[len(sorted_v) // 2]

    @property
    def p95(self) -> float:
        if not self.values:
            return 0.0
        sorted_v = sorted(self.values)
        idx = int(len(sorted_v) * 0.95)
        return sorted_v[min(idx, len(sorted_v) - 1)]

    @property
    def p99(self) -> float:
        if not self.values:
            return 0.0
        sorted_v = sorted(self.values)
        idx = int(len(sorted_v) * 0.99)
        return sorted_v[min(idx, len(sorted_v) - 1)]

    def observe(self, value: float):
        self.values.append(value)
        self._sum += value
        self._count += 1
        # Keep last 1000 values for percentile calc
        if len(self.values) > 1000:
            self.values = self.values[-1000:]


class MetricsCollector:
    """Thread-safe metrics collector with label support."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, MetricCounter] = {}
        self._gauges: Dict[str, MetricGauge] = {}
        self._histograms: Dict[str, MetricHistogram] = {}
        self._start_time = datetime.now()

    def increment(self, name: str, amount: int = 1, labels: Optional[Dict[str, str]] = None):
        key = _metric_key(name, labels)
        with self._lock:
            if key not in self._counters:
                self._counters[key] = MetricCounter(labels=labels or {})
            self._counters[key].value += amount

    def gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        key = _metric_key(name, labels)
        with self._lock:
            if key not in self._gauges:
                self._gauges[key] = MetricGauge(labels=labels or {})
            self._gauges[key].value = value

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        key = _metric_key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = MetricHistogram(labels=labels or {})
            self._histograms[key].observe(value)

    def get_counter(self, name: str, labels: Optional[Dict[str, str]] = None) -> int:
        key = _metric_key(name, labels)
        with self._lock:
            return self._counters.get(key, MetricCounter()).value

    def get_gauge(self, name: str, labels: Optional[Dict[str, str]] = None) -> float:
        key = _metric_key(name, labels)
        with self._lock:
            return self._gauges.get(key, MetricGauge()).value

    def get_histogram(self, name: str, labels: Optional[Dict[str, str]] = None) -> MetricHistogram:
        key = _metric_key(name, labels)
        with self._lock:
            return self._histograms.get(key, MetricHistogram())

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "counters": {k: c.value for k, c in self._counters.items()},
                "gauges": {k: g.value for k, g in self._gauges.items()},
                "histograms": {
                    k: {
                        "count": h.count,
                        "sum": round(h.sum, 4),
                        "avg": round(h.avg, 4),
                        "p50": round(h.p50, 4),
                        "p95": round(h.p95, 4),
                        "p99": round(h.p99, 4),
                    }
                    for k, h in self._histograms.items()
                },
            }

    def uptime_seconds(self) -> float:
        return (datetime.now() - self._start_time).total_seconds()

    def prometheus_text(self) -> str:
        lines = [
            "# HELP tos_metrics Territory Optimization System metrics",
            "# TYPE tos_metrics untyped",
        ]
        snapshot = self.snapshot()
        for name, value in snapshot.get("counters", {}).items():
            lines.append(f'tos_{name}{{}} {value}')
        for name, value in snapshot.get("gauges", {}).items():
            lines.append(f'tos_{name}{{}} {value}')
        for name, hist in snapshot.get("histograms", {}).items():
            lines.append(f'tos_{name}_count{{}} {hist["count"]}')
            lines.append(f'tos_{name}_sum{{}} {hist["sum"]}')
            lines.append(f'tos_{name}_avg{{}} {hist["avg"]}')
            lines.append(f'tos_{name}_p95{{}} {hist["p95"]}')
        lines.append(f"tos_uptime_seconds{{}} {self.uptime_seconds()}")
        return "\n".join(lines) + "\n"


def _metric_key(name: str, labels: Optional[Dict[str, str]] = None) -> str:
    if labels:
        parts = [f"{k}={v}" for k, v in sorted(labels.items())]
        return f"{name}[{','.join(parts)}]"
    return name


# Global metrics collector
_global_collector = MetricsCollector()


def get_metrics() -> MetricsCollector:
    return _global_collector


# Metric names
METRIC_GRAPH_BUILD_TIME = "graph_build_time_seconds"
METRIC_GRAPH_NODE_COUNT = "graph_node_count"
METRIC_GRAPH_EDGE_COUNT = "graph_edge_count"
METRIC_PARTITION_TIME = "partition_time_seconds"
METRIC_REFINE_TIME = "refine_time_seconds"
METRIC_REFINE_ITERATIONS = "refine_iterations"
METRIC_VALIDATE_TIME = "validate_time_seconds"
METRIC_SM_REGIONS_TOTAL = "sm_regions_total"
METRIC_DEALERS_TOTAL = "dealers_total"
METRIC_FTCS_TOTAL = "ftcs_total"
METRIC_JOB_DURATION = "job_duration_seconds"
METRIC_MEMORY_USAGE = "memory_usage_bytes"
METRIC_CACHE_HIT = "cache_hit_total"
METRIC_CACHE_MISS = "cache_miss_total"
METRIC_DISK_USAGE = "disk_usage_bytes"
METRIC_ACTIVE_JOBS = "active_jobs"
METRIC_COMPLETED_JOBS = "completed_jobs"
METRIC_ERROR_COUNT = "error_total"
METRIC_POLYGON_GEN_TIME = "polygon_generation_time_seconds"
METRIC_EXPORT_TIME = "export_time_seconds"
METRIC_UPLOAD_SIZE = "upload_size_bytes"
METRIC_UPLOAD_TIME = "upload_processing_time_seconds"


class Timer:
    """Context manager for timing operations and recording to metrics."""

    def __init__(self, metric_name: str, labels: Optional[Dict[str, str]] = None):
        self.metric_name = metric_name
        self.labels = labels
        self._start: Optional[float] = None

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed = time.perf_counter() - self._start
        get_metrics().observe(self.metric_name, elapsed, self.labels)

    @property
    def elapsed(self) -> float:
        if self._start is None:
            return 0.0
        return time.perf_counter() - self._start
