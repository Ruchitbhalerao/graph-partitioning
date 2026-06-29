"""Optimization engine — orchestrates the full optimization pipeline.

Supports parallel SM region processing, graph caching, monitoring
integration, and resource management for production-scale workloads.
"""

from typing import List, Dict, Optional, Callable
import networkx as nx
from datetime import datetime
import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..models.schemas import (
    DealerRecord, FTCRecord, FTCRelationshipRecord,
    OptimizationConfig,
)
from ..models.enums import OptimizationPhase, DealerType
from ..models.progress import (
    OptimizationProgressEvent, SMProgress, RefinerIteration,
    PhaseTiming,
)
from ..data.processor import DataProcessor
from .graph_builder import DealerGraphBuilder
from .partitioner import TerritoryPartitioner
from .refiner import TerritoryRefiner
from .validator import BusinessRuleValidator
from ..config import settings
from ..monitoring.metrics import (
    get_metrics, Timer,
    METRIC_GRAPH_BUILD_TIME, METRIC_GRAPH_NODE_COUNT, METRIC_GRAPH_EDGE_COUNT,
    METRIC_PARTITION_TIME, METRIC_REFINE_TIME, METRIC_JOB_DURATION,
    METRIC_SM_REGIONS_TOTAL, METRIC_DEALERS_TOTAL, METRIC_FTCS_TOTAL,
    METRIC_ERROR_COUNT, METRIC_ACTIVE_JOBS, METRIC_COMPLETED_JOBS,
)
from ..monitoring.cache import get_graph_cache, get_polygon_cache
from ..monitoring.resource import (
    get_resource_monitor, get_temp_file_manager, get_timeout_manager,
    ConcurrencyLimiter,
)
from ..monitoring.profiler import profile, CumulativeProfiler


class OptimizationEngine:
    def __init__(self, config: OptimizationConfig):
        self.config = config
        self.processor = DataProcessor()
        self.graph_builder = DealerGraphBuilder(proximity_km=config.proximity_km)
        self.partitioner = TerritoryPartitioner(self.graph_builder)
        self.refiner = TerritoryRefiner(
            graph_builder=self.graph_builder,
            travel_weight=config.travel_weight,
            workload_weight=config.workload_weight,
            compactness_weight=config.compactness_weight,
            productivity_weight=config.productivity_weight,
            max_iterations=config.max_refinement_iterations,
        )
        self.validator = BusinessRuleValidator()
        self.job_id: str = ""
        self._progress_callback: Optional[Callable] = None
        self._cancel_event: Optional[threading.Event] = None
        self._timing: List[PhaseTiming] = []
        self._current_phase_start: Optional[datetime] = None
        self._sm_results: Dict[str, SMProgress] = {}
        self._total_sms = 0
        self._sm_completed = 0
        self._refiner_callback: Optional[Callable] = None
        self._profiler = CumulativeProfiler()
        self._concurrency_limiter = ConcurrencyLimiter(
            max_concurrent=settings.MAX_CONCURRENT_SM
        )

    def set_progress_callback(self, callback: Callable):
        self._progress_callback = callback

    def set_refiner_callback(self, callback: Callable):
        self._refiner_callback = callback

    def set_cancel_event(self, event: threading.Event):
        self._cancel_event = event

    def is_cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _begin_phase(self, phase: OptimizationPhase):
        self._current_phase_start = datetime.now()

    def _end_phase(self, phase: OptimizationPhase):
        if self._current_phase_start:
            duration = (datetime.now() - self._current_phase_start).total_seconds()
            self._timing.append(PhaseTiming(
                phase=str(phase.value),
                started_at=self._current_phase_start,
                completed_at=datetime.now(),
                duration_sec=round(duration, 1),
            ))

    def _emit_progress(
        self,
        phase: OptimizationPhase,
        progress: float,
        message: str,
        sm_progress: Optional[SMProgress] = None,
        refiner_iter: Optional[RefinerIteration] = None,
    ):
        remaining = None
        if self._total_sms > 0 and self._sm_completed > 0:
            elapsed = (datetime.now() - self._progress_start_time).total_seconds()
            rate = self._sm_completed / max(elapsed, 0.1)
            remaining_sms = self._total_sms - self._sm_completed
            if rate > 0:
                remaining = round(remaining_sms / rate, 1)

        event = OptimizationProgressEvent(
            job_id=self.job_id,
            phase=phase,
            progress=progress,
            message=message,
            current_sm=sm_progress.sm_id if sm_progress else None,
            sm_total=self._total_sms,
            sm_completed=self._sm_completed,
            sm_progress=sm_progress,
            refiner_iteration=refiner_iter,
            timing=list(self._timing),
            estimated_remaining_sec=remaining,
        )
        if self._progress_callback:
            self._progress_callback(event)

    def _wrap_refiner_callback(self, sm_id: str, progress_base: float = 0.0):
        original = self.refiner._progress_callback
        def wrapped(refiner_data: dict):
            if self.is_cancelled():
                return
            iteration = refiner_data.get("iteration", 0)
            if iteration % 5 == 0 or iteration <= 3:
                ri = RefinerIteration(
                    iteration=iteration,
                    fitness=refiner_data.get("fitness", 0.0),
                    best_fitness=refiner_data.get("best_fitness", 0.0),
                    travel_penalty=refiner_data.get("travel", 0.0),
                    workload_penalty=refiner_data.get("workload", 0.0),
                    compactness_penalty=refiner_data.get("compactness", 0.0),
                    moves_accepted=refiner_data.get("moves_accepted", 0),
                    stagnation=refiner_data.get("stagnation", 0),
                )
                self._emit_progress(
                    OptimizationPhase.TERRITORY_REFINEMENT,
                    progress_base + 30.0,
                    f"Refining {sm_id}: iter {iteration}",
                    refiner_iter=ri,
                )
            if original:
                original(refiner_data)
        return wrapped

    def run(
        self,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        rels: List[FTCRelationshipRecord],
    ) -> Dict:
        self.job_id = str(uuid.uuid4())
        t_start = time.perf_counter()
        self._progress_start_time = datetime.now()
        self._timing = []
        self._sm_results = {}
        self._profiler = CumulativeProfiler()

        # Record job start in metrics
        get_metrics().increment(METRIC_ACTIVE_JOBS)
        get_metrics().gauge(METRIC_DEALERS_TOTAL, len(dealers))
        get_metrics().gauge(METRIC_FTCS_TOTAL, len(ftcs))

        self._emit_progress(
            OptimizationPhase.GRAPH_CONSTRUCTION, 0.0,
            "Grouping data by SM region",
        )

        regions = self.processor.group_by_sm(dealers, ftcs, rels)
        results: Dict = {}
        sm_ids = sorted(regions.keys())
        self._total_sms = len(sm_ids)
        self._sm_completed = 0
        get_metrics().gauge(METRIC_SM_REGIONS_TOTAL, self._total_sms)

        if self.is_cancelled():
            return self._cancelled_result()

        self._emit_progress(
            OptimizationPhase.GRAPH_CONSTRUCTION, 2.0,
            f"Building proximity graph for {len(dealers)} dealers",
        )

        # Build graph with timing and caching
        with Timer(METRIC_GRAPH_BUILD_TIME):
            G = self.graph_builder.build(dealers)

        node_count = G.number_of_nodes()
        edge_count = G.number_of_edges()
        get_metrics().gauge(METRIC_GRAPH_NODE_COUNT, node_count)
        get_metrics().gauge(METRIC_GRAPH_EDGE_COUNT, edge_count)

        # Cache full graph for SM subgraph reuse
        if settings.ENABLE_GRAPH_CACHE:
            node_to_sm = {d.Dealer_id: d.SM_id for d in dealers}
            get_graph_cache().set_full_graph(G, node_to_sm)

        self._emit_progress(
            OptimizationPhase.GRAPH_CONSTRUCTION, 5.0,
            f"Graph built: {node_count} nodes, {edge_count} edges",
        )

        self._begin_phase(OptimizationPhase.INITIAL_TERRITORIES)

        if settings.PARALLEL_SM_PROCESSING and self._total_sms > 1:
            results = self._run_parallel(regions, sm_ids)
        else:
            results = self._run_sequential(regions, sm_ids)

        self._end_phase(OptimizationPhase.INITIAL_TERRITORIES)

        if self.is_cancelled():
            return self._cancelled_result()

        self._emit_progress(
            OptimizationPhase.VALIDATION, 95.0,
            "Computing final metrics and summary",
        )

        self._begin_phase(OptimizationPhase.POLYGON_GENERATION)
        summary = self._generate_summary(results, dealers, ftcs)
        self._end_phase(OptimizationPhase.POLYGON_GENERATION)

        # Clear caches after job completion
        if settings.ENABLE_GRAPH_CACHE:
            get_graph_cache().clear()
        if settings.ENABLE_POLYGON_CACHE:
            get_polygon_cache().clear()

        # Record job completion
        job_duration = time.perf_counter() - t_start
        get_metrics().observe(METRIC_JOB_DURATION, job_duration)
        get_metrics().increment(METRIC_COMPLETED_JOBS)
        get_metrics().gauge(METRIC_ACTIVE_JOBS, max(0, get_metrics().get_gauge(METRIC_ACTIVE_JOBS) - 1))

        self._emit_progress(
            OptimizationPhase.COMPLETE, 100.0,
            f"Optimization complete in {job_duration:.1f}s",
        )

        return {
            "job_id": self.job_id,
            "status": "completed",
            "results": results,
            "summary": summary,
            "timing": [t.model_dump() for t in self._timing],
            "sm_progress": {
                k: v.model_dump() for k, v in self._sm_results.items()
            },
            "profiling": self._profiler.snapshot(),
        }

    def _run_sequential(
        self,
        regions: Dict[str, "SMRegion"],
        sm_ids: List[str],
    ) -> Dict:
        results = {}
        for idx, sm_id in enumerate(sm_ids):
            if self.is_cancelled():
                return self._cancelled_result().get("results", {})

            region = regions[sm_id]
            progress_base = (idx / self._total_sms) * 70.0

            sm_progress = SMProgress(
                sm_id=sm_id,
                status="processing",
                dealers_count=len(region.dealers),
                ftcs_count=len(region.ftcs),
            )

            self._emit_progress(
                OptimizationPhase.INITIAL_TERRITORIES,
                progress_base,
                f"Partitioning SM {sm_id} ({idx + 1}/{self._total_sms})",
                sm_progress=sm_progress,
            )

            sm_progress, sm_result = self._optimize_sm_region(
                sm_id, region.dealers, region.ftcs, region.relationships,
                sm_progress, idx,
            )
            results[sm_id] = sm_result
            self._sm_results[sm_id] = sm_progress
            self._sm_completed += 1

            self._emit_progress(
                OptimizationPhase.VALIDATION,
                progress_base + 40.0,
                f"Validated SM {sm_id}: {'OK' if sm_progress.is_valid else f'{len(sm_progress.errors)} errors'}",
                sm_progress=sm_progress,
            )

        return results

    def _run_parallel(
        self,
        regions: Dict[str, "SMRegion"],
        sm_ids: List[str],
    ) -> Dict:
        results: Dict = {}
        results_lock = threading.Lock()
        sm_progress_lock = threading.Lock()

        def process_sm(sm_id: str, idx: int) -> tuple:
            with self._concurrency_limiter:
                if self.is_cancelled():
                    return sm_id, None, None

                region = regions[sm_id]
                sm_progress = SMProgress(
                    sm_id=sm_id,
                    status="processing",
                    dealers_count=len(region.dealers),
                    ftcs_count=len(region.ftcs),
                )

                sm_progress, sm_result = self._optimize_sm_region(
                    sm_id, region.dealers, region.ftcs, region.relationships,
                    sm_progress, idx,
                )

                return sm_id, sm_progress, sm_result

        with ThreadPoolExecutor(max_workers=settings.MAX_CONCURRENT_SM) as executor:
            futures = {
                executor.submit(process_sm, sm_id, idx): (sm_id, idx)
                for idx, sm_id in enumerate(sm_ids)
            }

            for future in as_completed(futures):
                sm_id, sm_progress, sm_result = future.result()
                if sm_id is None:
                    continue

                with results_lock:
                    results[sm_id] = sm_result or {}
                with sm_progress_lock:
                    self._sm_results[sm_id] = sm_progress or SMProgress(sm_id=sm_id, status="error")

                self._sm_completed += 1
                progress_base = ((sm_ids.index(sm_id)) / self._total_sms) * 70.0
                self._emit_progress(
                    OptimizationPhase.VALIDATION,
                    progress_base + 40.0,
                    f"Completed SM {sm_id} ({self._sm_completed}/{self._total_sms})",
                    sm_progress=sm_progress,
                )

        return results

    def _optimize_sm_region(
        self,
        sm_id: str,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        rels: List[FTCRelationshipRecord],
        sm_progress: SMProgress,
        idx: int = 0,
    ) -> tuple:
        t_start = time.perf_counter()
        progress_base = (idx / self._total_sms) * 70.0 if self._total_sms > 0 else 0.0

        static_dealers, mobile_dealers = self.processor.separate_dealer_types(dealers)

        static_assignments: Dict[str, List[str]] = {f.FTC_id: [] for f in ftcs}
        static_dealer_set = {d.Dealer_id for d in static_dealers}
        for r in rels:
            if r.Dealer_id in static_dealer_set and r.FTC_id in static_assignments:
                static_assignments[r.FTC_id].append(r.Dealer_id)

        existing_assignments: Dict[str, List[str]] = {f.FTC_id: [] for f in ftcs}
        if self.config.preserve_existing:
            for r in rels:
                if r.FTC_id in existing_assignments:
                    existing_assignments[r.FTC_id].append(r.Dealer_id)

        anchors = self.processor.select_anchor_dealers(mobile_dealers, ftcs)

        self._emit_progress(
            OptimizationPhase.INITIAL_TERRITORIES,
            progress_base + 5.0,
            f"Partitioning {len(mobile_dealers)} mobile dealers in {sm_id}",
            sm_progress=sm_progress,
        )

        t_part = time.perf_counter()
        with Timer(METRIC_PARTITION_TIME, labels={"sm_id": sm_id}):
            assignments = self.partitioner.partition(
                mobile_dealers, ftcs, static_assignments, anchors,
            )
        sm_progress.partition_time = round(time.perf_counter() - t_part, 2)
        self._profiler.record(f"{sm_id}_partition", time.perf_counter() - t_part)

        if not self.config.preserve_existing:
            all_static_ids = set()
            for ids in static_assignments.values():
                all_static_ids.update(ids)
            for ftc_id in assignments:
                for d_id in all_static_ids:
                    if d_id not in assignments[ftc_id]:
                        found = False
                        for dealers_list in assignments.values():
                            if d_id in dealers_list:
                                found = True
                                break
                        if not found:
                            assignments[ftc_id].append(d_id)

        if self.is_cancelled():
            return sm_progress, {}

        self._emit_progress(
            OptimizationPhase.TERRITORY_REFINEMENT,
            progress_base + 15.0,
            f"Refining {sm_id} with Tabu Search",
            sm_progress=sm_progress,
        )

        original_cb = self.refiner._progress_callback
        self.refiner._progress_callback = self._wrap_refiner_callback(sm_id, progress_base)

        t_ref = time.perf_counter()
        with Timer(METRIC_REFINE_TIME, labels={"sm_id": sm_id}):
            refined = self.refiner.refine(mobile_dealers, ftcs, assignments)
        sm_progress.refine_time = round(time.perf_counter() - t_ref, 2)
        self._profiler.record(f"{sm_id}_refine", time.perf_counter() - t_ref)

        self.refiner._progress_callback = original_cb

        refiner_report = getattr(self.refiner, 'report', None)
        if refiner_report:
            sm_progress.refine_iterations = refiner_report.iterations_performed
            sm_progress.refine_improvement_pct = round(refiner_report.improvement_pct, 1)

        if self.config.preserve_existing:
            for ftc_id, dealers_list in existing_assignments.items():
                if ftc_id in refined:
                    existing_set = set(dealers_list)
                    refined_set = set(refined[ftc_id])
                    refined[ftc_id] = list(existing_set | refined_set)

        self._emit_progress(
            OptimizationPhase.VALIDATION,
            progress_base + 35.0,
            f"Validating {sm_id} territories",
            sm_progress=sm_progress,
        )

        # Use cached subgraph for validation instead of rebuilding
        if settings.ENABLE_GRAPH_CACHE and mobile_dealers:
            G_sub = get_graph_cache().get_sm_subgraph(sm_id, [d.Dealer_id for d in mobile_dealers])
        else:
            G_sub = self.graph_builder.build(mobile_dealers)

        is_valid, errors = self.validator.validate_all(
            refined, dealers, ftcs, G_sub
        )
        sm_progress.is_valid = is_valid
        sm_progress.errors = errors
        sm_progress.status = "valid" if is_valid else "errors"

        result = {
            "sm_id": sm_id,
            "static_dealers": len(static_dealers),
            "mobile_dealers": len(mobile_dealers),
            "ftc_count": len(ftcs),
            "assignments": refined,
            "anchors": {k: v.Dealer_id for k, v in anchors.items()},
            "is_valid": is_valid,
            "validation_errors": errors,
        }

        return sm_progress, result

    def _generate_summary(
        self, results: Dict, dealers: List[DealerRecord], ftcs: List[FTCRecord],
    ) -> Dict:
        total_static = 0; total_mobile = 0; total_ftcs = 0
        total_valid = 0; total_errors = 0
        for sm_id, result in results.items():
            total_static += result.get("static_dealers", 0)
            total_mobile += result.get("mobile_dealers", 0)
            total_ftcs += result.get("ftc_count", 0)
            if result.get("is_valid", False):
                total_valid += 1
            else:
                total_errors += 1
        return {
            "total_sm_regions": len(results),
            "total_dealers": total_static + total_mobile,
            "total_static": total_static,
            "total_mobile": total_mobile,
            "total_ftcs": total_ftcs,
            "valid_regions": total_valid,
            "regions_with_errors": total_errors,
        }

    def _cancelled_result(self) -> Dict:
        get_metrics().increment(METRIC_ERROR_COUNT, labels={"type": "cancelled"})
        self._emit_progress(
            OptimizationPhase.FAILED, 0.0, "Optimization cancelled",
        )
        return {
            "job_id": self.job_id,
            "status": "cancelled",
            "results": {},
            "summary": {},
        }
