import { useState, useCallback, useRef, useEffect } from "react";
import type {
  UploadResponse,
  UploadStatus,
  OptimizeStatus,
  OptimizationConfig,
  OptimizationStatus,
  OptimizationResults,
  AnalyticsReport,
  OptimizationProgressEvent,
  RefinerIteration,
  SMProgress,
} from "../types";
import * as api from "../services/api";

export function useOptimization() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [uploadResponse, setUploadResponse] =
    useState<UploadResponse | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);

  const [optimizeStatus, setOptimizeStatus] = useState<OptimizeStatus>("idle");
  const [optimizationStatus, setOptimizationStatus] =
    useState<OptimizationStatus | null>(null);
  const [progressEvent, setProgressEvent] =
    useState<OptimizationProgressEvent | null>(null);
  const [refinerHistory, setRefinerHistory] = useState<RefinerIteration[]>([]);
  const [smProgressMap, setSmProgressMap] = useState<
    Record<string, SMProgress>
  >({});

  const [results, setResults] = useState<OptimizationResults | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  const pollingRef = useRef<number | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const refinerHistoryRef = useRef<RefinerIteration[]>([]);

  // === UPLOAD ===

  const uploadFile = useCallback(async (file: File) => {
    setIsProcessing(true);
    setError(null);
    setUploadProgress(0);
    setUploadStatus("uploading");
    try {
      const response = await api.uploadExcel(file, (pct) => {
        setUploadProgress(pct);
      });
      setJobId(response.job_id);
      setUploadResponse(response);
      setUploadStatus(response.status as UploadStatus);
      return response;
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Upload failed";
      setError(message);
      setUploadStatus("error");
      throw err;
    } finally {
      setIsProcessing(false);
    }
  }, []);

  // === OPTIMIZATION RUN / CANCEL ===

  const startOptimization = useCallback(
    async (config?: Partial<OptimizationConfig>) => {
      if (!jobId) return;
      setIsProcessing(true);
      setError(null);
      setOptimizeStatus("running");
      setRefinerHistory([]);
      setSmProgressMap({});
      refinerHistoryRef.current = [];
      setProgressEvent(null);

      // Open SSE stream FIRST
      const source = api.createProgressEventSource(
        jobId,
        (event) => {
          setProgressEvent(event);
          if (event.refiner_iteration) {
            setRefinerHistory((prev) => {
              const next = [...prev, event.refiner_iteration!];
              refinerHistoryRef.current = next;
              return next;
            });
          }
          if (event.sm_progress) {
            setSmProgressMap((prev) => ({
              ...prev,
              [event.sm_progress!.sm_id]: event.sm_progress!,
            }));
          }
          setOptimizationStatus({
            job_id: event.job_id,
            phase: event.phase,
            progress: event.progress,
            message: event.message,
            started_at: null,
            completed_at: null,
          });
          if (event.phase === "complete") {
            setOptimizeStatus("completed");
            setIsProcessing(false);
            fetchResults(jobId);
            source.close();
          } else if (event.phase === "failed") {
            setOptimizeStatus("cancelled");
            setIsProcessing(false);
            source.close();
          }
        },
        () => {
          fetchResults(jobId);
        },
        () => {
          // SSE error — fall back to polling
          pollStatus(jobId);
        },
      );
      eventSourceRef.current = source;

      // Then kick off the optimization
      try {
        await api.runOptimization(jobId, config);
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : "Optimization failed";
        setError(message);
        setOptimizeStatus("failed");
        setIsProcessing(false);
        source.close();
      }
    },
    [jobId],
  );

  const cancelOptimization = useCallback(async () => {
    if (!jobId) return;
    try {
      await api.cancelOptimization(jobId);
      setOptimizeStatus("cancelled");
      setIsProcessing(false);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : "Failed to cancel optimization",
      );
    }
  }, [jobId]);

  const fetchResults = useCallback(async (jid: string) => {
    try {
      const resultData = await api.getResult(jid);
      setResults(resultData);
      const analyticsData = await api.getAnalytics(jid);
      setAnalytics(analyticsData);
    } catch {
      // fall through
    }
  }, []);

  // === POLLING FALLBACK ===

  const pollStatus = useCallback(async (jid: string) => {
    const poll = async () => {
      try {
        const status = await api.getStatus(jid);
        setOptimizationStatus(status);
        if (status.phase === "complete" || status.phase === "failed") {
          if (pollingRef.current) {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
          }
          setIsProcessing(false);
          setOptimizeStatus(
            status.phase === "complete" ? "completed" : "failed",
          );
          if (status.phase === "complete") {
            fetchResults(jid);
          }
        }
      } catch {
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
        setIsProcessing(false);
      }
    };
    await poll();
    pollingRef.current = window.setInterval(poll, 2000);
  }, [fetchResults]);

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  // === RESET ===

  const reset = useCallback(() => {
    setJobId(null);
    setUploadStatus("idle");
    setUploadResponse(null);
    setUploadProgress(0);
    setOptimizeStatus("idle");
    setOptimizationStatus(null);
    setProgressEvent(null);
    setRefinerHistory([]);
    setSmProgressMap({});
    setResults(null);
    setAnalytics(null);
    setError(null);
    setIsProcessing(false);
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  return {
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
  };
}
