import axios from "axios";
import type {
  UploadResponse,
  OptimizationConfig,
  OptimizationStatus,
  OptimizationResult,
  AnalyticsReport,
  OptimizationResults,
  OptimizationProgressEvent,
  OptimizationSummary,
  SMProgress,
  PhaseTiming,
  GeoJSONCollection,
  ExportGenerateResponse,
  ExportStatusResponse,
  ExportValidationResponse,
  BulkExportResponse,
  ExportFileInfo,
} from "../types";

const API_BASE = "/api/v1";

const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000,
});

export async function uploadExcel(
  file: File,
  onProgress?: (pct: number) => void,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const { data } = await api.post<UploadResponse>("/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (e) => {
      if (e.total && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    },
  });
  return data;
}

export async function runOptimization(
  jobId: string,
  config?: Partial<OptimizationConfig>,
): Promise<OptimizationResult> {
  const { data } = await api.post<OptimizationResult>(
    `/optimize/${jobId}`,
    config || {},
  );
  return data;
}

export async function cancelOptimization(
  jobId: string,
): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post(`/optimize/cancel/${jobId}`);
  return data;
}

export async function getStatus(
  jobId: string,
): Promise<OptimizationStatus> {
  const { data } = await api.get<OptimizationStatus>(`/status/${jobId}`);
  return data;
}

export async function getResult(
  jobId: string,
): Promise<OptimizationResults> {
  const { data } = await api.get<OptimizationResults>(`/result/${jobId}`);
  return data;
}

export async function getJobDetails(jobId: string): Promise<{
  job_id: string;
  status: string;
  phase: string;
  progress: number;
  message: string;
  started_at: string | null;
  completed_at: string | null;
  config: OptimizationConfig | null;
  summary: OptimizationSummary | null;
  timing: PhaseTiming[] | null;
  sm_progress: Record<string, SMProgress> | null;
  refiner_iterations: number;
}> {
  const { data } = await api.get(`/job/${jobId}`);
  return data;
}

export async function getAnalytics(
  jobId: string,
): Promise<AnalyticsReport> {
  const { data } = await api.get<AnalyticsReport>(`/analytics/${jobId}`);
  return data;
}

export function getExportUrl(jobId: string, format: string): string {
  return `${API_BASE}/export/${jobId}?format=${format}`;
}

export async function listJobs(): Promise<
  Array<{
    job_id: string;
    status: string;
    started_at: string | null;
    completed_at: string | null;
  }>
> {
  const { data } = await api.get("/jobs");
  return data;
}

export async function getTerritories(
  jobId: string,
): Promise<GeoJSONCollection> {
  const { data } = await api.get<GeoJSONCollection>(`/territories/${jobId}`);
  return data;
}


export async function generateExports(
  jobId: string,
  includeRoutes: boolean = false,
): Promise<ExportGenerateResponse> {
  const { data } = await api.post<ExportGenerateResponse>(
    `/export/${jobId}/generate`,
    null,
    { params: { include_routes: includeRoutes } },
  );
  return data;
}

export async function getExportStatus(
  jobId: string,
): Promise<ExportStatusResponse> {
  const { data } = await api.get<ExportStatusResponse>(
    `/export/${jobId}/status`,
  );
  return data;
}

export async function listExportFiles(
  jobId: string,
): Promise<{ job_id: string; files: ExportFileInfo[] }> {
  const { data } = await api.get(`/export/${jobId}/files`);
  return data;
}

export async function validateExports(
  jobId: string,
): Promise<ExportValidationResponse> {
  const { data } = await api.get<ExportValidationResponse>(
    `/export/${jobId}/validate`,
  );
  return data;
}

export async function bulkExport(
  jobIds: string[],
  formats: string[] = ["geojson", "csv", "zip"],
): Promise<BulkExportResponse> {
  const { data } = await api.post<BulkExportResponse>("/export/bulk", {
    job_ids: jobIds,
    formats,
  });
  return data;
}

export function getExportFileUrl(
  jobId: string,
  fileType: string,
): string {
  return `${API_BASE}/export/${jobId}/${fileType}`;
}


export function createProgressEventSource(
  jobId: string,
  onEvent: (event: OptimizationProgressEvent) => void,
  onDone?: () => void,
  onError?: (err: Event) => void,
): EventSource {
  const url = `${API_BASE}/optimize/progress/${jobId}`;
  const source = new EventSource(url);

  source.onmessage = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === "done" || data.type === "heartbeat") {
        if (data.type === "done" && onDone) onDone();
        return;
      }
      onEvent(data as OptimizationProgressEvent);
    } catch {
      // ignore parse errors
    }
  };

  source.onerror = (err: Event) => {
    if (onError) onError(err);
  };

  return source;
}


