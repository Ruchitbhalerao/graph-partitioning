import os
import threading
from datetime import datetime
from typing import Optional, List

from flask import Blueprint, request, jsonify, Response, send_file

from ..config import settings
from ..models.schemas import (
    UploadResponse, ValidationErrorItem, OptimizationConfig,
    OptimizationStatusResponse, OptimizationResult,
    ExportRequest, AnalyticsReport,
)
from ..models.enums import OutputFormat, OptimizationPhase
from ..services.optimization_service import OptimizationService
from ..services.upload_service import UploadService
from ..services.analytics_service import AnalyticsService
from ..services.export_service import ExportService
from .dependencies import (
    get_optimization_service,
    get_upload_service,
    get_analytics_service,
    get_export_service,
)

bp = Blueprint("api", __name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _get_json_body():
    return request.get_json(silent=True) or {}


@bp.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file provided"}), 400

    content = file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return jsonify({
            "error": f"File too large ({len(content) / 1024 / 1024:.1f} MB). "
                     f"Max {MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB."
        }), 413

    opt_service = get_optimization_service()
    upload_service = get_upload_service()

    result = upload_service.process_upload(content, file.filename)
    upload_job_id = result.job_id

    job_id = opt_service.start_optimization()
    upload_job = upload_service.get_job(upload_job_id)
    opt_service.set_job_data(
        job_id=job_id,
        dealers=upload_job.get("dealers", []) if upload_job else [],
        ftcs=upload_job.get("ftcs", []) if upload_job else [],
        rels=upload_job.get("rels", []) if upload_job else [],
        status=result.status,
    )
    result.job_id = job_id

    return jsonify(result.model_dump()), 200


@bp.route("/optimize/<job_id>", methods=["POST"])
def run_optimization(job_id: str):
    service = get_optimization_service()
    body = _get_json_body()
    config_data = body if body else None

    config = None
    if config_data:
        config = OptimizationConfig(**config_data)
        weights = [
            config.travel_weight, config.workload_weight,
            config.compactness_weight, config.productivity_weight,
        ]
        if abs(sum(weights) - 1.0) > 0.01:
            return jsonify({
                "error": f"Weights must sum to 1.0 (got {sum(weights):.2f})"
            }), 422

    # Run optimization in background thread
    def _run():
        service.run_optimization(job_id, config)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "status": "started"}), 200


@bp.route("/optimize/progress/<job_id>")
def optimization_progress_stream(job_id: str):
    service = get_optimization_service()
    response = Response(
        service.progress_stream(job_id),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    response.direct_passthrough = True
    return response


@bp.route("/optimize/cancel/<job_id>", methods=["POST"])
def cancel_optimization(job_id: str):
    service = get_optimization_service()
    cancelled = service.cancel_optimization(job_id)
    if not cancelled:
        return jsonify({"error": f"No running optimization found for job {job_id}"}), 404
    return jsonify({"job_id": job_id, "status": "cancelled"}), 200


@bp.route("/optimize/history/<job_id>")
def get_optimization_history(job_id: str):
    service = get_optimization_service()
    history = service.get_refiner_history(job_id)
    return jsonify({"job_id": job_id, "refiner_iterations": history})


@bp.route("/status/<job_id>")
def get_status(job_id: str):
    service = get_optimization_service()
    status = service.get_status(job_id)
    if not status:
        return jsonify({"error": f"Job {job_id} not found"}), 404
    return jsonify(status.model_dump())


@bp.route("/result/<job_id>")
def get_result(job_id: str):
    service = get_optimization_service()
    result = service.get_result(job_id)
    if not result:
        return jsonify({"error": f"Job {job_id} result not found"}), 404
    return jsonify(result)


@bp.route("/job/<job_id>")
def get_job_details(job_id: str):
    service = get_optimization_service()
    details = service.get_job_details(job_id)
    if not details:
        return jsonify({"error": f"Job {job_id} not found"}), 404
    return jsonify(details)


@bp.route("/export/<job_id>")
def export_results(job_id: str):
    service = get_optimization_service()
    export_service = get_export_service()

    fmt = request.args.get("format", "geojson")
    include_routes = request.args.get("include_routes", "false").lower() == "true"

    valid_formats = {"geojson", "shapefile", "csv"}
    if fmt not in valid_formats:
        return jsonify({
            "error": f"Invalid format '{fmt}'. Valid: {', '.join(valid_formats)}"
        }), 400

    export_files = service.get_export(job_id, include_routes)
    if not export_files:
        return jsonify({"error": f"No export data found for job {job_id}"}), 404

    file_type_map = {
        "geojson": "territories_geojson",
        "shapefile": "shapefile_zip",
        "csv": "assignments_csv",
    }
    target_key = file_type_map.get(fmt, "territories_geojson")

    file_response = export_service.get_export_file(export_files, target_key)
    if not file_response:
        return jsonify({
            "error": f"Export file not available for format '{fmt}'"
        }), 404
    return file_response


@bp.route("/analytics/<job_id>")
def get_analytics(job_id: str):
    service = get_optimization_service()
    analytics_service = get_analytics_service()

    result = service.get_result(job_id)
    if not result:
        return jsonify({"error": f"Job {job_id} result not found"}), 404

    job = None
    for jid, jdata in service.jobs.items():
        if jid == job_id:
            job = jdata
            break

    if not job:
        return jsonify({"error": f"Job {job_id} not found"}), 404

    report = analytics_service.generate_report(
        result, job.get("dealers", []), job.get("ftcs", [])
    )
    return jsonify(report.model_dump())


@bp.route("/territories/<job_id>")
def get_territories_geojson(job_id: str):
    service = get_optimization_service()
    geojson = service.get_territories_geojson(job_id)
    if not geojson:
        return jsonify({"error": f"No territory data found for job {job_id}"}), 404
    return jsonify(geojson)


@bp.route("/export/<job_id>/generate", methods=["POST"])
def generate_exports(job_id: str):
    service = get_optimization_service()
    export_service = get_export_service()

    include_routes = request.args.get("include_routes", "false").lower() == "true"

    job = service.get_job_details(job_id)
    if not job:
        return jsonify({"error": f"Job {job_id} not found"}), 404
    if job.get("status") not in ("completed",):
        return jsonify({
            "error": f"Job status is '{job.get('status')}', must be 'completed'"
        }), 400

    result = service.get_result(job_id)
    if not result:
        return jsonify({"error": "No result found"}), 404

    results_dict = result.get("results", {})

    jd = None
    for jid, jdata in service.jobs.items():
        if jid == job_id:
            jd = jdata
            break

    if not jd:
        return jsonify({"error": "Job data not found"}), 404

    dealers = jd.get("dealers", [])
    ftcs = jd.get("ftcs", [])

    if not results_dict:
        return jsonify({
            "job_id": job_id,
            "status": "error",
            "error": "No optimization results to export. The data may have had no valid dealer records.",
        }), 400

    from ..geography.qgis_exporter import QGISExporter
    exporter = QGISExporter(output_dir=settings.OUTPUT_DIR)
    try:
        export_files = exporter.export_all(
            job_id, results_dict, dealers, ftcs,
            include_routes=include_routes,
            style_info={"config": job.get("config")},
        )
    except Exception as e:
        return jsonify({
            "job_id": job_id,
            "status": "error",
            "error": f"Export generation failed: {e}",
        }), 500

    export_service.job_manager.set_status(job_id, {
        "job_id": job_id,
        "status": "completed",
        "created_at": datetime.now().isoformat(),
        "include_routes": include_routes,
        "files": list(export_files.keys()),
    })

    files_list = [
        {"key": k, "path": v, "size": os.path.getsize(v) if os.path.exists(v) else 0}
        for k, v in export_files.items() if os.path.exists(v)
    ]

    return jsonify({
        "job_id": job_id,
        "status": "completed",
        "files": files_list,
        "total_size": sum(f["size"] for f in files_list),
        "manifest": export_files.get("manifest_json"),
    })


@bp.route("/export/<job_id>/status")
def get_export_status(job_id: str):
    export_service = get_export_service()
    status = export_service.get_export_status(job_id)
    if not status:
        return jsonify({"error": f"No exports found for job {job_id}"}), 404
    return jsonify(status)


@bp.route("/export/<job_id>/validate")
def validate_exports(job_id: str):
    export_service = get_export_service()
    report = export_service.validate_exports(job_id)
    if "error" in report:
        return jsonify({"error": report["error"]}), 404
    return jsonify(report)


@bp.route("/export/<job_id>/files")
def list_export_files(job_id: str):
    export_service = get_export_service()
    files = export_service.list_export_files(job_id)
    return jsonify({"job_id": job_id, "files": files})


@bp.route("/export/bulk", methods=["POST"])
def bulk_export():
    export_service = get_export_service()
    body = _get_json_body()
    if not body:
        return jsonify({"error": "Request body required"}), 400

    job_ids = body.get("job_ids", [])
    formats = body.get("formats", ["geojson", "csv", "zip"])

    result = export_service.generate_bulk_export(job_ids, formats)
    if not result:
        return jsonify({
            "error": "No export data found for the specified jobs"
        }), 404
    return jsonify(result)


@bp.route("/export/bulk/<bulk_id>")
def download_bulk_export(bulk_id: str):
    export_service = get_export_service()
    bulk_dir = os.path.join(settings.OUTPUT_DIR, bulk_id)
    response = export_service.get_bulk_export_zip(bulk_dir)
    if not response:
        return jsonify({"error": "Bulk export not found"}), 404
    return response


@bp.route("/jobs")
def list_jobs():
    service = get_optimization_service()
    jobs = service.get_jobs_list()
    return jsonify(jobs)


@bp.route("/export/<job_id>/<file_type>")
def get_export_file(job_id: str, file_type: str):
    service = get_optimization_service()
    export_service = get_export_service()

    export_files = service.get_export(job_id)
    if not export_files:
        return jsonify({"error": "No exports found"}), 404

    file_response = export_service.get_export_file(export_files, file_type)
    if not file_response:
        return jsonify({"error": f"File type '{file_type}' not available"}), 404
    return file_response
