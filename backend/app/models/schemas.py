from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from .enums import DealerType, ProductGroup, OptimizationPhase, OutputFormat


class DealerRecord(BaseModel):
    SM_id: str
    Dealer_id: str
    Dealer_type: DealerType
    Product_group: ProductGroup
    Count_BFL_disbursement: int = 0
    Average_cases_per_day: float = 0.0
    Dealer_latitude: float
    Dealer_longitude: float

    class Config:
        frozen = True


class FTCRecord(BaseModel):
    FTC_id: str
    SM_id: str
    Product_Group: ProductGroup
    FTC_VIntage: int = 0
    Count_BFL_disbursement: int = 0
    Average_cases_per_day: float = 0.0
    Per_sum_MOB: float = 0.0
    NTB_share: float = 0.0
    Cross_sell: float = 0.0

    class Config:
        frozen = True


class FTCRelationshipRecord(BaseModel):
    Dealer_id: str
    FTC_id: str
    Product_category: ProductGroup
    Avg_cases_per_day: float = 0.0

    class Config:
        frozen = True


class ValidationErrorItem(BaseModel):
    sheet: str
    row: Optional[int] = None
    column: Optional[str] = None
    message: str
    error_type: str = "validation"
    value: Optional[Any] = None


class DataPreviewRow(BaseModel):
    row_number: int
    data: Dict[str, Any]


class SheetPreview(BaseModel):
    sheet_name: str
    columns: List[Dict[str, str]]
    total_rows: int
    sample_rows: List[DataPreviewRow]


class DataPreview(BaseModel):
    dealers: SheetPreview
    ftcs: SheetPreview
    relationships: SheetPreview


class ColumnCompleteness(BaseModel):
    column: str
    non_null_count: int
    null_count: int
    completeness_pct: float


class DataQualityMetrics(BaseModel):
    total_rows_parsed: int
    valid_rows: int
    error_rows: int
    completeness: List[ColumnCompleteness]
    duplicate_count: int
    unique_dealers: int
    unique_ftcs: int
    unique_sm_regions: int
    geo_coverage_hint: str
    data_quality_score: float


class UploadSummary(BaseModel):
    total_dealers: int
    total_ftcs: int
    total_relationships: int
    total_sm_regions: int
    static_dealers: int
    mobile_dealers: int
    sm_ids: List[str]


class UploadResponse(BaseModel):
    job_id: str
    status: str
    message: str
    summary: Optional[UploadSummary] = None
    errors: List[ValidationErrorItem] = []
    preview: Optional[DataPreview] = None
    quality_metrics: Optional[DataQualityMetrics] = None


class OptimizationConfig(BaseModel):
    travel_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    workload_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    compactness_weight: float = Field(default=0.20, ge=0.0, le=1.0)
    productivity_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    proximity_km: float = Field(default=5.0, ge=1.0, le=50.0)
    preserve_existing: bool = False
    target_cases_per_ftc: Optional[float] = None
    max_refinement_iterations: int = Field(default=100, ge=10, le=1000)
    parallel_process: bool = True


class OptimizationStatusResponse(BaseModel):
    job_id: str
    phase: OptimizationPhase
    progress: float = 0.0
    message: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class OptimizationResult(BaseModel):
    job_id: str
    status: str
    summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExportRequest(BaseModel):
    job_id: str
    format: OutputFormat
    include_routes: bool = False
    include_polygons: bool = True
    include_assignments: bool = True
    include_analytics: bool = True


class TerritoryMetrics(BaseModel):
    ftc_id: str
    dealer_count: int
    static_count: int
    mobile_count: int
    average_cases_per_day: float
    total_distance_km: float
    average_distance_km: float
    compactness_score: float
    workload_score: float
    anchor_dealer_id: Optional[str] = None


class SMMetrics(BaseModel):
    sm_id: str
    ftc_count: int
    dealer_count: int
    total_cases: float
    total_distance_km: float
    workload_variance: float
    territory_count: int
    metrics: List[TerritoryMetrics]


class AnalyticsReport(BaseModel):
    job_id: str
    generated_at: datetime
    total_dealers: int
    total_ftcs: int
    total_sms: int
    total_static_assignments: int
    total_mobile_assignments: int
    average_workload_per_ftc: float
    workload_variance: float
    average_travel_distance_km: float
    max_travel_distance_km: float
    total_coverage_percent: float
    territory_compactness_avg: float
    sm_reports: List[SMMetrics]
