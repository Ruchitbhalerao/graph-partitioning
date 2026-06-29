import React, { useState, useMemo } from "react";
import type { SMResult, AnalyticsReport } from "../types";

interface Props {
  smResult: SMResult | null;
  smId: string | null;
  ftcId: string | null;
  onFtcClick: (ftcId: string) => void;
  onBack: () => void;
  analytics: AnalyticsReport;
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  title: {
    fontSize: "22px",
    fontWeight: 700,
  },
  subtitle: {
    fontSize: "14px",
    color: "#666",
    marginTop: "2px",
  },
  backButton: {
    padding: "8px 16px",
    border: "1px solid #ddd",
    borderRadius: "6px",
    background: "white",
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 500,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "16px",
  },
  card: {
    background: "white",
    borderRadius: "12px",
    padding: "20px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
  },
  cardTitle: {
    fontSize: "15px",
    fontWeight: 600,
    marginBottom: "12px",
  },
  metricGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: "10px",
  },
  metric: {
    padding: "10px",
    background: "#f8f9fa",
    borderRadius: "6px",
    textAlign: "center" as const,
  },
  metricValue: {
    fontSize: "18px",
    fontWeight: 700,
    color: "#1a1a2e",
  },
  metricLabel: {
    fontSize: "10px",
    color: "#888",
    marginTop: "2px",
    textTransform: "uppercase" as const,
    letterSpacing: "0.3px",
  },
  searchInput: {
    width: "100%",
    padding: "8px 12px",
    border: "1px solid #ddd",
    borderRadius: "6px",
    fontSize: "13px",
    outline: "none",
    marginBottom: "10px",
    boxSizing: "border-box" as const,
  },
  ftcList: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
  },
  ftcCard: {
    padding: "10px 14px",
    borderRadius: "8px",
    border: "1px solid #eee",
    cursor: "pointer",
    transition: "all 0.15s",
  },
  ftcCardSelected: {
    borderColor: "#4a90d9",
    background: "#f0f6ff",
  },
  ftcName: {
    fontWeight: 600,
    fontSize: "13px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  ftcStats: {
    fontSize: "11px",
    color: "#888",
    marginTop: "3px",
  },
  dealerTable: {
    width: "100%",
    borderCollapse: "collapse" as const,
    fontSize: "13px",
  },
  th: {
    textAlign: "left" as const,
    padding: "8px 12px",
    borderBottom: "2px solid #eee",
    color: "#888",
    fontWeight: 600,
    fontSize: "11px",
    textTransform: "uppercase" as const,
  },
  td: {
    padding: "8px 12px",
    borderBottom: "1px solid #f0f0f0",
  },
  anchorBadge: {
    padding: "2px 6px",
    borderRadius: "4px",
    background: "#dcfce7",
    color: "#166534",
    fontSize: "10px",
    fontWeight: 600,
  },
  territoryBadge: {
    padding: "2px 8px",
    borderRadius: "10px",
    fontSize: "10px",
    fontWeight: 600,
  },
  miniMetrics: {
    display: "flex",
    gap: "12px",
    marginTop: "6px",
    fontSize: "11px",
    color: "#888",
  },
};

export function DrillDown({
  smResult,
  smId,
  ftcId,
  onFtcClick,
  onBack,
  analytics,
}: Props) {
  const [search, setSearch] = useState("");

  const smAnalytics = useMemo(
    () => analytics.sm_reports.find((r) => r.sm_id === smId) ?? null,
    [analytics.sm_reports, smId],
  );

  const ftcIds = useMemo(
    () => (smResult ? Object.keys(smResult.assignments) : []),
    [smResult],
  );

  const filteredFtcIds = useMemo(
    () =>
      ftcIds.filter(
        (fid) =>
          !search ||
          fid.toLowerCase().includes(search.toLowerCase()) ||
          smResult?.assignments[fid]?.some((d) =>
            d.toLowerCase().includes(search.toLowerCase()),
          ),
      ),
    [ftcIds, search, smResult],
  );

  const selectedFtcDealers = useMemo(
    () =>
      ftcId && smResult ? smResult.assignments[ftcId] || [] : [],
    [ftcId, smResult],
  );

  const getFtcAnalytics = (fid: string) =>
    smAnalytics?.metrics.find((m) => m.ftc_id === fid) ?? null;

  const compactnessColor = (v: number) => {
    if (v >= 0.7) return "#166534";
    if (v >= 0.4) return "#92400e";
    return "#991b1b";
  };

  const compactnessBg = (v: number) => {
    if (v >= 0.7) return "#dcfce7";
    if (v >= 0.4) return "#fef3c7";
    return "#fef2f2";
  };

  if (!smId) {
    return (
      <div style={styles.container}>
        <div style={styles.title}>Drill Down Analysis</div>
        <div style={styles.subtitle}>
          Select an SM region from the Dashboard map or list to drill down
        </div>
      </div>
    );
  }

  if (!smResult) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <div>
            <div style={styles.title}>SM Region: {smId}</div>
            <div style={styles.subtitle}>
              No data available for this region
            </div>
          </div>
          <button style={styles.backButton} onClick={onBack}>
            &larr; Dashboard
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div>
          <div style={styles.title}>SM Region: {smId}</div>
          <div style={styles.subtitle}>
            {smResult.ftc_count} FTCs |{" "}
            {smResult.static_dealers + smResult.mobile_dealers} Dealers |{" "}
            {smResult.is_valid ? (
              <span style={{ color: "#166534" }}>Valid</span>
            ) : (
              <span style={{ color: "#991b1b" }}>Validation Errors</span>
            )}
          </div>
        </div>
        <button style={styles.backButton} onClick={onBack}>
          &larr; Dashboard
        </button>
      </div>

      <div style={styles.grid}>
        <div style={styles.card}>
          <div style={styles.cardTitle}>SM Overview</div>
          <div style={styles.metricGrid}>
            <div style={styles.metric}>
              <div style={styles.metricValue}>{smResult.ftc_count}</div>
              <div style={styles.metricLabel}>FTCs</div>
            </div>
            <div style={styles.metric}>
              <div style={styles.metricValue}>
                {smResult.static_dealers}
              </div>
              <div style={styles.metricLabel}>Static</div>
            </div>
            <div style={styles.metric}>
              <div style={styles.metricValue}>
                {smResult.mobile_dealers}
              </div>
              <div style={styles.metricLabel}>Mobile</div>
            </div>
            <div style={styles.metric}>
              <div style={styles.metricValue}>
                {smAnalytics
                  ? `${smAnalytics.total_cases.toFixed(0)}`
                  : "N/A"}
              </div>
              <div style={styles.metricLabel}>Total Cases</div>
            </div>
            <div style={styles.metric}>
              <div style={styles.metricValue}>
                {smAnalytics
                  ? `${smAnalytics.total_distance_km.toFixed(1)}`
                  : "N/A"}
              </div>
              <div style={styles.metricLabel}>Total Km</div>
            </div>
            <div style={styles.metric}>
              <div style={styles.metricValue}>
                {smAnalytics
                  ? smAnalytics.workload_variance.toFixed(4)
                  : "N/A"}
              </div>
              <div style={styles.metricLabel}>Wrkld Variance</div>
            </div>
          </div>
          {!smResult.is_valid && (
            <div
              style={{
                marginTop: "12px",
                padding: "10px",
                background: "#fef2f2",
                borderRadius: "6px",
                color: "#991b1b",
                fontSize: "12px",
              }}
            >
              <strong>Validation Issues:</strong>
              {smResult.validation_errors.map((err, i) => (
                <div key={i} style={{ marginTop: "4px" }}>
                  &bull; {err}
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={styles.card}>
          <div style={styles.cardTitle}>
            FTC Territories ({filteredFtcIds.length})
          </div>
          <input
            style={styles.searchInput}
            placeholder="Search FTC or dealer..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div style={{ maxHeight: "320px", overflowY: "auto" }}>
            {filteredFtcIds.map((fid) => {
              const isSelected = fid === ftcId;
              const dealers = smResult.assignments[fid];
              const anchor = smResult.anchors[fid];
              const ftcA = getFtcAnalytics(fid);
              return (
                <div
                  key={fid}
                  style={{
                    ...styles.ftcCard,
                    ...(isSelected ? styles.ftcCardSelected : {}),
                  }}
                  onClick={() => onFtcClick(fid === ftcId ? "" : fid)}
                >
                  <div style={styles.ftcName}>
                    {fid}
                    {anchor && (
                      <span style={styles.anchorBadge}>
                        Anchor: {anchor}
                      </span>
                    )}
                  </div>
                  <div style={styles.ftcStats}>
                    {dealers.length} dealers
                    {ftcA && (
                      <>
                        {" "}
                        &middot; {ftcA.average_cases_per_day.toFixed(1)}{" "}
                        cases/day
                      </>
                    )}
                  </div>
                  {ftcA && (
                    <div style={styles.miniMetrics}>
                      <span>
                        Dist: {ftcA.average_distance_km.toFixed(1)}km
                      </span>
                      <span
                        style={{
                          ...styles.territoryBadge,
                          color: compactnessColor(ftcA.compactness_score),
                          background: compactnessBg(
                            ftcA.compactness_score,
                          ),
                        }}
                      >
                        C: {ftcA.compactness_score.toFixed(2)}
                      </span>
                      <span
                        style={{
                          ...styles.territoryBadge,
                          color: compactnessColor(ftcA.workload_score),
                          background: compactnessBg(ftcA.workload_score),
                        }}
                      >
                        W: {ftcA.workload_score.toFixed(2)}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
            {filteredFtcIds.length === 0 && (
              <div
                style={{
                  textAlign: "center",
                  color: "#999",
                  fontSize: "13px",
                  padding: "16px",
                }}
              >
                No FTCs match search
              </div>
            )}
          </div>
        </div>
      </div>

      {ftcId && selectedFtcDealers.length > 0 && (
        <div style={styles.card}>
          <div style={styles.cardTitle}>
            Dealers Assigned to {ftcId}
          </div>
          <table style={styles.dealerTable}>
            <thead>
              <tr>
                <th style={styles.th}>Dealer ID</th>
                <th style={styles.th}>Type</th>
                <th style={styles.th}>Role</th>
              </tr>
            </thead>
            <tbody>
              {selectedFtcDealers.map((dId) => {
                const isAnchor = smResult.anchors[ftcId] === dId;
                return (
                  <tr key={dId}>
                    <td style={styles.td}>
                      {dId}
                      {isAnchor && (
                        <span
                          style={{
                            ...styles.anchorBadge,
                            marginLeft: "8px",
                          }}
                        >
                          Anchor
                        </span>
                      )}
                    </td>
                    <td style={styles.td}>
                      {smResult.static_dealers > 0 &&
                      smResult.assignments[ftcId]?.includes(dId)
                        ? "Mobile"
                        : "Static"}
                    </td>
                    <td style={styles.td}>
                      {isAnchor ? (
                        <span style={{ color: "#166534", fontWeight: 600 }}>
                          Primary
                        </span>
                      ) : (
                        <span style={{ color: "#888" }}>Assigned</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {selectedFtcDealers.length === 0 && (
            <div
              style={{
                textAlign: "center",
                color: "#999",
                fontSize: "13px",
                padding: "16px",
              }}
            >
              No dealers assigned to this FTC
            </div>
          )}
        </div>
      )}
    </div>
  );
}
