"""Monitoring dashboard — system health, metrics, and performance views.

Provides FastAPI router with endpoints for:
  - GET /monitoring/metrics — Prometheus text format
  - GET /monitoring/health — Detailed system health
  - GET /monitoring/performance — Recent performance snapshots
  - GET /monitoring/logs/recent — Recent log entries (SSE or JSON)
  - GET /monitoring/resources — CPU/memory/disk usage
  - GET /monitoring/jobs — Job statistics
"""

import json
import time
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .metrics import get_metrics
from .resource import get_resource_monitor, get_temp_file_manager
from .logging_config import LogBuffer, JSONFormatter
from .cache import get_graph_cache, get_polygon_cache

import logging

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_log_buffer = LogBuffer(max_entries=1000)


def get_log_buffer() -> LogBuffer:
    return _log_buffer


@router.get("/metrics")
async def metrics_endpoint():
    """Prometheus-compatible metrics endpoint."""
    metrics = get_metrics()
    return Response(
        content=metrics.prometheus_text(),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/metrics/json")
async def metrics_json():
    """JSON snapshot of all metrics."""
    metrics = get_metrics()
    snapshot = metrics.snapshot()
    snapshot["uptime_seconds"] = metrics.uptime_seconds()
    return snapshot


@router.get("/health")
async def detailed_health():
    """Detailed system health check with component status."""
    monitor = get_resource_monitor()
    mem_mb = monitor.memory_usage_mb()
    cpu = monitor.cpu_percent()

    graph_cache = get_graph_cache()
    polygon_cache = get_polygon_cache()

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "memory_mb": round(mem_mb, 1),
        "cpu_percent": cpu,
        "caches": {
            "graph_cache_size": graph_cache._sm_subgraphs.__len__(),
            "polygon_cache_size": polygon_cache.size(),
        },
        "metrics_uptime_sec": round(get_metrics().uptime_seconds(), 1),
        "components": {
            "api": "up",
            "optimization_engine": "up",
        },
    }


@router.get("/performance")
async def performance_snapshot():
    """Current performance metrics snapshot."""
    metrics = get_metrics()
    snapshot = metrics.snapshot()

    # Extract key performance indicators
    hist = snapshot.get("histograms", {})

    def _p95(name: str) -> float:
        h = hist.get(name, {})
        return h.get("p95", 0.0)

    return {
        "timestamp": datetime.now().isoformat(),
        "graph_build_p95_sec": _p95("graph_build_time_seconds"),
        "partition_p95_sec": _p95("partition_time_seconds"),
        "refine_p95_sec": _p95("refine_time_seconds"),
        "validate_p95_sec": _p95("validate_time_seconds"),
        "polygon_gen_p95_sec": _p95("polygon_generation_time_seconds"),
        "export_p95_sec": _p95("export_time_seconds"),
        "counters": snapshot.get("counters", {}),
        "caches": {
            "graph_cache_hits": metrics.get_counter("cache_hit_total", {"type": "graph"}),
            "polygon_cache_hits": metrics.get_counter("cache_hit_total", {"type": "polygon"}),
        },
    }


@router.get("/logs/recent")
async def recent_logs(n: int = Query(50, ge=1, le=500)):
    """Recent structured log entries."""
    buffer = get_log_buffer()
    return buffer.recent(n)


@router.get("/resources")
async def system_resources():
    """Current system resource usage."""
    monitor = get_resource_monitor()
    temp_mgr = get_temp_file_manager()
    return {
        "timestamp": datetime.now().isoformat(),
        "memory_mb": round(monitor.memory_usage_mb(), 1),
        "cpu_percent": monitor.cpu_percent(),
        "disk_usage_bytes": temp_mgr.total_disk_usage(),
        "tracked_jobs": len(temp_mgr._tracked),
    }


@router.get("/jobs")
async def job_stats():
    """Job statistics from metrics collector."""
    metrics = get_metrics()
    return {
        "active_jobs": metrics.get_gauge("active_jobs"),
        "completed_jobs": metrics.get_counter("completed_jobs"),
        "error_total": metrics.get_counter("error_total"),
        "total_jobs": (
            metrics.get_counter("completed_jobs")
            + metrics.get_gauge("active_jobs")
        ),
    }
