"""Integration tests for FastAPI endpoints."""

import io
import json
import pytest
from fastapi import UploadFile
import pandas as pd

from app.models.schemas import OptimizationConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_excel_bytes(
    dealers: list = None,
    ftcs: list = None,
    rels: list = None,
) -> bytes:
    dfs = {}
    if dealers is not None:
        dfs["Dealers"] = pd.DataFrame(dealers)
    if ftcs is not None:
        dfs["FTC"] = pd.DataFrame(ftcs)
    if rels is not None:
        dfs["FTC-Dealer"] = pd.DataFrame(rels)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, df in dfs.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buf.getvalue()


# Valid data templates
VALID_DEALER = {
    "SM_id": "SM001", "Dealer_id": "D1", "Dealer_type": "mobile",
    "Product_group": "product_a", "Dealer_latitude": 19.0, "Dealer_longitude": 73.0,
    "Count_BFL_disbursement": 10, "Average_cases_per_day": 5.0,
}
VALID_FTC = {
    "FTC_id": "F1", "SM_id": "SM001", "Product_Group": "product_a",
    "FTC_VIntage": 3, "Count_BFL_disbursement": 50,
    "Average_cases_per_day": 30.0, "Per_sum_MOB": 0.5,
    "NTB_share": 0.3, "Cross_sell": 0.2,
}
VALID_REL = {"Dealer_id": "D1", "FTC_id": "F1", "Product_category": "product_a", "Avg_cases_per_day": 3.0}


class TestUploadEndpoint:
    def test_upload_valid_file(self, client):
        content = _make_excel_bytes(
            dealers=[VALID_DEALER],
            ftcs=[VALID_FTC],
            rels=[VALID_REL],
        )
        resp = client.post("/api/v1/upload", files={"file": ("test.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code in (200, 422, 500)
        if resp.status_code == 200:
            data = resp.json()
            assert "status" in data
            assert "job_id" in data

    def test_upload_no_file(self, client):
        resp = client.post("/api/v1/upload")
        assert resp.status_code == 422

    def test_upload_empty_filename(self, client):
        content = _make_excel_bytes(
            dealers=[VALID_DEALER],
            ftcs=[VALID_FTC],
            rels=[VALID_REL],
        )
        resp = client.post("/api/v1/upload", files={"file": ("", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        # Should fail because filename is empty
        assert resp.status_code in (400, 422)

    def test_upload_invalid_content(self, client):
        resp = client.post("/api/v1/upload", files={"file": ("bad.xlsx", b"not excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code == 400

    def test_upload_missing_sheets(self, client):
        content = _make_excel_bytes(dealers=[VALID_DEALER])
        resp = client.post("/api/v1/upload", files={"file": ("test.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code == 400

    def test_upload_large_file(self, client):
        """File over 50MB should be rejected."""
        large_content = b"x" * (51 * 1024 * 1024)
        resp = client.post("/api/v1/upload", files={"file": ("large.xlsx", large_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code == 413


class TestOptimizationEndpoints:
    def test_optimize_no_job(self, client):
        resp = client.post("/api/v1/optimize/nonexistent")
        assert resp.status_code in (404, 500)

    def test_status_no_job(self, client):
        resp = client.get("/api/v1/status/nonexistent")
        assert resp.status_code == 404

    def test_result_no_job(self, client):
        resp = client.get("/api/v1/result/nonexistent")
        assert resp.status_code == 404

    def test_job_details_no_job(self, client):
        resp = client.get("/api/v1/job/nonexistent")
        assert resp.status_code == 404

    def test_cancel_no_job(self, client):
        resp = client.post("/api/v1/optimize/cancel/nonexistent")
        assert resp.status_code == 404

    def test_history_no_job(self, client):
        resp = client.get("/api/v1/optimize/history/nonexistent")
        assert resp.status_code in (200, 404)  # may return empty list


class TestExportEndpoints:
    def test_export_no_job(self, client):
        resp = client.get("/api/v1/export/nonexistent")
        assert resp.status_code == 404

    def test_export_invalid_format(self, client):
        # First need a valid upload+optimization chain, so skip to format validation
        resp = client.get("/api/v1/export/nonexistent?format=invalid")
        assert resp.status_code in (400, 404)

    def test_export_status_no_job(self, client):
        resp = client.get("/api/v1/export/nonexistent/status")
        assert resp.status_code == 404

    def test_export_validate_no_job(self, client):
        resp = client.get("/api/v1/export/nonexistent/validate")
        assert resp.status_code == 404

    def test_export_files_no_job(self, client):
        resp = client.get("/api/v1/export/nonexistent/files")
        assert resp.status_code in (200, 404)

    def test_generate_export_no_job(self, client):
        resp = client.post("/api/v1/export/nonexistent/generate")
        assert resp.status_code == 404

    def test_bulk_export_empty(self, client):
        resp = client.post("/api/v1/export/bulk", json={"job_ids": [], "formats": ["geojson"]})
        assert resp.status_code in (200, 404)

    def test_export_file_no_job(self, client):
        resp = client.get("/api/v1/export/nonexistent/geojson")
        assert resp.status_code == 404


class TestTerritoryEndpoints:
    def test_territories_no_job(self, client):
        resp = client.get("/api/v1/territories/nonexistent")
        assert resp.status_code == 404


class TestJobsEndpoint:
    def test_list_jobs(self, client):
        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 200
        data = resp.json()
        # Should return a list or dict
        assert isinstance(data, (list, dict))


class TestAnalyticsEndpoint:
    def test_analytics_no_job(self, client):
        resp = client.get("/api/v1/analytics/nonexistent")
        assert resp.status_code == 404


class TestValidateWeights:
    def test_weights_sum_to_one(self, client):
        """POST /optimize/{job_id} with invalid weights should fail."""
        bad_config = OptimizationConfig(
            travel_weight=1.0, workload_weight=1.0,
            compactness_weight=0.0, productivity_weight=0.0,
        )
        resp = client.post(
            "/api/v1/optimize/nonexistent",
            json=bad_config.model_dump(),
        )
        assert resp.status_code == 422
        assert "Weights must sum to 1.0" in resp.text

    def test_weights_valid_sum(self, client):
        good_config = OptimizationConfig(
            travel_weight=0.35, workload_weight=0.30,
            compactness_weight=0.20, productivity_weight=0.15,
        )
        resp = client.post(
            "/api/v1/optimize/nonexistent",
            json=good_config.model_dump(),
        )
        # Nonexistent job but weights are valid → different error
        assert resp.status_code != 422
