"""Unit tests for ExcelLoader — Excel parsing and validation."""

import io
import pytest
from fastapi import UploadFile, HTTPException

import pandas as pd
from app.data.loader import ExcelLoader
from app.models.enums import DealerType, ProductGroup


def _make_excel_bytes(
    dealers: list = None,
    ftcs: list = None,
    rels: list = None,
) -> bytes:
    """Create an in-memory Excel file from DataFrames."""
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


def _make_upload(content: bytes, filename: str = "test.xlsx") -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


class TestExcelLoader:
    # Minimal valid data
    VALID_DEALER = {
        "SM_id": "SM001", "Dealer_id": "D1", "Dealer_type": "mobile",
        "Product_group": "product_a", "Dealer_latitude": 19.0, "Dealer_longitude": 73.0,
    }
    VALID_FTC = {
        "FTC_id": "F1", "SM_id": "SM001", "Product_Group": "product_a",
        "FTC_VIntage": 3, "Per_sum_MOB": 0.5, "NTB_share": 0.3, "Cross_sell": 0.2,
    }
    VALID_REL = {"Dealer_id": "D1", "FTC_id": "F1", "Product_category": "product_a"}

    @pytest.mark.asyncio
    async def test_valid_file(self):
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        upload = _make_upload(content)
        loader = ExcelLoader()
        dealers, ftcs, rels = await loader.load(upload)

        assert len(dealers) == 1
        assert len(ftcs) == 1
        assert len(rels) == 1
        assert dealers[0].Dealer_id == "D1"
        assert ftcs[0].FTC_id == "F1"

    @pytest.mark.asyncio
    async def test_missing_sheet(self):
        content = _make_excel_bytes(dealers=[self.VALID_DEALER])
        upload = _make_upload(content)
        loader = ExcelLoader()
        with pytest.raises(HTTPException) as exc:
            await loader.load(upload)
        assert exc.value.status_code == 400
        assert "Missing required sheets" in exc.value.detail

    @pytest.mark.asyncio
    async def test_invalid_excel(self):
        content = b"not an excel file"
        upload = _make_upload(content)
        loader = ExcelLoader()
        with pytest.raises(HTTPException) as exc:
            await loader.load(upload)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_dealer_columns(self):
        bad_dealer = {"Dealer_id": "D1"}  # missing all required cols
        content = _make_excel_bytes(
            dealers=[bad_dealer],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        upload = _make_upload(content)
        loader = ExcelLoader()
        with pytest.raises(HTTPException) as exc:
            await loader.load(upload)
        assert exc.value.status_code == 400
        assert "Dealers" in exc.value.detail

    @pytest.mark.asyncio
    async def test_missing_ftc_columns(self):
        bad_ftc = {"FTC_id": "F1"}  # missing required cols
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[bad_ftc],
            rels=[self.VALID_REL],
        )
        upload = _make_upload(content)
        loader = ExcelLoader()
        with pytest.raises(HTTPException) as exc:
            await loader.load(upload)
        assert exc.value.status_code == 400
        assert "FTC" in exc.value.detail

    @pytest.mark.asyncio
    async def test_missing_rel_columns(self):
        bad_rel = {"Dealer_id": "D1"}  # missing FTC_id and Product_category
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[self.VALID_FTC],
            rels=[bad_rel],
        )
        upload = _make_upload(content)
        loader = ExcelLoader()
        with pytest.raises(HTTPException) as exc:
            await loader.load(upload)
        assert exc.value.status_code == 400
        assert "FTC-Dealer" in exc.value.detail

    @pytest.mark.asyncio
    async def test_dealer_type_parsing(self):
        content = _make_excel_bytes(
            dealers=[dict(self.VALID_DEALER, Dealer_type="STATIC")],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        dealers, _, _ = await loader.load(_make_upload(content))
        assert dealers[0].Dealer_type == DealerType.STATIC

    @pytest.mark.asyncio
    async def test_multiple_rows(self):
        dealers = [
            dict(self.VALID_DEALER, Dealer_id="D1"),
            dict(self.VALID_DEALER, Dealer_id="D2"),
        ]
        ftcs = [self.VALID_FTC]
        rels = [
            dict(self.VALID_REL, Dealer_id="D1"),
            dict(self.VALID_REL, Dealer_id="D2"),
        ]
        content = _make_excel_bytes(dealers=dealers, ftcs=ftcs, rels=rels)
        loader = ExcelLoader()
        dealers_out, ftcs_out, rels_out = await loader.load(_make_upload(content))
        assert len(dealers_out) == 2
        assert len(rels_out) == 2

    @pytest.mark.asyncio
    async def test_no_file_name(self):
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        upload = UploadFile(filename="", file=io.BytesIO(content))
        loader = ExcelLoader()
        with pytest.raises(HTTPException) as exc:
            await loader.load(upload)
        assert exc.value.status_code == 400  # or 422 handled by route
        # Loader itself doesn't check filename, so may pass

    @pytest.mark.asyncio
    async def test_summary(self):
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        dealers, ftcs, rels = await loader.load(_make_upload(content))
        summary = loader.get_summary(dealers, ftcs, rels)
        assert summary["total_dealers"] == 1
        assert summary["total_ftcs"] == 1
        assert summary["total_relationships"] == 1
        assert summary["total_sm_regions"] == 1
        assert summary["static_dealers"] == 0
        assert summary["mobile_dealers"] == 1
        assert summary["sm_ids"] == ["SM001"]

    @pytest.mark.asyncio
    async def test_summary_multiple_sm(self):
        dealers = [
            dict(self.VALID_DEALER, Dealer_id="D1", SM_id="SM001"),
            dict(self.VALID_DEALER, Dealer_id="D2", SM_id="SM002"),
        ]
        ftcs = [
            dict(self.VALID_FTC, FTC_id="F1", SM_id="SM001"),
            dict(self.VALID_FTC, FTC_id="F2", SM_id="SM002"),
        ]
        content = _make_excel_bytes(dealers=dealers, ftcs=ftcs, rels=[])
        loader = ExcelLoader()
        dealers, ftcs, _ = await loader.load(_make_upload(content))
        summary = loader.get_summary(dealers, ftcs, [])
        assert summary["total_sm_regions"] == 2
        assert summary["sm_ids"] == ["SM001", "SM002"]

    @pytest.mark.asyncio
    async def test_empty_sheets(self):
        content = _make_excel_bytes(dealers=[], ftcs=[], rels=[])
        loader = ExcelLoader()
        dealers, ftcs, rels = await loader.load(_make_upload(content))
        assert dealers == []
        assert ftcs == []
        assert rels == []

    @pytest.mark.asyncio
    async def test_extra_columns_ignored(self):
        dealer_with_extra = dict(self.VALID_DEALER, Extra_Col="ignored")
        content = _make_excel_bytes(
            dealers=[dealer_with_extra],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        dealers, _, _ = await loader.load(_make_upload(content))
        assert dealers[0].Dealer_id == "D1"
