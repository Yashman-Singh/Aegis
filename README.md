# Aegis

A local inference runtime that sits between your apps and [Ollama](https://ollama.com). It manages GPU memory, queues inference jobs, and makes sure your machine doesn't freeze when running AI models locally.

## The problem

Ollama is great for running local LLMs, but it has a blind spot: after each inference, it holds the model in GPU memory for 5 minutes with no awareness of how much VRAM is actually available. On Apple Silicon (where CPU and GPU share the same memory pool), this is especially bad. Fire off a couple of requests in a row, or load a model that's slightly too large, and macOS starts killing processes to survive.

There's no built-in way to say "check memory first" or "evict the model when you're done." Aegis adds that layer.

## What it does

Aegis runs as a background service on your machine. Other applications send inference requests to its API instead of hitting Ollama directly. For each request, Aegis:

1. Validates the request and adds it to a priority queue
2. Checks available GPU memory before touching Ollama
3. Acquires an exclusive inference lock (only one job runs at a time)
4. Dispatches the request to Ollama
5. Evicts the model from VRAM immediately after the job completes
6. Releases the lock so the next job can start clean

The sequential execution is intentional — it's the simplest way to guarantee that two models never compete for the same memory. The eviction-inside-lock pattern prevents a race condition where the next job reads stale VRAM state before the previous model has actually been unloaded.

## Architecture

```
Client apps  ──HTTP──▶  Aegis backend (FastAPI, port 8000)  ──HTTP──▶  Ollama (port 11434)
                              │
                              ├── Priority queue (asyncio.PriorityQueue)
                              ├── Inference lock (asyncio.Lock)
                              ├── SQLite database (WAL mode, async)
                              └── Hardware monitor (Metal / NVML / psutil fallback)

Dashboard (Next.js, port 3000)  ──polls every 2s──▶  GET /v1/metrics
```

- **Backend**: Python 3.11, FastAPI, fully async. Handles request ingestion, job lifecycle, VRAM checks, Ollama dispatch, and forced model eviction. Jobs are persisted to SQLite via async SQLAlchemy.
- **Hardware layer**: Pluggable provider pattern. Apple Silicon uses Metal's `recommendedMaxWorkingSetSize()` for VRAM data. NVIDIA uses NVML. CPU-only systems fall back to psutil. The rest of the codebase is hardware-agnostic.
- **Queue engine**: `asyncio.PriorityQueue` with a worker loop. Priority ties are broken by submission time (FIFO). Jobs move through a strict state machine: `QUEUED → ALLOCATING → RUNNING → COMPLETED / FAILED`.
- **Dashboard**: Next.js app that polls the metrics endpoint every 2 seconds. Shows VRAM pressure over time, the job queue, which model is loaded, and throughput stats. Read-only — no job submission from the UI.

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** (Python package manager)
- **Node.js 18+** and npm
- **[Ollama](https://ollama.com)** installed and working (`ollama run llama3.2:3b` should work)

## Setup

```bash
# Clone the repo
git clone https://github.com/<your-username>/aegis.git
cd aegis

# Install backend dependencies
cd backend
uv sync
cd ..

# Install dashboard dependencies
cd dashboard
npm install
cd ..

# Create your .env file
cp .env.example .env   # or create it manually — see Configuration below
```

## Running

You need three terminals. Start Ollama first.

```bash
# Terminal 1 — Ollama
ollama serve

# Terminal 2 — Aegis backend
cd backend && PYTHONPATH="$PWD/.." uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Terminal 3 — Dashboard
cd dashboard && npm run dev
```

> The `PYTHONPATH` override is needed because `uv` runs from `backend/` (where `pyproject.toml` lives) but the code uses `backend.*` import paths that resolve relative to the project root.

Once everything is up:
- **Dashboard**: http://localhost:3000
- **API docs**: http://localhost:8000/docs

## Usage

Submit a job:

```bash
curl -X POST http://localhost:8000/v1/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "llama3.2:3b",
    "priority": 1,
    "payload": {
      "prompt": "Explain what a mutex is in two sentences.",
      "stream": false
    }
  }'
```

Response:

```json
{
  "job_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "QUEUED"
}
```

Check the result:

```bash
curl http://localhost:8000/v1/jobs/<job_id>
```

Get system metrics (what the dashboard polls):

```bash
curl http://localhost:8000/v1/metrics
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/jobs/submit` | Submit an inference job. Priority 1–10 (lower = higher). |
| `GET` | `/v1/jobs/{job_id}` | Get job status, result, timing, and error info. |
| `GET` | `/v1/metrics` | VRAM state, queue depth, loaded model, throughput stats. |

Full interactive docs at `/docs` when the backend is running.

## Configuration

All via `.env` in the project root:

| Variable | Default | Description |
|----------|---------|-------------|
| `AEGIS_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `AEGIS_OLLAMA_TIMEOUT_SECONDS` | `120` | Max wait for an inference response |
| `AEGIS_VRAM_THRESHOLD` | `0.75` | Fraction of GPU memory treated as allocatable (safety margin) |
| `AEGIS_MIN_FREE_VRAM_BYTES` | `536870912` | Minimum free VRAM (bytes) before a job can start. Default: 512MB |
| `AEGIS_JOB_RETENTION_HOURS` | `24` | Auto-delete completed/failed jobs after this many hours |
| `AEGIS_DB_PATH` | `~/.aegis/aegis.db` | SQLite database location |

## Tech stack

| Layer | Technologies |
|-------|-------------|
| Backend | Python 3.11, FastAPI, Uvicorn, async SQLAlchemy, aiosqlite, httpx |
| GPU telemetry | pyobjc-framework-Metal (Apple Silicon), pynvml (NVIDIA), psutil (fallback) |
| Frontend | Next.js (App Router), Tailwind CSS, Shadcn UI, Recharts |
| Database | SQLite with WAL mode |
| Service mgmt | launchd (macOS), systemd (Linux) |

## Project structure

```
aegis/
├── backend/
│   ├── main.py                    # FastAPI app, lifespan, route mounting
│   ├── core/
│   │   ├── queue_engine.py        # Worker loop, inference lock, dispatch + eviction
│   │   ├── database.py            # Async SQLAlchemy engine, WAL init
│   │   └── ollama_client.py       # Ollama HTTP client (generate + evict)
│   ├── models/
│   │   ├── job.py                 # Job ORM model
│   │   └── schemas.py             # Pydantic request/response schemas
│   └── hardware/
│       ├── registry.py            # Provider detection and loading
│       ├── apple_silicon.py       # Metal API provider
│       ├── nvidia.py              # NVML provider
│       └── cpu_fallback.py        # psutil fallback
├── dashboard/
│   ├── src/app/page.tsx           # Dashboard root, polling orchestration
│   └── src/components/
│       ├── MemoryPressureChart.tsx # VRAM pressure time-series
│       ├── JobQueueTable.tsx       # Active + recent jobs
│       ├── LoadedModelCard.tsx     # Current model status
│       └── ThroughputStats.tsx     # Latency and completion stats
├── launchd/                       # macOS service config
├── systemd/                       # Linux service config
├── scripts/                       # Stress tests and comparison scripts
└── .env                           # Local config (not committed)
```

## Known limitations

- **Apple Silicon VRAM is approximate.** Metal reports a recommended working set size, not a real-time allocation count. Current usage is estimated from system memory pressure. This is a known constraint of the Metal API.
- **One job at a time.** Sequential execution is a deliberate V1 design choice. Parallel inference is planned for V2.
- **Ollama must be running independently.** Aegis doesn't start or manage the Ollama process.
- **Polling only.** No webhooks or WebSocket push — clients poll for results.


