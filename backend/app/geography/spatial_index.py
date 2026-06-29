from typing import List, Tuple, Optional, Dict
import numpy as np
from scipy.spatial import KDTree
from ..models.schemas import DealerRecord


class SpatialIndex:
    def __init__(self):
        self.tree: Optional[KDTree] = None
        self.coords: List[Tuple[float, float]] = []
        self.dealer_ids: List[str] = []
        self.dealer_map: Dict[str, DealerRecord] = {}

    def build(self, dealers: List[DealerRecord]):
        self.coords = [
            (self._to_radians(d.Dealer_latitude),
             self._to_radians(d.Dealer_longitude))
            for d in dealers
        ]
        self.dealer_ids = [d.Dealer_id for d in dealers]
        self.dealer_map = {d.Dealer_id: d for d in dealers}
        self.tree = KDTree(self.coords)

    def query_radius(
        self,
        dealer_id: str,
        radius_km: float,
    ) -> List[Tuple[str, float]]:
        if self.tree is None or dealer_id not in self.dealer_map:
            return []

        d = self.dealer_map[dealer_id]
        point = np.array([
            [self._to_radians(d.Dealer_latitude),
             self._to_radians(d.Dealer_longitude)]
        ])
        radius_rad = radius_km / 6371.0
        indices = self.tree.query_ball_point(point[0], radius_rad)

        results = []
        for idx in indices:
            nid = self.dealer_ids[idx]
            if nid == dealer_id:
                continue
            nd = self.dealer_map[nid]
            dist = self._haversine(
                d.Dealer_latitude, d.Dealer_longitude,
                nd.Dealer_latitude, nd.Dealer_longitude,
            )
            results.append((nid, dist))

        return sorted(results, key=lambda x: x[1])

    def nearest_neighbors(
        self,
        dealer_id: str,
        k: int = 5,
    ) -> List[Tuple[str, float]]:
        if self.tree is None or dealer_id not in self.dealer_map:
            return []

        d = self.dealer_map[dealer_id]
        point = np.array([
            [self._to_radians(d.Dealer_latitude),
             self._to_radians(d.Dealer_longitude)]
        ])
        distances, indices = self.tree.query(point[0], k=min(k + 1, len(self.coords)))

        if k == 1:
            distances = [distances]
            indices = [indices]

        results = []
        for dist_rad, idx in zip(distances, indices):
            nid = self.dealer_ids[idx]
            if nid == dealer_id:
                continue
            nd = self.dealer_map[nid]
            dist = self._haversine(
                d.Dealer_latitude, d.Dealer_longitude,
                nd.Dealer_latitude, nd.Dealer_longitude,
            )
            results.append((nid, dist))

        return results[:k]

    @staticmethod
    def _to_radians(deg: float) -> float:
        return np.radians(deg)

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
