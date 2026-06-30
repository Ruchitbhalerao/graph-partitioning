"""Monitoring dashboard — system health, metrics, and performance views.

Provides Flask Blueprint with endpoints for:
  - GET /metrics — Prometheus text format
  - GET /metrics/json — JSON snapshot
  - GET /health — Detailed system health
  - GET /performance — Recent performance snapshots
  - GET /logs/recent — Recent log entries
  - GET /resources — CPU/memory/disk usage
  - GET /jobs — Job statistics
"""

import json
import time
from datetime import datetime

from flask import Blueprint, jsonify, request, Response

from .metrics import get_metrics
from .resource import get_resource_monitor, get_temp_file_manager
from .logging_config import LogBuffer, JSONFormatter
from .cache import get_graph_cache, get_polygon_cache

import logging

bp = Blueprint("monitoring", __name__)

_log_buffer = LogBuffer(max_entries=1000)


def get_log_buffer() -> LogBuffer:
    return _log_buffer


@bp.route("/metrics")
def metrics_endpoint():
    """Prometheus-compatible metrics endpoint."""
    metrics = get_metrics()
    return Response(
        metrics.prometheus_text(),
        mimetype="text/plain; version=0.0.4",
    )


@bp.route("/metrics/json")
def metrics_json():
    """JSON snapshot of all metrics."""
    metrics = get_metrics()
    snapshot = metrics.snapshot()
    snapshot["uptime_seconds"] = metrics.uptime_seconds()
    return jsonify(snapshot)


@bp.route("/health")
def detailed_health():
    """Detailed system health check with component status."""
    monitor = get_resource_monitor()
    mem_mb = monitor.memory_usage_mb()
    cpu = monitor.cpu_percent()

    graph_cache = get_graph_cache()
    polygon_cache = get_polygon_cache()

    return jsonify({
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
    })


@bp.route("/performance")
def performance_snapshot():
    """Current performance metrics snapshot."""
    metrics = get_metrics()
    snapshot = metrics.snapshot()

    hist = snapshot.get("histograms", {})

    def _p95(name: str) -> float:
        h = hist.get(name, {})
        return h.get("p95", 0.0)

    return jsonify({
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
    })


@bp.route("/logs/recent")
def recent_logs():
    """Recent structured log entries."""
    n = request.args.get("n", 50, type=int)
    n = max(1, min(n, 500))
    buffer = get_log_buffer()
    return jsonify(buffer.recent(n))


@bp.route("/resources")
def system_resources():
    """Current system resource usage."""
    monitor = get_resource_monitor()
    temp_mgr = get_temp_file_manager()
    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "memory_mb": round(monitor.memory_usage_mb(), 1),
        "cpu_percent": monitor.cpu_percent(),
        "disk_usage_bytes": temp_mgr.total_disk_usage(),
        "tracked_jobs": len(temp_mgr._tracked),
    })


@bp.route("/jobs")
def job_stats():
    """Job statistics from metrics collector."""
    metrics = get_metrics()
    return jsonify({
        "active_jobs": metrics.get_gauge("active_jobs"),
        "completed_jobs": metrics.get_counter("completed_jobs"),
        "error_total": metrics.get_counter("error_total"),
        "total_jobs": (
            metrics.get_counter("completed_jobs")
            + metrics.get_gauge("active_jobs")
        ),
    })
