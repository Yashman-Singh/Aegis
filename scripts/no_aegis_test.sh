#!/bin/bash
# =============================================================================
# Ollama Direct Test (NO Aegis) — demonstrates VRAM accumulation without eviction
# =============================================================================
# This script hits Ollama directly, bypassing Aegis entirely.
# Ollama's default behavior: keeps models in VRAM for 5 minutes after last use.
# Without Aegis evicting, you'll see VRAM pressure climb and stay high.
#
# Watch the Aegis dashboard at http://localhost:3000 to see the pressure chart
# spike — even though these jobs don't go through Aegis, the hardware monitor
# still reads system memory pressure.
#
# Prerequisites:
#   1. Aegis backend + dashboard running (for the pressure chart)
#   2. Ollama running (ollama serve)
#   3. Models pulled: llama3:8b, llama3.2:1b, llama3.2:3b, qwen2.5:1.5b
#
# Usage: bash scripts/no_aegis_test.sh
# =============================================================================

OLLAMA="http://localhost:11434"

echo ""
echo "========================================="
echo "  OLLAMA DIRECT TEST (NO EVICTION)"
echo "========================================="
echo "  Watch the Aegis dashboard VRAM chart!"
echo "  Models will stay loaded → pressure climbs"
echo ""

echo "--- Baseline pressure before any loads ---"
curl -s http://127.0.0.1:8000/v1/metrics | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  VRAM Pressure: {d['hardware']['vram_pressure_percent']:.1f}%\")
"
echo ""

# Load model 1: llama3.2:1b (~1.3GB) — stays in VRAM
echo "▸ Loading llama3.2:1b (Ollama direct, no eviction)..."
curl -s "$OLLAMA/api/generate" -d '{"model":"llama3.2:1b","prompt":"Say hi.","stream":false}' > /dev/null
echo "  Done. Model stays loaded in VRAM."
sleep 2
curl -s http://127.0.0.1:8000/v1/metrics | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  VRAM Pressure after llama3.2:1b: {d['hardware']['vram_pressure_percent']:.1f}%\")
"
echo ""

# Load model 2: llama3.2:3b (~2GB) — ALSO stays in VRAM (previous still loaded)
echo "▸ Loading llama3.2:3b (Ollama direct, no eviction)..."
curl -s "$OLLAMA/api/generate" -d '{"model":"llama3.2:3b","prompt":"Say hi.","stream":false}' > /dev/null
echo "  Done. Now TWO models in VRAM."
sleep 2
curl -s http://127.0.0.1:8000/v1/metrics | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  VRAM Pressure after +llama3.2:3b: {d['hardware']['vram_pressure_percent']:.1f}%\")
"
echo ""

# Load model 3: qwen2.5:1.5b (~1GB) — ALSO stays in VRAM
echo "▸ Loading qwen2.5:1.5b (Ollama direct, no eviction)..."
curl -s "$OLLAMA/api/generate" -d '{"model":"qwen2.5:1.5b","prompt":"Say hi.","stream":false}' > /dev/null
echo "  Done. Now THREE models in VRAM."
sleep 2
curl -s http://127.0.0.1:8000/v1/metrics | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  VRAM Pressure after +qwen2.5:1.5b: {d['hardware']['vram_pressure_percent']:.1f}%\")
"
echo ""

# Load model 4: llama3:8b (~4.7GB) — BIG model, likely pushes pressure very high
echo "▸ Loading llama3:8b (Ollama direct, no eviction)..."
echo "  This is the big one (4.7GB). Watch the dashboard chart spike!"
curl -s "$OLLAMA/api/generate" -d '{"model":"llama3:8b","prompt":"Say hi.","stream":false}' > /dev/null
echo "  Done. Now FOUR models in VRAM."
sleep 2
curl -s http://127.0.0.1:8000/v1/metrics | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  VRAM Pressure after +llama3:8b: {d['hardware']['vram_pressure_percent']:.1f}%\")
"
echo ""

echo "========================================="
echo "  ALL 4 MODELS NOW LOADED IN VRAM"
echo "========================================="
echo "  Without Aegis eviction, they stay for ~5 min."
echo "  Check the dashboard chart — pressure should be HIGH."
echo ""
echo "  To manually evict all models and drop pressure:"
echo "    curl $OLLAMA/api/generate -d '{\"model\":\"llama3.2:1b\",\"keep_alive\":0}'"
echo "    curl $OLLAMA/api/generate -d '{\"model\":\"llama3.2:3b\",\"keep_alive\":0}'"
echo "    curl $OLLAMA/api/generate -d '{\"model\":\"qwen2.5:1.5b\",\"keep_alive\":0}'"
echo "    curl $OLLAMA/api/generate -d '{\"model\":\"llama3:8b\",\"keep_alive\":0}'"
echo ""
echo "  Or just wait ~5 minutes for Ollama's auto-eviction."
echo ""
