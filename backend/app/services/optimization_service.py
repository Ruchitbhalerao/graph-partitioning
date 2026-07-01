from typing import Dict, Optional, List, Generator
from datetime import datetime
import uuid
import json
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from ..models.schemas import (
    DealerRecord, FTCRecord, FTCRelationshipRecord,
    OptimizationConfig, OptimizationStatusResponse,
    OptimizationResult,
)
from ..models.enums import OptimizationPhase
from ..models.progress import OptimizationProgressEvent
from ..data.loader import ExcelLoader
from ..data.validator import DataValidator
from ..data.processor import DataProcessor
from ..optimization.engine import OptimizationEngine
from shapely.geometry import mapping as shapely_mapping
from ..geography.qgis_exporter import QGISExporter
from ..geography.polygon_generator import TerritoryPolygonGenerator
from ..config import settings


class OptimizationService:
    def __init__(self):
        self.jobs: Dict[str, Dict] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self._progress_queues: Dict[str, queue.Queue] = {}
        self._progress_events: Dict[str, List[Dict]] = {}
        self.loader = ExcelLoader()
        self.validator = DataValidator()
        self.processor = DataProcessor()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()

    def start_optimization(
        self,
        file_content: bytes = b"",
        config: Optional[OptimizationConfig] = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self.jobs[job_id] = {
                "status": "uploaded",
                "phase": OptimizationPhase.GRAPH_CONSTRUCTION,
                "progress": 0.0,
                "message": "Data uploaded, waiting to start",
                "started_at": datetime.now(),
                "dealers": None, "ftcs": None, "rels": None,
                "config": config or OptimizationConfig(),
                "result": None, "completed_at": None,
                "refiner_history": [],
            }
            self._cancel_events[job_id] = threading.Event()
            self._progress_queues[job_id] = queue.Queue(maxsize=500)
            self._progress_events[job_id] = []
        return job_id

    def set_job_data(
        self,
        job_id: str,
        dealers: list,
        ftcs: list,
        rels: list,
        status: str = "validated",
    ):
        with self._lock:
            if job_id not in self.jobs:
                self.jobs[job_id] = {
                    "status": status,
                    "phase": OptimizationPhase.GRAPH_CONSTRUCTION,
                    "progress": 0.0, "message": "",
                    "started_at": datetime.now(),
                    "dealers": None, "ftcs": None, "rels": None,
                    "config": OptimizationConfig(),
                    "result": None, "completed_at": None,
                    "refiner_history": [],
                }
                self._cancel_events[job_id] = threading.Event()
                self._progress_queues[job_id] = queue.Queue(maxsize=500)
                self._progress_events[job_id] = []
            self.jobs[job_id]["dealers"] = dealers
            self.jobs[job_id]["ftcs"] = ftcs
            self.jobs[job_id]["rels"] = rels
            self.jobs[job_id]["status"] = status
            self.jobs[job_id]["message"] = (
                "Data validated successfully" if status == "validated"
                else "Validation failed"
            )

    def run_optimization(
        self,
        job_id: str,
        config: Optional[OptimizationConfig] = None,
    ) -> OptimizationResult:
        job = self.jobs.get(job_id)
        if not job:
            return OptimizationResult(
                job_id=job_id, status="error",
                error=f"Job {job_id} not found",
            )
        if job["dealers"] is None:
            return OptimizationResult(
                job_id=job_id, status="error",
                error="No data loaded. Please upload data first.",
            )

        cfg = config or job.get("config") or OptimizationConfig()
        job["config"] = cfg
        job["status"] = "running"

        with self._lock:
            self._cancel_events[job_id] = threading.Event()
            if job_id not in self._progress_queues:
                self._progress_queues[job_id] = queue.Queue(maxsize=500)
            if job_id not in self._progress_events:
                self._progress_events[job_id] = []

        try:
            result = self._run_optimization_sync(
                job_id,
                job["dealers"],
                job["ftcs"],
                job["rels"],
                cfg,
            )
        except Exception as e:
            error_msg = str(e)
            with self._lock:
                job["status"] = "error"
                job["phase"] = OptimizationPhase.FAILED
                job["message"] = f"Optimization failed: {error_msg}"
                job["completed_at"] = datetime.now()
            self._push_progress(job_id, OptimizationProgressEvent(
                job_id=job_id,
                phase=OptimizationPhase.FAILED,
                progress=0.0,
                message=f"Optimization failed: {error_msg}",
            ))
            return OptimizationResult(
                job_id=job_id,
                status="error",
                error=error_msg,
            )

        # Push COMPLETE to the queue FIRST so the SSE generator sees the
        # event before it checks job["status"]. If we set status first, the
        # generator could read "completed" on a timeout and send "done"
        # before the COMPLETE event reaches the queue.
        self._push_progress(job_id, OptimizationProgressEvent(
            job_id=job_id,
            phase=OptimizationPhase.COMPLETE,
            progress=100.0,
            message="Optimization complete",
        ))

        with self._lock:
            job["status"] = result.get("status", "completed")
            job["phase"] = OptimizationPhase.COMPLETE
            job["result"] = result
            job["completed_at"] = datetime.now()
            if "timing" in result:
                job["timing"] = result["timing"]
            if "sm_progress" in result:
                job["sm_progress"] = result["sm_progress"]

        return OptimizationResult(
            job_id=job_id,
            status=result.get("status", "completed"),
            summary=result.get("summary"),
        )

    def _run_optimization_sync(
        self,
        job_id: str,
        dealers: list,
        ftcs: list,
        rels: list,
        config: OptimizationConfig,
    ) -> Dict:
        cancel_event = self._cancel_events.get(job_id)
        if cancel_event and cancel_event.is_set():
            return {"job_id": job_id, "status": "cancelled", "results": {}, "summary": {}}

        engine = OptimizationEngine(config)
        engine.set_cancel_event(cancel_event)

        def progress_callback(event: OptimizationProgressEvent):
            if cancel_event and cancel_event.is_set():
                return
            with self._lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["phase"] = event.phase
                    self.jobs[job_id]["progress"] = event.progress
                    self.jobs[job_id]["message"] = event.message
                    if event.refiner_iteration:
                        self.jobs[job_id].setdefault("refiner_history", []).append(
                            event.refiner_iteration.model_dump()
                        )
            self._push_progress(job_id, event)

        engine.set_progress_callback(progress_callback)
        return engine.run(dealers, ftcs, rels)

    def _push_progress(self, job_id: str, event: OptimizationProgressEvent):
        q = self._progress_queues.get(job_id)
        if q:
            try:
                q.put(event, timeout=1.0)
            except (queue.Full, Exception):
                pass
        events = self._progress_events.get(job_id)
        if events is not None:
            events.append(event.model_dump())
            if len(events) > 5000:
                events[:1000] = []

    def progress_stream(
        self, job_id: str,
    ) -> Generator[bytes, None, None]:
        q = self._progress_queues.get(job_id)
        if not q:
            yield f"data: {json.dumps({'error': 'Job not found'})}\n\n".encode()
            return

        # Flush an initial event immediately so the EventSource connection is
        # established and the browser does not time out waiting for the first byte.
        job = self.jobs.get(job_id, {})
        initial_status = job.get("status", "")
        if initial_status in ("completed", "cancelled", "error"):
            yield f"data: {json.dumps({'type': 'done', 'job_id': job_id})}\n\n".encode()
            return
        yield f"data: {json.dumps({'type': 'connected', 'job_id': job_id})}\n\n".encode()

        while True:
            try:
                event = q.get(timeout=5.0)
                data = event.model_dump_json()
                yield f"data: {data}\n\n".encode()

                # After sending any event, check if the job is done.
                # The service sets job["status"] before pushing the final
                # event, so this catches completion even if the terminal
                # event was dropped or never pushed.
                job = self.jobs.get(job_id, {})
                if job.get("status") in ("completed", "cancelled", "error"):
                    yield f"data: {json.dumps({'type': 'done', 'job_id': job_id})}\n\n".encode()
                    break
            except queue.Empty:
                # Re-read job status each timeout — the optimization thread
                # may have finished between our last queue read and now.
                job = self.jobs.get(job_id, {})
                status = job.get("status", "")
                if status in ("completed", "cancelled", "error"):
                    yield f"data: {json.dumps({'type': 'done', 'job_id': job_id})}\n\n".encode()
                    break
                yield f"data: {json.dumps({'type': 'heartbeat', 'job_id': job_id})}\n\n".encode()

    def cancel_optimization(self, job_id: str) -> bool:
        cancel_event = self._cancel_events.get(job_id)
        if cancel_event:
            cancel_event.set()
            with self._lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "cancelled"
                    self.jobs[job_id]["phase"] = OptimizationPhase.FAILED
                    self.jobs[job_id]["message"] = "Cancelled by user"
            self._push_progress(job_id, OptimizationProgressEvent(
                job_id=job_id,
                phase=OptimizationPhase.FAILED,
                progress=0.0,
                message="Cancelled by user",
            ))
            return True
        return False

    def get_progress_events(self, job_id: str) -> List[Dict]:
        return self._progress_events.get(job_id, [])

    def get_status(self, job_id: str) -> Optional[OptimizationStatusResponse]:
        job = self.jobs.get(job_id)
        if not job:
            return None
        return OptimizationStatusResponse(
            job_id=job_id,
            phase=job.get("phase", OptimizationPhase.GRAPH_CONSTRUCTION),
            progress=job.get("progress", 0.0),
            message=job.get("message", ""),
            started_at=job.get("started_at"),
            completed_at=job.get("completed_at"),
        )

    def get_result(self, job_id: str) -> Optional[Dict]:
        job = self.jobs.get(job_id)
        return job.get("result") if job else None

    def get_export(
        self, job_id: str, include_routes: bool = False,
    ) -> Optional[Dict[str, str]]:
        job = self.jobs.get(job_id)
        if not job or not job.get("result"):
            return None

        # Return cached export files if available
        cached = job.get("export_files")
        if cached and not include_routes:
            return cached

        result = job["result"]
        results_dict = result.get("results", {})
        dealers = job.get("dealers", [])
        ftcs = job.get("ftcs", [])
        exporter = QGISExporter(output_dir=settings.OUTPUT_DIR)
        export_files = exporter.export_all(
            job_id, results_dict, dealers, ftcs, include_routes
        )
        if export_files and not include_routes:
            job["export_files"] = export_files
        return export_files

    def get_jobs_list(self) -> list:
        return [
            {
                "job_id": jid,
                "status": jdata.get("status"),
                "started_at": jdata.get("started_at").isoformat()
                if jdata.get("started_at") else None,
                "completed_at": jdata.get("completed_at").isoformat()
                if jdata.get("completed_at") else None,
            }
            for jid, jdata in self.jobs.items()
        ]

    def get_refiner_history(self, job_id: str) -> List[Dict]:
        job = self.jobs.get(job_id)
        return job.get("refiner_history", []) if job else []

    def get_job_details(self, job_id: str) -> Optional[Dict]:
        job = self.jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job_id,
            "status": job.get("status"),
            "phase": str(job.get("phase", OptimizationPhase.GRAPH_CONSTRUCTION).value),
            "progress": job.get("progress", 0.0),
            "message": job.get("message", ""),
            "started_at": job.get("started_at").isoformat()
            if job.get("started_at") else None,
            "completed_at": job.get("completed_at").isoformat()
            if job.get("completed_at") else None,
            "config": job.get("config").model_dump() if job.get("config") else None,
            "summary": job.get("result", {}).get("summary") if job.get("result") else None,
            "timing": job.get("timing"),
            "sm_progress": job.get("sm_progress"),
            "refiner_iterations": len(job.get("refiner_history", [])),
        }

    def get_territories_geojson(self, job_id: str) -> Optional[Dict]:
        job = self.jobs.get(job_id)
        if not job or not job.get("result"):
            return None

        result = job["result"]
        results_dict = result.get("results", {})
        dealers = job.get("dealers", [])
        if not dealers or not results_dict:
            return None

        sm_ids = list(results_dict.keys())
        colors = [
            "#4a90d9", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
            "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16",
            "#e11d48", "#0ea5e9", "#34d399", "#fb923c", "#a78bfa",
        ]

        generator = TerritoryPolygonGenerator(buffer_km=0.5)
        dealer_map = {d.Dealer_id: d for d in dealers}

        features = []
        color_idx = 0

        for sm_id in sm_ids:
            sm_result = results_dict.get(sm_id, {})
            assignments = sm_result.get("assignments", {})
            anchors = sm_result.get("anchors", {})
            sm_color = colors[color_idx % len(colors)]
            color_idx += 1

            ftc_idx = 0
            for ftc_id, dealer_ids in assignments.items():
                ftc_color = colors[(color_idx + ftc_idx) % len(colors)]

                territory_poly = generator.generate_territory_polygon(dealer_ids, dealers)
                if territory_poly and not territory_poly.is_empty:
                    try:
                        poly_geom = shapely_mapping(territory_poly)
                        features.append({
                            "type": "Feature",
                            "geometry": poly_geom,
                            "properties": {
                                "feature_type": "territory",
                                "sm_id": sm_id,
                                "ftc_id": ftc_id,
                                "dealer_count": len(dealer_ids),
                                "color": ftc_color,
                                "sm_color": sm_color,
                                "anchor_dealer": anchors.get(ftc_id),
                            },
                        })
                    except Exception:
                        pass

                for d_id in dealer_ids:
                    d = dealer_map.get(d_id)
                    if d:
                        is_anchor = anchors.get(ftc_id) == d_id
                        features.append({
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [d.Dealer_longitude, d.Dealer_latitude],
                            },
                            "properties": {
                                "feature_type": "dealer",
                                "dealer_id": d.Dealer_id,
                                "dealer_type": d.Dealer_type.value,
                                "sm_id": sm_id,
                                "ftc_id": ftc_id,
                                "product_group": d.Product_group.value,
                                "cases_per_day": d.Average_cases_per_day,
                                "is_anchor": is_anchor,
                                "color": ftc_color,
                            },
                        })

                ftc_idx += 1

        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "job_id": job_id,
                "total_sms": len(sm_ids),
                "total_features": len(features),
            },
        }
