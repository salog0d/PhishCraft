#!/usr/bin/env bash
# One-time bootstrap for a freshly cloned repo on the VM, so the reliability
# matrix runs with a single command afterwards. Idempotent: safe to re-run.
#
#   bash scripts/vm_setup.sh        # install deps + freeze the model tags
#   OLLAMA_API_BASE=http://... bash scripts/vm_setup.sh   # remote Ollama host
#
# After this, run the matrix with the single command:
#   python scripts/reliability_matrix.py
#
# ponytail: pull-then-cp reproduces the frozen tags because `ollama cp` keeps
# the base weights; if Ollama has since moved the base pointer the digest will
# drift from docs/reference/model-versions.md — eyeball the two after a pull.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== python deps =="
python -m pip install -q -r requirements.txt

echo "== ensure models present (pull if missing) =="
# must match DEFAULT_MODELS + the critic. 3 generators + deepseek critic.
need() {  # $1=tag
  if ollama list | grep -q "^$1[[:space:]]"; then
    echo "  $1: present"
  else
    echo "  pull $1"
    ollama pull "$1"
  fi
}
need qwen3:14b
need phi4:14b
need ministral-3:14b-instruct-2512-q8_0
need deepseek-r1:14b   # critic (self-refinement)

echo
echo "setup done. run the matrix with:"
echo "  python scripts/reliability_matrix.py"
