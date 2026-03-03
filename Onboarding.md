# Aegis — Contributor Onboarding Guide
### What it is, how it works, and how we're building it

---

## The Problem We're Solving

If you've ever run a local AI model (like Llama, Mistral, or any other LLM) on your laptop, you've probably experienced one of these:

- Your computer freezes completely mid-generation
- Your browser and other apps become unresponsive
- In extreme cases, macOS kills processes to prevent a full crash

This happens because running AI models is extremely memory-intensive — specifically GPU memory (VRAM). The tool most developers use to run local models, **Ollama**, is great at inference but has no awareness of your system's available memory. It just loads a model and holds it in VRAM for 5 minutes after each use, even if you're done with it. If you fire off multiple requests quickly, or run a model that's too large, your machine runs out of VRAM and the OS panics.

**Aegis fixes this.** It sits between your apps and Ollama, acting as a traffic controller for AI inference.

---

## What Aegis Actually Does

Think of Aegis as a **smart queue manager and memory bodyguard** for local AI. Here's its job in plain English:

1. **Receives requests** from other apps that want to run AI inference (e.g. "summarise this document using llama3")
2. **Checks available memory** before doing anything — if there isn't enough VRAM, it holds the request in a queue instead of letting it crash the system
3. **Runs jobs one at a time** — only one AI inference happens at a time, eliminating VRAM contention entirely
4. **Forces the model out of memory** the instant a job finishes — rather than waiting 5 idle minutes, Aegis immediately evicts the model from VRAM so the next job can start cleanly
5. **Tracks everything in a database** — every job has a state (queued, running, completed, failed) and a result you can retrieve
6. **Shows you what's happening** via a live dashboard in your browser

---

## System Architecture (Plain English)

Aegis has three parts that talk to each other:

```
┌─────────────────┐     HTTP      ┌──────────────────────────┐     HTTP      ┌─────────┐
│   Client Apps   │ ──────────>   │   Aegis Backend Service  │ ──────────>   │ Ollama  │
│ (your scripts,  │               │   (FastAPI on port 8000)  │               │ (port   │
│  other tools)   │               │                          │               │  11434) │
└─────────────────┘               │  ┌────────────────────┐  │               └─────────┘
                                  │  │  Priority Queue    │  │
┌─────────────────┐   HTTP poll   │  │  (asyncio)         │  │
│  Aegis Dashboard│ <──────────>  │  ├────────────────────┤  │
│  (Next.js on    │               │  │  SQLite Database   │  │
│   port 3000)    │               │  ├────────────────────┤  │
└─────────────────┘               │  │  Hardware Monitor  │  │
                                  │  │  (VRAM telemetry)  │  │
                                  │  └────────────────────┘  │
                                  └──────────────────────────┘
```

### The Backend (Python / FastAPI)
The core of the system. It's a background service (like a daemon) that runs silently on your machine. It exposes an HTTP API so other applications can submit jobs and check results. Internally it runs a queue worker loop that processes one job at a time.

### The Hardware Monitor
Because Aegis runs on both Macs (Apple Silicon) and Linux (NVIDIA GPUs), it has a pluggable hardware layer. On a Mac, it talks to Apple's Metal GPU API to get accurate unified memory readings. On Linux/NVIDIA, it talks to the NVIDIA Management Library (NVML). This is abstracted behind a common interface so the rest of the code doesn't care which hardware it's running on.

### The Queue Engine
An in-memory priority queue (Python's `asyncio.PriorityQueue`). Jobs sit here waiting their turn. The worker loop dequeues one job at a time, checks that VRAM is available, acquires an exclusive inference lock, runs the job, evicts the model, then moves to the next job. Everything happens sequentially — this is the key design decision that prevents crashes.

### The Database (SQLite)
Every job is persisted to a local SQLite file. Jobs move through a strict state machine: `QUEUED → ALLOCATING → RUNNING → COMPLETED / FAILED`. Results and error messages are stored here. The dashboard reads from this DB. We use Write-Ahead Logging (WAL) mode so reads and writes don't block each other.

### The Dashboard (Next.js)
A local web app at `localhost:3000`. Read-only — you can't submit jobs from here. It polls the backend every 2 seconds and shows you: live VRAM usage, the job queue, which model is currently loaded, and throughput statistics. Built with Tailwind CSS and Shadcn UI components.

---

## The Job Lifecycle (Step by Step)

This is the most important thing to understand about Aegis:

```
1. Client app sends POST /v1/jobs/submit
        │
        ▼
2. Job created in DB with status: QUEUED
   Job added to asyncio.PriorityQueue
        │
        ▼
3. Queue worker picks it up
   Acquires inference_lock (asyncio.Lock)
        │
        ▼
4. VRAM check: is free memory ≥ minimum threshold?
   ├── NO  → re-queue the job, release lock, sleep 2s, retry
   └── YES → continue
        │
        ▼
5. Job status → ALLOCATING
   Job status → RUNNING
        │
        ▼
6. HTTP POST to Ollama /api/generate
   (waits for response, up to 120s timeout)
        │
        ▼
7. Response received
   Job status → COMPLETED (result saved) or FAILED (error saved)
        │
        ▼
8. Evict model from VRAM:
   POST to Ollama with {"model": "...", "keep_alive": 0}
   Verify response contains "done_reason": "unload"
        │
        ▼
9. Release inference_lock
   Worker moves to next job in queue
```

---

## Tech Stack Reference

| Layer | What | Why |
|---|---|---|
| Backend language | Python 3.10+ | asyncio for non-blocking I/O; great ecosystem for systems tooling |
| API framework | FastAPI + Uvicorn | Async, auto-generates OpenAPI docs, minimal boilerplate |
| Database | SQLite + SQLAlchemy (async) + aiosqlite | Zero-setup local DB; WAL mode handles concurrent reads/writes |
| GPU telemetry (Mac) | pyobjc-framework-Metal | Only way to get accurate unified memory data on Apple Silicon |
| GPU telemetry (NVIDIA) | pynvml | Direct bindings to NVIDIA's management library |
| System metrics | psutil | Cross-platform CPU/RAM data |
| HTTP client | httpx (async) | Used to call Ollama's API |
| Frontend | Next.js (App Router) | React-based, good for the polling data patterns we need |
| UI components | Shadcn UI + Tailwind CSS | Accessible, unstyled-by-default components; full design control |
| Charts | Recharts | Lightweight, React-native charting library |
| Service management | launchd (macOS) / systemd (Linux) | Makes Aegis start automatically on login/boot |

---

## What We Are NOT Building (V1 Scope)

To keep things focused, these are explicitly out of scope:

- User authentication or accounts
- Concurrent multi-model inference (one job at a time, always)
- Model downloading or management (use `ollama pull` in your terminal)
- A UI for submitting jobs (jobs come from other apps via the API)
- Any cloud or remote inference — this is 100% local
- Docker or containerisation (strips GPU access on macOS)
- Streaming inference responses

---

## Key Files You'll Work In

```
aegis/
├── backend/
│   ├── main.py                  # App startup, router mounting
│   ├── core/
│   │   ├── queue_engine.py      # THE most important file — the worker loop
│   │   ├── database.py          # DB setup, WAL config, session factory
│   │   └── ollama_client.py     # All Ollama HTTP calls (generate + evict)
│   ├── models/
│   │   ├── job.py               # Job database model / state machine
│   │   └── schemas.py           # Pydantic API request/response shapes
│   └── hardware/
│       ├── registry.py          # Picks the right hardware provider at startup
│       ├── apple_silicon.py     # Metal GPU queries
│       └── nvidia.py            # NVML queries
└── dashboard/
    ├── app/page.tsx             # Dashboard root, polling logic
    └── components/              # Chart, table, cards
```

---

## Environment Variables (Quick Reference)

All configurable via a `.env` file in the project root:

| Variable | Default | Meaning |
|---|---|---|
| `AEGIS_OLLAMA_URL` | `http://localhost:11434` | Where Ollama is running |
| `AEGIS_OLLAMA_TIMEOUT_SECONDS` | `120` | Max wait for an inference response |
| `AEGIS_VRAM_THRESHOLD` | `0.75` | Use max 75% of available GPU memory |
| `AEGIS_MIN_FREE_VRAM_BYTES` | `536870912` | Don't start a job unless 512MB+ is free |
| `AEGIS_JOB_RETENTION_HOURS` | `24` | Delete old completed jobs after 24h |
| `AEGIS_DB_PATH` | `~/.aegis/aegis.db` | Where the SQLite file lives |

---

## The One Tricky Thing: Apple Silicon Memory

This is worth understanding before touching any hardware code. Apple Silicon (M1/M2/M3/M4) uses **unified memory** — the CPU and GPU share the same physical RAM pool. This means there's no dedicated VRAM chip with a fixed size. The amount of memory the GPU can use is dynamic and reported by Apple's Metal API via `recommendedMaxWorkingSetSize()`.

The important consequence: **you cannot use standard system RAM tools (like `psutil`) to get GPU memory usage on a Mac.** psutil reports total system RAM, not the GPU's allocation. We use the Metal API for the memory ceiling and psutil only as a rough proxy for current pressure. This is documented as a known limitation.

---

## Running Locally (Once Set Up)

```bash
# Terminal 1: Start Ollama (must be running first)
ollama serve

# Terminal 2: Start Aegis backend
cd aegis/backend
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 3: Start dashboard
cd aegis/dashboard
npm run dev

# Dashboard available at: http://localhost:3000
# API docs available at:  http://localhost:8000/docs
```

---

## Good Starting Points

- To understand the core logic: read `queue_engine.py` first
- To understand the API surface: visit `localhost:8000/docs` once the backend is running
- To understand job states: read the `Job` model in `models/job.py`
- To understand hardware abstraction: read `hardware/registry.py` then `hardware/apple_silicon.py`
