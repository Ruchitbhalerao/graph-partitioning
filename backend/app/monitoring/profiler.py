"""Profiling decorators and utilities for performance measurement.

Provides:
  - @profile — decorator that records timing + memory to metrics
  - @track_calls — decorator that counts calls and records duration
  - Profiler — context manager for manual profiling blocks
"""

import functools
import tracemalloc
import time
from typing import Optional, Dict, Callable, Any

from .metrics import get_metrics, Timer


def profile(metric_name: Optional[str] = None, labels: Optional[Dict[str, str]] = None):
    """Decorator that times a function and records to metrics.

    Usage:
        @profile(metric_name="my_func_time")
        def my_func():
            ...
    """
    def decorator(func: Callable) -> Callable:
        name = metric_name or f"{func.__module__}.{func.__qualname__}"
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with Timer(name, labels):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def track_calls(metric_name: Optional[str] = None):
    """Decorator that counts function calls and tracks duration.

    Records:
      - call count (counter)
      - last duration (gauge)
      - histogram of durations
    """
    def decorator(func: Callable) -> Callable:
        name = metric_name or f"{func.__module__}.{func.__qualname__}"
        counter_name = f"{name}_calls"
        duration_name = f"{name}_duration"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            get_metrics().increment(counter_name)
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                get_metrics().gauge(duration_name, elapsed)
                get_metrics().observe(duration_name, elapsed)
        return wrapper
    return decorator


class MemoryProfiler:
    """Context manager for memory profiling a block of code."""

    def __init__(self, metric_name: str = "memory_usage"):
        self.metric_name = metric_name
        self._snapshot_start = None
        self._snapshot_end = None
        self._tracing = False

    def __enter__(self):
        tracemalloc.start()
        self._tracing = True
        self._snapshot_start = tracemalloc.take_snapshot()
        return self

    def __exit__(self, *args):
        self._snapshot_end = tracemalloc.take_snapshot()
        if self._tracing:
            tracemalloc.stop()
            self._tracing = False
        self._report()

    def current_memory(self) -> int:
        """Get current memory usage in bytes."""
        snapshot = tracemalloc.take_snapshot()
        total = sum(stat.size for stat in snapshot.statistics("lineno"))
        return total

    def _report(self):
        if self._snapshot_start and self._snapshot_end:
            diff = self._snapshot_end.compare_to(self._snapshot_start, "lineno")
            total_diff = sum(d.size_diff for d in diff)
            get_metrics().gauge(self.metric_name, total_diff)

    def top_lines(self, n: int = 10) -> list:
        """Return top N memory-consuming lines."""
        if not self._snapshot_end:
            return []
        stats = self._snapshot_end.statistics("lineno")
        return [(stat, stat.size) for stat in stats[:n]]


class CumulativeProfiler:
    """Accumulate timing for repeated operations (e.g., per-SM costs)."""

    def __init__(self):
        self._totals: Dict[str, float] = {}
        self._counts: Dict[str, int] = {}

    def record(self, key: str, duration: float):
        self._totals[key] = self._totals.get(key, 0.0) + duration
        self._counts[key] = self._counts.get(key, 0) + 1

    def total(self, key: str) -> float:
        return self._totals.get(key, 0.0)

    def count(self, key: str) -> int:
        return self._counts.get(key, 0)

    def avg(self, key: str) -> float:
        c = self.count(key)
        return self.total(key) / max(c, 1)

    def snapshot(self) -> Dict:
        return {
            k: {
                "total_sec": round(v, 4),
                "count": self._counts.get(k, 0),
                "avg_sec": round(v / max(self._counts.get(k, 0), 1), 4),
            }
            for k, v in self._totals.items()
        }
