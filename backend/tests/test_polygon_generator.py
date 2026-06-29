"""Tests for TerritoryPolygonGenerator — territory polygon generation."""

import pytest
from shapely.geometry import Point, Polygon, MultiPolygon
from app.geography.polygon_generator import TerritoryPolygonGenerator
from helpers import make_dealer


class TestTerritoryPolygonGenerator:
    def test_empty_dealers(self):
        gen = TerritoryPolygonGenerator(buffer_km=0.5)
        poly = gen.generate_territory_polygon([], [])
        assert poly is None

    def test_single_dealer(self):
        gen = TerritoryPolygonGenerator(buffer_km=1.0)
        dealer = make_dealer("D1", lat=19.0, lng=73.0)
        poly = gen.generate_territory_polygon(["D1"], [dealer])
        assert poly is not None
        assert isinstance(poly, Polygon)
        assert not poly.is_empty
        # Should be a buffered circle-like polygon
        assert poly.area > 0
        assert poly.contains(Point(73.0, 19.0))

    def test_two_dealers(self):
        gen = TerritoryPolygonGenerator(buffer_km=0.5)
        dealers = [
            make_dealer("D1", lat=19.0, lng=73.0),
            make_dealer("D2", lat=19.01, lng=73.01),
        ]
        poly = gen.generate_territory_polygon(["D1", "D2"], dealers)
        assert poly is not None
        assert isinstance(poly, Polygon)
        assert poly.contains(Point(73.0, 19.0))
        assert poly.contains(Point(73.01, 19.01))

    def test_three_dealers_convex_hull(self):
        gen = TerritoryPolygonGenerator(buffer_km=1.0)
        dealers = [
            make_dealer("D1", lat=19.0, lng=73.0),
            make_dealer("D2", lat=19.05, lng=73.05),
            make_dealer("D3", lat=19.02, lng=73.08),
        ]
        poly = gen.generate_territory_polygon(["D1", "D2", "D3"], dealers)
        assert poly is not None
        assert isinstance(poly, Polygon)
        assert poly.is_valid
        assert poly.area > 0

    def test_collinear_points(self):
        """Collinear points produce a line, not a polygon."""
        gen = TerritoryPolygonGenerator(buffer_km=0.0)
        dealers = [
            make_dealer("D1", lat=19.0, lng=73.0),
            make_dealer("D2", lat=19.0, lng=73.05),
            make_dealer("D3", lat=19.0, lng=73.10),
        ]
        poly = gen.generate_territory_polygon(["D1", "D2", "D3"], dealers)
        # With zero buffer, collinear points cannot form a polygon
        assert poly is None or poly.is_valid

    def test_sm_region_polygon_empty(self):
        gen = TerritoryPolygonGenerator()
        poly = gen.generate_sm_region_polygon([])
        assert poly is None

    def test_sm_region_polygon_single(self):
        gen = TerritoryPolygonGenerator(buffer_km=0.5)
        dealer = make_dealer("D1", lat=19.0, lng=73.0)
        territory = gen.generate_territory_polygon(["D1"], [dealer])
        sm_poly = gen.generate_sm_region_polygon([territory])
        assert sm_poly is not None
        assert isinstance(sm_poly, Polygon)

    def test_generate_all_territories(self):
        gen = TerritoryPolygonGenerator(buffer_km=0.5)
        dealers = [
            make_dealer("D1", lat=19.0, lng=73.0),
            make_dealer("D2", lat=19.01, lng=73.01),
            make_dealer("D3", lat=19.02, lng=73.02),
        ]
        assignments = {
            "FTC_1": ["D1", "D2"],
            "FTC_2": ["D3"],
        }
        territories = gen.generate_all_territories(assignments, dealers)
        assert "FTC_1" in territories
        assert "FTC_2" in territories
        assert territories["FTC_1"] is not None
        assert territories["FTC_2"] is not None

    def test_dealer_not_found(self):
        gen = TerritoryPolygonGenerator(buffer_km=0.5)
        dealers = [make_dealer("D1", lat=19.0, lng=73.0)]
        poly = gen.generate_territory_polygon(["UNKNOWN"], dealers)
        assert poly is None

    def test_buffer_effect(self):
        """Larger buffer should produce larger area."""
        gen_small = TerritoryPolygonGenerator(buffer_km=0.5)
        gen_large = TerritoryPolygonGenerator(buffer_km=5.0)
        dealer = make_dealer("D1", lat=19.0, lng=73.0)
        small = gen_small.generate_territory_polygon(["D1"], [dealer])
        large = gen_large.generate_territory_polygon(["D1"], [dealer])
        assert large.area > small.area

    def test_smooth_polygon(self):
        """Smoothing should produce a valid polygon."""
        gen = TerritoryPolygonGenerator(buffer_km=0.5, smooth_iterations=3)
        dealers = [
            make_dealer("D1", lat=19.0, lng=73.0),
            make_dealer("D2", lat=19.05, lng=73.05),
            make_dealer("D3", lat=19.02, lng=73.08),
        ]
        poly = gen.generate_territory_polygon(["D1", "D2", "D3"], dealers)
        assert poly is not None
        assert poly.is_valid
