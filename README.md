# Aegis

A local inference runtime that sits between your apps and [Ollama](https://ollama.com). Aegis manages queueing, VRAM-aware scheduling, model lifecycle, and runtime visibility for local model inference.

## V2 highlights

- Configurable concurrent workers via `AEGIS_MAX_CONCURRENT_JOBS`
- Atomic VRAM reservations to avoid scheduling overcommit
- Per-model lifecycle locks and refcounted load/evict behavior
- Warm-cache batching (single-worker mode only)
- Profiling-based model registry refinement (single-worker mode only)
- Additive DB migrations for V2 columns + `model_vram_profiles`
- Versioned metrics contracts: `/v1/metrics` and `/v2/metrics`
- Queue management endpoint: `POST /v1/jobs/cancel-queued`
- Dashboard cards for active models, concurrency, warm-cache, and model registry

## Architecture

```text
Client Apps ──HTTP──▶ Aegis Backend (FastAPI:8000) ──HTTP──▶ Ollama (11434)
                             │
                             ├── Priority queue + worker tasks
                             ├── VRAM reservation + model lock state
                             ├── SQLite (jobs + model_vram_profiles)
                             └── Hardware monitor (Apple/NVIDIA/CPU fallback)

Dashboard (Next.js:3000) ──polls──▶ /v1/metrics + /v1/models/registry
```

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- [Ollama](https://ollama.com)

## Setup

```bash
git clone https://github.com/<your-username>/aegis.git
cd aegis

cd backend
uv sync
cd ..

cd dashboard
npm install
cd ..
```

Create `.env` in the project root (example values below).

## Running

Start each service in a separate terminal.

```bash
# Terminal 1
ollama serve

# Terminal 2
cd backend && PYTHONPATH="$PWD/.." uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Terminal 3
cd dashboard && npm run dev
```

- Dashboard: `http://127.0.0.1:3000`
- API docs: `http://127.0.0.1:8000/docs`

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/v1/jobs/submit` | Submit inference job (`priority` 1-10, lower is higher priority). |
| `GET` | `/v1/jobs/{job_id}` | Poll job status/result. |
| `POST` | `/v1/jobs/cancel-queued` | Cancel all queued jobs (or only one model with `?model_name=...`). |
| `GET` | `/v1/metrics` | Backward-compatible metrics (includes `loaded_model` + `loaded_models`). |
| `GET` | `/v2/metrics` | V2 metrics contract (`loaded_models` only). |
| `GET` | `/v1/models/registry` | Model VRAM registry view (p95, buffered estimate, sample count, source). |

## Example request

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "llama3.2:3b",
    "priority": 3,
    "payload": {
      "prompt": "Explain mutexes in two sentences.",
      "stream": false
    }
  }'
```

## Configuration

All values are read from `.env` at backend startup.

| Variable | Default | Notes |
|---|---|---|
| `AEGIS_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `AEGIS_OLLAMA_TIMEOUT_SECONDS` | `120` | Ollama inference timeout |
| `AEGIS_DB_PATH` | `~/.aegis/aegis.db` | SQLite DB path |
| `AEGIS_JOB_RETENTION_HOURS` | `24` | Cleanup window for terminal jobs |
| `AEGIS_MIN_FREE_VRAM_BYTES` | `536870912` | Additional minimum free VRAM gate |
| `AEGIS_MAX_CONCURRENT_JOBS` | `1` | Worker count + semaphore slots |
| `AEGIS_CONCURRENT_VRAM_BUFFER` | `0.20` | Buffer multiplier for model estimates |
| `AEGIS_EMERGENCY_VRAM_FLOOR_BYTES` | `1073741824` | Reserved VRAM floor during scheduling |
| `AEGIS_WARM_CACHE_ENABLED` | `true` | Warm-cache batching toggle |
| `AEGIS_WARM_CACHE_MAX_DRAIN` | `10` | Max same-model queue drain per batch |
| `AEGIS_PROFILE_VRAM` | `true` | Per-job VRAM profiling toggle |
| `AEGIS_PROFILE_SAMPLE_INTERVAL_MS` | `500` | Profiling sample cadence |
| `AEGIS_MODEL_REGISTRY_PATH` | `~/.aegis/model_registry.json` | Registry cache/export path |
| `AEGIS_FAIL_NONTERMINAL_ON_STARTUP` | `false` | If true, startup marks stale non-terminal jobs as failed |

### Policy rules

- If `AEGIS_MAX_CONCURRENT_JOBS > 1`, warm-cache is auto-disabled even if enabled in env.
- If `AEGIS_MAX_CONCURRENT_JOBS > 1`, profiling is auto-disabled even if enabled in env.

## Validation and tests

### Backend tests

```bash
cd backend
PYTHONPATH="$PWD/.." uv run pytest
```

### End-to-end validation (concurrent + dashboard contracts)

```bash
bash scripts/v2_validation.sh
```

### Non-concurrent profiling run (registry sample/p95 updates)

Use only when backend is running with `AEGIS_MAX_CONCURRENT_JOBS=1`.

```bash
bash scripts/v2_profile_run.sh
```

## Notes

- Queue rows persist in SQLite across restarts. Use `POST /v1/jobs/cancel-queued` (or the dashboard button) to clear queued jobs.
- `/v1/metrics` keeps legacy compatibility while exposing V2 fields additively.
- `/v2/metrics` is the forward-only contract for new consumers.
