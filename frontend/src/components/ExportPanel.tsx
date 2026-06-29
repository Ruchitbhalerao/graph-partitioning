import React, { useState, useCallback, useEffect } from "react";
import {
  getExportUrl,
  getExportFileUrl,
  generateExports,
  getExportStatus,
  listExportFiles,
  validateExports,
  getJobDetails,
} from "../services/api";
import type {
  OptimizationSummary,
  ExportFileInfo,
  ExportGenerateResponse,
  ExportValidationResponse,
} from "../types";

interface Props {
  jobId: string;
}

type ExportFormat = "all" | "geojson" | "shapefile" | "csv";

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "white",
    borderRadius: "12px",
    padding: "24px",
    marginTop: "16px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "16px",
  },
  title: {
    fontSize: "18px",
    fontWeight: 600,
  },
  subtitle: {
    fontSize: "12px",
    color: "#888",
    marginTop: "2px",
  },
  formatRow: {
    display: "grid",
    gridTemplateColumns: "repeat(4, 1fr)",
    gap: "10px",
    marginBottom: "16px",
  },
  formatOption: {
    padding: "14px 12px",
    border: "2px solid #eee",
    borderRadius: "8px",
    cursor: "pointer",
    textAlign: "center" as const,
    transition: "all 0.15s",
    display: "flex",
    flexDirection: "column",
    gap: "4px",
    opacity: 1,
  },
  formatOptionSelected: {
    borderColor: "#4a90d9",
    background: "#f0f6ff",
  },
  formatOptionDisabled: {
    opacity: 0.5,
    cursor: "not-allowed",
  },
  formatLabel: {
    fontSize: "13px",
    fontWeight: 600,
    color: "#1a1a2e",
  },
  formatHint: {
    fontSize: "10px",
    color: "#888",
  },
  checkboxRow: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    fontSize: "13px",
    color: "#666",
    marginBottom: "16px",
    cursor: "pointer",
  },
  metaSection: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
    gap: "8px",
    padding: "12px",
    background: "#f8f9fa",
    borderRadius: "8px",
    marginBottom: "16px",
    fontSize: "12px",
    color: "#666",
  },
  metaItem: {
    display: "flex",
    flexDirection: "column",
    gap: "2px",
  },
  metaLabel: {
    fontSize: "10px",
    textTransform: "uppercase" as const,
    letterSpacing: "0.5px",
    color: "#999",
  },
  metaValue: {
    fontWeight: 600,
    color: "#1a1a2e",
  },
  actions: {
    display: "flex",
    gap: "12px",
    alignItems: "center",
    flexWrap: "wrap" as const,
  },
  generateBtn: {
    padding: "10px 24px",
    border: "none",
    borderRadius: "8px",
    background: "linear-gradient(135deg, #1a1a2e, #16213e)",
    color: "white",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: 600,
    transition: "opacity 0.2s",
  },
  downloadBtn: {
    padding: "10px 24px",
    border: "none",
    borderRadius: "8px",
    background: "#22c55e",
    color: "white",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: 600,
    transition: "opacity 0.2s",
  },
  secondaryBtn: {
    padding: "10px 20px",
    border: "1px solid #ddd",
    borderRadius: "8px",
    background: "white",
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 500,
    color: "#666",
    transition: "all 0.15s",
  },
  fileList: {
    display: "flex",
    flexDirection: "column" as const,
    gap: "6px",
    marginTop: "16px",
    padding: "12px",
    background: "#f8f9fa",
    borderRadius: "8px",
  },
  fileItem: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "8px 12px",
    borderRadius: "6px",
    background: "white",
    border: "1px solid #eee",
    fontSize: "13px",
  },
  fileName: {
    fontWeight: 500,
    color: "#1a1a2e",
  },
  fileSize: {
    color: "#888",
    fontSize: "11px",
  },
  fileDownload: {
    color: "#4a90d9",
    cursor: "pointer",
    fontWeight: 600,
    fontSize: "12px",
    textDecoration: "none",
    padding: "4px 8px",
    borderRadius: "4px",
    background: "#f0f6ff",
  },
  progressBar: {
    width: "100%",
    height: "4px",
    background: "#eee",
    borderRadius: "2px",
    overflow: "hidden" as const,
    marginTop: "8px",
  },
  progressFill: {
    height: "100%",
    background: "linear-gradient(90deg, #4a90d9, #22c55e)",
    borderRadius: "2px",
    transition: "width 0.3s",
  },
  statusText: {
    fontSize: "12px",
    color: "#888",
    marginTop: "6px",
  },
  errorBox: {
    padding: "10px 14px",
    background: "#fef2f2",
    border: "1px solid #fecaca",
    borderRadius: "8px",
    color: "#991b1b",
    fontSize: "13px",
    marginTop: "12px",
  },
  validationBox: {
    padding: "10px 14px",
    background: "#f0fdf4",
    border: "1px solid #bbf7d0",
    borderRadius: "8px",
    fontSize: "12px",
    marginTop: "12px",
  },
  validationError: {
    color: "#991b1b",
  },
  validationWarn: {
    color: "#92400e",
  },
};

const FORMAT_CONFIGS: {
  value: ExportFormat;
  label: string;
  hint: string;
  key: string;
}[] = [
  {
    value: "all",
    label: "All Formats",
    hint: "Complete export package",
    key: "all",
  },
  {
    value: "geojson",
    label: "GeoJSON",
    hint: "QGIS-compatible layers",
    key: "territories_geojson",
  },
  {
    value: "shapefile",
    label: "Shapefile",
    hint: "ArcGIS / QGIS (ZIP)",
    key: "shapefile_zip",
  },
  {
    value: "csv",
    label: "CSV Tables",
    hint: "Assignments & summaries",
    key: "assignments_csv",
  },
];

export function ExportPanel({ jobId }: Props) {
  const [format, setFormat] = useState<ExportFormat>("all");
  const [includeRoutes, setIncludeRoutes] = useState(false);
  const [summary, setSummary] = useState<OptimizationSummary | null>(null);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generateDone, setGenerateDone] = useState(false);
  const [generateResult, setGenerateResult] =
    useState<ExportGenerateResponse | null>(null);
  const [exportFiles, setExportFiles] = useState<ExportFileInfo[]>([]);
  const [validation, setValidation] =
    useState<ExportValidationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);

  useEffect(() => {
    if (!summary && !loadingMeta) {
      setLoadingMeta(true);
      getJobDetails(jobId)
        .then((d) => setSummary(d.summary))
        .catch(() => {})
        .finally(() => setLoadingMeta(false));
    }
  }, [jobId, summary, loadingMeta]);

  const fetchFileList = useCallback(async () => {
    try {
      const res = await listExportFiles(jobId);
      setExportFiles(res.files || []);
    } catch {
      setExportFiles([]);
    }
  }, [jobId]);

  useEffect(() => {
    if (generateDone) {
      fetchFileList();
    }
  }, [generateDone, fetchFileList]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    setGenerateDone(false);
    setGenerateResult(null);
    setExportFiles([]);
    setValidation(null);
    try {
      const res = await generateExports(jobId, includeRoutes);
      setGenerateResult(res);
      setGenerateDone(true);
    } catch (e: any) {
      setError(
        e?.response?.data?.detail || e?.message || "Export generation failed",
      );
    } finally {
      setGenerating(false);
    }
  };

  const handleValidate = async () => {
    setValidating(true);
    setError(null);
    try {
      const res = await validateExports(jobId);
      setValidation(res);
    } catch (e: any) {
      setError(
        e?.response?.data?.detail || e?.message || "Validation failed",
      );
    } finally {
      setValidating(false);
    }
  };

  const handleRefresh = () => {
    fetchFileList();
    getExportStatus(jobId).catch(() => {});
  };

  const getDownloadUrl = (fileType: string) => {
    return getExportFileUrl(jobId, fileType);
  };

  const formatKeyMap: Record<string, string> = {
    all: "manifest_json",
    geojson: "territories_geojson",
    shapefile: "shapefile_zip",
    csv: "assignments_csv",
  };

  const primaryDownloadKey =
    format === "all" ? "manifest_json" : formatKeyMap[format] || format;

  const primaryDownloadUrl =
    generateDone && primaryDownloadKey
      ? getDownloadUrl(primaryDownloadKey)
      : getExportUrl(jobId, format);

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <div style={styles.title}>Export Results</div>
          <div style={styles.subtitle}>
            {generateDone
              ? "Exports generated. Select format and download."
              : "Generate export files for GIS integration and analysis"}
          </div>
        </div>
        {generateDone && (
          <button style={styles.secondaryBtn} onClick={handleRefresh}>
            Refresh
          </button>
        )}
      </div>

      <div style={styles.formatRow}>
        {FORMAT_CONFIGS.map((f) => {
          const isSelected = format === f.value;
          return (
            <div
              key={f.value}
              style={{
                ...styles.formatOption,
                ...(isSelected ? styles.formatOptionSelected : {}),
              }}
              onClick={() => setFormat(f.value)}
            >
              <div style={styles.formatLabel}>{f.label}</div>
              <div style={styles.formatHint}>{f.hint}</div>
            </div>
          );
        })}
      </div>

      <label style={styles.checkboxRow}>
        <input
          type="checkbox"
          checked={includeRoutes}
          onChange={(e) => setIncludeRoutes(e.target.checked)}
        />
        Include optimized route data for daily planning
      </label>

      {summary && (
        <div style={styles.metaSection}>
          <div style={styles.metaItem}>
            <span style={styles.metaLabel}>SM Regions</span>
            <span style={styles.metaValue}>{summary.total_sm_regions}</span>
          </div>
          <div style={styles.metaItem}>
            <span style={styles.metaLabel}>FTCs</span>
            <span style={styles.metaValue}>{summary.total_ftcs}</span>
          </div>
          <div style={styles.metaItem}>
            <span style={styles.metaLabel}>Dealers</span>
            <span style={styles.metaValue}>
              {summary.total_static + summary.total_mobile}
            </span>
          </div>
          <div style={styles.metaItem}>
            <span style={styles.metaLabel}>Valid Regions</span>
            <span style={styles.metaValue}>
              {summary.valid_regions}/{summary.total_sm_regions}
            </span>
          </div>
          <div style={styles.metaItem}>
            <span style={styles.metaLabel}>Static/Mobile</span>
            <span style={styles.metaValue}>
              {summary.total_static}/{summary.total_mobile}
            </span>
          </div>
          <div style={styles.metaItem}>
            <span style={styles.metaLabel}>Job ID</span>
            <span
              style={{
                ...styles.metaValue,
                fontSize: "11px",
                fontFamily: "monospace",
              }}
            >
              {jobId.slice(0, 12)}...
            </span>
          </div>
        </div>
      )}

      {!generateDone && (
        <div>
          <div style={styles.actions}>
            <button
              style={{
                ...styles.generateBtn,
                opacity: generating ? 0.6 : 1,
              }}
              onClick={handleGenerate}
              disabled={generating}
            >
              {generating
                ? "Generating..."
                : "Generate Export Files"}
            </button>
          </div>
          {generating && (
            <div>
              <div style={styles.progressBar}>
                <div
                  style={{
                    ...styles.progressFill,
                    width: generating ? "80%" : "0%",
                  }}
                />
              </div>
              <div style={styles.statusText}>
                Generating territory polygons, dealer files, shapefiles, and
                metadata...
              </div>
            </div>
          )}
        </div>
      )}

      {generateDone && generateResult && (
        <div>
          <div style={styles.actions}>
            {primaryDownloadKey && (
              <a
                href={primaryDownloadUrl}
                style={{ textDecoration: "none" }}
              >
                <button style={styles.downloadBtn}>
                  Download{" "}
                  {format === "all"
                    ? "All"
                    : FORMAT_CONFIGS.find((f) => f.value === format)
                        ?.label}
                </button>
              </a>
            )}

            <button
              style={{
                ...styles.secondaryBtn,
                opacity: validating ? 0.6 : 1,
              }}
              onClick={handleValidate}
              disabled={validating}
            >
              {validating ? "Validating..." : "Validate Files"}
            </button>

            <button
              style={styles.secondaryBtn}
              onClick={handleGenerate}
            >
              Regenerate
            </button>
          </div>

          {generateResult.total_size > 0 && (
            <div style={styles.statusText}>
              Total export size:{" "}
              {generateResult.total_size > 1024 * 1024
                ? `${(generateResult.total_size / (1024 * 1024)).toFixed(1)} MB`
                : `${(generateResult.total_size / 1024).toFixed(0)} KB`}{" "}
              &middot; {generateResult.files.length} files generated
            </div>
          )}
        </div>
      )}

      {exportFiles.length > 0 && (
        <div style={styles.fileList}>
          <div
            style={{
              fontSize: "13px",
              fontWeight: 600,
              color: "#666",
              marginBottom: "4px",
            }}
          >
            Generated Files
          </div>
          {exportFiles.map((file) => (
            <div key={file.filename} style={styles.fileItem}>
              <div>
                <div style={styles.fileName}>{file.filename}</div>
                <div style={styles.fileSize}>{file.size_label}</div>
              </div>
              <a
                href={getExportFileUrl(jobId, file.filename)}
                style={styles.fileDownload}
                download
              >
                Download
              </a>
            </div>
          ))}
        </div>
      )}

      {validation && (
        <div style={styles.validationBox}>
          <div
            style={{
              fontSize: "13px",
              fontWeight: 600,
              marginBottom: "8px",
              color: validation.all_valid ? "#166534" : "#991b1b",
            }}
          >
            Export Validation
            {validation.all_valid ? " \u2713 All files valid" : ""}
          </div>
          {validation.reports.map((r, i) => (
            <div
              key={i}
              style={{
                marginTop: "6px",
                padding: "8px 10px",
                background: "white",
                borderRadius: "6px",
                fontSize: "12px",
              }}
            >
              <div
                style={{
                  fontWeight: 600,
                  color: r.valid ? "#166534" : "#991b1b",
                }}
              >
                {r.file} ({r.format}){" "}
                {r.valid ? "\u2713" : "\u2717"}
              </div>
              {r.feature_count !== undefined && (
                <div style={{ color: "#888" }}>
                  Features: {r.feature_count}
                </div>
              )}
              {r.row_count !== undefined && (
                <div style={{ color: "#888" }}>
                  Rows: {r.row_count}
                </div>
              )}
              {r.errors.map((e, j) => (
                <div key={j} style={styles.validationError}>
                  &bull; {e}
                </div>
              ))}
              {r.warnings.map((w, j) => (
                <div key={j} style={styles.validationWarn}>
                  &bull; {w}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {error && <div style={styles.errorBox}>{error}</div>}
    </div>
  );
}
