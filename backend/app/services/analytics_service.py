from typing import List, Dict, Optional
import numpy as np
from datetime import datetime

from ..models.schemas import (
    DealerRecord, FTCRecord,
    TerritoryMetrics, SMMetrics, AnalyticsReport,
)
from .optimization_service import OptimizationService
from ..geography.polygon_generator import TerritoryPolygonGenerator
from ..geography.routing import RouteOptimizer


class AnalyticsService:
    def __init__(self):
        self.polygon_generator = TerritoryPolygonGenerator()
        self.route_optimizer = RouteOptimizer()

    def generate_report(
        self,
        optimization_result: Dict,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
    ) -> AnalyticsReport:
        results_dict = optimization_result.get("results", {})
        dealer_map = {d.Dealer_id: d for d in dealers}

        total_dealers = len(dealers)
        total_ftcs = len(ftcs)
        total_sms = len(results_dict)

        all_territory_metrics = []
        sm_reports = []
        total_static_assignments = 0
        total_mobile_assignments = 0
        all_workloads = []
        all_distances = []
        all_compactness = []

        for sm_id, sm_result in results_dict.items():
            assignments = sm_result.get("assignments", {})
            anchors = sm_result.get("anchors", {})

            ftc_metrics = []
            for ftc_id, dealer_ids in assignments.items():
                static_count = sum(
                    1 for d_id in dealer_ids
                    if d_id in dealer_map
                    and dealer_map[d_id].Dealer_type.value == "static"
                )
                mobile_count = sum(
                    1 for d_id in dealer_ids
                    if d_id in dealer_map
                    and dealer_map[d_id].Dealer_type.value == "mobile"
                )
                total_cases = sum(
                    dealer_map[d_id].Average_cases_per_day
                    for d_id in dealer_ids if d_id in dealer_map
                )

                distances = []
                for i in range(len(dealer_ids)):
                    for j in range(i + 1, len(dealer_ids)):
                        d1 = dealer_map.get(dealer_ids[i])
                        d2 = dealer_map.get(dealer_ids[j])
                        if d1 and d2:
                            dist = self._haversine(
                                d1.Dealer_latitude, d1.Dealer_longitude,
                                d2.Dealer_latitude, d2.Dealer_longitude,
                            )
                            distances.append(dist)

                avg_dist = np.mean(distances) if distances else 0.0
                total_dist = sum(distances)

                territory_polygon = self.polygon_generator.generate_territory_polygon(
                    dealer_ids, dealers
                )
                compactness = 0.0
                if territory_polygon:
                    area = territory_polygon.area * 111.32 ** 2
                    perimeter = territory_polygon.length * 111.32
                    if perimeter > 0:
                        compactness = (4 * np.pi * area) / (perimeter ** 2)
                    compactness = min(compactness, 1.0)

                workload_score = 0.0
                ftc = next((f for f in ftcs if f.FTC_id == ftc_id), None)
                if ftc and ftc.Average_cases_per_day > 0:
                    workload_score = total_cases / ftc.Average_cases_per_day

                metric = TerritoryMetrics(
                    ftc_id=ftc_id,
                    dealer_count=len(dealer_ids),
                    static_count=static_count,
                    mobile_count=mobile_count,
                    average_cases_per_day=total_cases,
                    total_distance_km=round(total_dist, 2),
                    average_distance_km=round(avg_dist, 2),
                    compactness_score=round(compactness, 4),
                    workload_score=round(workload_score, 4),
                    anchor_dealer_id=anchors.get(ftc_id),
                )
                ftc_metrics.append(metric)

                total_static_assignments += static_count
                total_mobile_assignments += mobile_count
                all_workloads.append(workload_score)
                all_distances.append(total_dist)
                all_compactness.append(compactness)

            total_cases_sm = sum(m.average_cases_per_day for m in ftc_metrics)
            total_dist_sm = sum(m.total_distance_km for m in ftc_metrics)
            workloads_sm = [m.workload_score for m in ftc_metrics]
            wl_variance = float(np.var(workloads_sm)) if workloads_sm else 0.0

            sm_metrics = SMMetrics(
                sm_id=sm_id,
                ftc_count=len(ftc_metrics),
                dealer_count=sum(m.dealer_count for m in ftc_metrics),
                total_cases=round(total_cases_sm, 2),
                total_distance_km=round(total_dist_sm, 2),
                workload_variance=round(wl_variance, 4),
                territory_count=len(ftc_metrics),
                metrics=ftc_metrics,
            )
            sm_reports.append(sm_metrics)
            all_territory_metrics.extend(ftc_metrics)

        avg_workload = float(np.mean(all_workloads)) if all_workloads else 0.0
        workload_var = float(np.var(all_workloads)) if all_workloads else 0.0
        avg_travel = float(np.mean(all_distances)) if all_distances else 0.0
        max_travel = float(np.max(all_distances)) if all_distances else 0.0
        avg_compact = float(np.mean(all_compactness)) if all_compactness else 0.0

        covered = sum(
            1 for d in dealers
            if any(
                d.Dealer_id in a.get("assignments", {}).get(f.FTC_id, [])
                for a in results_dict.values()
                for f in ftcs
            )
        )
        coverage_pct = (covered / max(total_dealers, 1)) * 100.0

        return AnalyticsReport(
            job_id=optimization_result.get("job_id", ""),
            generated_at=datetime.now(),
            total_dealers=total_dealers,
            total_ftcs=total_ftcs,
            total_sms=total_sms,
            total_static_assignments=total_static_assignments,
            total_mobile_assignments=total_mobile_assignments,
            average_workload_per_ftc=round(avg_workload, 4),
            workload_variance=round(workload_var, 4),
            average_travel_distance_km=round(avg_travel, 2),
            max_travel_distance_km=round(max_travel, 2),
            total_coverage_percent=round(coverage_pct, 2),
            territory_compactness_avg=round(avg_compact, 4),
            sm_reports=sm_reports,
        )

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)
        a = (
            np.sin(dlat / 2) ** 2
            + np.cos(np.radians(lat1))
            * np.cos(np.radians(lat2))
            * np.sin(dlon / 2) ** 2
        )
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        return R * c
