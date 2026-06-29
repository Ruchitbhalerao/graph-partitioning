import React, { useState } from "react";
import type { AnalyticsReport, OptimizationResults } from "../types";
import { StatisticsPanel } from "./StatisticsPanel";
import { WorkloadChart } from "./WorkloadChart";
import { MapView } from "./MapView";

interface Props {
  analytics: AnalyticsReport;
  results: OptimizationResults;
  jobId: string;
  onSmClick: (smId: string) => void;
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
  },
  sectionTitle: {
    fontSize: "22px",
    fontWeight: 700,
    marginBottom: "4px",
  },
  sectionSubtitle: {
    fontSize: "14px",
    color: "#666",
    marginBottom: "16px",
  },
  mapRow: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "16px",
  },
  smList: {
    background: "white",
    borderRadius: "12px",
    padding: "20px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    maxHeight: "500px",
  },
  searchInput: {
    width: "100%",
    padding: "8px 12px",
    border: "1px solid #ddd",
    borderRadius: "6px",
    fontSize: "13px",
    outline: "none",
    boxSizing: "border-box" as const,
  },
  headerRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  smListTitle: {
    fontSize: "16px",
    fontWeight: 600,
  },
  filterBadge: {
    padding: "4px 10px",
    borderRadius: "12px",
    fontSize: "11px",
    fontWeight: 600,
    cursor: "pointer",
    border: "none",
    background: "#f0f0f0",
    color: "#666",
  },
  filterBadgeActive: {
    background: "#1a1a2e",
    color: "white",
  },
  scrollArea: {
    flex: 1,
    overflowY: "auto" as const,
  },
  smItem: {
    padding: "12px 16px",
    borderRadius: "8px",
    cursor: "pointer",
    border: "1px solid #eee",
    marginBottom: "8px",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    transition: "background 0.15s",
  },
  smName: {
    fontWeight: 600,
    fontSize: "14px",
  },
  smStats: {
    fontSize: "12px",
    color: "#888",
    marginTop: "2px",
  },
  badge: {
    padding: "4px 8px",
    borderRadius: "4px",
    fontSize: "11px",
    fontWeight: 600,
  },
  badgeValid: {
    background: "#dcfce7",
    color: "#166534",
  },
  badgeInvalid: {
    background: "#fef2f2",
    color: "#991b1b",
  },
};

export function Dashboard({
  analytics,
  results,
  jobId,
  onSmClick,
}: Props) {
  const smReports = analytics.sm_reports;
  const [search, setSearch] = useState("");
  const [validFilter, setValidFilter] = useState<"all" | "valid" | "invalid">(
    "all",
  );

  const filtered = smReports.filter((sm) => {
    const matchSearch =
      !search ||
      sm.sm_id.toLowerCase().includes(search.toLowerCase());
    const smResult = results.results[sm.sm_id];
    const isValid = smResult?.is_valid ?? false;
    const matchFilter =
      validFilter === "all" ||
      (validFilter === "valid" && isValid) ||
      (validFilter === "invalid" && !isValid);
    return matchSearch && matchFilter;
  });

  return (
    <div style={styles.container}>
      <div>
        <div style={styles.sectionTitle}>Optimization Dashboard</div>
        <div style={styles.sectionSubtitle}>
          Overview of territory optimization results across all SM regions
        </div>
      </div>

      <StatisticsPanel analytics={analytics} results={results} />

      <div style={styles.mapRow}>
        <MapView
          jobId={jobId}
          selectedSmId={null}
          onSmClick={onSmClick}
          onFtcClick={() => {}}
        />

        <div style={styles.smList}>
          <div style={styles.headerRow}>
            <div style={styles.smListTitle}>
              SM Regions ({filtered.length}/{smReports.length})
            </div>
            <div style={{ display: "flex", gap: "6px" }}>
              <button
                style={{
                  ...styles.filterBadge,
                  ...(validFilter === "all" ? styles.filterBadgeActive : {}),
                }}
                onClick={() => setValidFilter("all")}
              >
                All
              </button>
              <button
                style={{
                  ...styles.filterBadge,
                  ...(validFilter === "valid"
                    ? styles.filterBadgeActive
                    : {}),
                }}
                onClick={() => setValidFilter("valid")}
              >
                Valid
              </button>
              <button
                style={{
                  ...styles.filterBadge,
                  ...(validFilter === "invalid"
                    ? styles.filterBadgeActive
                    : {}),
                }}
                onClick={() => setValidFilter("invalid")}
              >
                Errors
              </button>
            </div>
          </div>
          <input
            style={styles.searchInput}
            placeholder="Search SM region..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div style={styles.scrollArea}>
            {filtered.map((sm) => {
              const smResult = results.results[sm.sm_id];
              const isValid = smResult?.is_valid ?? false;
              return (
                <div
                  key={sm.sm_id}
                  style={styles.smItem}
                  onClick={() => onSmClick(sm.sm_id)}
                >
                  <div>
                    <div style={styles.smName}>SM: {sm.sm_id}</div>
                    <div style={styles.smStats}>
                      {sm.ftc_count} FTCs | {sm.dealer_count} Dealers |{" "}
                      {sm.total_cases.toFixed(0)} cases |{" "}
                      {sm.total_distance_km.toFixed(1)} km
                    </div>
                  </div>
                  <span
                    style={{
                      ...styles.badge,
                      ...(isValid ? styles.badgeValid : styles.badgeInvalid),
                    }}
                  >
                    {isValid ? "Valid" : "Errors"}
                  </span>
                </div>
              );
            })}
            {filtered.length === 0 && (
              <div
                style={{
                  textAlign: "center",
                  color: "#999",
                  fontSize: "13px",
                  padding: "24px",
                }}
              >
                No SM regions match your filter
              </div>
            )}
          </div>
        </div>
      </div>

      <WorkloadChart analytics={analytics} />

      {results.summary.regions_with_errors > 0 && (
        <div
          style={{
            padding: "12px 16px",
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: "8px",
            color: "#991b1b",
            fontSize: "13px",
          }}
        >
          <strong>{results.summary.regions_with_errors}</strong> region(s) have
          validation errors. Click on an SM to view details.
        </div>
      )}
    </div>
  );
}
