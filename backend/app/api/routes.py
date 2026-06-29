import os
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query, Body, Request, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse

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

router = APIRouter(prefix="/api/v1", tags=["territory-optimization"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    opt_service: OptimizationService = Depends(get_optimization_service),
    upload_service: UploadService = Depends(get_upload_service),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Max {MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB.",
        )

    result = upload_service.process_upload(content, file.filename)
    upload_job_id = result.job_id

    if result.status in ("validated", "validation_failed"):
        job_id = await opt_service.start_optimization()
        upload_job = upload_service.get_job(upload_job_id)
        opt_service.set_job_data(
            job_id=job_id,
            dealers=upload_job.get("dealers", []) if upload_job else [],
            ftcs=upload_job.get("ftcs", []) if upload_job else [],
            rels=upload_job.get("rels", []) if upload_job else [],
            status=result.status,
        )
        result.job_id = job_id

    return result


@router.post("/optimize/{job_id}", response_model=OptimizationResult)
async def run_optimization(
    job_id: str,
    config: Optional[OptimizationConfig] = Body(None),
    service: OptimizationService = Depends(get_optimization_service),
):
    if config:
        weights = [
            config.travel_weight, config.workload_weight,
            config.compactness_weight, config.productivity_weight,
        ]
        if abs(sum(weights) - 1.0) > 0.01:
            raise HTTPException(
                status_code=422,
                detail=f"Weights must sum to 1.0 (got {sum(weights):.2f})",
            )
    return await service.run_optimization(job_id, config)


@router.get("/optimize/progress/{job_id}")
async def optimization_progress_stream(
    job_id: str,
    service: OptimizationService = Depends(get_optimization_service),
):
    return StreamingResponse(
        service.progress_stream(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/optimize/cancel/{job_id}")
async def cancel_optimization(
    job_id: str,
    service: OptimizationService = Depends(get_optimization_service),
):
    cancelled = await service.cancel_optimization(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail=f"No running optimization found for job {job_id}",
        )
    return {"job_id": job_id, "status": "cancelled"}


@router.get("/optimize/history/{job_id}")
async def get_optimization_history(
    job_id: str,
    service: OptimizationService = Depends(get_optimization_service),
):
    history = await service.get_refiner_history(job_id)
    return {"job_id": job_id, "refiner_iterations": history}


@router.get("/status/{job_id}", response_model=OptimizationStatusResponse)
async def get_status(
    job_id: str,
    service: OptimizationService = Depends(get_optimization_service),
):
    status = await service.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return status


@router.get("/result/{job_id}")
async def get_result(
    job_id: str,
    service: OptimizationService = Depends(get_optimization_service),
):
    result = await service.get_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Job {job_id} result not found")
    return result


@router.get("/job/{job_id}")
async def get_job_details(
    job_id: str,
    service: OptimizationService = Depends(get_optimization_service),
):
    details = await service.get_job_details(job_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return details


@router.get("/export/{job_id}")
async def export_results(
    job_id: str,
    format: str = Query("geojson", description="Export format: geojson, shapefile, csv"),
    include_routes: bool = Query(False),
    service: OptimizationService = Depends(get_optimization_service),
    export_service: ExportService = Depends(get_export_service),
):
    valid_formats = {"geojson", "shapefile", "csv"}
    if format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format '{format}'. Valid: {', '.join(valid_formats)}",
        )

    export_files = await service.get_export(job_id, include_routes)
    if not export_files:
        raise HTTPException(
            status_code=404,
            detail=f"No export data found for job {job_id}",
        )

    file_type_map = {
        "geojson": "territories_geojson",
        "shapefile": "shapefile_zip",
        "csv": "assignments_csv",
    }
    target_key = file_type_map.get(format, "territories_geojson")

    file_response = export_service.get_export_file(export_files, target_key)
    if not file_response:
        raise HTTPException(
            status_code=404,
            detail=f"Export file not available for format '{format}'",
        )
    return file_response


@router.get("/analytics/{job_id}", response_model=AnalyticsReport)
async def get_analytics(
    job_id: str,
    service: OptimizationService = Depends(get_optimization_service),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
):
    result = await service.get_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Job {job_id} result not found")

    job = None
    for jid, jdata in service.jobs.items():
        if jid == job_id:
            job = jdata
            break

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return analytics_service.generate_report(
        result, job.get("dealers", []), job.get("ftcs", [])
    )


@router.get("/territories/{job_id}")
async def get_territories_geojson(
    job_id: str,
    service: OptimizationService = Depends(get_optimization_service),
):
    geojson = await service.get_territories_geojson(job_id)
    if not geojson:
        raise HTTPException(
            status_code=404,
            detail=f"No territory data found for job {job_id}",
        )
    return JSONResponse(content=geojson)


@router.post("/export/{job_id}/generate")
async def generate_exports(
    job_id: str,
    include_routes: bool = Query(False),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    service: OptimizationService = Depends(get_optimization_service),
    export_service: ExportService = Depends(get_export_service),
):
    job = await service.get_job_details(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.get("status") not in ("completed",):
        raise HTTPException(
            status_code=400,
            detail=f"Job status is '{job.get('status')}', must be 'completed'",
        )

    result = await service.get_result(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="No result found")

    results_dict = result.get("results", {})

    jd = None
    for jid, jdata in service.jobs.items():
        if jid == job_id:
            jd = jdata
            break

    if not jd:
        raise HTTPException(status_code=404, detail="Job data not found")

    dealers = jd.get("dealers", [])
    ftcs = jd.get("ftcs", [])

    from ..geography.qgis_exporter import QGISExporter
    exporter = QGISExporter(output_dir=settings.OUTPUT_DIR)
    export_files = exporter.export_all(
        job_id, results_dict, dealers, ftcs,
        include_routes=include_routes,
        style_info={"config": job.get("config")},
    )

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

    return {
        "job_id": job_id,
        "status": "completed",
        "files": files_list,
        "total_size": sum(f["size"] for f in files_list),
        "manifest": export_files.get("manifest_json"),
    }


@router.get("/export/{job_id}/status")
async def get_export_status(
    job_id: str,
    export_service: ExportService = Depends(get_export_service),
):
    status = export_service.get_export_status(job_id)
    if not status:
        raise HTTPException(
            status_code=404,
            detail=f"No exports found for job {job_id}",
        )
    return status


@router.get("/export/{job_id}/validate")
async def validate_exports(
    job_id: str,
    export_service: ExportService = Depends(get_export_service),
):
    report = export_service.validate_exports(job_id)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return report


@router.get("/export/{job_id}/files")
async def list_export_files(
    job_id: str,
    export_service: ExportService = Depends(get_export_service),
):
    files = export_service.list_export_files(job_id)
    return {"job_id": job_id, "files": files}


@router.post("/export/bulk")
async def bulk_export(
    job_ids: List[str] = Body(...),
    formats: List[str] = Body(["geojson", "csv", "zip"]),
    export_service: ExportService = Depends(get_export_service),
):
    result = export_service.generate_bulk_export(job_ids, formats)
    if not result:
        raise HTTPException(
            status_code=404,
            detail="No export data found for the specified jobs",
        )
    return result


@router.get("/export/bulk/{bulk_id}")
async def download_bulk_export(
    bulk_id: str,
    export_service: ExportService = Depends(get_export_service),
):
    bulk_dir = os.path.join(settings.OUTPUT_DIR, bulk_id)
    response = export_service.get_bulk_export_zip(bulk_dir)
    if not response:
        raise HTTPException(status_code=404, detail="Bulk export not found")
    return response


@router.get("/jobs")
async def list_jobs(
    service: OptimizationService = Depends(get_optimization_service),
):
    return await service.get_jobs_list()


@router.get("/export/{job_id}/{file_type}")
async def get_export_file(
    job_id: str,
    file_type: str,
    service: OptimizationService = Depends(get_optimization_service),
    export_service: ExportService = Depends(get_export_service),
):
    export_files = await service.get_export(job_id)
    if not export_files:
        raise HTTPException(status_code=404, detail="No exports found")

    file_response = export_service.get_export_file(export_files, file_type)
    if not file_response:
        raise HTTPException(
            status_code=404,
            detail=f"File type '{file_type}' not available",
        )
    return file_response
