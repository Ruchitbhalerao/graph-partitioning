from typing import Dict, Optional, List, AsyncGenerator
from datetime import datetime
import uuid
import asyncio
import json
import threading
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
        self._progress_queues: Dict[str, asyncio.Queue] = {}
        self._progress_events: Dict[str, List[Dict]] = {}
        self.loader = ExcelLoader()
        self.validator = DataValidator()
        self.processor = DataProcessor()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()

    async def start_optimization(
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
            self._progress_queues[job_id] = asyncio.Queue(maxsize=500)
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
                self._progress_queues[job_id] = asyncio.Queue(maxsize=500)
                self._progress_events[job_id] = []
            self.jobs[job_id]["dealers"] = dealers
            self.jobs[job_id]["ftcs"] = ftcs
            self.jobs[job_id]["rels"] = rels
            self.jobs[job_id]["status"] = status
            self.jobs[job_id]["message"] = (
                "Data validated successfully" if status == "validated"
                else "Validation failed"
            )

    async def run_optimization(
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
                self._progress_queues[job_id] = asyncio.Queue(maxsize=500)
            if job_id not in self._progress_events:
                self._progress_events[job_id] = []

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self.executor,
            partial(
                self._run_optimization_sync,
                job_id,
                job["dealers"],
                job["ftcs"],
                job["rels"],
                cfg,
            ),
        )

        with self._lock:
            job["status"] = result.get("status", "completed")
            job["result"] = result
            job["completed_at"] = datetime.now()
            if "timing" in result:
                job["timing"] = result["timing"]
            if "sm_progress" in result:
                job["sm_progress"] = result["sm_progress"]

        # Signal SSE consumers that we're done
        await self._push_progress(job_id, OptimizationProgressEvent(
            job_id=job_id,
            phase=OptimizationPhase.COMPLETE,
            progress=100.0,
            message="Optimization complete",
        ))

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
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(
                        self._push_progress(job_id, event), loop
                    )
                    future.result(timeout=0.5)
            except (RuntimeError, Exception):
                pass

        engine.set_progress_callback(progress_callback)
        return engine.run(dealers, ftcs, rels)

    async def _push_progress(self, job_id: str, event: OptimizationProgressEvent):
        queue = self._progress_queues.get(job_id)
        if queue:
            try:
                await asyncio.wait_for(queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                pass
        events = self._progress_events.get(job_id)
        if events is not None:
            events.append(event.model_dump())
            if len(events) > 5000:
                events[:1000] = []

    async def progress_stream(
        self, job_id: str,
    ) -> AsyncGenerator[str, None]:
        queue = self._progress_queues.get(job_id)
        if not queue:
            yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
            return

        job = self.jobs.get(job_id, {})
        session_events = 0
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                session_events += 1
                data = event.model_dump_json()
                yield f"data: {data}\n\n"

                if event.phase == OptimizationPhase.COMPLETE or event.phase == OptimizationPhase.FAILED:
                    break
            except asyncio.TimeoutError:
                status = job.get("status", "")
                if status in ("completed", "cancelled", "error"):
                    yield f"data: {json.dumps({'type': 'done', 'job_id': job_id})}\n\n"
                    break
                yield f"data: {json.dumps({'type': 'heartbeat', 'job_id': job_id})}\n\n"

    async def cancel_optimization(self, job_id: str) -> bool:
        cancel_event = self._cancel_events.get(job_id)
        if cancel_event:
            cancel_event.set()
            with self._lock:
                if job_id in self.jobs:
                    self.jobs[job_id]["status"] = "cancelled"
                    self.jobs[job_id]["message"] = "Cancelled by user"
            await self._push_progress(job_id, OptimizationProgressEvent(
                job_id=job_id,
                phase=OptimizationPhase.FAILED,
                progress=0.0,
                message="Cancelled by user",
            ))
            return True
        return False

    async def get_progress_events(self, job_id: str) -> List[Dict]:
        return self._progress_events.get(job_id, [])

    async def get_status(self, job_id: str) -> Optional[OptimizationStatusResponse]:
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

    async def get_result(self, job_id: str) -> Optional[Dict]:
        job = self.jobs.get(job_id)
        return job.get("result") if job else None

    async def get_export(
        self, job_id: str, include_routes: bool = False,
    ) -> Optional[Dict[str, str]]:
        job = self.jobs.get(job_id)
        if not job or not job.get("result"):
            return None
        result = job["result"]
        results_dict = result.get("results", {})
        dealers = job.get("dealers", [])
        ftcs = job.get("ftcs", [])
        exporter = QGISExporter(output_dir=settings.OUTPUT_DIR)
        return exporter.export_all(
            job_id, results_dict, dealers, ftcs, include_routes
        )

    async def get_jobs_list(self) -> list:
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

    async def get_refiner_history(self, job_id: str) -> List[Dict]:
        job = self.jobs.get(job_id)
        return job.get("refiner_history", []) if job else []

    async def get_job_details(self, job_id: str) -> Optional[Dict]:
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

    async def get_territories_geojson(self, job_id: str) -> Optional[Dict]:
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
