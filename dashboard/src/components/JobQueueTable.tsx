"use client";

import { Badge } from "@/components/ui/badge";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { QueueJobSummary } from "@/lib/api";

interface JobQueueTableProps {
    jobs: QueueJobSummary[];
}

const STATUS_STYLES: Record<string, string> = {
    QUEUED: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    ALLOCATING: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
    RUNNING: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
    COMPLETED: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    FAILED: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

function truncateId(id: string): string {
    return id.slice(0, 8) + "…";
}

function formatElapsed(createdAt: string): string {
    const diffMs = Date.now() - new Date(createdAt).getTime();
    const secs = Math.max(0, Math.floor(diffMs / 1000));
    if (secs < 60) return `${secs}s`;
    const mins = Math.floor(secs / 60);
    const remSecs = secs % 60;
    return `${mins}m ${remSecs}s`;
}

export function JobQueueTable({ jobs }: JobQueueTableProps) {
    return (
        <Card className="col-span-full">
            <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                    Job Queue
                </CardTitle>
            </CardHeader>
            <CardContent>
                {jobs.length === 0 ? (
                    <p className="py-6 text-center text-sm text-muted-foreground">
                        No active jobs
                    </p>
                ) : (
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Job ID</TableHead>
                                <TableHead>Model</TableHead>
                                <TableHead>Priority</TableHead>
                                <TableHead>Status</TableHead>
                                <TableHead>Submitted</TableHead>
                                <TableHead>Elapsed</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {jobs.map((job) => (
                                <TableRow key={job.job_id}>
                                    <TableCell className="font-mono text-xs">
                                        {truncateId(job.job_id)}
                                    </TableCell>
                                    <TableCell className="font-medium">
                                        {job.model_name}
                                    </TableCell>
                                    <TableCell>{job.priority}</TableCell>
                                    <TableCell>
                                        <Badge
                                            variant="outline"
                                            className={STATUS_STYLES[job.status] ?? ""}
                                        >
                                            {job.status}
                                        </Badge>
                                    </TableCell>
                                    <TableCell className="text-xs text-muted-foreground">
                                        {new Date(job.created_at).toLocaleTimeString()}
                                    </TableCell>
                                    <TableCell className="text-xs text-muted-foreground">
                                        {formatElapsed(job.created_at)}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </CardContent>
        </Card>
    );
}
