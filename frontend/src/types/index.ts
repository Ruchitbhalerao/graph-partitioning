export interface UploadSummary {
  total_dealers: number;
  total_ftcs: number;
  total_relationships: number;
  total_sm_regions: number;
  static_dealers: number;
  mobile_dealers: number;
  sm_ids: string[];
}

export interface ValidationErrorItem {
  sheet: string;
  row: number | null;
  column: string | null;
  message: string;
  error_type: string;
  value?: unknown;
}

export interface DataPreviewRow {
  row_number: number;
  data: Record<string, unknown>;
}

export interface ColumnInfo {
  name: string;
  dtype: string;
}

export interface SheetPreview {
  sheet_name: string;
  columns: ColumnInfo[];
  total_rows: number;
  sample_rows: DataPreviewRow[];
}

export interface DataPreview {
  dealers: SheetPreview;
  ftcs: SheetPreview;
  relationships: SheetPreview;
}

export interface ColumnCompleteness {
  column: string;
  non_null_count: number;
  null_count: number;
  completeness_pct: number;
}

export interface DataQualityMetrics {
  total_rows_parsed: number;
  valid_rows: number;
  error_rows: number;
  completeness: ColumnCompleteness[];
  duplicate_count: number;
  unique_dealers: number;
  unique_ftcs: number;
  unique_sm_regions: number;
  geo_coverage_hint: string;
  data_quality_score: number;
}

export interface UploadResponse {
  job_id: string;
  status: string;
  message: string;
  summary: UploadSummary | null;
  errors: ValidationErrorItem[];
  preview: DataPreview | null;
  quality_metrics: DataQualityMetrics | null;
}

export interface OptimizationConfig {
  travel_weight: number;
  workload_weight: number;
  compactness_weight: number;
  productivity_weight: number;
  proximity_km: number;
  preserve_existing: boolean;
  target_cases_per_ftc?: number;
  max_refinement_iterations: number;
  parallel_process: boolean;
}

export interface OptimizationStatus {
  job_id: string;
  phase: string;
  progress: number;
  message: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface OptimizationResult {
  job_id: string;
  status: string;
  summary: OptimizationSummary | null;
  error?: string;
}

export interface OptimizationSummary {
  total_sm_regions: number;
  total_dealers: number;
  total_static: number;
  total_mobile: number;
  total_ftcs: number;
  valid_regions: number;
  regions_with_errors: number;
}

// ===== OPTIMIZATION PROGRESS TYPES =====

export interface SMProgress {
  sm_id: string;
  status: string;
  dealers_count: number;
  ftcs_count: number;
  partition_time: number;
  refine_time: number;
  refine_iterations: number;
  refine_improvement_pct: number;
  is_valid: boolean;
  errors: string[];
}

export interface RefinerIteration {
  iteration: number;
  fitness: number;
  best_fitness: number;
  travel_penalty: number;
  workload_penalty: number;
  compactness_penalty: number;
  moves_accepted: number;
  stagnation: number;
}

export interface PhaseTiming {
  phase: string;
  started_at: string | null;
  completed_at: string | null;
  duration_sec: number;
}

export interface OptimizationProgressEvent {
  job_id: string;
  phase: string;
  progress: number;
  message: string;
  current_sm: string | null;
  sm_total: number;
  sm_completed: number;
  sm_progress: SMProgress | null;
  refiner_iteration: RefinerIteration | null;
  timing: PhaseTiming[];
  error: string | null;
  estimated_remaining_sec: number | null;
  timestamp: string;
}

// ===== END PROGRESS TYPES =====

export interface TerritoryMetrics {
  ftc_id: string;
  dealer_count: number;
  static_count: number;
  mobile_count: number;
  average_cases_per_day: number;
  total_distance_km: number;
  average_distance_km: number;
  compactness_score: number;
  workload_score: number;
  anchor_dealer_id: string | null;
}

export interface SMMetrics {
  sm_id: string;
  ftc_count: number;
  dealer_count: number;
  total_cases: number;
  total_distance_km: number;
  workload_variance: number;
  territory_count: number;
  metrics: TerritoryMetrics[];
}

export interface AnalyticsReport {
  job_id: string;
  generated_at: string;
  total_dealers: number;
  total_ftcs: number;
  total_sms: number;
  total_static_assignments: number;
  total_mobile_assignments: number;
  average_workload_per_ftc: number;
  workload_variance: number;
  average_travel_distance_km: number;
  max_travel_distance_km: number;
  total_coverage_percent: number;
  territory_compactness_avg: number;
  sm_reports: SMMetrics[];
}

export interface SMResult {
  sm_id: string;
  static_dealers: number;
  mobile_dealers: number;
  ftc_count: number;
  assignments: Record<string, string[]>;
  anchors: Record<string, string>;
  is_valid: boolean;
  validation_errors: string[];
}

export interface OptimizationResults {
  job_id: string;
  status: string;
  results: Record<string, SMResult>;
  summary: OptimizationSummary;
}

export interface GeoJSONPointGeometry {
  type: "Point";
  coordinates: [number, number];
}

export interface GeoJSONPolygonGeometry {
  type: "Polygon";
  coordinates: [number, number][][];
}

export interface GeoJSONMultiPolygonGeometry {
  type: "MultiPolygon";
  coordinates: [number, number][][][];
}

export type GeoJSONGeometry =
  | GeoJSONPointGeometry
  | GeoJSONPolygonGeometry
  | GeoJSONMultiPolygonGeometry;

export interface GeoJSONFeature {
  type: "Feature";
  properties: Record<string, any>;
  geometry: GeoJSONGeometry;
}

export interface GeoJSONCollection {
  type: "FeatureCollection";
  features: GeoJSONFeature[];
}

// ===== EXPORT TYPES =====

export interface ExportFileInfo {
  key: string;
  filename: string;
  size_bytes: number;
  size_label: string;
  type?: string;
}

export interface ExportManifest {
  job_id: string;
  generated_at: string;
  files: ExportFileInfo[];
  total_files: number;
}

export interface ExportGenerateResponse {
  job_id: string;
  status: string;
  files: { key: string; path: string; size: number }[];
  total_size: number;
  manifest: string | null;
}

export interface ExportStatusResponse {
  job_id: string;
  status?: string;
  created_at?: string;
  include_routes?: boolean;
  files?: ExportFileInfo[];
  total_size?: number;
  total_files?: number;
}

export interface ExportValidationReport {
  file: string;
  format: string;
  valid: boolean;
  feature_count?: number;
  row_count?: number;
  columns?: string[];
  file_count?: number;
  files?: string[];
  errors: string[];
  warnings: string[];
}

export interface ExportValidationResponse {
  job_id: string;
  validated_at: string;
  reports: ExportValidationReport[];
  total_valid: number;
  total_with_errors: number;
  all_valid: boolean;
}

export interface BulkExportResponse {
  bulk_id: string;
  bulk_dir: string;
}

export interface ExportOptions {
  include_routes: boolean;
  format: "geojson" | "shapefile" | "csv";
}

// ===== END EXPORT TYPES =====

export type UploadStatus =
  | "idle"
  | "selecting"
  | "uploading"
  | "validating"
  | "validated"
  | "validation_failed"
  | "error";

export type OptimizeStatus =
  | "idle"
  | "running"
  | "completed"
  | "cancelled"
  | "failed";

export type AppView = "upload" | "dashboard" | "drilldown";
