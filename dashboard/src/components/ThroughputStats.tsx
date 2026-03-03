"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ThroughputMetrics, QueueMetrics } from "@/lib/api";

interface ThroughputStatsProps {
    throughput: ThroughputMetrics;
    queueDepth: number;
}

export function ThroughputStats({ throughput, queueDepth }: ThroughputStatsProps) {
    const stats = [
        {
            label: "Completed",
            value: throughput.jobs_completed_total.toLocaleString(),
        },
        {
            label: "Failed",
            value: throughput.jobs_failed_total.toLocaleString(),
        },
        {
            label: "Avg Latency",
            value: throughput.avg_latency_ms_last_100 != null
                ? `${(throughput.avg_latency_ms_last_100 / 1000).toFixed(1)}s`
                : "—",
        },
        {
            label: "Queue Depth",
            value: queueDepth.toString(),
        },
    ];

    return (
        <>
            {stats.map((stat) => (
                <Card key={stat.label} className="min-w-[140px]">
                    <CardHeader className="pb-2">
                        <CardTitle className="text-sm font-medium text-muted-foreground">
                            {stat.label}
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <span className="text-2xl font-bold tracking-tight">
                            {stat.value}
                        </span>
                    </CardContent>
                </Card>
            ))}
        </>
    );
}
