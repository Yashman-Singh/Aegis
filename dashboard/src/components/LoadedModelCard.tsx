"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { HardwareMetrics } from "@/lib/api";

interface LoadedModelCardProps {
    loadedModel: string | null;
    hardware: HardwareMetrics;
    jobStartedAt: string | null;
}

export function LoadedModelCard({
    loadedModel,
    hardware,
    jobStartedAt,
}: LoadedModelCardProps) {
    // Compute elapsed time if a job is running
    let elapsed = "";
    if (jobStartedAt) {
        const startMs = new Date(jobStartedAt).getTime();
        const nowMs = Date.now();
        const diffS = Math.max(0, Math.floor((nowMs - startMs) / 1000));
        const mins = Math.floor(diffS / 60);
        const secs = diffS % 60;
        elapsed = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
    }

    const pressureColor =
        hardware.vram_pressure_percent > 85
            ? "bg-red-500"
            : hardware.vram_pressure_percent > 60
                ? "bg-yellow-500"
                : "bg-emerald-500";

    return (
        <Card className="min-w-[240px]">
            <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                    Active Model
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
                <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-bold tracking-tight">
                        {loadedModel ?? "Idle"}
                    </span>
                    {loadedModel && (
                        <span className="text-xs font-medium text-blue-500">RUNNING</span>
                    )}
                </div>
                {elapsed && (
                    <p className="text-xs text-muted-foreground">Elapsed: {elapsed}</p>
                )}
                <div className="space-y-1">
                    <div className="flex justify-between text-xs text-muted-foreground">
                        <span>VRAM Pressure</span>
                        <span>{hardware.vram_pressure_percent.toFixed(1)}%</span>
                    </div>
                    <Progress
                        value={hardware.vram_pressure_percent}
                        className={`h-2 [&>[data-slot=progress-indicator]]:${pressureColor}`}
                    />
                </div>
            </CardContent>
        </Card>
    );
}
