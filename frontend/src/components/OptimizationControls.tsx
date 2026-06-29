import React, { useState, useMemo } from "react";
import type {
  OptimizationConfig,
  OptimizationStatus,
  OptimizationProgressEvent,
  RefinerIteration,
  SMProgress,
  OptimizeStatus,
} from "../types";

interface Props {
  onOptimize: (config?: Partial<OptimizationConfig>) => Promise<void>;
  onCancel: () => Promise<void>;
  isProcessing: boolean;
  optimizeStatus: OptimizeStatus;
  optimizationStatus: OptimizationStatus | null;
  progressEvent: OptimizationProgressEvent | null;
  refinerHistory: RefinerIteration[];
  smProgressMap: Record<string, SMProgress>;
  onViewDashboard: () => void;
}

const PHASE_LABELS: Record<string, string> = {
  graph_construction: "Building Graph",
  initial_territories: "Partitioning",
  territory_refinement: "Refining Territories",
  validation: "Validating",
  polygon_generation: "Generating Polygons",
  complete: "Complete",
  failed: "Failed",
};

const PHASE_COLORS: Record<string, string> = {
  graph_construction: "#6366f1",
  initial_territories: "#8b5cf6",
  territory_refinement: "#f59e0b",
  validation: "#10b981",
  polygon_generation: "#06b6d4",
  complete: "#22c55e",
  failed: "#ef4444",
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: "white",
    borderRadius: "12px",
    padding: "24px",
    marginTop: "16px",
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)",
  },
  title: { fontSize: "18px", fontWeight: 600, marginBottom: "16px" },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: "16px",
    marginBottom: "20px",
  },
  field: { display: "flex", flexDirection: "column" as const, gap: "6px" },
  label: { fontSize: "13px", fontWeight: 500, color: "#555" },
  slider: { width: "100%", accentColor: "#6366f1" },
  value: { fontSize: "14px", fontWeight: 600, color: "#1a1a2e", minWidth: "36px" },
  sliderRow: { display: "flex", alignItems: "center", gap: "8px" },
  input: {
    padding: "8px 12px",
    border: "1px solid #ddd",
    borderRadius: "6px",
    fontSize: "14px",
    outline: "none",
    width: "100%",
  },
  checkbox: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "8px 0",
    fontSize: "14px",
    color: "#555",
    cursor: "pointer",
  },
  buttonRow: { display: "flex", gap: "12px", alignItems: "center", marginTop: "16px" },
  button: {
    padding: "12px 24px",
    border: "none",
    borderRadius: "8px",
    fontSize: "14px",
    fontWeight: 600,
    cursor: "pointer",
    transition: "all 0.2s",
  },
  primaryButton: {
    background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
    color: "white",
  },
  dangerButton: {
    background: "#fee2e2",
    color: "#dc2626",
    border: "1px solid #fecaca",
  },
  secondaryButton: {
    background: "#f0f0f0",
    color: "#333",
  },
  disabledButton: {
    opacity: 0.5,
    cursor: "not-allowed",
  },

  // === Progress Section ===
  progressSection: {
    marginTop: "20px",
    padding: "20px",
    background: "#f8f9fa",
    borderRadius: "8px",
    border: "1px solid #e5e7eb",
  },
  progressTitle: { fontSize: "15px", fontWeight: 600, marginBottom: "12px", color: "#1a1a2e" },
  progressBarOuter: {
    width: "100%",
    height: "10px",
    background: "#e5e7eb",
    borderRadius: "5px",
    overflow: "hidden",
    marginBottom: "8px",
  },
  progressBarInner: {
    height: "100%",
    borderRadius: "5px",
    transition: "width 0.4s ease, background 0.3s ease",
  },
  progressMessage: {
    fontSize: "13px",
    color: "#667085",
    marginBottom: "4px",
    display: "flex",
    justifyContent: "space-between",
  },
  phaseLabel: {
    fontSize: "12px",
    fontWeight: 600,
    padding: "2px 8px",
    borderRadius: "4px",
    display: "inline-block",
    marginRight: "8px",
  },

  // === Phase Timeline ===
  timeline: { marginTop: "16px" },
  timelineItem: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    padding: "6px 0",
    fontSize: "13px",
  },
  timelineDot: {
    width: "10px",
    height: "10px",
    borderRadius: "50%",
    flexShrink: 0,
  },
  timelineLabel: { flex: 1, color: "#344054" },
  timelineDuration: { color: "#98a2b3", fontSize: "12px", whiteSpace: "nowrap" as const },

  // === Refiner Metrics ===
  refinerSection: { marginTop: "12px" },
  refinerGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))",
    gap: "8px",
    marginTop: "8px",
  },
  refinerCard: {
    padding: "8px",
    background: "white",
    borderRadius: "6px",
    border: "1px solid #e5e7eb",
    textAlign: "center" as const,
  },
  refinerLabel: { fontSize: "10px", color: "#98a2b3", marginBottom: "2px", textTransform: "uppercase" as const },
  refinerValue: { fontSize: "16px", fontWeight: 700, color: "#1a1a2e" },

  // === SM Grid ===
  smGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
    gap: "8px",
    marginTop: "8px",
    maxHeight: "160px",
    overflowY: "auto" as const,
  },
  smCard: {
    padding: "8px 10px",
    borderRadius: "6px",
    fontSize: "12px",
    border: "1px solid #e5e7eb",
    background: "white",
  },
  smCardActive: { borderColor: "#f59e0b", background: "#fffbeb" },
  smCardDone: { borderColor: "#22c55e", background: "#f0fdf4" },
  smCardError: { borderColor: "#ef4444", background: "#fef2f2" },
  smCardPending: { borderColor: "#e5e7eb", background: "#f9fafb" },
  smName: { fontWeight: 600, fontSize: "13px" },
  smDetail: { fontSize: "11px", color: "#98a2b3", marginTop: "2px" },
};

function formatSec(sec: number): string {
  if (sec < 60) return `${sec.toFixed(0)}s`;
  return `${Math.floor(sec / 60)}m ${(sec % 60).toFixed(0)}s`;
}

export function OptimizationControls({
  onOptimize,
  onCancel,
  isProcessing: _isProcessing,
  optimizeStatus,
  optimizationStatus,
  progressEvent,
  refinerHistory,
  smProgressMap,
  onViewDashboard,
}: Props) {
  const [config, setConfig] = useState({
    travel_weight: 0.35,
    workload_weight: 0.30,
    compactness_weight: 0.20,
    productivity_weight: 0.15,
    proximity_km: 5,
    preserve_existing: false,
    max_refinement_iterations: 200,
    parallel_process: true,
  });

  const updateConfig = (key: string, value: number | boolean) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  const handleOptimize = () => onOptimize(config);
  const handleCancel = () => onCancel();

  const isRunning = optimizeStatus === "running";
  const isIdle = optimizeStatus === "idle";
  const isCompleted = optimizeStatus === "completed";

  const currentPhase = optimizationStatus?.phase || "";
  const phaseColor = PHASE_COLORS[currentPhase] || "#6366f1";
  const totalSMs = progressEvent?.sm_total || 0;
  const completedSMs = progressEvent?.sm_completed || 0;

  const latestRefiner = refinerHistory.length > 0
    ? refinerHistory[refinerHistory.length - 1]
    : null;

  const smArray = useMemo(
    () => Object.values(smProgressMap).sort((a, b) => a.sm_id.localeCompare(b.sm_id)),
    [smProgressMap],
  );

  const phaseOrder = [
    "graph_construction", "initial_territories", "territory_refinement",
    "validation", "polygon_generation", "complete",
  ];
  const completedPhases = useMemo(() => {
    const idx = phaseOrder.indexOf(currentPhase);
    return idx >= 0 ? phaseOrder.slice(0, idx) : [];
  }, [currentPhase]);

  return (
    <div style={styles.container}>
      <div style={styles.title}>Optimization Configuration</div>

      <div style={styles.grid}>
        {/* Travail Weight */}
        <div style={styles.field}>
          <label style={styles.label}>Travel Weight</label>
          <div style={styles.sliderRow}>
            <input
              type="range" min="0" max="1" step="0.05"
              value={config.travel_weight}
              onChange={(e) => updateConfig("travel_weight", parseFloat(e.target.value))}
              style={styles.slider}
              disabled={isRunning}
            />
            <span style={styles.value}>{config.travel_weight.toFixed(2)}</span>
          </div>
        </div>

        {/* Workload Weight */}
        <div style={styles.field}>
          <label style={styles.label}>Workload Weight</label>
          <div style={styles.sliderRow}>
            <input
              type="range" min="0" max="1" step="0.05"
              value={config.workload_weight}
              onChange={(e) => updateConfig("workload_weight", parseFloat(e.target.value))}
              style={styles.slider}
              disabled={isRunning}
            />
            <span style={styles.value}>{config.workload_weight.toFixed(2)}</span>
          </div>
        </div>

        {/* Compactness Weight */}
        <div style={styles.field}>
          <label style={styles.label}>Compactness Weight</label>
          <div style={styles.sliderRow}>
            <input
              type="range" min="0" max="1" step="0.05"
              value={config.compactness_weight}
              onChange={(e) => updateConfig("compactness_weight", parseFloat(e.target.value))}
              style={styles.slider}
              disabled={isRunning}
            />
            <span style={styles.value}>{config.compactness_weight.toFixed(2)}</span>
          </div>
        </div>

        {/* Productivity Weight */}
        <div style={styles.field}>
          <label style={styles.label}>Productivity Weight</label>
          <div style={styles.sliderRow}>
            <input
              type="range" min="0" max="1" step="0.05"
              value={config.productivity_weight}
              onChange={(e) => updateConfig("productivity_weight", parseFloat(e.target.value))}
              style={styles.slider}
              disabled={isRunning}
            />
            <span style={styles.value}>{config.productivity_weight.toFixed(2)}</span>
          </div>
        </div>

        {/* Proximity */}
        <div style={styles.field}>
          <label style={styles.label}>Proximity (km)</label>
          <input
            type="number" min="1" max="50"
            value={config.proximity_km}
            onChange={(e) => updateConfig("proximity_km", parseInt(e.target.value) || 5)}
            style={styles.input}
            disabled={isRunning}
          />
        </div>

        {/* Max Iterations */}
        <div style={styles.field}>
          <label style={styles.label}>Max Refinement Iterations</label>
          <input
            type="number" min="10" max="1000"
            value={config.max_refinement_iterations}
            onChange={(e) => updateConfig("max_refinement_iterations", parseInt(e.target.value) || 200)}
            style={styles.input}
            disabled={isRunning}
          />
        </div>
      </div>

      {/* Checkboxes */}
      <label style={styles.checkbox}>
        <input
          type="checkbox"
          checked={config.preserve_existing}
          onChange={(e) => updateConfig("preserve_existing", e.target.checked)}
          disabled={isRunning}
        />
        Preserve existing FTC-dealer assignments
      </label>
      <label style={styles.checkbox}>
        <input
          type="checkbox"
          checked={config.parallel_process}
          onChange={(e) => updateConfig("parallel_process", e.target.checked)}
          disabled={isRunning}
        />
        Process SM regions in parallel
      </label>

      {/* Buttons */}
      <div style={styles.buttonRow}>
        {!isRunning && isIdle && (
          <button
            style={{ ...styles.button, ...styles.primaryButton }}
            onClick={handleOptimize}
          >
            Run Optimization
          </button>
        )}
        {isRunning && (
          <button
            style={{ ...styles.button, ...styles.dangerButton }}
            onClick={handleCancel}
          >
            Cancel
          </button>
        )}
        {isCompleted && (
          <button
            style={{ ...styles.button, ...styles.primaryButton }}
            onClick={onViewDashboard}
          >
            View Dashboard
          </button>
        )}
        {isCompleted && (
          <button
            style={{ ...styles.button, ...styles.secondaryButton }}
            onClick={handleOptimize}
          >
            Re-run
          </button>
        )}
      </div>

      {/* === PROGRESS DISPLAY === */}
      {(isRunning || isCompleted) && optimizationStatus && (
        <div style={styles.progressSection}>
          <div style={styles.progressTitle}>
            {isRunning ? "Optimization in Progress" : "Optimization Complete"}
            {progressEvent?.estimated_remaining_sec != null && isRunning && (
              <span style={{ fontSize: "12px", fontWeight: 400, color: "#98a2b3", marginLeft: "12px" }}>
                ~{formatSec(progressEvent.estimated_remaining_sec)} remaining
              </span>
            )}
          </div>

          {/* Progress Bar */}
          <div style={styles.progressBarOuter}>
            <div
              style={{
                ...styles.progressBarInner,
                width: `${optimizationStatus.progress}%`,
                background: phaseColor,
              }}
            />
          </div>
          <div style={styles.progressMessage}>
            <span>
              <span style={{ ...styles.phaseLabel, background: phaseColor + "22", color: phaseColor }}>
                {PHASE_LABELS[currentPhase] || currentPhase}
              </span>
              {optimizationStatus.message}
            </span>
            <span>{Math.round(optimizationStatus.progress)}%</span>
          </div>

          {/* SM Region Progress */}
          {totalSMs > 0 && (
            <div style={{ fontSize: "12px", color: "#98a2b3", marginBottom: "8px" }}>
              SM regions: {completedSMs} / {totalSMs} completed
            </div>
          )}

          {/* Phase Timeline */}
          <div style={styles.timeline}>
            {phaseOrder.map((phase) => {
              const isActive = phase === currentPhase && isRunning;
              const isDone = completedPhases.includes(phase) || (phase === "complete" && isCompleted);
              const color = PHASE_COLORS[phase] || "#d0d5dd";
              const timing = progressEvent?.timing?.find((t) => t.phase === phase);
              return (
                <div key={phase} style={{ ...styles.timelineItem, opacity: isDone || isActive ? 1 : 0.4 }}>
                  <div
                    style={{
                      ...styles.timelineDot,
                      background: isDone ? color : isActive ? color : "#d0d5dd",
                      boxShadow: isActive ? `0 0 0 3px ${color}33` : "none",
                    }}
                  />
                  <span style={styles.timelineLabel}>
                    {isActive && "→ "}{PHASE_LABELS[phase] || phase}
                  </span>
                  {timing && (
                    <span style={styles.timelineDuration}>{formatSec(timing.duration_sec)}</span>
                  )}
                </div>
              );
            })}
          </div>

          {/* Refiner Metrics */}
          {latestRefiner && isRunning && (
            <div style={styles.refinerSection}>
              <div style={{ fontSize: "12px", fontWeight: 600, color: "#667085" }}>
                Tabu Search — Iteration {latestRefiner.iteration}
              </div>
              <div style={styles.refinerGrid}>
                <div style={styles.refinerCard}>
                  <div style={styles.refinerLabel}>Fitness</div>
                  <div style={styles.refinerValue}>{latestRefiner.fitness.toFixed(1)}</div>
                </div>
                <div style={styles.refinerCard}>
                  <div style={styles.refinerLabel}>Best</div>
                  <div style={{ ...styles.refinerValue, color: "#22c55e" }}>
                    {latestRefiner.best_fitness.toFixed(1)}
                  </div>
                </div>
                <div style={styles.refinerCard}>
                  <div style={styles.refinerLabel}>Travel</div>
                  <div style={styles.refinerValue}>{latestRefiner.travel_penalty.toFixed(0)}</div>
                </div>
                <div style={styles.refinerCard}>
                  <div style={styles.refinerLabel}>Moves</div>
                  <div style={styles.refinerValue}>{latestRefiner.moves_accepted}</div>
                </div>
                <div style={styles.refinerCard}>
                  <div style={styles.refinerLabel}>Stagnation</div>
                  <div style={{ ...styles.refinerValue, color: latestRefiner.stagnation > 10 ? "#f59e0b" : "#667085" }}>
                    {latestRefiner.stagnation}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* SM Grid */}
          {smArray.length > 0 && (
            <div style={styles.refinerSection}>
              <div style={{ fontSize: "12px", fontWeight: 600, color: "#667085", marginBottom: "4px" }}>
                SM Regions Detail
              </div>
              <div style={styles.smGrid}>
                {smArray.map((sm) => {
                  let cardStyle = styles.smCardPending;
                  if (sm.status === "processing") cardStyle = { ...styles.smCard, ...styles.smCardActive };
                  else if (sm.status === "valid" && sm.is_valid) cardStyle = { ...styles.smCard, ...styles.smCardDone };
                  else if (!sm.is_valid) cardStyle = { ...styles.smCard, ...styles.smCardError };
                  else if (sm.status === "valid") cardStyle = { ...styles.smCard, ...styles.smCardDone };
                  return (
                    <div key={sm.sm_id} style={cardStyle}>
                      <div style={styles.smName}>{sm.sm_id}</div>
                      <div style={styles.smDetail}>
                        {sm.dealers_count} dealers, {sm.ftcs_count} FTCs
                      </div>
                      {sm.refine_iterations > 0 && (
                        <div style={styles.smDetail}>
                          {sm.refine_iterations} iters, {sm.refine_improvement_pct}% improv
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Refiner History Chart data (number of iterations) */}
          {refinerHistory.length > 0 && (
            <div style={{ ...styles.refinerSection, fontSize: "11px", color: "#98a2b3", textAlign: "right" as const }}>
              {refinerHistory.length} refiner updates received
            </div>
          )}
        </div>
      )}
    </div>
  );
}
