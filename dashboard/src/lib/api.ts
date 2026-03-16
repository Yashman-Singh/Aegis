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
    batch_id?: string | null;
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

export interface ConcurrencyMetrics {
    max_concurrent_jobs: number;
    currently_running: number;
    active_reservations_bytes: number;
    vram_available_for_scheduling: number;
}

export interface MetricsResponse {
    hardware: HardwareMetrics;
    queue: QueueMetrics;
    loaded_model: string | null;
    loaded_models: string[];
    concurrency: ConcurrencyMetrics;
    warm_cache_active: boolean;
    warm_cache_model: string | null;
    warm_cache_queue_depth: number;
    throughput: ThroughputMetrics;
}

export interface MetricsV2Response {
    hardware: HardwareMetrics;
    queue: QueueMetrics;
    loaded_models: string[];
    concurrency: ConcurrencyMetrics;
    warm_cache_active: boolean;
    warm_cache_model: string | null;
    warm_cache_queue_depth: number;
    throughput: ThroughputMetrics;
}

export interface ModelRegistryEntry {
    model_name: string;
    p95_bytes: number;
    p95_gb: number;
    with_buffer_bytes: number;
    sample_count: number;
    source: string;
}

export interface ModelRegistryResponse {
    models: ModelRegistryEntry[];
}

export interface CancelQueuedResponse {
    cancelled_count: number;
}

// ---------------------------------------------------------------------------
// Fetch wrapper
// ---------------------------------------------------------------------------

export async function fetchMetrics(): Promise<MetricsResponse> {
    const res = await fetch(`${BASE_URL}/v1/metrics`);
    if (!res.ok) {
        throw new Error(`Failed to fetch metrics: ${res.status}`);
    }
    const payload = (await res.json()) as Partial<MetricsResponse>;
    return {
        loaded_model: payload.loaded_model ?? null,
        loaded_models: payload.loaded_models ?? (payload.loaded_model ? [payload.loaded_model] : []),
        concurrency: payload.concurrency ?? {
            max_concurrent_jobs: 1,
            currently_running: 0,
            active_reservations_bytes: 0,
            vram_available_for_scheduling: 0,
        },
        warm_cache_active: payload.warm_cache_active ?? false,
        warm_cache_model: payload.warm_cache_model ?? null,
        warm_cache_queue_depth: payload.warm_cache_queue_depth ?? 0,
        hardware: payload.hardware as HardwareMetrics,
        queue: payload.queue as QueueMetrics,
        throughput: payload.throughput as ThroughputMetrics,
    };
}

export async function fetchMetricsV2(): Promise<MetricsV2Response> {
    const res = await fetch(`${BASE_URL}/v2/metrics`);
    if (!res.ok) {
        throw new Error(`Failed to fetch v2 metrics: ${res.status}`);
    }
    return res.json();
}

export async function fetchModelRegistry(): Promise<ModelRegistryResponse> {
    const res = await fetch(`${BASE_URL}/v1/models/registry`);
    if (!res.ok) {
        throw new Error(`Failed to fetch model registry: ${res.status}`);
    }
    return res.json();
}

export async function cancelQueuedJobs(modelName?: string): Promise<CancelQueuedResponse> {
    const query = modelName ? `?model_name=${encodeURIComponent(modelName)}` : "";
    const res = await fetch(`${BASE_URL}/v1/jobs/cancel-queued${query}`, {
        method: "POST",
    });
    if (!res.ok) {
        throw new Error(`Failed to cancel queued jobs: ${res.status}`);
    }
    return res.json();
}
