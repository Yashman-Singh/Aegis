"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { fetchMetrics, type MetricsResponse } from "@/lib/api";
import { LoadedModelCard } from "@/components/LoadedModelCard";
import { ThroughputStats } from "@/components/ThroughputStats";
import { MemoryPressureChart, type DataPoint } from "@/components/MemoryPressureChart";
import { JobQueueTable } from "@/components/JobQueueTable";

const POLL_INTERVAL_MS = 2000;
const MAX_CHART_POINTS = 60; // 2 minutes of history at 2s intervals

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pressureHistory, setPressureHistory] = useState<DataPoint[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const data = await fetchMetrics();
      setMetrics(data);
      setError(null);

      // Append to rolling pressure buffer
      const now = new Date();
      const timeLabel = now.toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });

      setPressureHistory((prev) => {
        const next = [
          ...prev,
          { time: timeLabel, pressure: data.hardware.vram_pressure_percent },
        ];
        // Keep only the last MAX_CHART_POINTS entries
        return next.length > MAX_CHART_POINTS
          ? next.slice(next.length - MAX_CHART_POINTS)
          : next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch metrics");
    }
  }, []);

  useEffect(() => {
    // Initial fetch
    poll();

    // Start polling
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [poll]);

  // Find the currently running job's started_at for elapsed timer
  const runningJob = metrics?.queue.jobs.find((j) => j.status === "RUNNING");

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              Aegis Dashboard
            </h1>
            <p className="text-sm text-muted-foreground">
              AI Inference Runtime Monitor
            </p>
          </div>
          {error && (
            <span className="rounded-md bg-red-100 px-3 py-1 text-xs font-medium text-red-700 dark:bg-red-900/40 dark:text-red-300">
              {error}
            </span>
          )}
          {!error && metrics && (
            <span className="rounded-md bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
              Connected • {metrics.hardware.provider}
            </span>
          )}
        </div>

        {metrics ? (
          <div className="space-y-6">
            {/* Row 1: LoadedModelCard + ThroughputStats */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
              <LoadedModelCard
                loadedModel={metrics.loaded_model}
                hardware={metrics.hardware}
                jobStartedAt={runningJob?.created_at ?? null}
              />
              <ThroughputStats
                throughput={metrics.throughput}
                queueDepth={metrics.queue.depth}
              />
            </div>

            {/* Row 2: Memory Pressure Chart */}
            <MemoryPressureChart data={pressureHistory} />

            {/* Row 3: Job Queue Table */}
            <JobQueueTable jobs={metrics.queue.jobs} />
          </div>
        ) : (
          <div className="flex h-64 items-center justify-center">
            <p className="text-sm text-muted-foreground">
              {error ? "Backend unreachable" : "Connecting to backend…"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
