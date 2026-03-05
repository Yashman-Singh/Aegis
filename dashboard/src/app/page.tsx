"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { fetchMetrics, type MetricsResponse } from "@/lib/api";
import { LoadedModelCard } from "@/components/LoadedModelCard";
import { ThroughputStats } from "@/components/ThroughputStats";
import {
  MemoryPressureChart,
  type DataPoint,
} from "@/components/MemoryPressureChart";
import { JobQueueTable } from "@/components/JobQueueTable";
import { Shield } from "lucide-react";

const POLL_INTERVAL_MS = 2000;
const MAX_CHART_POINTS = 60;

function formatProvider(provider: string) {
  if (!provider) return "";
  const p = provider.toUpperCase();
  if (p.includes("APPLE") || p.includes("SILICON") || p === "APPLE_SILICON") return "Apple Silicon";
  if (p.includes("NVIDIA")) return "NVIDIA GPU";
  if (p.includes("CPU")) return "CPU Fallback";
  return provider;
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pressureHistory, setPressureHistory] = useState<DataPoint[]>([]);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const data = await fetchMetrics();
      setMetrics(data);
      setError(null);
      setLastUpdated(new Date());

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
        return next.length > MAX_CHART_POINTS
          ? next.slice(next.length - MAX_CHART_POINTS)
          : next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch metrics");
    }
  }, []);

  useEffect(() => {
    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [poll]);

  useEffect(() => {
    const ticker = setInterval(() => {
      if (lastUpdated) {
        setSecondsAgo(Math.floor((Date.now() - lastUpdated.getTime()) / 1000));
      }
    }, 1000);
    return () => clearInterval(ticker);
  }, [lastUpdated]);

  const runningJob = metrics?.queue.jobs.find((j) => j.status === "RUNNING");

  return (
    <div className="min-h-screen bg-background">
      {/* Top bar */}
      <header className="border-b border-border bg-[#111318]">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <Shield className="h-5 w-5 text-indigo-500" />
            <div>
              <h1 className="text-sm font-bold tracking-tight text-white">
                Aegis
              </h1>
              <p className="text-[11px] uppercase tracking-[0.08em] text-slate-400">
                Inference Runtime
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {lastUpdated && !error && (
              <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-indigo-500" />
                </span>
                {secondsAgo <= 1 ? "LIVE" : `${secondsAgo}s AGO`}
              </span>
            )}
            {error ? (
              <span className="rounded bg-red-500/10 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider text-red-400">
                Disconnected
              </span>
            ) : metrics ? (
              <span className="rounded bg-indigo-500/10 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider text-indigo-400">
                {formatProvider(metrics.hardware.provider)}
              </span>
            ) : null}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-6 py-5">
        {metrics ? (
          <div className="space-y-4">
            {/* Row 1: 5-column stat grid */}
            <div className="grid grid-cols-5 gap-3">
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

            {/* Row 2: Chart */}
            <MemoryPressureChart
              data={pressureHistory}
              vramUsedBytes={metrics.hardware.vram_used_bytes}
              vramTotalBytes={metrics.hardware.vram_total_bytes}
            />

            {/* Row 3: Table */}
            <JobQueueTable jobs={metrics.queue.jobs} />
          </div>
        ) : (
          <div className="flex h-64 items-center justify-center">
            <p className="text-[13px] text-slate-400">
              {error ? "Backend unreachable" : "Connecting…"}
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
