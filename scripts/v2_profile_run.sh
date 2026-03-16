#!/bin/bash
# =============================================================================
# Aegis V2 Non-Concurrent Profiling Runner
# =============================================================================
# Purpose:
# - Run sequential jobs in non-concurrent mode (max_concurrent_jobs=1)
# - Verify model registry sample_count and p95 values update
#
# Usage:
#   bash scripts/v2_profile_run.sh
#
# Optional env vars:
#   AEGIS_API_URL=http://127.0.0.1:8000
#   OLLAMA_API_URL=http://127.0.0.1:11434
#   JOBS_PER_MODEL=22
#   MODELS_TO_PROFILE=2
# =============================================================================

set -u

API="${AEGIS_API_URL:-http://127.0.0.1:8000}"
OLLAMA_API="${OLLAMA_API_URL:-http://127.0.0.1:11434}"
JOBS_PER_MODEL="${JOBS_PER_MODEL:-25}"
MODELS_TO_PROFILE="${MODELS_TO_PROFILE:-3}"

PASS=0
FAIL=0

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

  if command -v ollama >/dev/null 2>&1; then
    local list_output
    list_output=$(ollama list 2>/dev/null || true)
    if [ -n "$list_output" ]; then
      while IFS= read -r model; do
        [ -n "$model" ] && models+=("$model")
      done < <(echo "$list_output" | awk 'NR>1 {print $1}')
    fi
  fi

  if [ ${#models[@]} -eq 0 ] && [ -d "$HOME/.ollama/models/manifests/registry.ollama.ai/library" ]; then
    while IFS= read -r path; do
      rel="${path##*/library/}"
      model="${rel/\//:}"
      [ -n "$model" ] && models+=("$model")
    done < <(find "$HOME/.ollama/models/manifests/registry.ollama.ai/library" -type f 2>/dev/null)
  fi

  # Deduplicate
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
  local prompt="$2"
  local label="$3"

  echo -n "  [$label] submit model=$model ... " >&2
  local response
  response=$(curl -sS -X POST "$API/v1/jobs/submit" \
    -H "Content-Type: application/json" \
    -d "{\"model_name\":\"$model\",\"priority\":5,\"payload\":{\"prompt\":\"$prompt\",\"stream\":false}}" || true)

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
    local payload status
    payload=$(curl -sS "$API/v1/jobs/$job_id" || true)
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

echo ""
echo "========================================="
echo "  AEGIS V2 NON-CONCURRENT PROFILING"
echo "========================================="
echo ""

echo "1) Endpoint checks..."
backend_ok=1
check_endpoint "$API/v1/metrics" "Backend /v1/metrics" || backend_ok=0
check_endpoint "$API/v1/models/registry" "Backend /v1/models/registry" || backend_ok=0
check_endpoint "$OLLAMA_API/api/tags" "Ollama /api/tags" || backend_ok=0
if [ "$backend_ok" -ne 1 ]; then
  echo "Backend/Ollama unavailable. Start services first."
  exit 1
fi

echo ""
echo "2) Verify non-concurrent mode..."
MAX_CONCURRENT=$(curl -s "$API/v1/metrics" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(int(d.get("concurrency",{}).get("max_concurrent_jobs",1)))')
if [ "$MAX_CONCURRENT" -ne 1 ]; then
  echo "  [FAIL] max_concurrent_jobs=$MAX_CONCURRENT (expected 1 for profiling)."
  echo "  Set AEGIS_MAX_CONCURRENT_JOBS=1 and restart backend."
  exit 1
fi
echo "  [OK] max_concurrent_jobs=1"
PASS=$((PASS + 1))

echo ""
echo "3) Discover pulled models..."
PULLED=()
while IFS= read -r model; do
  [ -n "$model" ] && PULLED+=("$model")
done < <(discover_models)

if [ ${#PULLED[@]} -eq 0 ]; then
  echo "  [FAIL] No pulled models found."
  exit 1
fi

echo "  Pulled models:"
for m in "${PULLED[@]}"; do
  echo "   - $m"
done

# choose smallest MODELS_TO_PROFILE pulled models by with_buffer estimate from registry
SELECTED=()
while IFS= read -r m; do
  [ -n "$m" ] && SELECTED+=("$m")
done < <(
  python3 - <<PY
import json, sys, subprocess
pulled = json.loads("""$(printf '%s\n' "${PULLED[@]}" | python3 -c 'import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')""")
payload = subprocess.check_output(["curl","-s","$API/v1/models/registry"], text=True)
data = json.loads(payload)
rows = data.get("models", [])
def estimate(model):
    for r in rows:
        n = r.get("model_name","")
        if model == n or model.startswith(n):
            return int(r.get("with_buffer_bytes", 10**18))
    return 10**18
pulled_sorted = sorted(pulled, key=estimate)
for model in pulled_sorted[:int("$MODELS_TO_PROFILE")]:
    print(model)
PY
)

echo "  Selected for profiling (${#SELECTED[@]}):"
for m in "${SELECTED[@]}"; do
  echo "   - $m"
done
PASS=$((PASS + 1))

echo ""
echo "4) Registry BEFORE..."
BEFORE_JSON=$(curl -s "$API/v1/models/registry")
echo "$BEFORE_JSON" | python3 -c '
import sys, json
d=json.load(sys.stdin)
print("  model_name | sample_count | p95_gb")
for r in d.get("models", []):
    print(f"  {r.get('model_name')} | {r.get('sample_count')} | {r.get('p95_gb')}")
'

echo ""
echo "5) Running ${JOBS_PER_MODEL} sequential jobs per selected model..."
for model in "${SELECTED[@]}"; do
  echo "  -> model: $model"
  for i in $(seq 1 "$JOBS_PER_MODEL"); do
    label="${model//:/_}-$i"
    prompt="Reply exactly with: profile-${i}"
    if jid=$(submit_job "$model" "$prompt" "$label"); then
      wait_for_job "$jid" "$label" || true
    fi
  done
done

echo ""
echo "6) Registry AFTER..."
AFTER_JSON=$(curl -s "$API/v1/models/registry")
echo "$AFTER_JSON" | python3 -c '
import sys, json
d=json.load(sys.stdin)
print("  model_name | sample_count | p95_gb")
for r in d.get("models", []):
    print(f"  {r.get('model_name')} | {r.get('sample_count')} | {r.get('p95_gb')}")
'

echo ""
echo "7) Delta for selected models..."
python3 - <<PY
import json
before = json.loads("""$BEFORE_JSON""")
after = json.loads("""$AFTER_JSON""")
selected = json.loads("""$(printf '%s\n' "${SELECTED[@]}" | python3 -c 'import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')""")

def as_map(payload):
    out = {}
    for r in payload.get("models", []):
        out[r["model_name"]] = r
    return out

b = as_map(before)
a = as_map(after)
print("  model | sample_count_before -> after | p95_gb_before -> after")
for m in selected:
    rb = b.get(m, {"sample_count": 0, "p95_gb": None})
    ra = a.get(m, {"sample_count": 0, "p95_gb": None})
    print(f"  {m} | {rb.get('sample_count')} -> {ra.get('sample_count')} | {rb.get('p95_gb')} -> {ra.get('p95_gb')}")
PY

echo ""
echo "========================================="
echo "  Done"
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "========================================="

