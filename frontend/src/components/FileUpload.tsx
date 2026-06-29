import React, { useCallback, useRef, useState, useMemo } from "react";
import type { UploadResponse, UploadStatus, ValidationErrorItem, DataPreview, DataQualityMetrics } from "../types";

interface Props {
  onUpload: (file: File) => Promise<UploadResponse>;
  isProcessing: boolean;
  uploadStatus: UploadStatus;
  uploadResponse: UploadResponse | null;
  uploadProgress?: number;
}

const MAX_SIZE_MB = 50;
const ALLOWED_TYPES = [".xlsx", ".xls"];
const PREVIEW_COLS_PER_SHEET: Record<string, string[]> = {
  Dealers: ["Dealer_id", "Dealer_type", "Product_group", "Dealer_latitude", "Dealer_longitude", "Average_cases_per_day"],
  FTC: ["FTC_id", "Product_Group", "FTC_VIntage", "Average_cases_per_day", "NTB_share"],
  "FTC-Dealer": ["Dealer_id", "FTC_id", "Product_category", "Avg_cases_per_day"],
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "white",
    borderRadius: "12px",
    padding: "32px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
  },
  title: {
    fontSize: "20px",
    fontWeight: 600,
    marginBottom: "4px",
  },
  subtitle: {
    fontSize: "14px",
    color: "#666",
    marginBottom: "24px",
  },
  dropzone: {
    border: "2px dashed #d0d5dd",
    borderRadius: "12px",
    padding: "40px 24px",
    textAlign: "center" as const,
    cursor: "pointer",
    transition: "all 0.2s ease",
    background: "#f9fafb",
  },
  dropzoneDragging: {
    borderColor: "#2563eb",
    background: "#eff6ff",
    transform: "scale(1.01)",
  },
  dropzoneDisabled: {
    opacity: 0.5,
    cursor: "not-allowed",
    pointerEvents: "none" as const,
  },
  dropzoneIcon: {
    fontSize: "40px",
    marginBottom: "12px",
    display: "block",
  },
  dropzoneText: {
    fontSize: "16px",
    fontWeight: 500,
    color: "#344054",
    marginBottom: "8px",
  },
  dropzoneLink: {
    color: "#2563eb",
    textDecoration: "underline",
    cursor: "pointer",
  },
  dropzoneHint: {
    fontSize: "13px",
    color: "#98a2b3",
  },
  fileCard: {
    marginTop: "16px",
    padding: "12px 16px",
    background: "#f8f9fa",
    borderRadius: "8px",
    border: "1px solid #e5e7eb",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  fileInfo: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
  },
  fileIcon: {
    fontSize: "24px",
  },
  fileName: {
    fontSize: "14px",
    fontWeight: 600,
    color: "#1a1a2e",
  },
  fileSize: {
    fontSize: "12px",
    color: "#98a2b3",
  },
  uploadBtn: {
    padding: "8px 20px",
    background: "#2563eb",
    color: "white",
    border: "none",
    borderRadius: "6px",
    fontSize: "14px",
    fontWeight: 500,
    cursor: "pointer",
  },
  cancelBtn: {
    padding: "8px 16px",
    background: "transparent",
    color: "#667085",
    border: "1px solid #d0d5dd",
    borderRadius: "6px",
    fontSize: "14px",
    cursor: "pointer",
    marginLeft: "8px",
  },
  progressWrap: {
    marginTop: "16px",
  },
  progressBarOuter: {
    width: "100%",
    height: "8px",
    background: "#e5e7eb",
    borderRadius: "4px",
    overflow: "hidden",
  },
  progressBarInner: {
    height: "100%",
    background: "linear-gradient(90deg, #2563eb, #7c3aed)",
    borderRadius: "4px",
    transition: "width 0.3s ease",
  },
  progressLabel: {
    fontSize: "13px",
    color: "#667085",
    marginTop: "8px",
    textAlign: "center" as const,
  },
  section: {
    marginTop: "24px",
    padding: "20px",
    background: "#f8f9fa",
    borderRadius: "8px",
  },
  sectionTitle: {
    fontSize: "16px",
    fontWeight: 600,
    marginBottom: "4px",
  },
  sectionSubtitle: {
    fontSize: "13px",
    color: "#98a2b3",
    marginBottom: "16px",
  },
  statGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
    gap: "12px",
  },
  statCard: {
    padding: "12px",
    background: "white",
    borderRadius: "8px",
    border: "1px solid #e5e7eb",
  },
  statLabel: {
    fontSize: "12px",
    color: "#98a2b3",
    marginBottom: "4px",
  },
  statValue: {
    fontSize: "22px",
    fontWeight: 700,
    color: "#1a1a2e",
  },
  qualityScore: {
    display: "flex",
    alignItems: "center",
    gap: "16px",
    flexWrap: "wrap" as const,
  },
  scoreCircle: {
    width: "64px",
    height: "64px",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "18px",
    fontWeight: 700,
    color: "white",
    flexShrink: 0,
  },
  scoreDetails: {
    fontSize: "13px",
    color: "#667085",
  },
  scoreDetailRow: {
    display: "flex",
    gap: "16px",
    marginTop: "4px",
  },
  scoreBadge: {
    padding: "2px 8px",
    borderRadius: "4px",
    fontSize: "12px",
    fontWeight: 500,
  },
  tabs: {
    display: "flex",
    gap: "4px",
    marginBottom: "12px",
    borderBottom: "1px solid #e5e7eb",
    paddingBottom: "8px",
  },
  tab: {
    padding: "6px 14px",
    border: "none",
    background: "transparent",
    fontSize: "13px",
    fontWeight: 500,
    color: "#98a2b3",
    cursor: "pointer",
    borderRadius: "6px",
    transition: "all 0.15s",
  },
  tabActive: {
    background: "#2563eb",
    color: "white",
  },
  previewTable: {
    width: "100%",
    borderCollapse: "collapse" as const,
    fontSize: "13px",
    overflowX: "auto" as const,
    display: "block",
  },
  previewTh: {
    padding: "8px 12px",
    background: "#f1f5f9",
    borderBottom: "2px solid #e5e7eb",
    fontWeight: 600,
    color: "#344054",
    textAlign: "left" as const,
    whiteSpace: "nowrap" as const,
    fontSize: "12px",
  },
  previewTd: {
    padding: "6px 12px",
    borderBottom: "1px solid #f0f0f0",
    color: "#344054",
    maxWidth: "160px",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap" as const,
  },
  errorList: {
    maxHeight: "240px",
    overflowY: "auto" as const,
  },
  errorItem: {
    padding: "8px 12px",
    borderLeft: "3px solid #ef4444",
    background: "#fef2f2",
    marginBottom: "6px",
    borderRadius: "0 6px 6px 0",
    fontSize: "13px",
    lineHeight: "1.4",
  },
  errorType: {
    display: "inline-block",
    padding: "1px 6px",
    borderRadius: "3px",
    fontSize: "11px",
    fontWeight: 600,
    marginRight: "8px",
  },
  errorBadgeGeo: { background: "#fee2e2", color: "#dc2626" },
  errorBadgeType: { background: "#fef3c7", color: "#d97706" },
  errorBadgeMissing: { background: "#e0e7ff", color: "#4f46e5" },
  errorBadgeDuplicate: { background: "#fce7f3", color: "#db2777" },
  errorBadgeDefault: { background: "#f3f4f6", color: "#6b7280" },
  successBanner: {
    padding: "12px 16px",
    background: "#ecfdf5",
    border: "1px solid #a7f3d0",
    borderRadius: "8px",
    color: "#065f46",
    fontSize: "14px",
    fontWeight: 500,
    marginTop: "16px",
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
};

function getErrorStyle(type: string): React.CSSProperties {
  switch (type) {
    case "geo_error": return styles.errorBadgeGeo;
    case "type_error": case "range_error": case "enum_error": return styles.errorBadgeType;
    case "missing_sheet": case "missing_column": return styles.errorBadgeMissing;
    case "duplicate": return styles.errorBadgeDuplicate;
    default: return styles.errorBadgeDefault;
  }
}

function getErrorLabel(type: string): string {
  switch (type) {
    case "geo_error": return "GEO";
    case "type_error": case "range_error": case "enum_error": return "TYPE";
    case "missing_sheet": case "missing_column": return "MISSING";
    case "duplicate": return "DUP";
    case "file_type": case "file_read": return "FILE";
    default: return type.replace("_", " ").toUpperCase();
  }
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function PreviewTable({ preview, sheetKey }: { preview: DataPreview; sheetKey: "dealers" | "ftcs" | "relationships" }) {
  const sheet = preview[sheetKey];
  if (!sheet || sheet.sample_rows.length === 0) {
    return <div style={{ fontSize: "13px", color: "#98a2b3", padding: "16px 0" }}>No data rows to preview</div>;
  }

  const preferredCols = PREVIEW_COLS_PER_SHEET[sheet.sheet_name] || [];
  const allCols = sheet.columns.map((c) => c.name);
  const visibleCols = preferredCols.filter((c) => allCols.includes(c));
  const cols = visibleCols.length > 0 ? visibleCols : allCols;

  return (
    <table style={styles.previewTable}>
      <thead>
        <tr>
          <th style={styles.previewTh}>#</th>
          {cols.map((col) => (
            <th key={col} style={styles.previewTh}>{col}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sheet.sample_rows.map((row) => (
          <tr key={row.row_number}>
            <td style={styles.previewTd}>{row.row_number}</td>
            {cols.map((col) => (
              <td key={col} style={styles.previewTd}>
                {formatCellValue(row.data[col])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function formatCellValue(val: unknown): string {
  if (val === null || val === undefined) return "—";
  if (typeof val === "number") return Number.isInteger(val) ? val.toString() : val.toFixed(4);
  if (typeof val === "boolean") return val ? "true" : "false";
  return String(val);
}

function groupErrors(errors: ValidationErrorItem[]): Record<string, ValidationErrorItem[]> {
  const groups: Record<string, ValidationErrorItem[]> = {};
  for (const e of errors) {
    const key = e.error_type || "other";
    if (!groups[key]) groups[key] = [];
    groups[key].push(e);
  }
  return groups;
}

const ERROR_TYPE_ORDER = ["missing_sheet", "missing_column", "geo_error", "type_error", "enum_error", "range_error", "duplicate", "parse_error", "file_type", "file_read", "validation", "unknown_column", "other"];

function sortErrorTypes(types: string[]): string[] {
  return [...types].sort((a, b) => {
    const ai = ERROR_TYPE_ORDER.indexOf(a);
    const bi = ERROR_TYPE_ORDER.indexOf(b);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
}

function ErrorDisplay({ errors }: { errors: ValidationErrorItem[] }) {
  const grouped = useMemo(() => groupErrors(errors), [errors]);
  const types = useMemo(() => sortErrorTypes(Object.keys(grouped)), [grouped]);

  if (errors.length === 0) return null;

  return (
    <div>
      <div style={{ fontSize: "14px", fontWeight: 600, marginBottom: "12px", color: "#dc2626" }}>
        {errors.length} error{errors.length !== 1 ? "s" : ""} found
      </div>
      <div style={styles.errorList}>
        {types.map((type) => (
          <div key={type} style={{ marginBottom: "12px" }}>
            <div style={{ fontSize: "12px", fontWeight: 600, color: "#667085", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.5px" }}>
              {type.replace(/_/g, " ")} ({grouped[type].length})
            </div>
            {grouped[type].map((e, i) => (
              <div key={i} style={styles.errorItem}>
                <span style={{ ...styles.errorType, ...getErrorStyle(e.error_type) }}>
                  {getErrorLabel(e.error_type)}
                </span>
                {e.sheet && <span style={{ fontWeight: 500, marginRight: "4px" }}>[{e.sheet}]</span>}
                {e.row && <span style={{ color: "#98a2b3", marginRight: "4px" }}>Row {e.row}:</span>}
                {e.message}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function QualityDisplay({ quality }: { quality: DataQualityMetrics }) {
  const score = quality.data_quality_score;
  const scoreColor = score >= 90 ? "#059669" : score >= 70 ? "#d97706" : "#dc2626";
  const scoreLabel = score >= 90 ? "Excellent" : score >= 70 ? "Fair" : "Poor";

  return (
    <div style={styles.qualityScore}>
      <div style={{ ...styles.scoreCircle, background: scoreColor }}>
        {score.toFixed(0)}
      </div>
      <div>
        <div style={{ fontSize: "14px", fontWeight: 600, color: "#1a1a2e" }}>
          Data Quality: {scoreLabel}
        </div>
        <div style={styles.scoreDetails}>
          <span>{quality.valid_rows} valid rows parsed</span>
          <span style={{ margin: "0 8px", color: "#d0d5dd" }}>|</span>
          <span>{quality.unique_dealers} unique dealers</span>
          <span style={{ margin: "0 8px", color: "#d0d5dd" }}>|</span>
          <span>{quality.unique_ftcs} unique FTCs</span>
        </div>
        <div style={styles.scoreDetailRow}>
          <span style={styles.scoreBadge}>Duplicates: {quality.duplicate_count}</span>
          <span style={styles.scoreBadge}>Errors: {quality.error_rows}</span>
          <span style={styles.scoreBadge}>{quality.geo_coverage_hint}</span>
        </div>
      </div>
    </div>
  );
}

export function FileUpload({
  onUpload,
  isProcessing,
  uploadStatus,
  uploadResponse,
  uploadProgress = 0,
}: Props) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewTab, setPreviewTab] = useState<"dealers" | "ftcs" | "relationships">("dealers");
  const inputRef = useRef<HTMLInputElement>(null);

  const fileError = useMemo(() => {
    if (!selectedFile) return null;
    const ext = "." + selectedFile.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_TYPES.includes(ext)) {
      return `Invalid file type "${ext}". Only .xlsx and .xls files are accepted.`;
    }
    if (selectedFile.size > MAX_SIZE_MB * 1024 * 1024) {
      return `File exceeds ${MAX_SIZE_MB} MB limit (${formatFileSize(selectedFile.size)})`;
    }
    return null;
  }, [selectedFile]);

  const handleFile = useCallback(
    async (file: File) => {
      setSelectedFile(file);
      const ext = "." + file.name.split(".").pop()?.toLowerCase();
      if (!ALLOWED_TYPES.includes(ext)) return;
      if (file.size > MAX_SIZE_MB * 1024 * 1024) return;
      try {
        await onUpload(file);
      } catch {
        // error is handled by parent
      }
    },
    [onUpload],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleBrowse = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const handleRetry = useCallback(() => {
    setSelectedFile(null);
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const showDropzone = !selectedFile || uploadStatus === "error" || uploadStatus === "idle";
  const isUploading = uploadStatus === "uploading";
  const isValidated = uploadStatus === "validated";
  const isValidationFailed = uploadStatus === "validation_failed";
  const isError = uploadStatus === "error";

  const summary = uploadResponse?.summary ?? null;
  const preview = uploadResponse?.preview ?? null;
  const quality = uploadResponse?.quality_metrics ?? null;
  const errors = uploadResponse?.errors ?? [];

  return (
    <div style={styles.container}>
      <div style={styles.title}>Upload Data File</div>
      <div style={styles.subtitle}>
        Upload an Excel file containing Dealers, FTC, and FTC-Dealer Relationship sheets
      </div>

      {showDropzone && (
        <div
          style={{
            ...styles.dropzone,
            ...(dragActive ? styles.dropzoneDragging : {}),
            ...(isProcessing ? styles.dropzoneDisabled : {}),
          }}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={handleBrowse}
        >
          <span style={styles.dropzoneIcon}>
            {dragActive ? "📂" : "📄"}
          </span>
          <div style={styles.dropzoneText}>
            {dragActive
              ? "Drop your file here"
              : <>
                  <span style={styles.dropzoneLink}>Click to upload</span> or drag and drop
                </>
            }
          </div>
          <div style={styles.dropzoneHint}>
            .xlsx or .xls files (max {MAX_SIZE_MB} MB)
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xls"
            onChange={handleChange}
            style={{ display: "none" }}
          />
        </div>
      )}

      {selectedFile && !showDropzone && (
        <div style={styles.fileCard}>
          <div style={styles.fileInfo}>
            <span style={styles.fileIcon}>📎</span>
            <div>
              <div style={styles.fileName}>{selectedFile.name}</div>
              <div style={styles.fileSize}>{formatFileSize(selectedFile.size)}</div>
            </div>
          </div>
          {!isUploading && !isValidated && (
            <div>
              <button
                style={styles.uploadBtn}
                onClick={(e) => { e.stopPropagation(); handleFile(selectedFile); }}
                disabled={!!fileError || isProcessing}
              >
                {isProcessing ? "Processing..." : "Upload"}
              </button>
              <button style={styles.cancelBtn} onClick={handleRetry}>
                Change
              </button>
            </div>
          )}
        </div>
      )}

      {isUploading && (
        <div style={styles.progressWrap}>
          <div style={styles.progressBarOuter}>
            <div style={{ ...styles.progressBarInner, width: `${Math.min(uploadProgress, 100)}%` }} />
          </div>
          <div style={styles.progressLabel}>
            {uploadProgress < 100 ? `Uploading... ${uploadProgress}%` : "Validating data..."}
          </div>
        </div>
      )}

      {isError && (
        <div style={{ ...styles.section, background: "#fef2f2", border: "1px solid #fecaca" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ ...styles.sectionTitle, color: "#dc2626" }}>Upload Failed</div>
              <div style={{ ...styles.sectionSubtitle, color: "#ef4444" }}>
                {uploadResponse?.message || "An error occurred during upload"}
              </div>
            </div>
            <button style={styles.uploadBtn} onClick={handleRetry}>
              Try Again
            </button>
          </div>
        </div>
      )}

      {isValidationFailed && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Validation Report</div>
          <div style={{ ...styles.sectionSubtitle, color: "#dc2626" }}>
            {uploadResponse?.message || "Data validation failed"}
          </div>
          <ErrorDisplay errors={errors} />
          {preview && (
            <>
              <div style={{ ...styles.sectionTitle, marginTop: "16px", marginBottom: "4px" }}>Data Preview</div>
              <div style={styles.sectionSubtitle}>Sample rows from your file</div>
              <div style={styles.tabs}>
                {(["dealers", "ftcs", "relationships"] as const).map((key) => (
                  <button
                    key={key}
                    style={{ ...styles.tab, ...(previewTab === key ? styles.tabActive : {}) }}
                    onClick={() => setPreviewTab(key)}
                  >
                    {preview[key].sheet_name} ({preview[key].total_rows})
                  </button>
                ))}
              </div>
              <PreviewTable preview={preview} sheetKey={previewTab} />
            </>
          )}
          <div style={{ marginTop: "12px" }}>
            <button style={styles.uploadBtn} onClick={handleRetry}>
              Try Again with Different File
            </button>
          </div>
        </div>
      )}

      {isValidated && (
        <>
          {summary && (
            <div style={styles.section}>
              <div style={styles.sectionTitle}>Data Summary</div>
              <div style={styles.sectionSubtitle}>Successfully parsed from uploaded file</div>
              <div style={styles.statGrid}>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Dealers</div>
                  <div style={styles.statValue}>{summary.total_dealers}</div>
                  <div style={{ fontSize: "12px", color: "#98a2b3" }}>
                    {summary.static_dealers} static / {summary.mobile_dealers} mobile
                  </div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>FTCs</div>
                  <div style={styles.statValue}>{summary.total_ftcs}</div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Relationships</div>
                  <div style={styles.statValue}>{summary.total_relationships}</div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>SM Regions</div>
                  <div style={styles.statValue}>{summary.total_sm_regions}</div>
                  <div style={{ fontSize: "12px", color: "#98a2b3" }}>
                    {summary.sm_ids.slice(0, 3).join(", ")}{summary.sm_ids.length > 3 ? "..." : ""}
                  </div>
                </div>
              </div>
            </div>
          )}

          {quality && (
            <div style={styles.section}>
              <div style={styles.sectionTitle}>Data Quality</div>
              <div style={styles.sectionSubtitle}>
                {quality.data_quality_score >= 90
                  ? "High quality data — ready for optimization"
                  : "Some data quality issues detected"}
              </div>
              <QualityDisplay quality={quality} />
            </div>
          )}

          {preview && (
            <div style={styles.section}>
              <div style={styles.sectionTitle}>Data Preview</div>
              <div style={styles.sectionSubtitle}>
                Showing first {Math.min(preview.dealers.sample_rows.length, 5)} rows of each sheet
              </div>
              <div style={styles.tabs}>
                {(["dealers", "ftcs", "relationships"] as const).map((key) => (
                  <button
                    key={key}
                    style={{ ...styles.tab, ...(previewTab === key ? styles.tabActive : {}) }}
                    onClick={() => setPreviewTab(key)}
                  >
                    {preview[key].sheet_name} ({preview[key].total_rows})
                  </button>
                ))}
              </div>
              <PreviewTable preview={preview} sheetKey={previewTab} />
            </div>
          )}

          {errors.length > 0 && (
            <div style={styles.section}>
              <ErrorDisplay errors={errors} />
            </div>
          )}

          <div style={styles.successBanner}>
            <span>✓</span>
            <span>File uploaded and validated successfully. Configure optimization parameters below.</span>
          </div>
        </>
      )}
    </div>
  );
}
