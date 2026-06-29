import React, { useState, useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
  Cell,
  ComposedChart,
  Line,
} from "recharts";
import type { AnalyticsReport } from "../types";

interface Props {
  analytics: AnalyticsReport;
}

const CHART_COLORS = [
  "#4a90d9", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16",
];

type ChartMode = "bar" | "scatter";

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
    marginBottom: "16px",
  },
  title: {
    fontSize: "18px",
    fontWeight: 600,
  },
  toggleGroup: {
    display: "flex",
    gap: "4px",
    background: "#f0f0f0",
    borderRadius: "6px",
    padding: "2px",
  },
  toggleBtn: {
    padding: "6px 12px",
    border: "none",
    borderRadius: "4px",
    background: "transparent",
    cursor: "pointer",
    fontSize: "12px",
    fontWeight: 500,
    color: "#666",
    transition: "all 0.15s",
  },
  toggleBtnActive: {
    background: "white",
    color: "#1a1a2e",
    boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
  },
  chartContainer: {
    width: "100%",
    height: "350px",
  },
  summaryRow: {
    display: "flex",
    gap: "16px",
    marginTop: "12px",
    padding: "12px",
    background: "#f8f9fa",
    borderRadius: "8px",
    fontSize: "12px",
    color: "#666",
  },
  statItem: {
    display: "flex",
    gap: "6px",
    alignItems: "center",
  },
  statValue: {
    fontWeight: 700,
    color: "#1a1a2e",
  },
};

export function WorkloadChart({ analytics }: Props) {
  const [mode, setMode] = useState<ChartMode>("bar");

  const workloadData = useMemo(
    () =>
      analytics.sm_reports.flatMap((sm) =>
        sm.metrics.map((m) => ({
          name:
            m.ftc_id.length > 14
              ? m.ftc_id.slice(0, 14) + "..."
              : m.ftc_id,
          fullName: m.ftc_id,
          sm_id: sm.sm_id,
          workload: Number(m.workload_score.toFixed(3)),
          distance: Number(m.average_distance_km.toFixed(1)),
          compactness: Number((m.compactness_score * 100).toFixed(1)),
          dealers: m.dealer_count,
          cases: Number(m.average_cases_per_day.toFixed(1)),
        })),
      ),
    [analytics.sm_reports],
  );

  const workloadHistogram = useMemo(() => {
    const bins: Record<string, number> = {};
    const step = 0.1;
    for (let i = 0; i <= 1; i += step) {
      const key = `${i.toFixed(1)}-${(i + step).toFixed(1)}`;
      bins[key] = 0;
    }
    workloadData.forEach((d) => {
      const binIdx = Math.min(
        Math.floor(d.workload / step),
        Object.keys(bins).length - 1,
      );
      const key = Object.keys(bins)[binIdx];
      if (key) bins[key]++;
    });
    return Object.entries(bins).map(([range, count]) => ({
      range,
      count,
    }));
  }, [workloadData]);

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const entry = workloadData.find(
        (d) => d.name === label || d.fullName === label,
      );
      return (
        <div
          style={{
            background: "white",
            border: "1px solid #ddd",
            borderRadius: "8px",
            padding: "10px 14px",
            fontSize: "12px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "4px" }}>
            {entry?.fullName || label}
          </div>
          {payload.map((p: any, i: number) => (
            <div
              key={i}
              style={{ color: p.color, marginTop: "2px" }}
            >{`${p.name}: ${p.value}`}</div>
          ))}
          {entry && (
            <div style={{ color: "#888", marginTop: "4px" }}>
              SM: {entry.sm_id}
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  const avgWorkload = workloadData.length
    ? (
        workloadData.reduce((s, d) => s + d.workload, 0) /
        workloadData.length
      ).toFixed(3)
    : "0";
  const maxWorkload = workloadData.length
    ? Math.max(...workloadData.map((d) => d.workload)).toFixed(3)
    : "0";
  const minWorkload = workloadData.length
    ? Math.min(...workloadData.map((d) => d.workload)).toFixed(3)
    : "0";

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.title}>Workload Analysis</div>
        <div style={styles.toggleGroup}>
          <button
            style={{
              ...styles.toggleBtn,
              ...(mode === "bar" ? styles.toggleBtnActive : {}),
            }}
            onClick={() => setMode("bar")}
          >
            FTC View
          </button>
          <button
            style={{
              ...styles.toggleBtn,
              ...(mode === "scatter" ? styles.toggleBtnActive : {}),
            }}
            onClick={() => setMode("scatter")}
          >
            Histogram
          </button>
        </div>
      </div>

      <div style={styles.chartContainer}>
        {mode === "bar" ? (
          <ResponsiveContainer>
            <ComposedChart
              data={workloadData.slice(0, 40)}
              margin={{ top: 10, right: 20, left: 0, bottom: 60 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="name"
                angle={-45}
                textAnchor="end"
                height={80}
                interval={0}
                fontSize={10}
              />
              <YAxis
                yAxisId="left"
                fontSize={12}
                domain={[0, "auto"]}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                fontSize={12}
                domain={[0, "auto"]}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <Bar
                yAxisId="left"
                dataKey="workload"
                fill="#4a90d9"
                name="Workload Score"
                radius={[3, 3, 0, 0]}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="dealers"
                stroke="#22c55e"
                name="Dealer Count"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <ResponsiveContainer>
            <BarChart
              data={workloadHistogram}
              margin={{ top: 10, right: 20, left: 0, bottom: 10 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="range"
                fontSize={11}
                label={{
                  value: "Workload Score Range",
                  position: "bottom",
                  fontSize: 11,
                  offset: -5,
                }}
              />
              <YAxis
                fontSize={12}
                label={{
                  value: "FTC Count",
                  angle: -90,
                  position: "insideLeft",
                  fontSize: 11,
                  offset: 10,
                }}
              />
              <Tooltip />
              <Legend />
              <Bar
                dataKey="count"
                fill="#8b5cf6"
                name="FTCs"
                radius={[4, 4, 0, 0]}
              >
                {workloadHistogram.map((_, i) => (
                  <Cell
                    key={i}
                    fill={CHART_COLORS[i % CHART_COLORS.length]}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div style={styles.summaryRow}>
        <div style={styles.statItem}>
          FTCs: <span style={styles.statValue}>{workloadData.length}</span>
        </div>
        <div style={styles.statItem}>
          Avg Workload:{" "}
          <span style={styles.statValue}>{avgWorkload}</span>
        </div>
        <div style={styles.statItem}>
          Min: <span style={styles.statValue}>{minWorkload}</span>
        </div>
        <div style={styles.statItem}>
          Max: <span style={styles.statValue}>{maxWorkload}</span>
        </div>
      </div>
    </div>
  );
}
