from typing import List, Dict, Tuple, Optional
import numpy as np
from shapely.geometry import (
    Point, Polygon, MultiPoint, MultiPolygon, mapping
)
from shapely.ops import unary_union
from shapely import wkt
from scipy.spatial import ConvexHull, Delaunay
from ..models.schemas import DealerRecord


class TerritoryPolygonGenerator:
    def __init__(self, buffer_km: float = 1.0, smooth_iterations: int = 3):
        self.buffer_km = buffer_km
        self.smooth_iterations = smooth_iterations
        self._km_per_degree = 111.32

    def generate_territory_polygon(
        self,
        dealer_ids: List[str],
        dealers: List[DealerRecord],
    ) -> Optional[Polygon]:
        dealer_map = {d.Dealer_id: d for d in dealers}
        points = []
        for d_id in dealer_ids:
            d = dealer_map.get(d_id)
            if d:
                points.append(Point(d.Dealer_longitude, d.Dealer_latitude))

        if len(points) == 0:
            return None
        if len(points) == 1:
            return self._point_to_polygon(points[0])
        if len(points) == 2:
            return self._two_point_polygon(points[0], points[1])

        coords = np.array([(p.x, p.y) for p in points])
        try:
            hull = ConvexHull(coords)
            hull_poly = Polygon([coords[i] for i in hull.vertices])
            return self._smooth_polygon(hull_poly)
        except Exception:
            mpoint = MultiPoint(points)
            hull = mpoint.convex_hull
            if isinstance(hull, Polygon):
                return self._smooth_polygon(hull)
            return None

    def generate_sm_region_polygon(
        self,
        ftc_territories: List[Polygon],
    ) -> Optional[Polygon]:
        valid = [p for p in ftc_territories if p and not p.is_empty]
        if not valid:
            return None
        merged = unary_union(valid)
        if isinstance(merged, Polygon):
            return merged
        elif isinstance(merged, MultiPolygon):
            return merged.convex_hull
        return None

    def generate_all_territories(
        self,
        assignments: Dict[str, List[str]],
        dealers: List[DealerRecord],
    ) -> Dict[str, Optional[Polygon]]:
        return {
            ftc_id: self.generate_territory_polygon(dealer_ids, dealers)
            for ftc_id, dealer_ids in assignments.items()
        }

    def _point_to_polygon(self, point: Point) -> Polygon:
        buffer_deg = self.buffer_km / self._km_per_degree
        return point.buffer(buffer_deg, resolution=16)

    def _two_point_polygon(self, p1: Point, p2: Point) -> Polygon:
        mid = Point((p1.x + p2.x) / 2, (p1.y + p2.y) / 2)
        buff_deg = (
            self.buffer_km / self._km_per_degree
            + p1.distance(p2) / 2
        )
        return mid.buffer(buff_deg, resolution=16)

    def _smooth_polygon(self, polygon: Polygon) -> Polygon:
        result = polygon
        for _ in range(self.smooth_iterations):
            coords = list(result.exterior.coords)
            smoothed = []
            n = len(coords) - 1
            for i in range(n):
                prev_coord = coords[(i - 1) % n]
                curr_coord = coords[i]
                next_coord = coords[(i + 1) % n]
                sx = 0.25 * prev_coord[0] + 0.5 * curr_coord[0] + 0.25 * next_coord[0]
                sy = 0.25 * prev_coord[1] + 0.5 * curr_coord[1] + 0.25 * next_coord[1]
                smoothed.append((sx, sy))
            smoothed.append(smoothed[0])
            result = Polygon(smoothed)
        if self.buffer_km > 0:
            buff_deg = self.buffer_km / self._km_per_degree
            result = result.buffer(buff_deg, resolution=8)
            result = result.simplify(buff_deg * 0.5, preserve_topology=True)
        return result
