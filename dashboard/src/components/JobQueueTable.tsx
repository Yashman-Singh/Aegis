"use client";

import { Inbox } from "lucide-react";
import type { QueueJobSummary } from "@/lib/api";

interface JobQueueTableProps {
    jobs: QueueJobSummary[];
}

function getPriorityPill(priority: number) {
    if (priority <= 3) {
        return { label: `P${priority} High`, cls: "bg-red-500/10 text-red-400" };
    }
    if (priority <= 6) {
        return { label: `P${priority} Mid`, cls: "bg-amber-500/10 text-amber-400" };
    }
    return { label: `P${priority} Low`, cls: "bg-slate-500/10 text-slate-400" };
}

function statusCls(status: string): string {
    const map: Record<string, string> = {
        QUEUED: "bg-slate-500/10 text-slate-300",
        ALLOCATING: "bg-amber-500/10 text-amber-400",
        RUNNING: "bg-indigo-500/10 text-indigo-400",
        COMPLETED: "bg-emerald-500/10 text-emerald-400",
        FAILED: "bg-red-500/10 text-red-400",
    };
    return map[status] ?? "bg-slate-500/10 text-slate-300";
}

function truncateId(id: string): string {
    return id.slice(0, 8);
}

function formatElapsed(createdAt: string): string {
    const secs = Math.max(
        0,
        Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000)
    );
    if (secs < 60) return `${secs}s`;
    const m = Math.floor(secs / 60);
    return `${m}m ${secs % 60}s`;
}

export function JobQueueTable({ jobs }: JobQueueTableProps) {
    return (
        <div className="rounded-xl border border-white/5 bg-[#111318] shadow-lg shadow-black/20">
            {/* Header */}
            <div className="flex items-baseline justify-between px-4 py-3">
                <h3 className="text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                    Job Queue
                </h3>
                <span className="text-[13px] tabular-nums text-slate-300">
                    {jobs.length} active
                </span>
            </div>

            {jobs.length === 0 ? (
                /* Proper empty state */
                <div className="px-4 pb-4">
                    <div className="flex flex-col items-center justify-center rounded-lg bg-white/[0.02] py-12">
                        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-white/[0.05]">
                            <Inbox className="h-6 w-6 text-slate-400" />
                        </div>
                        <p className="text-[13px] font-medium text-slate-300">
                            Queue is empty
                        </p>
                        <p className="mt-1 text-[12px] text-slate-500">
                            Submit a job to see it here
                        </p>
                    </div>
                </div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead>
                            <tr className="border-t border-border">
                                <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                    Job ID
                                </th>
                                <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                    Model
                                </th>
                                <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                    Priority
                                </th>
                                <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                    Status
                                </th>
                                <th className="px-4 py-2 text-left text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                    Submitted
                                </th>
                                <th className="px-4 py-2 text-right text-[11px] font-medium uppercase tracking-[0.08em] text-slate-400">
                                    Elapsed
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {jobs.map((job) => {
                                const pri = getPriorityPill(job.priority);
                                const isRunning = job.status === "RUNNING";

                                return (
                                    <tr
                                        key={job.job_id}
                                        className={`border-t transition-colors ${isRunning
                                            ? "border-l-2 border-l-indigo-500 border-t-border/50 bg-indigo-500/[0.03]"
                                            : "border-t-border/50 hover:bg-white/[0.02]"
                                            }`}
                                    >
                                        <td className="px-4 py-2.5 font-mono text-[12px] text-slate-400">
                                            {truncateId(job.job_id)}
                                        </td>
                                        <td className="px-4 py-2.5 text-[13px] font-medium text-white">
                                            {job.model_name}
                                        </td>
                                        <td className="px-4 py-2.5">
                                            <span
                                                className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${pri.cls}`}
                                            >
                                                {pri.label}
                                            </span>
                                        </td>
                                        <td className="px-4 py-2.5">
                                            <span
                                                className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${statusCls(job.status)}`}
                                            >
                                                {job.status}
                                            </span>
                                        </td>
                                        <td className="px-4 py-2.5 text-[13px] text-slate-300">
                                            {new Date(job.created_at).toLocaleTimeString()}
                                        </td>
                                        <td className="px-4 py-2.5 text-right text-[13px] tabular-nums text-slate-300">
                                            {formatElapsed(job.created_at)}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
