"use client";

import {
    CheckCircle2,
    XCircle,
    Timer,
    Layers,
} from "lucide-react";
import type { ThroughputMetrics } from "@/lib/api";

interface ThroughputStatsProps {
    throughput: ThroughputMetrics;
    queueDepth: number;
}

export function ThroughputStats({
    throughput,
    queueDepth,
}: ThroughputStatsProps) {
    const latencyMs = throughput.avg_latency_ms_last_100;

    const stats = [
        {
            label: "Completed",
            primary: throughput.jobs_completed_total.toLocaleString(),
            secondary: "since last restart",
            icon: CheckCircle2,
        },
        {
            label: "Failed",
            primary: throughput.jobs_failed_total.toLocaleString(),
            secondary:
                throughput.jobs_completed_total > 0
                    ? `${((throughput.jobs_failed_total / (throughput.jobs_completed_total + throughput.jobs_failed_total)) * 100).toFixed(1)}% error rate`
                    : "no data",
            icon: XCircle,
        },
        {
            label: "Avg Latency",
            primary:
                latencyMs != null ? `${(latencyMs / 1000).toFixed(1)}s` : "—",
            secondary: "per request",
            icon: Timer,
        },
        {
            label: "Queue Depth",
            primary: queueDepth.toString(),
            secondary: queueDepth === 0 ? "idle" : `${queueDepth} waiting`,
            icon: Layers,
        },
    ];

    return (
        <>
            {stats.map((stat) => {
                const Icon = stat.icon;
                return (
                    <div
                        key={stat.label}
                        className="rounded-xl border border-white/5 bg-[#111318] p-4 shadow-lg shadow-black/20"
                    >
                        {/* Label row */}
                        <div className="mb-3 flex items-center gap-2">
                            <Icon className="h-3.5 w-3.5 text-slate-400" />
                            <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                {stat.label}
                            </span>
                        </div>

                        {/* Primary metric — 48px for single-digit feel */}
                        <p className="text-[42px] font-bold leading-none tracking-tight text-white">
                            {stat.primary}
                        </p>

                        {/* Secondary detail */}
                        <p className="mt-1 text-[13px] text-slate-300">
                            {stat.secondary}
                        </p>
                    </div>
                );
            })}
        </>
    );
}
