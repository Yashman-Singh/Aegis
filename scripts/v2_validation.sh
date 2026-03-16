#!/bin/bash
# =============================================================================
# Aegis V2 Validation Script
# =============================================================================
# Validates:
# - Backend health and V2 endpoints
# - Dashboard reachability
# - Job execution across pulled Ollama models
# - Warm-cache and concurrency metrics visibility
#
# Usage:
#   bash scripts/v2_validation.sh
#
# Prerequisites:
#   1) Ollama server running on 127.0.0.1:11434
#   2) Aegis backend running on 127.0.0.1:8000
#   3) Dashboard running on 127.0.0.1:3000 (optional but recommended)
# =============================================================================

API="${AEGIS_API_URL:-http://127.0.0.1:8000}"
OLLAMA_API="${OLLAMA_API_URL:-http://127.0.0.1:11434}"
DASHBOARD_URL="${AEGIS_DASHBOARD_URL:-http://127.0.0.1:3000}"

PASS=0
FAIL=0

print_header() {
  echo ""
  echo "========================================="
  echo "  AEGIS V2 VALIDATION"
  echo "========================================="
  echo ""
}

check_endpoint() {
  local url="$1"
  local label="$2"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  if [ "$code" = "200" ]; then
    echo "  [OK] $label ($code)"
    PASS=$((PASS + 1))
    return 0
  fi
  echo "  [FAIL] $label ($code)"
  FAIL=$((FAIL + 1))
  return 1
}

discover_models() {
  local models=()

  # First try `ollama list`.
  if command -v ollama >/dev/null 2>&1; then
    local list_output
    list_output=$(ollama list 2>/dev/null || true)
    if [ -n "$list_output" ]; then
      while IFS= read -r model; do
        [ -n "$model" ] && models+=("$model")
      done < <(echo "$list_output" | awk 'NR>1 {print $1}')
    fi
  fi

  # Fallback: parse local manifests (works even when `ollama list` crashes).
  if [ ${#models[@]} -eq 0 ] && [ -d "$HOME/.ollama/models/manifests/registry.ollama.ai/library" ]; then
    while IFS= read -r path; do
      rel="${path##*/library/}"
      model="${rel/\//:}"
      [ -n "$model" ] && models+=("$model")
    done < <(find "$HOME/.ollama/models/manifests/registry.ollama.ai/library" -type f 2>/dev/null)
  fi

  # Deduplicate while preserving order.
  local deduped=()
  local seen="|"
  for model in "${models[@]}"; do
    if [[ "$seen" != *"|$model|"* ]]; then
      deduped+=("$model")
      seen="${seen}${model}|"
    fi
  done

  printf '%s\n' "${deduped[@]}"
}

submit_job() {
  local model="$1"
  local priority="$2"
  local prompt="$3"
  local label="$4"

  echo -n "  [$label] submit model=$model priority=$priority ... " >&2
  local response
  response=$(curl -sS -X POST "$API/v1/jobs/submit" \
    -H "Content-Type: application/json" \
    -d "{\"model_name\":\"$model\",\"priority\":$priority,\"payload\":{\"prompt\":\"$prompt\",\"stream\":false}}" || true)

  local job_id
  job_id=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('job_id',''))" 2>/dev/null)
  if [ -z "$job_id" ]; then
    echo "FAILED ($response)" >&2
    FAIL=$((FAIL + 1))
    return 1
  fi

  echo "queued ($job_id)" >&2
  echo "$job_id"
  return 0
}

wait_for_job() {
  local job_id="$1"
  local label="$2"
  local timeout=240
  local elapsed=0

  while [ $elapsed -lt $timeout ]; do
    local payload
    payload=$(curl -s "$API/v1/jobs/$job_id")
    local status
    status=$(echo "$payload" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null)

    if [ "$status" = "COMPLETED" ]; then
      local latency
      latency=$(echo "$payload" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('latency_ms',0):.0f}ms\")" 2>/dev/null)
      echo "  [$label] $job_id -> COMPLETED ($latency)"
      PASS=$((PASS + 1))
      return 0
    fi

    if [ "$status" = "FAILED" ]; then
      local error_msg
      error_msg=$(echo "$payload" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error_message','unknown'))" 2>/dev/null)
      echo "  [$label] $job_id -> FAILED ($error_msg)"
      FAIL=$((FAIL + 1))
      return 1
    fi

    if [ -z "$status" ] && echo "$payload" | grep -q "Job not found"; then
      echo "  [$label] $job_id -> INVALID JOB ID (backend says not found)"
      FAIL=$((FAIL + 1))
      return 1
    fi

    if [ $((elapsed % 10)) -eq 0 ]; then
      echo "  [$label] $job_id -> waiting (${elapsed}s)"
    fi

    sleep 2
    elapsed=$((elapsed + 2))
  done

  echo "  [$label] $job_id -> TIMEOUT after ${timeout}s"
  FAIL=$((FAIL + 1))
  return 1
}

print_metrics_snapshot() {
  echo ""
  echo "--- Metrics Snapshot ---"
  local payload
  payload=$(curl -sS "$API/v1/metrics" || true)
  if [ -z "$payload" ]; then
    echo "  (metrics unavailable)"
    echo "------------------------"
    return
  fi
  echo "$payload" | python3 -c '
import sys, json
try:
    d=json.load(sys.stdin)
except Exception:
    print("  (metrics payload not JSON)")
    raise SystemExit(0)
h=d.get("hardware", {})
t=d.get("throughput", {})
c=d.get("concurrency", {})
print("  loaded_model:            ", d.get("loaded_model"))
print("  loaded_models:           ", d.get("loaded_models"))
print("  warm_cache_active:       ", d.get("warm_cache_active"))
print("  warm_cache_model:        ", d.get("warm_cache_model"))
print("  warm_cache_queue_depth:  ", d.get("warm_cache_queue_depth"))
print("  max_concurrent_jobs:     ", c.get("max_concurrent_jobs"))
print("  currently_running:       ", c.get("currently_running"))
print("  active_reservations:     ", c.get("active_reservations_bytes"))
print("  vram_pressure_percent:   ", h.get("vram_pressure_percent"))
print("  completed/failed:        ", t.get("jobs_completed_total"), "/", t.get("jobs_failed_total"))
'
  echo "------------------------"
}

get_max_concurrent_jobs() {
  local payload
  payload=$(curl -sS "$API/v1/metrics" || true)
  if [ -z "$payload" ]; then
    echo "1"
    return
  fi
  echo "$payload" | python3 -c '
import sys, json
try:
    d=json.load(sys.stdin)
except Exception:
    print(1)
    raise SystemExit(0)
print(int(d.get("concurrency", {}).get("max_concurrent_jobs", 1)))
'
}

get_schedulable_bytes() {
  local payload
  payload=$(curl -sS "$API/v1/metrics" || true)
  if [ -z "$payload" ]; then
    echo "0"
    return
  fi
  echo "$payload" | python3 -c '
import sys, json
try:
    d=json.load(sys.stdin)
except Exception:
    print(0)
    raise SystemExit(0)
print(int(d.get("concurrency", {}).get("vram_available_for_scheduling", 0)))
'
}

get_model_with_buffer_bytes() {
  local model="$1"
  local payload
  payload=$(curl -sS "$API/v1/models/registry" || true)
  if [ -z "$payload" ]; then
    echo "0"
    return
  fi
  echo "$payload" | python3 -c "
import sys, json
target = \"$model\"
try:
    d = json.load(sys.stdin)
except Exception:
    print(0)
    raise SystemExit(0)
for row in d.get('models', []):
    name = str(row.get('model_name', ''))
    if target == name or target.startswith(name):
        print(int(row.get('with_buffer_bytes', 0)))
        raise SystemExit(0)
print(0)
"
}

wait_for_running_at_least() {
  local target="$1"
  local timeout="${2:-45}"
  local elapsed=0

  while [ "$elapsed" -lt "$timeout" ]; do
    local payload running
    payload=$(curl -sS "$API/v1/metrics" || true)
    running=$(echo "$payload" | python3 -c '
import sys, json
try:
    d=json.load(sys.stdin)
except Exception:
    print(0)
    raise SystemExit(0)
print(int(d.get("concurrency", {}).get("currently_running", 0)))
')

    if [ "$running" -ge "$target" ]; then
      echo "  [OK] Observed concurrent running jobs: $running (target >= $target)"
      PASS=$((PASS + 1))
      return 0
    fi

    if [ $((elapsed % 5)) -eq 0 ]; then
      echo "  waiting for concurrency signal... running=$running elapsed=${elapsed}s"
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  echo "  [FAIL] Did not observe currently_running >= $target within ${timeout}s"
  FAIL=$((FAIL + 1))
  return 1
}

print_header

echo "1) Checking required endpoints..."
backend_ok=1
ollama_ok=1
check_endpoint "$API/v1/metrics" "Backend /v1/metrics" || backend_ok=0
check_endpoint "$API/v2/metrics" "Backend /v2/metrics" || backend_ok=0
check_endpoint "$API/v1/models/registry" "Backend /v1/models/registry" || backend_ok=0
check_endpoint "$OLLAMA_API/api/tags" "Ollama /api/tags" || ollama_ok=0

echo ""
echo "2) Checking dashboard (frontend)..."
if check_endpoint "$DASHBOARD_URL" "Dashboard /"; then
  echo "  Open $DASHBOARD_URL and watch: Active Models, Warm Cache badge, Concurrency, Model Registry."
fi

if [ "$backend_ok" -ne 1 ] || [ "$ollama_ok" -ne 1 ]; then
  echo ""
  echo "Backend or Ollama is not reachable. Fix connectivity first, then rerun:"
  echo "  - Ollama:  ollama serve"
  echo "  - Backend: cd backend && PYTHONPATH=\"\$PWD/..\" uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000"
  exit 1
fi

echo ""
echo "3) Detecting pulled models..."
MODELS=()
while IFS= read -r model; do
  [ -n "$model" ] && MODELS+=("$model")
done < <(discover_models)
if [ ${#MODELS[@]} -eq 0 ]; then
  echo "  [FAIL] No pulled models detected."
  echo "  Pull at least one model, e.g.: ollama pull llama3.2:1b"
  exit 1
fi

echo "  Found ${#MODELS[@]} model(s):"
for m in "${MODELS[@]}"; do
  echo "   - $m"
done
PASS=$((PASS + 1))

PRIMARY="${MODELS[0]}"
SECONDARY="$PRIMARY"
if [ ${#MODELS[@]} -ge 2 ]; then
  SECONDARY="${MODELS[1]}"
fi

MAX_CONCURRENT=$(get_max_concurrent_jobs)
echo "  Runtime max_concurrent_jobs from backend: $MAX_CONCURRENT"

echo ""
if [ "$MAX_CONCURRENT" -gt 1 ]; then
  echo "4) Running explicit concurrency test (max_concurrent=$MAX_CONCURRENT)..."
  SCHEDULABLE=$(get_schedulable_bytes)
  echo "  Current schedulable VRAM: $SCHEDULABLE bytes"

  CANDIDATES=()
  for model in "${MODELS[@]}"; do
    estimate=$(get_model_with_buffer_bytes "$model")
    if [ "$estimate" -gt 0 ] && [ "$estimate" -le "$SCHEDULABLE" ]; then
      CANDIDATES+=("$model")
    else
      echo "  [skip] $model appears unschedulable right now (estimate=${estimate}B)"
    fi
  done

  if [ ${#CANDIDATES[@]} -eq 0 ]; then
    echo "  [WARN] No schedulable models detected from registry; falling back to detected model list."
    CANDIDATES=("${MODELS[@]}")
  fi

  CONC_IDS=()
  submit_count=$((MAX_CONCURRENT + 2))
  if [ "$submit_count" -gt 8 ]; then
    submit_count=8
  fi

  for i in $(seq 1 "$submit_count"); do
    idx=$(( (i - 1) % ${#CANDIDATES[@]} ))
    model="${CANDIDATES[$idx]}"
    if cid=$(submit_job "$model" 2 "Return exactly: concurrent-$i" "C$i"); then
      CONC_IDS+=("$cid")
    fi
  done

  wait_for_running_at_least "$MAX_CONCURRENT" 45 || true
  for i in "${!CONC_IDS[@]}"; do
    wait_for_job "${CONC_IDS[$i]}" "C$((i+1))" || true
  done
  print_metrics_snapshot

  echo ""
  echo "5) Warm-cache sequence skipped (disabled when max_concurrent_jobs > 1)."
else
  echo "4) Running warm-cache style sequence on $PRIMARY..."
  if J1=$(submit_job "$PRIMARY" 5 "Return exactly: warm-cache-1" "W1"); then
    wait_for_job "$J1" "W1" || true
  fi
  if J2=$(submit_job "$PRIMARY" 5 "Return exactly: warm-cache-2" "W2"); then
    wait_for_job "$J2" "W2" || true
  fi
  if J3=$(submit_job "$PRIMARY" 5 "Return exactly: warm-cache-3" "W3"); then
    wait_for_job "$J3" "W3" || true
  fi
  print_metrics_snapshot

  echo ""
  echo "5) Running mixed-model queue test ($PRIMARY, $SECONDARY, $PRIMARY)..."
  if M1=$(submit_job "$PRIMARY" 4 "Return exactly: mixed-1" "M1"); then
    wait_for_job "$M1" "M1" || true
  fi
  if M2=$(submit_job "$SECONDARY" 4 "Return exactly: mixed-2" "M2"); then
    wait_for_job "$M2" "M2" || true
  fi
  if M3=$(submit_job "$PRIMARY" 4 "Return exactly: mixed-3" "M3"); then
    wait_for_job "$M3" "M3" || true
  fi
  print_metrics_snapshot
fi

echo ""
echo "6) Running burst test (up to 8 jobs across detected models)..."
JOB_IDS=()
BURST_MODELS=("${MODELS[@]}")
if [ "$MAX_CONCURRENT" -gt 1 ] && [ ${#CANDIDATES[@]} -gt 0 ]; then
  BURST_MODELS=("${CANDIDATES[@]}")
fi
for i in {1..8}; do
  idx=$(( (i - 1) % ${#BURST_MODELS[@]} ))
  model="${BURST_MODELS[$idx]}"
  prio=$(( (i % 5) + 1 ))
  jid=$(submit_job "$model" "$prio" "Say: burst-$i" "B$i") || true
  [ -n "$jid" ] && JOB_IDS+=("$jid")
done

for i in "${!JOB_IDS[@]}"; do
  wait_for_job "${JOB_IDS[$i]}" "B$((i+1))" || true
done
print_metrics_snapshot

echo ""
echo "7) Final summary"
echo "========================================="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "  Total:  $((PASS + FAIL))"
echo "========================================="
echo ""

if [ "$FAIL" -eq 0 ]; then
  echo "All checks passed."
else
  echo "Some checks failed. Scroll up for failing step details."
fi
