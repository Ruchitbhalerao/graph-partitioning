import React, { useState } from "react";
import { FileUpload } from "./components/FileUpload";
import { OptimizationControls } from "./components/OptimizationControls";
import { Dashboard } from "./components/Dashboard";
import { DrillDown } from "./components/DrillDown";
import { ExportPanel } from "./components/ExportPanel";
import { useOptimization } from "./hooks/useOptimization";
import type { AppView, SMResult } from "./types";

const styles: Record<string, React.CSSProperties> = {
  app: {
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    minHeight: "100vh",
    background: "#f5f7fa",
    color: "#1a1a2e",
  },
  header: {
    background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)",
    color: "white",
    padding: "16px 32px",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
  },
  headerTitle: {
    fontSize: "20px",
    fontWeight: 700,
    letterSpacing: "0.5px",
  },
  headerSubtitle: {
    fontSize: "13px",
    opacity: 0.7,
    marginTop: "2px",
  },
  nav: {
    display: "flex",
    gap: "8px",
  },
  navButton: {
    padding: "8px 16px",
    border: "none",
    borderRadius: "6px",
    background: "rgba(255,255,255,0.1)",
    color: "white",
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 500,
    transition: "background 0.2s",
  },
  navButtonActive: {
    background: "rgba(255,255,255,0.25)",
  },
  content: {
    maxWidth: "1400px",
    margin: "0 auto",
    padding: "24px",
  },
};

function App() {
  const {
    jobId,
    uploadStatus,
    uploadResponse,
    uploadProgress,
    optimizeStatus,
    optimizationStatus,
    progressEvent,
    refinerHistory,
    smProgressMap,
    results,
    analytics,
    error,
    isProcessing,
    uploadFile,
    startOptimization,
    cancelOptimization,
    reset,
  } = useOptimization();

  const [view, setView] = useState<AppView>("upload");
  const [selectedSmId, setSelectedSmId] = useState<string | null>(null);
  const [selectedFtcId, setSelectedFtcId] = useState<string | null>(null);

  const hasResults = results !== null && analytics !== null;
  const isOptimized = optimizeStatus === "completed" || hasResults;

  const handleSmClick = (smId: string) => {
    setSelectedSmId(smId);
    setSelectedFtcId(null);
    setView("drilldown");
  };

  const handleFtcClick = (ftcId: string) => {
    setSelectedFtcId(ftcId);
  };

  const getSelectedSmResult = (): SMResult | null => {
    if (!results || !selectedSmId) return null;
    return results.results[selectedSmId] || null;
  };

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        <div>
          <div style={styles.headerTitle}>
            Territory Optimization System
          </div>
          <div style={styles.headerSubtitle}>
            Enterprise Territory Planning &rarr;{" "}
            {uploadStatus === "validated"
              ? `Uploaded • Job: ${jobId?.slice(0, 8)}...`
              : optimizeStatus === "completed"
                ? "Optimization Complete"
                : optimizeStatus === "running"
                  ? "Optimizing..."
                  : "No active job"}
          </div>
        </div>
        <nav style={styles.nav}>
          <button
            style={{
              ...styles.navButton,
              ...(view === "upload" ? styles.navButtonActive : {}),
            }}
            onClick={() => { setView("upload"); reset(); }}
          >
            Upload
          </button>
          <button
            style={{
              ...styles.navButton,
              ...(view === "dashboard" ? styles.navButtonActive : {}),
            }}
            onClick={() => setView("dashboard")}
            disabled={!isOptimized}
          >
            Dashboard
          </button>
          <button
            style={{
              ...styles.navButton,
              ...(view === "drilldown" ? styles.navButtonActive : {}),
            }}
            onClick={() => setView("drilldown")}
            disabled={!isOptimized}
          >
            Drill Down
          </button>
        </nav>
      </header>

      <div style={styles.content}>
        {error && (
          <div
            style={{
              background: "#fff0f0",
              border: "1px solid #ffcccc",
              color: "#cc0000",
              padding: "12px 16px",
              borderRadius: "8px",
              marginBottom: "16px",
              fontSize: "14px",
            }}
          >
            {error}
          </div>
        )}

        {view === "upload" && (
          <div>
            <FileUpload
              onUpload={uploadFile}
              isProcessing={isProcessing}
              uploadStatus={uploadStatus}
              uploadResponse={uploadResponse}
              uploadProgress={uploadProgress}
            />
            {uploadStatus === "validated" && (
              <OptimizationControls
                onOptimize={startOptimization}
                onCancel={cancelOptimization}
                isProcessing={isProcessing}
                optimizeStatus={optimizeStatus}
                optimizationStatus={optimizationStatus}
                progressEvent={progressEvent}
                refinerHistory={refinerHistory}
                smProgressMap={smProgressMap}
                onViewDashboard={() => setView("dashboard")}
              />
            )}
          </div>
        )}

        {view === "dashboard" && isOptimized && (
          <Dashboard
            analytics={analytics!}
            results={results!}
            jobId={jobId!}
            onSmClick={handleSmClick}
          />
        )}

        {view === "drilldown" && isOptimized && (
          <DrillDown
            smResult={getSelectedSmResult()}
            smId={selectedSmId}
            ftcId={selectedFtcId}
            onFtcClick={handleFtcClick}
            onBack={() => setView("dashboard")}
            analytics={analytics!}
          />
        )}

        {isOptimized && (
          <ExportPanel jobId={jobId!} />
        )}
      </div>
    </div>
  );
}

export default App;
