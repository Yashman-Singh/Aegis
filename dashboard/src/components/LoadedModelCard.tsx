"use client";

import { Cpu } from "lucide-react";
import type { HardwareMetrics } from "@/lib/api";

interface LoadedModelCardProps {
    loadedModel: string | null;
    hardware: HardwareMetrics;
    jobStartedAt: string | null;
}

function fmtGB(bytes: number): string {
    return (bytes / 1024 ** 3).toFixed(1);
}

export function LoadedModelCard({
    loadedModel,
    hardware,
    jobStartedAt,
}: LoadedModelCardProps) {
    let elapsed = "";
    if (jobStartedAt) {
        const diffS = Math.max(
            0,
            Math.floor((Date.now() - new Date(jobStartedAt).getTime()) / 1000)
        );
        const m = Math.floor(diffS / 60);
        const s = diffS % 60;
        elapsed = m > 0 ? `${m}m ${s}s` : `${s}s`;
    }

    const pct = hardware.vram_pressure_percent;
    const barColor =
        pct > 90 ? "bg-red-500" : pct > 70 ? "bg-amber-500" : "bg-indigo-500";

    return (
        <div className="rounded-xl border border-white/5 bg-[#111318] p-4 shadow-lg shadow-black/20">
            {/* Label */}
            <div className="mb-3 flex items-center gap-2">
                <Cpu className="h-3.5 w-3.5 text-slate-400" />
                <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                    Active Model
                </span>
            </div>

            {/* Primary: model name — 48px tier would be too large for model names, using 24px */}
            <div className="mb-0.5 flex items-baseline gap-2">
                <span className="text-[22px] font-bold leading-tight tracking-tight text-white">
                    {loadedModel ?? "Idle"}
                </span>
                {loadedModel && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-[0.1em] text-indigo-400">
                        <span className="relative flex h-1.5 w-1.5">
                            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-75" />
                            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-indigo-400" />
                        </span>
                        Running
                    </span>
                )}
            </div>

            {/* Secondary detail */}
            <p className="mb-3 text-[13px] text-slate-300">
                {elapsed ? `Elapsed ${elapsed}` : "No job in progress"}
            </p>

            {/* VRAM micro-bar */}
            <div className="space-y-1">
                <div className="flex items-baseline justify-between">
                    <span className="text-[11px] uppercase tracking-[0.08em] text-slate-400">
                        VRAM
                    </span>
                    <span className="text-[13px] font-semibold tabular-nums text-white">
                        {pct.toFixed(1)}%
                    </span>
                </div>
                <div className="h-1 w-full overflow-hidden rounded-full bg-slate-800">
                    <div
                        className={`h-full rounded-full transition-all duration-700 ${barColor}`}
                        style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                </div>
                <p className="text-[11px] tabular-nums text-slate-400">
                    {fmtGB(hardware.vram_used_bytes)} / {fmtGB(hardware.vram_total_bytes)} GB
                </p>
            </div>
        </div>
    );
}
