from typing import List, Dict, Tuple, Optional
import numpy as np
from ..models.schemas import DealerRecord
from ..models.enums import DealerType


class RouteOptimizer:
    def __init__(self, avg_speed_kph: float = 30.0):
        self.avg_speed_kph = avg_speed_kph

    def optimize_daily_route(
        self,
        ftc_id: str,
        dealer_ids: List[str],
        dealers: List[DealerRecord],
        anchor_dealer_id: Optional[str] = None,
    ) -> Dict:
        dealer_map = {d.Dealer_id: d for d in dealers}
        route_dealers = [
            d_id for d_id in dealer_ids if d_id in dealer_map
        ]

        if not route_dealers:
            return {
                "ftc_id": ftc_id,
                "route": [],
                "total_distance_km": 0.0,
                "total_time_min": 0.0,
                "dealer_order": [],
            }

        if anchor_dealer_id and anchor_dealer_id in route_dealers:
            start_idx = route_dealers.index(anchor_dealer_id)
            route_dealers = (
                route_dealers[start_idx:]
                + route_dealers[:start_idx]
            )

        ordered = self._nearest_neighbor_heuristic(
            route_dealers, dealer_map
        )

        total_distance = 0.0
        for i in range(len(ordered) - 1):
            d1 = dealer_map[ordered[i]]
            d2 = dealer_map[ordered[i + 1]]
            total_distance += self._haversine(
                d1.Dealer_latitude, d1.Dealer_longitude,
                d2.Dealer_latitude, d2.Dealer_longitude,
            )

        total_time = (total_distance / self.avg_speed_kph) * 60.0

        return {
            "ftc_id": ftc_id,
            "route": [
                {
                    "dealer_id": d_id,
                    "latitude": dealer_map[d_id].Dealer_latitude,
                    "longitude": dealer_map[d_id].Dealer_longitude,
                    "dealer_type": dealer_map[d_id].Dealer_type.value,
                }
                for d_id in ordered
            ],
            "total_distance_km": round(total_distance, 2),
            "total_time_min": round(total_time, 1),
            "dealer_order": ordered,
        }

    def optimize_all_routes(
        self,
        assignments: Dict[str, List[str]],
        dealers: List[DealerRecord],
        anchors: Dict[str, str],
    ) -> Dict[str, Dict]:
        return {
            ftc_id: self.optimize_daily_route(
                ftc_id, dealer_ids, dealers,
                anchor_dealer_id=anchors.get(ftc_id),
            )
            for ftc_id, dealer_ids in assignments.items()
        }

    def _nearest_neighbor_heuristic(
        self,
        dealer_ids: List[str],
        dealer_map: Dict[str, DealerRecord],
    ) -> List[str]:
        if len(dealer_ids) <= 2:
            return dealer_ids

        unvisited = set(dealer_ids[1:])
        ordered = [dealer_ids[0]]

        while unvisited:
            current = ordered[-1]
            current_d = dealer_map[current]
            nearest = min(
                unvisited,
                key=lambda d_id: self._haversine(
                    current_d.Dealer_latitude,
                    current_d.Dealer_longitude,
                    dealer_map[d_id].Dealer_latitude,
                    dealer_map[d_id].Dealer_longitude,
                ),
            )
            ordered.append(nearest)
            unvisited.remove(nearest)

        return ordered

    def generate_route_geojson(
        self,
        route: Dict,
        dealer_map: Dict[str, DealerRecord],
    ) -> Dict:
        coordinates = [
            [stop["longitude"], stop["latitude"]]
            for stop in route["route"]
        ]

        return {
            "type": "Feature",
            "properties": {
                "ftc_id": route["ftc_id"],
                "total_distance_km": route["total_distance_km"],
                "total_time_min": route["total_time_min"],
                "stop_count": len(route["dealer_order"]),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
        }

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
