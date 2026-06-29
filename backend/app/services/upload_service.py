from typing import Tuple, List, Dict, Optional, Any
from datetime import datetime, timedelta
import uuid
import io
import os
import re
import tempfile
import threading

import pandas as pd
from openpyxl import load_workbook

from ..models.schemas import (
    DealerRecord, FTCRecord, FTCRelationshipRecord,
    UploadResponse, ValidationErrorItem, DataPreviewRow,
    SheetPreview, DataPreview, ColumnCompleteness,
    DataQualityMetrics, UploadSummary,
)
from ..models.enums import DealerType, ProductGroup
from ..data.validator import DataValidator
from ..data.processor import DataProcessor


REQUIRED_SHEETS = {"Dealers", "FTC", "FTC-Dealer"}

COLUMN_ALIASES = {
    "Dealers": {
        "dealer_id": "Dealer_id",
        "dealerid": "Dealer_id",
        "sm_id": "SM_id",
        "dealer_type_static_mobile": "Dealer_type",
        "dealer_type": "Dealer_type",
        "avgcasesperday": "Average_cases_per_day",
        "avg_cases_per_day": "Average_cases_per_day",
        "count_bfl_disbursement": "Count_BFL_disbursement",
        "dealer_latitude": "Dealer_latitude",
        "dealer_lat": "Dealer_latitude",
        "dealer_longitude": "Dealer_longitude",
        "dealer_lng": "Dealer_longitude",
        "dealer_long": "Dealer_longitude",
        "product_group": "Product_group",
    },
    "FTC": {
        "ftc_id": "FTC_id",
        "ftc": "FTC_id",
        "fte_id": "FTE_id",
        "avgcasesperday": "Average_cases_per_day",
        "avg_cases_per_day": "Average_cases_per_day",
        "count_bfl_disbursement": "Count_BFL_disbursement",
        "per_sum_mob03": "Per_sum_MOB",
        "per_sum_mob": "Per_sum_MOB",
        "ftc_vintage": "FTC_VIntage",
        "vintage": "FTC_VIntage",
        "ntb_share_per": "NTB_share",
        "ntb_share": "NTB_share",
        "cross_sell_share_per": "Cross_sell",
        "cross_sell": "Cross_sell",
        "product_group": "Product_Group",
    },
    "FTC-Dealer": {
        "dealer_id": "Dealer_id",
        "dealerid": "Dealer_id",
        "ftc_id": "FTC_id",
        "FTC_ID": "FTC_id",
        "ftc": "FTC_id",
        "avgcasesperday": "Avg_cases_per_day",
        "avg_cases_per_day": "Avg_cases_per_day",
        "product_category": "Product_category",
    },
}

DEALER_COLUMNS = {
    "SM_id", "Dealer_id", "Dealer_type", "Product_group",
    "Count_BFL_disbursement", "Average_cases_per_day",
    "Dealer_latitude", "Dealer_longitude",
}
DEALER_REQUIRED = {"SM_id", "Dealer_id", "Dealer_type",
                   "Dealer_latitude", "Dealer_longitude"}
DEALER_NUMERIC = {"Count_BFL_disbursement", "Average_cases_per_day",
                  "Dealer_latitude", "Dealer_longitude"}

FTC_COLUMNS = {
    "FTC_id", "SM_id", "Product_Group", "FTC_VIntage",
    "Count_BFL_disbursement", "Average_cases_per_day",
    "Per_sum_MOB", "NTB_share", "Cross_sell",
}
FTC_REQUIRED = {"FTC_id"}
FTC_NUMERIC = {"FTC_VIntage", "Count_BFL_disbursement",
               "Average_cases_per_day", "Per_sum_MOB",
               "NTB_share", "Cross_sell"}

REL_COLUMNS = {"Dealer_id", "FTC_id", "Product_category", "Avg_cases_per_day"}
REL_REQUIRED = {"Dealer_id", "FTC_id"}
REL_NUMERIC = {"Avg_cases_per_day"}

VALID_DEALER_TYPES = {"static", "mobile"}
VALID_PRODUCT_GROUPS = {"product_a", "product_b", "product_c"}


class ParsedSheet:
    def __init__(self, sheet_name: str, df: pd.DataFrame):
        self.sheet_name = sheet_name
        self.df = df
        self.errors: List[ValidationErrorItem] = []
        self.columns = list(df.columns)
        self.total_rows = len(df)


class UploadService:
    def __init__(self):
        self.validator = DataValidator()
        self.processor = DataProcessor()
        self._jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self.PREVIEW_ROWS = 5

    # ==================================================================
    # MAIN ENTRY POINT
    # ==================================================================

    def process_upload(self, file_content: bytes, filename: str) -> UploadResponse:
        job_id = str(uuid.uuid4())
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        errors: List[ValidationErrorItem] = []

        if ext in ("csv",):
            try:
                dealers_ps, ftc_ps, rel_ps = self._parse_csv_files(file_content, filename)
            except Exception as e:
                errors.append(ValidationErrorItem(
                    sheet="", row=None, column=None,
                    message=f"Failed to read CSV: {e}",
                    error_type="file_read",
                ))
                return UploadResponse(
                    job_id=job_id, status="error",
                    message="Failed to read CSV file", errors=errors,
                )
        elif ext in ("xlsx", "xls"):
            try:
                xls = self._read_excel(file_content)
            except Exception as e:
                errors.append(ValidationErrorItem(
                    sheet="", row=None, column=None,
                    message=f"Failed to read Excel file: {e}",
                    error_type="file_read",
                ))
                return UploadResponse(
                    job_id=job_id, status="error",
                    message="Failed to read Excel file", errors=errors,
                )

            sheet_names = set(xls.sheet_names)
            aliased_sheets = {self._normalize_sheet_name(s) for s in sheet_names}
            missing_sheets = REQUIRED_SHEETS - aliased_sheets
            if missing_sheets:
                for s in sorted(missing_sheets):
                    errors.append(ValidationErrorItem(
                        sheet=s, row=None, column=None,
                        message=f"Missing required sheet '{s}'",
                        error_type="missing_sheet",
                    ))
                return UploadResponse(
                    job_id=job_id, status="error",
                    message=f"Missing sheets: {', '.join(sorted(missing_sheets))}",
                    errors=errors,
                )

            dealers_ps, ftc_ps, rel_ps = self._parse_all_sheets(xls)
        else:
            errors.append(ValidationErrorItem(
                sheet="", row=None, column=None,
                message=f"Unsupported file type '.{ext}'. Only .xlsx, .xls, and .csv files are accepted.",
                error_type="file_type",
            ))
            return UploadResponse(
                job_id=job_id, status="error",
                message=f"Unsupported file type '.{ext}'", errors=errors,
            )
        all_errors: List[ValidationErrorItem] = []
        all_errors.extend(dealers_ps.errors)
        all_errors.extend(ftc_ps.errors)
        all_errors.extend(rel_ps.errors)

        if all_errors:
            return UploadResponse(
                job_id=job_id,
                status="error",
                message=f"Found {len(all_errors)} parsing error(s)",
                errors=all_errors,
            )

        dealers = self._parse_dealers_df(dealers_ps.df, all_errors)
        ftcs = self._parse_ftcs_df(ftc_ps.df, all_errors)
        rels = self._parse_rels_df(rel_ps.df, all_errors)

        ftcs = self._infer_ftc_sm_ids(ftcs, rels, dealers)

        if all_errors:
            return UploadResponse(
                job_id=job_id,
                status="error",
                message=f"Found {len(all_errors)} data error(s)",
                errors=all_errors,
            )

        is_valid, validation_errors = self.validator.validate(dealers, ftcs, rels)
        for ve in validation_errors:
            all_errors.append(ValidationErrorItem(
                sheet="",
                row=None,
                column=None,
                message=ve,
                error_type="validation",
            ))

        quality = self._compute_quality_metrics(dealers, ftcs, rels, all_errors)
        preview = self._build_preview(dealers_ps.df, ftc_ps.df, rel_ps.df)
        summary = UploadSummary(
            total_dealers=len(dealers),
            total_ftcs=len(ftcs),
            total_relationships=len(rels),
            total_sm_regions=len({d.SM_id for d in dealers}),
            static_dealers=sum(1 for d in dealers if d.Dealer_type == DealerType.STATIC),
            mobile_dealers=sum(1 for d in dealers if d.Dealer_type == DealerType.MOBILE),
            sm_ids=sorted({d.SM_id for d in dealers}),
        )

        status = "validated" if is_valid else "validation_failed"
        message = (
            "File uploaded and validated successfully"
            if is_valid
            else f"Validation failed: {len(all_errors)} error(s)"
        )

        with self._lock:
            self._jobs[job_id] = {
                "status": status,
                "dealers": dealers,
                "ftcs": ftcs,
                "rels": rels,
                "summary": summary.model_dump(),
                "created_at": datetime.now(),
                "filename": filename,
            }

        return UploadResponse(
            job_id=job_id,
            status=status,
            message=message,
            summary=summary,
            errors=all_errors,
            preview=preview,
            quality_metrics=quality,
        )

    # ==================================================================
    # EXCEL READING
    # ==================================================================

    def _read_excel(self, content: bytes) -> pd.ExcelFile:
        return pd.ExcelFile(io.BytesIO(content))

    def _normalize_sheet_name(self, name: str) -> str:
        mapping = {
            "dealers": "Dealers",
            "ftc": "FTC",
            "ftc-dealer": "FTC-Dealer",
            "f2d": "FTC-Dealer",
            "f2d dataset": "FTC-Dealer",
            "dealer dataset": "Dealers",
            "ftc dataset": "FTC",
        }
        return mapping.get(name.strip().lower(), name)

    def _normalize_columns(self, df: pd.DataFrame, sheet_key: str) -> pd.DataFrame:
        aliases = COLUMN_ALIASES.get(sheet_key, {})
        renamed = {}
        for col in df.columns:
            c = str(col).strip()
            lowered = c.lower().replace(" ", "_")
            if c in aliases:
                renamed[c] = aliases[c]
            elif lowered in aliases:
                renamed[c] = aliases[lowered]
            else:
                renamed[c] = c
        df = df.rename(columns=renamed)
        drop_cols = [c for c in df.columns if c in ("FTE_id",)]
        if drop_cols:
            df = df.drop(columns=drop_cols)
        return df

    def _parse_csv_file(self, content: bytes, sheet_name: str, sheet_key: str):
        import csv
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        lines = [l for l in text.splitlines() if l.strip()]
        if not lines:
            return ParsedSheet(sheet_name, pd.DataFrame())
        processed = "\n".join(lines)
        df = pd.read_csv(io.StringIO(processed), dtype=str, keep_default_na=False)
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        df.replace("null", pd.NA, inplace=True)
        df.replace("", pd.NA, inplace=True)
        df = df.dropna(how="all").reset_index(drop=True)
        df = self._normalize_columns(df, sheet_key)
        return ParsedSheet(sheet_name, df)

    def _parse_csv_files(self, content: bytes, filename: str):
        base = filename.rsplit(".", 1)[0].lower()
        dealers_ps = ftc_ps = rel_ps = None
        if "dealer" in base:
            dealers_ps = self._parse_csv_file(content, "Dealers", "Dealers")
            return dealers_ps, ParsedSheet("FTC", pd.DataFrame()), ParsedSheet("FTC-Dealer", pd.DataFrame())
        elif "f2d" in base:
            rel_ps = self._parse_csv_file(content, "FTC-Dealer", "FTC-Dealer")
            return ParsedSheet("Dealers", pd.DataFrame()), ParsedSheet("FTC", pd.DataFrame()), rel_ps
        elif "ftc" in base:
            ftc_ps = self._parse_csv_file(content, "FTC", "FTC")
            return ParsedSheet("Dealers", pd.DataFrame()), ftc_ps, ParsedSheet("FTC-Dealer", pd.DataFrame())
        return (
            ParsedSheet("Dealers", pd.DataFrame()),
            ParsedSheet("FTC", pd.DataFrame()),
            ParsedSheet("FTC-Dealer", pd.DataFrame()),
        )

    def _resolve_sheet_name(self, xls: pd.ExcelFile, canonical: str) -> str:
        actual_names = list(xls.sheet_names)
        for name in actual_names:
            if self._normalize_sheet_name(name) == canonical:
                return name
        return canonical

    SHEET_CANONICAL = {"Dealers": "Dealers", "FTC": "FTC", "FTC-Dealer": "FTC-Dealer"}

    def _parse_all_sheets(
        self, xls: pd.ExcelFile
    ) -> Tuple[ParsedSheet, ParsedSheet, ParsedSheet]:
        dlr_name = self._resolve_sheet_name(xls, "Dealers")
        ftc_name = self._resolve_sheet_name(xls, "FTC")
        rel_name = self._resolve_sheet_name(xls, "FTC-Dealer")
        dealers_ps = self._parse_sheet(xls, dlr_name, "Dealers", DEALER_COLUMNS, DEALER_REQUIRED)
        ftc_ps = self._parse_sheet(xls, ftc_name, "FTC", FTC_COLUMNS, FTC_REQUIRED)
        rel_ps = self._parse_sheet(xls, rel_name, "FTC-Dealer", REL_COLUMNS, REL_REQUIRED)
        return dealers_ps, ftc_ps, rel_ps

    def _parse_sheet(
        self, xls: pd.ExcelFile, sheet_name: str, canonical: str,
        expected_columns: set, required_columns: set,
    ) -> ParsedSheet:
        df = pd.read_excel(xls, sheet_name=sheet_name)
        df = self._normalize_columns(df, canonical)
        ps = ParsedSheet(sheet_name, df)

        if df.empty:
            ps.errors.append(ValidationErrorItem(
                sheet=sheet_name, row=None, column=None,
                message=f"Sheet '{sheet_name}' is empty",
                error_type="empty_sheet",
            ))
            return ps

        actual_cols = set(str(c).strip() for c in df.columns)
        missing_required = required_columns - actual_cols
        for col in sorted(missing_required):
            ps.errors.append(ValidationErrorItem(
                sheet=sheet_name, row=None, column=col,
                message=f"Missing required column '{col}' in sheet '{sheet_name}'",
                error_type="missing_column",
            ))

        if missing_required:
            return ps

        df = df.loc[:, df.columns.isin(expected_columns | required_columns)]
        ps.df = df

        return ps

    # ==================================================================
    # PARSING TO MODEL OBJECTS
    # ==================================================================

    def _parse_dealers_df(
        self, df: pd.DataFrame, errors: List[ValidationErrorItem],
    ) -> List[DealerRecord]:
        records = []
        seen_ids: Dict[str, int] = {}

        for idx, row in df.iterrows():
            row_num = idx + 2
            dealer_id = self._safe_str(row, "Dealer_id", "Dealers")
            sm_id = self._safe_str(row, "SM_id", "Dealers")

            dealer_errors: List[str] = []

            for col in DEALER_NUMERIC:
                val = row.get(col)
                if val is not None:
                    try:
                        float(val)
                    except (ValueError, TypeError):
                        dealer_errors.append(f"'{col}' is not a valid number: '{val}'")
                        errors.append(ValidationErrorItem(
                            sheet="Dealers", row=row_num, column=col,
                            message=f"Not a valid number: '{val}'",
                            error_type="type_error", value=str(val),
                        ))

            dealer_type_raw = self._safe_str(row, "Dealer_type", "Dealers")
            if dealer_type_raw and dealer_type_raw.strip().lower() not in VALID_DEALER_TYPES:
                errors.append(ValidationErrorItem(
                    sheet="Dealers", row=row_num, column="Dealer_type",
                    message=f"Invalid Dealer_type '{dealer_type_raw}'. Must be 'static' or 'mobile'",
                    error_type="enum_error", value=dealer_type_raw,
                ))

            pg_raw = self._safe_str(row, "Product_group", "Dealers")
            if pg_raw:
                pg_key = pg_raw.strip().lower().replace(" ", "_")
                if pg_key not in VALID_PRODUCT_GROUPS:
                    errors.append(ValidationErrorItem(
                        sheet="Dealers", row=row_num, column="Product_group",
                        message=f"Invalid Product_group '{pg_raw}'. Must be Product_A, Product_B, or Product_C",
                        error_type="enum_error", value=pg_raw,
                    ))

            lat = self._safe_float(row, "Dealer_latitude")
            lon = self._safe_float(row, "Dealer_longitude")
            if lat is None or lon is None:
                continue
            if lat < -90 or lat > 90:
                errors.append(ValidationErrorItem(
                    sheet="Dealers", row=row_num, column="Dealer_latitude",
                    message=f"Latitude {lat} out of range [-90, 90]",
                    error_type="geo_error", value=str(lat),
                ))
                continue
            if lon < -180 or lon > 180:
                errors.append(ValidationErrorItem(
                    sheet="Dealers", row=row_num, column="Dealer_longitude",
                    message=f"Longitude {lon} out of range [-180, 180]",
                    error_type="geo_error", value=str(lon),
                ))
                continue

            if dealer_id in seen_ids:
                errors.append(ValidationErrorItem(
                    sheet="Dealers", row=row_num, column="Dealer_id",
                    message=f"Duplicate Dealer_id '{dealer_id}' (also at row {seen_ids[dealer_id]})",
                    error_type="duplicate", value=dealer_id,
                ))
            else:
                seen_ids[dealer_id] = row_num

            if dealer_errors or not dealer_id or not dealer_type_raw:
                continue

            try:
                record = DealerRecord(
                    SM_id=sm_id or "",
                    Dealer_id=dealer_id or "",
                    Dealer_type=DealerType(dealer_type_raw.strip().lower()),
                    Product_group=ProductGroup(self._normalize_product_group(pg_raw)),
                    Count_BFL_disbursement=self._safe_int(row, "Count_BFL_disbursement"),
                    Average_cases_per_day=self._safe_float(row, "Average_cases_per_day") or 0.0,
                    Dealer_latitude=lat,
                    Dealer_longitude=lon,
                )
                records.append(record)
            except (ValueError, KeyError) as e:
                errors.append(ValidationErrorItem(
                    sheet="Dealers", row=row_num, column=None,
                    message=f"Failed to parse dealer row: {e}",
                    error_type="parse_error",
                ))

        return records

    def _parse_ftcs_df(
        self, df: pd.DataFrame, errors: List[ValidationErrorItem],
    ) -> List[FTCRecord]:
        records = []
        seen_ids: Dict[str, int] = {}

        for idx, row in df.iterrows():
            row_num = idx + 2
            ftc_id = self._safe_str(row, "FTC_id", "FTC")

            for col in FTC_NUMERIC:
                val = row.get(col)
                if val is not None:
                    try:
                        float(val)
                    except (ValueError, TypeError):
                        errors.append(ValidationErrorItem(
                            sheet="FTC", row=row_num, column=col,
                            message=f"Not a valid number: '{val}'",
                            error_type="type_error", value=str(val),
                        ))

            pg_raw = self._safe_str(row, "Product_Group", "FTC")
            if pg_raw:
                pg_key = pg_raw.strip().lower().replace(" ", "_")
                if pg_key not in VALID_PRODUCT_GROUPS:
                    errors.append(ValidationErrorItem(
                        sheet="FTC", row=row_num, column="Product_Group",
                        message=f"Invalid Product_Group '{pg_raw}'",
                        error_type="enum_error", value=pg_raw,
                    ))

            ntb = self._safe_float(row, "NTB_share")
            if ntb is not None and ntb > 1:
                ntb = ntb / 100.0
            if ntb is not None and (ntb < 0 or ntb > 1):
                errors.append(ValidationErrorItem(
                    sheet="FTC", row=row_num, column="NTB_share",
                    message=f"NTB_share {ntb} out of range [0, 1]",
                    error_type="range_error", value=str(ntb),
                ))

            if ftc_id in seen_ids:
                errors.append(ValidationErrorItem(
                    sheet="FTC", row=row_num, column="FTC_id",
                    message=f"Duplicate FTC_id '{ftc_id}' (also at row {seen_ids[ftc_id]})",
                    error_type="duplicate", value=ftc_id,
                ))
            else:
                seen_ids[ftc_id] = row_num

            cs_raw = self._safe_float(row, "Cross_sell") or 0.0
            cs = cs_raw / 100.0 if cs_raw > 1 else cs_raw
            try:
                record = FTCRecord(
                    FTC_id=ftc_id,
                    SM_id=self._safe_str(row, "SM_id", "FTC") or "DEFAULT_SM",
                    Product_Group=ProductGroup(self._normalize_product_group(pg_raw)),
                    FTC_VIntage=self._safe_int(row, "FTC_VIntage"),
                    Count_BFL_disbursement=self._safe_int(row, "Count_BFL_disbursement"),
                    Average_cases_per_day=self._safe_float(row, "Average_cases_per_day") or 0.0,
                    Per_sum_MOB=self._safe_float(row, "Per_sum_MOB") or 0.0,
                    NTB_share=ntb or 0.0,
                    Cross_sell=cs,
                )
                records.append(record)
            except (ValueError, KeyError) as e:
                errors.append(ValidationErrorItem(
                    sheet="FTC", row=row_num, column=None,
                    message=f"Failed to parse FTC row: {e}",
                    error_type="parse_error",
                ))

        return records

    def _parse_rels_df(
        self, df: pd.DataFrame, errors: List[ValidationErrorItem],
    ) -> List[FTCRelationshipRecord]:
        records = []
        seen: set = set()

        for idx, row in df.iterrows():
            row_num = idx + 2
            dealer_id = self._safe_str(row, "Dealer_id", "FTC-Dealer")
            ftc_id = self._safe_str(row, "FTC_id", "FTC-Dealer")

            for col in REL_NUMERIC:
                val = row.get(col)
                if val is not None:
                    try:
                        float(val)
                    except (ValueError, TypeError):
                        errors.append(ValidationErrorItem(
                            sheet="FTC-Dealer", row=row_num, column=col,
                            message=f"Not a valid number: '{val}'",
                            error_type="type_error", value=str(val),
                        ))

            pg_raw = self._safe_str(row, "Product_category", "FTC-Dealer")

            pair = (dealer_id, ftc_id)
            if pair in seen:
                errors.append(ValidationErrorItem(
                    sheet="FTC-Dealer", row=row_num, column=None,
                    message=f"Duplicate relationship: Dealer '{dealer_id}' -> FTC '{ftc_id}'",
                    error_type="duplicate",
                ))
            else:
                seen.add(pair)

            try:
                record = FTCRelationshipRecord(
                    Dealer_id=dealer_id,
                    FTC_id=ftc_id,
                    Product_category=ProductGroup(self._normalize_product_group(pg_raw)),
                    Avg_cases_per_day=self._safe_float(row, "Avg_cases_per_day") or 0.0,
                )
                records.append(record)
            except (ValueError, KeyError) as e:
                errors.append(ValidationErrorItem(
                    sheet="FTC-Dealer", row=row_num, column=None,
                    message=f"Failed to parse relationship row: {e}",
                    error_type="parse_error",
                ))

        return records

    def _infer_ftc_sm_ids(
        self,
        ftcs: List[FTCRecord],
        rels: List[FTCRelationshipRecord],
        dealers: List[DealerRecord],
    ) -> List[FTCRecord]:
        dealer_sm = {d.Dealer_id: d.SM_id for d in dealers}
        ftc_dealer_sms: dict = {}
        for r in rels:
            sm = dealer_sm.get(r.Dealer_id)
            if sm and sm != "DEFAULT_SM":
                ftc_dealer_sms.setdefault(r.FTC_id, set()).add(sm)

        updated = []
        for ftc in ftcs:
            sm = ftc.SM_id
            if sm in ("DEFAULT_SM", "") and ftc.FTC_id in ftc_dealer_sms:
                matches = ftc_dealer_sms[ftc.FTC_id]
                if len(matches) == 1:
                    sm = next(iter(matches))
            if sm != ftc.SM_id:
                ftc = ftc.model_copy(update={"SM_id": sm})
            updated.append(ftc)
        return updated

    # ==================================================================
    # QUALITY METRICS
    # ==================================================================

    def _compute_quality_metrics(
        self,
        dealers: List[DealerRecord],
        ftcs: List[FTCRecord],
        rels: List[FTCRelationshipRecord],
        errors: List[ValidationErrorItem],
    ) -> DataQualityMetrics:
        completeness = []
        total_rows = len(dealers) + len(ftcs) + len(rels)

        for sheet_name, col_list in [
            ("Dealers", DEALER_COLUMNS),
            ("FTC", FTC_COLUMNS),
            ("FTC-Dealer", REL_COLUMNS),
        ]:
            for col in sorted(col_list):
                null_count = sum(
                    1 for e in errors
                    if e.sheet == sheet_name and e.column == col
                    and e.error_type == "missing_value"
                )
                completeness.append(ColumnCompleteness(
                    column=f"{sheet_name}.{col}",
                    non_null_count=total_rows - null_count,
                    null_count=null_count,
                    completeness_pct=round(
                        ((total_rows - null_count) / max(total_rows, 1)) * 100, 1
                    ),
                ))

        dealer_ids = {d.Dealer_id for d in dealers}
        ftc_ids = {f.FTC_id for f in ftcs}
        sm_ids = {d.SM_id for d in dealers}

        error_count = len(errors)
        total_parsed = len(dealers) + len(ftcs) + len(rels) + error_count
        quality_score = 100.0
        if total_parsed > 0:
            quality_score = round(
                max(0, 100 - (error_count / max(total_parsed, 1)) * 100), 1
            )

        lat_sum = sum(d.Dealer_latitude for d in dealers) / max(len(dealers), 1)
        lon_sum = sum(d.Dealer_longitude for d in dealers) / max(len(dealers), 1)
        if lat_sum > 30:
            coverage = "Primarily India subcontinent"
        elif lat_sum > 0:
            coverage = "Northern Hemisphere"
        elif lat_sum < -30:
            coverage = "Southern Hemisphere"
        else:
            coverage = "Global / mixed"

        return DataQualityMetrics(
            total_rows_parsed=total_parsed,
            valid_rows=len(dealers) + len(ftcs) + len(rels),
            error_rows=error_count,
            completeness=completeness,
            duplicate_count=sum(1 for e in errors if e.error_type == "duplicate"),
            unique_dealers=len(dealer_ids),
            unique_ftcs=len(ftc_ids),
            unique_sm_regions=len(sm_ids),
            geo_coverage_hint=coverage,
            data_quality_score=quality_score,
        )

    # ==================================================================
    # PREVIEW
    # ==================================================================

    def _build_preview(
        self, dealers_df: pd.DataFrame, ftc_df: pd.DataFrame, rel_df: pd.DataFrame,
    ) -> DataPreview:
        return DataPreview(
            dealers=self._sheet_preview("Dealers", dealers_df),
            ftcs=self._sheet_preview("FTC", ftc_df),
            relationships=self._sheet_preview("FTC-Dealer", rel_df),
        )

    def _sheet_preview(self, name: str, df: pd.DataFrame) -> SheetPreview:
        columns = [
            {"name": str(c), "dtype": str(df[c].dtype)}
            for c in df.columns
        ]
        sample = []
        for i, (_, row) in enumerate(df.head(self.PREVIEW_ROWS).iterrows()):
            sample.append(DataPreviewRow(
                row_number=i + 1,
                data={str(k): self._serialize(v) for k, v in row.items()},
            ))
        return SheetPreview(
            sheet_name=name,
            columns=columns,
            total_rows=len(df),
            sample_rows=sample,
        )

    # ==================================================================
    # HELPERS
    # ==================================================================

    def get_job(self, job_id: str) -> Optional[Dict]:
        return self._jobs.get(job_id)

    def _safe_str(self, row, col: str, sheet: str) -> str:
        v = row.get(col)
        if pd.isna(v):
            return ""
        if isinstance(v, (int, float)):
            return str(int(v))
        return str(v).strip()

    def _safe_float(self, row, col: str) -> Optional[float]:
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _safe_int(self, row, col: str) -> int:
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return 0

    def _normalize_product_group(self, raw: Optional[str]) -> str:
        if not raw:
            return "Product_A"
        raw = raw.strip()
        raw_lower = raw.lower().replace(" ", "_")
        if raw_lower in VALID_PRODUCT_GROUPS:
            mapping = {
                "product_a": "Product_A",
                "product_b": "Product_B",
                "product_c": "Product_C",
            }
            return mapping.get(raw_lower, raw)
        if raw.startswith("Product_") or raw.startswith("product_"):
            return raw[0].upper() + raw[1:]
        return raw

    def _serialize(self, v: Any) -> Any:
        if isinstance(v, (pd.Timestamp, datetime)):
            return v.isoformat()
        if isinstance(v, (float, int)):
            if isinstance(v, float) and pd.isna(v):
                return None
            return v
        if v is None:
            return None
        return str(v)

    def cleanup_old_jobs(self, max_age_hours: int = 24):
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        with self._lock:
            stale = [
                jid for jid, job in self._jobs.items()
                if job.get("created_at", datetime.min) < cutoff
            ]
            for jid in stale:
                del self._jobs[jid]

