"use client";

import type { ModelRegistryEntry } from "@/lib/api";

interface ModelRegistryTableProps {
    models: ModelRegistryEntry[];
}

function sourceBadgeClass(source: string): string {
    if (source === "empirical") return "bg-emerald-500/10 text-emerald-300";
    if (source === "manual_override") return "bg-amber-500/10 text-amber-300";
    return "bg-slate-500/10 text-slate-300";
}

export function ModelRegistryTable({ models }: ModelRegistryTableProps) {
    return (
        <div className="rounded-xl border border-white/5 bg-[#111318] shadow-lg shadow-black/20">
            <div className="flex items-baseline justify-between px-4 py-3">
                <h3 className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                    Model Registry
                </h3>
                <span className="text-[13px] tabular-nums text-slate-300">
                    {models.length} models
                </span>
            </div>

            <div className="overflow-x-auto">
                <table className="w-full">
                    <thead>
                        <tr className="border-t border-border">
                            <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                Model
                            </th>
                            <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                P95 (GB)
                            </th>
                            <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                Buffered (GB)
                            </th>
                            <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                Samples
                            </th>
                            <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                Source
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {models.map((model) => (
                            <tr
                                key={model.model_name}
                                className="border-t border-t-border/50 hover:bg-white/[0.02]"
                            >
                                <td className="px-4 py-2.5 text-[13px] font-medium text-white">
                                    {model.model_name}
                                </td>
                                <td className="px-4 py-2.5 text-[13px] tabular-nums text-slate-300">
                                    {model.p95_gb.toFixed(2)}
                                </td>
                                <td className="px-4 py-2.5 text-[13px] tabular-nums text-slate-300">
                                    {(model.with_buffer_bytes / 1024 ** 3).toFixed(2)}
                                </td>
                                <td className="px-4 py-2.5 text-[13px] tabular-nums text-slate-300">
                                    {model.sample_count}
                                </td>
                                <td className="px-4 py-2.5">
                                    <span
                                        className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${sourceBadgeClass(model.source)}`}
                                    >
                                        {model.source === "empirical" ? "Profiled" : "Estimated"}
                                    </span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
