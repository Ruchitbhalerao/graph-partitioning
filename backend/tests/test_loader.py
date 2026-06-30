"""Unit tests for ExcelLoader — Excel parsing and validation."""

import io
import pytest

import pandas as pd
from app.data.loader import ExcelLoader
from app.models.enums import DealerType, ProductGroup


DEALER_COLS = [
    "SM_id", "Dealer_id", "Dealer_type", "Product_group",
    "Dealer_latitude", "Dealer_longitude", "Count_BFL_disbursement", "Average_cases_per_day",
]
FTC_COLS = [
    "FTC_id", "SM_id", "Product_Group", "FTC_VIntage",
    "Count_BFL_disbursement", "Average_cases_per_day",
    "Per_sum_MOB", "NTB_share", "Cross_sell",
]
REL_COLS = ["Dealer_id", "FTC_id", "Product_category", "Avg_cases_per_day"]


def _make_excel_bytes(
    dealers: list = None,
    ftcs: list = None,
    rels: list = None,
) -> bytes:
    """Create an in-memory Excel file from DataFrames."""
    dfs = {}
    if dealers is not None:
        dfs["Dealers"] = pd.DataFrame(dealers, columns=DEALER_COLS) if not dealers else pd.DataFrame(dealers)
    if ftcs is not None:
        dfs["FTC"] = pd.DataFrame(ftcs, columns=FTC_COLS) if not ftcs else pd.DataFrame(ftcs)
    if rels is not None:
        dfs["FTC-Dealer"] = pd.DataFrame(rels, columns=REL_COLS) if not rels else pd.DataFrame(rels)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, df in dfs.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buf.getvalue()


class TestExcelLoader:
    # Minimal valid data
    VALID_DEALER = {
        "SM_id": "SM001", "Dealer_id": "D1", "Dealer_type": "mobile",
        "Product_group": "Product_A", "Dealer_latitude": 19.0, "Dealer_longitude": 73.0,
    }
    VALID_FTC = {
        "FTC_id": "F1", "SM_id": "SM001", "Product_Group": "Product_A",
        "FTC_VIntage": 3, "Per_sum_MOB": 0.5, "NTB_share": 0.3, "Cross_sell": 0.2,
    }
    VALID_REL = {"Dealer_id": "D1", "FTC_id": "F1", "Product_category": "Product_A"}

    def test_valid_file(self):
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        dealers, ftcs, rels = loader.load(content)

        assert len(dealers) == 1
        assert len(ftcs) == 1
        assert len(rels) == 1
        assert dealers[0].Dealer_id == "D1"
        assert ftcs[0].FTC_id == "F1"

    def test_missing_sheet(self):
        content = _make_excel_bytes(dealers=[self.VALID_DEALER])
        loader = ExcelLoader()
        with pytest.raises(ValueError, match="Missing required sheets"):
            loader.load(content)

    def test_invalid_excel(self):
        content = b"not an excel file"
        loader = ExcelLoader()
        with pytest.raises(ValueError, match="Invalid Excel file"):
            loader.load(content)

    def test_missing_dealer_columns(self):
        bad_dealer = {"Dealer_id": "D1"}
        content = _make_excel_bytes(
            dealers=[bad_dealer],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        with pytest.raises(ValueError, match="Dealers"):
            loader.load(content)

    def test_missing_ftc_columns(self):
        bad_ftc = {"FTC_id": "F1"}
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[bad_ftc],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        with pytest.raises(ValueError, match="FTC"):
            loader.load(content)

    def test_missing_rel_columns(self):
        bad_rel = {"Dealer_id": "D1"}
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[self.VALID_FTC],
            rels=[bad_rel],
        )
        loader = ExcelLoader()
        with pytest.raises(ValueError, match="FTC-Dealer"):
            loader.load(content)

    def test_dealer_type_parsing(self):
        content = _make_excel_bytes(
            dealers=[dict(self.VALID_DEALER, Dealer_type="STATIC")],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        dealers, _, _ = loader.load(content)
        assert dealers[0].Dealer_type == DealerType.STATIC

    def test_multiple_rows(self):
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
        dealers_out, ftcs_out, rels_out = loader.load(content)
        assert len(dealers_out) == 2
        assert len(rels_out) == 2

    def test_summary(self):
        content = _make_excel_bytes(
            dealers=[self.VALID_DEALER],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        dealers, ftcs, rels = loader.load(content)
        summary = loader.get_summary(dealers, ftcs, rels)
        assert summary["total_dealers"] == 1
        assert summary["total_ftcs"] == 1
        assert summary["total_relationships"] == 1
        assert summary["total_sm_regions"] == 1
        assert summary["static_dealers"] == 0
        assert summary["mobile_dealers"] == 1
        assert summary["sm_ids"] == ["SM001"]

    def test_summary_multiple_sm(self):
        dealers = [
            dict(self.VALID_DEALER, Dealer_id="D1", SM_id="SM001"),
            dict(self.VALID_DEALER, Dealer_id="D2", SM_id="SM002"),
        ]
        ftcs = [
            dict(self.VALID_FTC, FTC_id="F1", SM_id="SM001"),
            dict(self.VALID_FTC, FTC_id="F2", SM_id="SM002"),
        ]
        rels = [{"Dealer_id": "D1", "FTC_id": "F1", "Product_category": "Product_A"}]
        content = _make_excel_bytes(dealers=dealers, ftcs=ftcs, rels=rels)
        loader = ExcelLoader()
        dealers, ftcs, _ = loader.load(content)
        summary = loader.get_summary(dealers, ftcs, [])
        assert summary["total_sm_regions"] == 2
        assert summary["sm_ids"] == ["SM001", "SM002"]

    def test_empty_sheets(self):
        content = _make_excel_bytes(dealers=[], ftcs=[], rels=[])
        loader = ExcelLoader()
        dealers, ftcs, rels = loader.load(content)
        assert dealers == []
        assert ftcs == []
        assert rels == []

    def test_extra_columns_ignored(self):
        dealer_with_extra = dict(self.VALID_DEALER, Extra_Col="ignored")
        content = _make_excel_bytes(
            dealers=[dealer_with_extra],
            ftcs=[self.VALID_FTC],
            rels=[self.VALID_REL],
        )
        loader = ExcelLoader()
        dealers, _, _ = loader.load(content)
        assert dealers[0].Dealer_id == "D1"
