"""Tests for QGISExporter — GIS export formats and file generation."""

import os
import json
import csv
import tempfile
import pytest
from shapely.geometry import shape

from app.geography.qgis_exporter import QGISExporter, TERRITORY_STYLE_QML, DEALER_STYLE_QML
from app.models.enums import DealerType
from helpers import make_dealer, make_ftc


@pytest.fixture
def temp_output_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_results():
    """Minimal optimization results dict."""
    return {
        "SM001": {
            "assignments": {
                "FTC_1": ["D1", "D2"],
                "FTC_2": ["D3"],
            },
            "anchors": {"FTC_1": "D1", "FTC_2": "D3"},
            "ftc_count": 2,
            "static_dealers": 1,
            "mobile_dealers": 2,
            "is_valid": True,
        }
    }


@pytest.fixture
def sample_dealers():
    return [
        make_dealer("D1", sm_id="SM001", dealer_type=DealerType.STATIC, lat=19.0, lng=73.0),
        make_dealer("D2", sm_id="SM001", lat=19.01, lng=73.01),
        make_dealer("D3", sm_id="SM001", lat=19.02, lng=73.02),
    ]


@pytest.fixture
def sample_ftcs():
    return [
        make_ftc("FTC_1", sm_id="SM001"),
        make_ftc("FTC_2", sm_id="SM001"),
    ]


class TestQGISExporter:
    def test_export_all_basic(self, temp_output_dir, sample_results, sample_dealers, sample_ftcs):
        exporter = QGISExporter(output_dir=temp_output_dir)
        files = exporter.export_all("job_001", sample_results, sample_dealers, sample_ftcs)

        assert "territories_geojson" in files
        assert "dealers_geojson" in files
        assert "assignments_csv" in files
        assert "dealers_csv" in files
        assert "sm_summary_csv" in files
        assert "sm_boundaries_geojson" in files
        assert "metadata_json" in files
        assert "manifest_json" in files
        assert "qgis_project" in files

        for key, path in files.items():
            if key != "styles_dir" and os.path.isfile(path):
                assert os.path.exists(path), f"{key} at {path} not found"

    def test_export_territories_geojson(self, temp_output_dir, sample_results, sample_dealers, sample_ftcs):
        exporter = QGISExporter(output_dir=temp_output_dir)
        path = exporter._export_territory_polygons(
            temp_output_dir, "job_001", sample_results, sample_dealers, sample_ftcs
        )
        with open(path) as f:
            gj = json.load(f)

        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == 2
        feature = gj["features"][0]
        assert "properties" in feature
        assert "ftc_id" in feature["properties"]
        assert "sm_id" in feature["properties"]
        assert "dealer_count" in feature["properties"]
        assert "geometry" in feature
        assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")

    def test_export_dealers_geojson(self, temp_output_dir, sample_results, sample_dealers):
        exporter = QGISExporter(output_dir=temp_output_dir)
        path = exporter._export_dealer_points(
            temp_output_dir, "job_001", sample_results, sample_dealers
        )
        with open(path) as f:
            gj = json.load(f)

        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == 3
        for feat in gj["features"]:
            assert feat["geometry"]["type"] == "Point"
            assert "dealer_id" in feat["properties"]
            assert "assigned_ftc" in feat["properties"]

    def test_export_assignments_csv(self, temp_output_dir, sample_results):
        exporter = QGISExporter(output_dir=temp_output_dir)
        path = exporter._export_assignments(temp_output_dir, "job_001", sample_results)

        with open(path, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 4  # header + 3 dealer assignments
        assert rows[0] == ["SM_ID", "FTC_ID", "Dealer_ID", "Is_Anchor"]
        assert rows[1] == ["SM001", "FTC_1", "D1", "Yes"]
        assert rows[2] == ["SM001", "FTC_1", "D2", "No"]
        assert rows[3] == ["SM001", "FTC_2", "D3", "Yes"]

    def test_export_dealers_csv(self, temp_output_dir, sample_results, sample_dealers):
        exporter = QGISExporter(output_dir=temp_output_dir)
        path = exporter._export_dealers_csv(temp_output_dir, "job_001", sample_results, sample_dealers)

        with open(path, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 4  # header + 3 dealers
        assert rows[0][0] == "Dealer_ID"
        assert rows[1][0] == "D1"

    def test_export_sm_summary_csv(self, temp_output_dir, sample_results):
        exporter = QGISExporter(output_dir=temp_output_dir)
        path = exporter._export_sm_summary_csv(temp_output_dir, "job_001", sample_results)

        with open(path, newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 2  # header + 1 region
        assert rows[1][0] == "SM001"
        assert rows[1][5] == "Yes"

    def test_export_metadata(self, temp_output_dir, sample_results, sample_dealers, sample_ftcs):
        exporter = QGISExporter(output_dir=temp_output_dir)
        path = exporter._export_metadata(temp_output_dir, "job_001", sample_results, sample_dealers, sample_ftcs)

        with open(path) as f:
            meta = json.load(f)

        assert meta["job_id"] == "job_001"
        assert meta["total_dealers"] == 3
        assert meta["total_ftcs"] == 2
        assert meta["total_sm_regions"] == 1
        assert "optimization_parameters" in meta
        assert "output_files" in meta

    def test_export_manifest(self, temp_output_dir, sample_results, sample_dealers, sample_ftcs):
        exporter = QGISExporter(output_dir=temp_output_dir)
        files = exporter.export_all("job_001", sample_results, sample_dealers, sample_ftcs)
        manifest_path = files.get("manifest_json")
        assert manifest_path and os.path.exists(manifest_path)

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["job_id"] == "job_001"
        assert manifest["total_files"] >= 5
        for entry in manifest["files"]:
            assert "key" in entry
            assert "size_bytes" in entry

    def test_export_with_routes(self, temp_output_dir, sample_results, sample_dealers, sample_ftcs):
        exporter = QGISExporter(output_dir=temp_output_dir)
        files = exporter.export_all(
            "job_001", sample_results, sample_dealers, sample_ftcs,
            include_routes=True,
        )
        # Routes may not be generated if routing is not supported
        if "routes_geojson" in files:
            assert os.path.exists(files["routes_geojson"])

    def test_export_shapefile(self, temp_output_dir, sample_results, sample_dealers, sample_ftcs):
        exporter = QGISExporter(output_dir=temp_output_dir)
        files = exporter.export_all("job_001", sample_results, sample_dealers, sample_ftcs)
        zip_path = files.get("shapefile_zip")
        if zip_path and os.path.exists(zip_path):
            import zipfile
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert any(name.endswith(".shp") for name in names)

    def test_export_qgis_project(self, temp_output_dir, sample_results, sample_dealers, sample_ftcs):
        exporter = QGISExporter(output_dir=temp_output_dir)
        files = exporter.export_all("job_001", sample_results, sample_dealers, sample_ftcs)
        qgs_path = files.get("qgis_project")
        assert qgs_path and os.path.exists(qgs_path)
        with open(qgs_path) as f:
            content = f.read()
        assert "Territory Optimization" in content
        assert "Territories" in content

    def test_format_size(self):
        assert QGISExporter._format_size(500) == "500 B"
        assert QGISExporter._format_size(2048) == "2.0 KB"
        assert QGISExporter._format_size(1048576 * 2) == "2.0 MB"

    def test_style_qml_present(self):
        assert "qgis" in TERRITORY_STYLE_QML
        assert "ftc_id" in TERRITORY_STYLE_QML
        assert "qgis" in DEALER_STYLE_QML
        assert "dealer_type" in DEALER_STYLE_QML
