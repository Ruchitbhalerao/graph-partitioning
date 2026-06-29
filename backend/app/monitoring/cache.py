"""Caching utilities for the optimization system.

Provides:
  - TTLCache — time-based expiration cache
  - LRUCache — least-recently-used eviction cache
  - memoized — decorator for caching function results
  - GraphCache — specialized cache for NetworkX subgraphs
  - PolygonCache — cache for generated territory polygons
"""

import time
import threading
import functools
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple, List

from .metrics import get_metrics, METRIC_CACHE_HIT, METRIC_CACHE_MISS


class TTLCache:
    """Time-to-live cache with configurable expiration.

    Items expire after `ttl_seconds` from insertion.
    Thread-safe for concurrent access.
    """

    def __init__(self, ttl_seconds: float = 300.0, maxsize: int = 1000):
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._store: Dict[Any, Tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: Any) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                get_metrics().increment(METRIC_CACHE_MISS)
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                get_metrics().increment(METRIC_CACHE_MISS)
                return None
            get_metrics().increment(METRIC_CACHE_HIT)
            return value

    def set(self, key: Any, value: Any):
        with self._lock:
            expires_at = time.monotonic() + self._ttl
            self._store[key] = (expires_at, value)
            self._evict_if_needed()

    def _evict_if_needed(self):
        if len(self._store) > self._maxsize:
            # Remove oldest entries
            oldest = sorted(self._store.items(), key=lambda x: x[1][0])
            for k, _ in oldest[:len(oldest) - self._maxsize]:
                del self._store[k]

    def clear(self):
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


class LRUCache:
    """Least-recently-used cache with max size."""

    def __init__(self, maxsize: int = 1000):
        self._maxsize = maxsize
        self._store: OrderedDict = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: Any) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                get_metrics().increment(METRIC_CACHE_MISS)
                return None
            self._store.move_to_end(key)
            get_metrics().increment(METRIC_CACHE_HIT)
            return self._store[key]

    def set(self, key: Any, value: Any):
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            if len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def clear(self):
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def keys(self) -> list:
        with self._lock:
            return list(self._store.keys())


def memoized(ttl_seconds: float = 300.0, maxsize: int = 100):
    """Decorator that caches function results with TTL expiry.

    Usage:
        @memoized(ttl_seconds=60)
        def expensive_computation(x, y):
            ...
    """
    cache = TTLCache(ttl_seconds=ttl_seconds, maxsize=maxsize)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            result = cache.get(key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result
        return wrapper
    return decorator


class GraphCache:
    """Specialized cache for NetworkX subgraphs per SM region.

    Avoids rebuilding the proximity graph for each SM region by
    caching the full graph and providing O(1) subgraph extraction.
    """

    def __init__(self):
        self._full_graph = None
        self._node_to_sm: Dict[str, str] = {}
        self._sm_subgraphs: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def set_full_graph(self, graph, node_to_sm: Dict[str, str]):
        with self._lock:
            self._full_graph = graph
            self._node_to_sm = node_to_sm
            self._sm_subgraphs.clear()

    def get_sm_subgraph(self, sm_id: str, dealer_ids: List[str]):
        """Get or create a subgraph for an SM region."""
        with self._lock:
            if sm_id not in self._sm_subgraphs:
                nodes_in_sm = [
                    n for n in dealer_ids
                    if n in self._full_graph
                    and self._node_to_sm.get(n) == sm_id
                ]
                self._sm_subgraphs[sm_id] = self._full_graph.subgraph(nodes_in_sm)
            return self._sm_subgraphs[sm_id]

    def get_full_graph(self):
        return self._full_graph

    def clear(self):
        with self._lock:
            self._full_graph = None
            self._node_to_sm.clear()
            self._sm_subgraphs.clear()


class PolygonCache:
    """Cache for generated territory polygons.

    Polygons are expensive to compute (ConvexHull + smoothing + buffering)
    and are needed multiple times (analytics, export, validation).
    """

    def __init__(self, maxsize: int = 500):
        self._cache: Dict[str, Any] = {}
        self._maxsize = maxsize
        self._lock = threading.RLock()

    def get(self, territory_key: str):
        with self._lock:
            entry = self._cache.get(territory_key)
            if entry is not None:
                get_metrics().increment(METRIC_CACHE_HIT, labels={"type": "polygon"})
            else:
                get_metrics().increment(METRIC_CACHE_MISS, labels={"type": "polygon"})
            return entry

    def set(self, territory_key: str, polygon):
        with self._lock:
            if len(self._cache) >= self._maxsize:
                # Evict oldest
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[territory_key] = polygon

    def clear(self):
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)


# Global caches
_graph_cache = GraphCache()
_polygon_cache = PolygonCache()


def get_graph_cache() -> GraphCache:
    return _graph_cache


def get_polygon_cache() -> PolygonCache:
    return _polygon_cache
