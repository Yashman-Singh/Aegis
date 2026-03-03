/**
 * Typed fetch wrappers for all Aegis backend endpoints.
 * Base URL points to the backend running on port 8000.
 */

const BASE_URL = "http://127.0.0.1:8000";

// ---------------------------------------------------------------------------
// Types matching the backend Pydantic schemas
// ---------------------------------------------------------------------------

export interface HardwareMetrics {
    provider: string;
    vram_total_bytes: number;
    vram_used_bytes: number;
    vram_free_bytes: number;
    vram_threshold_bytes: number;
    vram_pressure_percent: number;
}

export interface QueueJobSummary {
    job_id: string;
    model_name: string;
    priority: number;
    status: string;
    created_at: string;
}

export interface QueueMetrics {
    depth: number;
    jobs: QueueJobSummary[];
}

export interface ThroughputMetrics {
    jobs_completed_total: number;
    jobs_failed_total: number;
    avg_latency_ms_last_100: number | null;
}

export interface MetricsResponse {
    hardware: HardwareMetrics;
    queue: QueueMetrics;
    loaded_model: string | null;
    throughput: ThroughputMetrics;
}

// ---------------------------------------------------------------------------
// Fetch wrapper
// ---------------------------------------------------------------------------

export async function fetchMetrics(): Promise<MetricsResponse> {
    const res = await fetch(`${BASE_URL}/v1/metrics`);
    if (!res.ok) {
        throw new Error(`Failed to fetch metrics: ${res.status}`);
    }
    return res.json();
}
