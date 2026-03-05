"use client";

import {
    AreaChart,
    Area,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ReferenceLine,
    ResponsiveContainer,
} from "recharts";

interface DataPoint {
    time: string;
    pressure: number;
}

interface MemoryPressureChartProps {
    data: DataPoint[];
    vramUsedBytes: number;
    vramTotalBytes: number;
}

function fmtGB(bytes: number): string {
    return (bytes / 1024 ** 3).toFixed(1);
}

/**
 * Returns a color that transitions:
 *   0-70%  → indigo (#6366f1)
 *   70-90% → amber (#f59e0b)
 *   90%+   → red   (#ef4444)
 */
function pressureColor(pct: number): string {
    if (pct >= 90) return "#ef4444";
    if (pct >= 70) return "#f59e0b";
    return "#6366f1";
}

export function MemoryPressureChart({
    data,
    vramUsedBytes,
    vramTotalBytes,
}: MemoryPressureChartProps) {
    const latest = data.length > 0 ? data[data.length - 1].pressure : 0;
    const color = pressureColor(latest);

    return (
        <div className="rounded-xl border border-white/5 bg-[#111318] p-4 shadow-lg shadow-black/20">
            {/* Header */}
            <div className="mb-4 flex items-end justify-between">
                <div>
                    <h3 className="text-[24px] font-bold tracking-tight text-white">
                        VRAM Pressure
                    </h3>
                    <p className="mt-0.5 text-[13px] text-slate-400">
                        {fmtGB(vramUsedBytes)} / {fmtGB(vramTotalBytes)} GB · last 2 min
                    </p>
                </div>
                <span
                    className="text-[42px] font-bold leading-none tabular-nums tracking-tight"
                    style={{ color }}
                >
                    {latest.toFixed(1)}
                    <span className="text-[18px] font-semibold text-slate-400">%</span>
                </span>
            </div>

            {/* Chart */}
            <div className="h-[200px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                    <AreaChart
                        data={data}
                        margin={{ top: 4, right: 4, bottom: 0, left: -20 }}
                    >
                        <defs>
                            <linearGradient id="pressureFill" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                                <stop offset="100%" stopColor={color} stopOpacity={0.02} />
                            </linearGradient>
                        </defs>
                        <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#1e2128"
                            vertical={false}
                        />
                        <XAxis
                            dataKey="time"
                            tick={{ fontSize: 10, fill: "#64748b" }}
                            tickLine={false}
                            axisLine={false}
                            interval={9}
                        />
                        <YAxis
                            domain={[0, 100]}
                            tick={{ fontSize: 10, fill: "#64748b" }}
                            tickLine={false}
                            axisLine={false}
                            tickFormatter={(v: number) => `${v}%`}
                        />
                        <Tooltip
                            contentStyle={{
                                backgroundColor: "#1a1d24",
                                border: "1px solid #2a2d35",
                                borderRadius: "8px",
                                padding: "8px 12px",
                                boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
                            }}
                            itemStyle={{ color, fontSize: "13px" }}
                            labelStyle={{ color: "#94a3b8", fontSize: "11px", marginBottom: "2px" }}
                            formatter={(value: number | undefined) => [
                                `${(value ?? 0).toFixed(1)}%`,
                                "Pressure",
                            ]}
                            labelFormatter={(label) => `${label}`}
                            cursor={{ stroke: "#475569", strokeDasharray: "4 4" }}
                        />
                        {/* 75% eviction threshold */}
                        <ReferenceLine
                            y={75}
                            stroke="#ef4444"
                            strokeDasharray="6 3"
                            strokeWidth={2}
                            strokeOpacity={0.8}
                            label={{
                                value: "75% Threshold",
                                position: "insideTopRight",
                                fill: "#ef4444",
                                fontSize: 11,
                                fontWeight: 500,
                            }}
                        />
                        <Area
                            type="monotone"
                            dataKey="pressure"
                            stroke={color}
                            strokeWidth={2}
                            fill="url(#pressureFill)"
                            dot={false}
                            activeDot={{
                                r: 4,
                                fill: color,
                                stroke: "#111318",
                                strokeWidth: 2,
                            }}
                        />
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    );
}

export type { DataPoint };
