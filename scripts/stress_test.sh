#!/bin/bash
# =============================================================================
# Aegis Stress Test Script
# =============================================================================
# Prerequisites:
#   1. Backend running:  cd backend && PYTHONPATH=.. uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
#   2. Dashboard running: cd dashboard && npm run dev
#   3. Models pulled:    ollama pull llama3:8b && ollama pull llama3.2:1b && ollama pull llama3.2:3b && ollama pull qwen2.5:1.5b
#
# Usage: bash scripts/stress_test.sh
# =============================================================================

API="http://127.0.0.1:8000"
PASS=0
FAIL=0

submit_job() {
    local model="$1"
    local priority="$2"
    local prompt="$3"
    local label="$4"

    echo -n "  [$label] model=$model priority=$priority ... " >&2
    RESPONSE=$(curl -s -X POST "$API/v1/jobs/submit" \
        -H 'Content-Type: application/json' \
        -d "{\"model_name\":\"$model\",\"priority\":$priority,\"payload\":{\"prompt\":\"$prompt\",\"stream\":false}}")

    JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])" 2>/dev/null)

    if [ -z "$JOB_ID" ]; then
        echo "SUBMIT FAILED: $RESPONSE" >&2
        FAIL=$((FAIL + 1))
        return 1
    fi

    echo "queued ($JOB_ID)" >&2
    # Only the job ID goes to stdout (for capture)
    echo "$JOB_ID"
    return 0
}

wait_for_job() {
    local job_id="$1"
    local label="$2"
    local timeout=180  # 3 minutes max per job
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        STATUS=$(curl -s "$API/v1/jobs/$job_id" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)

        if [ "$STATUS" = "COMPLETED" ]; then
            LATENCY=$(curl -s "$API/v1/jobs/$job_id" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d['latency_ms']:.0f}ms\")" 2>/dev/null)
            echo "  [$label] $job_id → COMPLETED ($LATENCY)"
            PASS=$((PASS + 1))
            return 0
        elif [ "$STATUS" = "FAILED" ]; then
            ERROR=$(curl -s "$API/v1/jobs/$job_id" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error_message','unknown'))" 2>/dev/null)
            echo "  [$label] $job_id → FAILED: $ERROR"
            FAIL=$((FAIL + 1))
            return 1
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "  [$label] $job_id → TIMEOUT after ${timeout}s (last status: $STATUS)"
    FAIL=$((FAIL + 1))
    return 1
}

print_metrics() {
    echo ""
    echo "--- Current Metrics ---"
    curl -s "$API/v1/metrics" | python3 -c "
import sys, json
d = json.load(sys.stdin)
h = d['hardware']
t = d['throughput']
q = d['queue']
print(f\"  Provider:       {h['provider']}\")
print(f\"  VRAM Pressure:  {h['vram_pressure_percent']:.1f}%\")
print(f\"  Loaded Model:   {d['loaded_model'] or 'None (idle)'}\")
print(f\"  Queue Depth:    {q['depth']}\")
print(f\"  Completed:      {t['jobs_completed_total']}\")
print(f\"  Failed:         {t['jobs_failed_total']}\")
avg = t['avg_latency_ms_last_100']
print(f\"  Avg Latency:    {avg:.0f}ms\" if avg else '  Avg Latency:    N/A')
"
    echo "-----------------------"
}

# =============================================================================
echo ""
echo "========================================="
echo "  AEGIS STRESS TEST"
echo "========================================="
echo ""

# --- Test 1: Health Check ---
echo "▸ Test 1: Backend Health Check"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API/v1/metrics")
if [ "$HTTP_CODE" = "200" ]; then
    echo "  ✓ Backend is reachable (HTTP $HTTP_CODE)"
    PASS=$((PASS + 1))
else
    echo "  ✗ Backend unreachable (HTTP $HTTP_CODE). Is it running?"
    echo "  Aborting."
    exit 1
fi
echo ""

# --- Test 2: Sequential Single-Model Jobs ---
echo "▸ Test 2: Sequential Single-Model (3 jobs, llama3.2:1b)"
JOB_IDS=()
for i in 1 2 3; do
    JOB_ID=$(submit_job "llama3.2:1b" 5 "Count to $i. Just the numbers." "T2-$i")
    JOB_IDS+=("$JOB_ID")
done
echo "  Waiting for completion..."
for i in "${!JOB_IDS[@]}"; do
    wait_for_job "${JOB_IDS[$i]}" "T2-$((i+1))"
done
print_metrics
echo ""

# --- Test 3: Priority Ordering ---
echo "▸ Test 3: Priority Ordering (5 jobs, mixed priorities)"
echo "  Submitting all at once — lower priority number should execute first."
P_IDS=()
JOB_ID=$(submit_job "llama3.2:1b" 10 "What is 1+1? One word." "T3-low")
P_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:1b" 1 "What is 2+2? One word." "T3-high")
P_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:1b" 5 "What is 3+3? One word." "T3-mid")
P_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:1b" 3 "What is 4+4? One word." "T3-med-hi")
P_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:1b" 7 "What is 5+5? One word." "T3-med-lo")
P_IDS+=("$JOB_ID")
echo "  Waiting for completion (order logged above)..."
for i in "${!P_IDS[@]}"; do
    wait_for_job "${P_IDS[$i]}" "T3-$((i+1))"
done
print_metrics
echo ""

# --- Test 4: Multi-Model Eviction Cycling ---
echo "▸ Test 4: Multi-Model Eviction Cycling (4 different models)"
echo "  Each job uses a different model — forces load/evict cycle each time."
M_IDS=()
JOB_ID=$(submit_job "llama3.2:1b" 1 "Say hello." "T4-1b")
M_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:3b" 2 "Say goodbye." "T4-3b")
M_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "qwen2.5:1.5b" 3 "What is Python?" "T4-qwen")
M_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3:8b" 4 "Name a color." "T4-8b")
M_IDS+=("$JOB_ID")
echo "  Waiting for completion..."
for i in "${!M_IDS[@]}"; do
    wait_for_job "${M_IDS[$i]}" "T4-$((i+1))"
done
print_metrics
echo ""

# --- Test 5: Burst Submission (10 jobs at once) ---
echo "▸ Test 5: Burst Submission (10 jobs, mixed models and priorities)"
B_IDS=()
JOB_ID=$(submit_job "llama3.2:1b" 2 "What day is today?" "T5-01")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:3b" 5 "What is the sun?" "T5-02")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:1b" 1 "Say yes." "T5-03")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "qwen2.5:1.5b" 8 "What is 10+10?" "T5-04")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:1b" 3 "Name a fruit." "T5-05")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3:8b" 6 "What is water?" "T5-06")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:3b" 4 "Why is the sky blue?" "T5-07")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:1b" 2 "Count to 3." "T5-08")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "qwen2.5:1.5b" 9 "What is AI?" "T5-09")
B_IDS+=("$JOB_ID")
JOB_ID=$(submit_job "llama3.2:1b" 1 "Say no." "T5-10")
B_IDS+=("$JOB_ID")
echo "  Waiting for all 10 to complete..."
for i in "${!B_IDS[@]}"; do
    wait_for_job "${B_IDS[$i]}" "T5-$((i+1))"
done
print_metrics
echo ""

# --- Test 6: Intentional Failure ---
echo "▸ Test 6: Intentional Failure (nonexistent model)"
JOB_ID=$(submit_job "nonexistent:latest" 5 "This should fail." "T6-fail")
wait_for_job "$JOB_ID" "T6-fail"
print_metrics
echo ""

# --- Final Summary ---
echo "========================================="
echo "  STRESS TEST COMPLETE"
echo "========================================="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "  Total:  $((PASS + FAIL))"
echo "========================================="
echo ""

if [ $FAIL -eq 0 ]; then
    echo "  ✓ ALL TESTS PASSED"
else
    echo "  ✗ SOME TESTS FAILED — check output above"
fi
echo ""
