import React from "react";
import type { AnalyticsReport, OptimizationResults } from "../types";

interface Props {
  analytics: AnalyticsReport;
  results: OptimizationResults;
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "white",
    borderRadius: "12px",
    padding: "24px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "20px",
  },
  title: {
    fontSize: "18px",
    fontWeight: 600,
  },
  exportBtn: {
    padding: "6px 14px",
    border: "1px solid #ddd",
    borderRadius: "6px",
    background: "white",
    cursor: "pointer",
    fontSize: "12px",
    fontWeight: 500,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
    gap: "12px",
  },
  card: {
    padding: "16px",
    borderRadius: "8px",
    textAlign: "center" as const,
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  value: {
    fontSize: "26px",
    fontWeight: 700,
    lineHeight: 1.1,
  },
  label: {
    fontSize: "11px",
    color: "#666",
    textTransform: "uppercase" as const,
    letterSpacing: "0.5px",
    fontWeight: 500,
  },
  subtitle: {
    fontSize: "10px",
    color: "#999",
  },
};

const cardBg = (score: number, inverse = false): string => {
  const val = inverse ? 1 - score : score;
  if (val >= 0.9) return "#f0fdf4";
  if (val >= 0.7) return "#fefce8";
  return "#fef2f2";
};

const cardBorder = (score: number, inverse = false): string => {
  const val = inverse ? 1 - score : score;
  if (val >= 0.9) return "#bbf7d0";
  if (val >= 0.7) return "#fde68a";
  return "#fecaca";
};

const valueColor = (score: number, inverse = false): string => {
  const val = inverse ? 1 - score : score;
  if (val >= 0.9) return "#166534";
  if (val >= 0.7) return "#92400e";
  return "#991b1b";
};

export function StatisticsPanel({ analytics, results }: Props) {
  const validRatio =
    results.summary.total_sm_regions > 0
      ? results.summary.valid_regions / results.summary.total_sm_regions
      : 0;
  const coverageScore = analytics.total_coverage_percent / 100;
  const workloadScore = Math.max(0, 1 - analytics.workload_variance * 10);
  const travelScore = Math.max(
    0,
    1 - analytics.average_travel_distance_km / 200,
  );
  const compactnessScore = Math.min(1, analytics.territory_compactness_avg);

  const kpiCard = (
    label: string,
    value: string | number,
    score: number,
    inverse = false,
    subtitle?: string,
  ) => (
    <div
      style={{
        ...styles.card,
        background: cardBg(score, inverse),
        border: `1px solid ${cardBorder(score, inverse)}`,
      }}
    >
      <div style={{ ...styles.value, color: valueColor(score, inverse) }}>
        {typeof value === "number" && Number.isFinite(value)
          ? typeof value === "number" && value % 1 !== 0
            ? (value as number).toFixed(1)
            : value
          : value}
      </div>
      <div style={styles.label}>{label}</div>
      {subtitle && <div style={styles.subtitle}>{subtitle}</div>}
    </div>
  );

  const handleExport = () => {
    const csv = [
      ["Metric", "Value"].join(","),
      ["SM Regions", analytics.total_sms].join(","),
      ["FTCs", analytics.total_ftcs].join(","),
      ["Dealers", analytics.total_dealers].join(","),
      ["Static Dealers", analytics.total_static_assignments].join(","),
      ["Mobile Dealers", analytics.total_mobile_assignments].join(","),
      ["Coverage %", analytics.total_coverage_percent.toFixed(1)].join(","),
      ["Avg Travel (km)", analytics.average_travel_distance_km.toFixed(1)].join(
        ",",
      ),
      ["Max Travel (km)", analytics.max_travel_distance_km.toFixed(1)].join(","),
      ["Avg Workload", analytics.average_workload_per_ftc.toFixed(3)].join(","),
      ["Workload Variance", analytics.workload_variance.toFixed(4)].join(","),
      ["Compactness", analytics.territory_compactness_avg.toFixed(3)].join(","),
      ["Valid Regions", `${results.summary.valid_regions}/${results.summary.total_sm_regions}`].join(","),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `kpi_${analytics.job_id.slice(0, 8)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.title}>Key Performance Indicators</div>
        <button style={styles.exportBtn} onClick={handleExport}>
          Export CSV
        </button>
      </div>
      <div style={styles.grid}>
        {kpiCard("SM Regions", analytics.total_sms, 1)}
        {kpiCard("FTCs", analytics.total_ftcs, 1)}
        {kpiCard("Total Dealers", analytics.total_dealers, 1)}
        {kpiCard(
          "Static",
          analytics.total_static_assignments,
          1,
          false,
          "dealers",
        )}
        {kpiCard(
          "Mobile",
          analytics.total_mobile_assignments,
          1,
          false,
          "dealers",
        )}
        {kpiCard("Coverage", `${analytics.total_coverage_percent.toFixed(0)}%`, coverageScore)}
        {kpiCard(
          "Avg Travel",
          `${analytics.average_travel_distance_km.toFixed(1)}km`,
          travelScore,
          true,
        )}
        {kpiCard(
          "Max Travel",
          `${analytics.max_travel_distance_km.toFixed(1)}km`,
          Math.max(0, 1 - analytics.max_travel_distance_km / 400),
          true,
        )}
        {kpiCard(
          "Avg Workload",
          analytics.average_workload_per_ftc.toFixed(2),
          Math.min(1, analytics.average_workload_per_ftc / 10),
        )}
        {kpiCard(
          "Wrkld Variance",
          analytics.workload_variance.toFixed(4),
          workloadScore,
          true,
        )}
        {kpiCard(
          "Compactness",
          analytics.territory_compactness_avg.toFixed(3),
          compactnessScore,
        )}
        {kpiCard(
          "Valid Regions",
          `${results.summary.valid_regions}/${results.summary.total_sm_regions}`,
          validRatio,
        )}
      </div>
    </div>
  );
}
