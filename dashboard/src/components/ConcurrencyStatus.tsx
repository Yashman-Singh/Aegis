"use client";

import { Rows4 } from "lucide-react";
import type { ConcurrencyMetrics } from "@/lib/api";

interface ConcurrencyStatusProps {
    concurrency: ConcurrencyMetrics;
}

function fmtGB(bytes: number): string {
    return (bytes / 1024 ** 3).toFixed(1);
}

export function ConcurrencyStatus({ concurrency }: ConcurrencyStatusProps) {
    const freeSlots = Math.max(
        0,
        concurrency.max_concurrent_jobs - concurrency.currently_running
    );

    return (
        <div className="rounded-xl border border-white/5 bg-[#111318] p-4 shadow-lg shadow-black/20">
            <div className="mb-3 flex items-center gap-2">
                <Rows4 className="h-3.5 w-3.5 text-slate-400" />
                <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                    Concurrency
                </span>
            </div>

            <p className="text-[28px] font-bold leading-none tracking-tight text-white">
                {concurrency.currently_running}/{concurrency.max_concurrent_jobs}
            </p>
            <p className="mt-1 text-[13px] text-slate-300">
                {freeSlots} slot{freeSlots === 1 ? "" : "s"} available
            </p>

            <div className="mt-3 space-y-1 text-[11px] text-slate-400">
                <p>Reserved: {fmtGB(concurrency.active_reservations_bytes)} GB</p>
                <p>Schedulable: {fmtGB(concurrency.vram_available_for_scheduling)} GB</p>
            </div>
        </div>
    );
}
