"use client";

import {
    AreaChart,
    Area,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface DataPoint {
    time: string;
    pressure: number;
}

interface MemoryPressureChartProps {
    data: DataPoint[];
}

export function MemoryPressureChart({ data }: MemoryPressureChartProps) {
    // Dynamic gradient color stop based on latest pressure value
    const latestPressure = data.length > 0 ? data[data.length - 1].pressure : 0;

    const strokeColor =
        latestPressure > 85
            ? "#ef4444"   // red
            : latestPressure > 60
                ? "#eab308" // yellow
                : "#10b981"; // green

    return (
        <Card className="col-span-full">
            <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                    VRAM Pressure (last 2 min)
                </CardTitle>
            </CardHeader>
            <CardContent>
                <div className="h-[200px] w-full">
                    <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={data}>
                            <defs>
                                <linearGradient id="pressureFill" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor={strokeColor} stopOpacity={0.3} />
                                    <stop offset="95%" stopColor={strokeColor} stopOpacity={0} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid
                                strokeDasharray="3 3"
                                className="stroke-muted"
                            />
                            <XAxis
                                dataKey="time"
                                tick={{ fontSize: 10 }}
                                className="text-muted-foreground"
                            />
                            <YAxis
                                domain={[0, 100]}
                                tick={{ fontSize: 10 }}
                                tickFormatter={(v: number) => `${v}%`}
                                className="text-muted-foreground"
                            />
                            <Tooltip
                                formatter={(value: number | undefined) => [
                                    `${(value ?? 0).toFixed(1)}%`,
                                    "Pressure",
                                ]}
                                labelFormatter={(label) => `Time: ${label}`}
                            />
                            <Area
                                type="monotone"
                                dataKey="pressure"
                                stroke={strokeColor}
                                strokeWidth={2}
                                fill="url(#pressureFill)"
                            />
                        </AreaChart>
                    </ResponsiveContainer>
                </div>
            </CardContent>
        </Card>
    );
}

export type { DataPoint };
