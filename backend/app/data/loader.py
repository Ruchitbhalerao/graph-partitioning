from typing import Tuple, List, Dict
import pandas as pd
from fastapi import UploadFile, HTTPException
from ..models.schemas import DealerRecord, FTCRecord, FTCRelationshipRecord
from ..models.enums import DealerType, ProductGroup
import io


class ExcelLoader:
    def __init__(self):
        self.required_sheets = {"Dealers", "FTC", "FTC-Dealer"}

    async def load(self, file: UploadFile) -> Tuple[
        List[DealerRecord], List[FTCRecord], List[FTCRelationshipRecord]
    ]:
        content = await file.read()
        try:
            xls = pd.ExcelFile(io.BytesIO(content))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Excel file: {e}")

        sheets = set(xls.sheet_names)
        missing = self.required_sheets - sheets
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required sheets: {', '.join(missing)}"
            )

        dealers_df = pd.read_excel(xls, sheet_name="Dealers")
        ftc_df = pd.read_excel(xls, sheet_name="FTC")
        rel_df = pd.read_excel(xls, sheet_name="FTC-Dealer")

        required_dealer_cols = {
            "SM_id", "Dealer_id", "Dealer_type",
            "Product_group", "Dealer_latitude", "Dealer_longitude"
        }
        required_ftc_cols = {
            "FTC_id", "SM_id", "Product_Group",
            "FTC_VIntage", "Per_sum_MOB", "NTB_share", "Cross_sell"
        }
        required_rel_cols = {"Dealer_id", "FTC_id", "Product_category"}

        self._validate_columns(dealers_df, required_dealer_cols, "Dealers")
        self._validate_columns(ftc_df, required_ftc_cols, "FTC")
        self._validate_columns(rel_df, required_rel_cols, "FTC-Dealer")

        dealers = self._parse_dealers(dealers_df)
        ftcs = self._parse_ftcs(ftc_df)
        rels = self._parse_relationships(rel_df)

        return dealers, ftcs, rels

    def _validate_columns(self, df: pd.DataFrame, required: set, sheet: str):
        actual = set(df.columns)
        missing = required - actual
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Sheet '{sheet}' missing columns: {', '.join(missing)}"
            )

    def _parse_dealers(self, df: pd.DataFrame) -> List[DealerRecord]:
        df = df.fillna({
            "Count_BFL_disbursement": 0,
            "Average_cases_per_day": 0.0
        })
        records = []
        for _, row in df.iterrows():
            records.append(DealerRecord(
                SM_id=str(row["SM_id"]),
                Dealer_id=str(row["Dealer_id"]),
                Dealer_type=DealerType(row["Dealer_type"].strip().lower()),
                Product_group=ProductGroup(row["Product_group"]),
                Count_BFL_disbursement=int(row.get("Count_BFL_disbursement", 0)),
                Average_cases_per_day=float(row.get("Average_cases_per_day", 0.0)),
                Dealer_latitude=float(row["Dealer_latitude"]),
                Dealer_longitude=float(row["Dealer_longitude"]),
            ))
        return records

    def _parse_ftcs(self, df: pd.DataFrame) -> List[FTCRecord]:
        df = df.fillna({
            "FTC_VIntage": 0,
            "Count_BFL_disbursement": 0,
            "Average_cases_per_day": 0.0,
            "Per_sum_MOB": 0.0,
            "NTB_share": 0.0,
            "Cross_sell": 0.0,
        })
        records = []
        for _, row in df.iterrows():
            records.append(FTCRecord(
                FTC_id=str(row["FTC_id"]),
                SM_id=str(row["SM_id"]),
                Product_Group=ProductGroup(row["Product_Group"]),
                FTC_VIntage=int(row.get("FTC_VIntage", 0)),
                Count_BFL_disbursement=int(row.get("Count_BFL_disbursement", 0)),
                Average_cases_per_day=float(row.get("Average_cases_per_day", 0.0)),
                Per_sum_MOB=float(row.get("Per_sum_MOB", 0.0)),
                NTB_share=float(row.get("NTB_share", 0.0)),
                Cross_sell=float(row.get("Cross_sell", 0.0)),
            ))
        return records

    def _parse_relationships(self, df: pd.DataFrame) -> List[FTCRelationshipRecord]:
        df = df.fillna({"Avg_cases_per_day": 0.0})
        records = []
        for _, row in df.iterrows():
            records.append(FTCRelationshipRecord(
                Dealer_id=str(row["Dealer_id"]),
                FTC_id=str(row["FTC_id"]),
                Product_category=ProductGroup(row["Product_category"]),
                Avg_cases_per_day=float(row.get("Avg_cases_per_day", 0.0)),
            ))
        return records

    def get_summary(self, dealers, ftcs, rels) -> dict:
        sm_ids = set(d.SM_id for d in dealers)
        return {
            "total_dealers": len(dealers),
            "total_ftcs": len(ftcs),
            "total_relationships": len(rels),
            "total_sm_regions": len(sm_ids),
            "static_dealers": sum(1 for d in dealers if d.Dealer_type == DealerType.STATIC),
            "mobile_dealers": sum(1 for d in dealers if d.Dealer_type == DealerType.MOBILE),
            "sm_ids": sorted(sm_ids),
        }
