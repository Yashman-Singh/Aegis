# Aegis — AI System Rules

## Project Purpose
Aegis is a local OS-level background service that acts as a priority queue, API gateway, and VRAM resource manager for local AI inference via Ollama. It prevents OOM crashes by enforcing sequential job execution and forceful model eviction after each job completes.

## Critical Architecture Decisions (Do Not Change Without Discussion)
- Jobs execute ONE AT A TIME via a single `asyncio.Lock`. Concurrent inference is out of scope for V1.
- Model eviction MUST happen INSIDE the inference lock, before the lock is released. Releasing the lock before eviction causes a race condition where the next job reads stale VRAM.
- Never sleep inside the inference lock. The `vram_sufficient` flag pattern is used to handle re-queuing outside the lock context.
- SQLite MUST be initialized in WAL mode with `timeout=5.0`. Never change this.
- Never use `psutil` to measure GPU memory on Apple Silicon. Use `pyobjc-framework-Metal` only.
- Docker/containerization is prohibited — it strips Metal GPU access on macOS.

## Build Order (Follow This Exactly)
Build in this sequence. Do not jump ahead.
1. `hardware/` — registry, apple_silicon provider, nvidia provider, cpu_fallback provider
2. `models/` — Job ORM model and Pydantic schemas
3. `core/database.py` — SQLAlchemy async engine, WAL init, session factory
4. `core/ollama_client.py` — generate() and evict() methods
5. `core/queue_engine.py` — worker loop with the exact pseudocode from the spec
6. `backend/main.py` — FastAPI app, lifespan startup, router mounting
7. `dashboard/` — frontend components in this order: api.ts fetchers, then components

## Key Conventions
- Python: use async/await throughout. No sync DB calls.
- All DB access goes through SQLAlchemy async sessions — never raw SQL strings.
- The Ollama eviction call MUST include the "model" field. An empty payload silently fails.
- Validate eviction by asserting response contains "done_reason": "unload".
- Environment variables are loaded from `.env`. Never hardcode URLs, ports, or thresholds.
- Frontend polling interval: 2000ms. Never poll faster than this.
- Constantly update STATUS.md with the latest status of the project. Carefully document with reasoning any deviations from the master specification.