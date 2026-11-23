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

echo "== freeze model tags (ollama cp; no-op if they already exist) =="
# base tag -> frozen tag (must match DEFAULT_MODELS + the critic in the script)
freeze() {  # $1=base  $2=frozen
  if ollama list | grep -q "^$2[[:space:]]"; then
    echo "  $2: present"
  else
    echo "  $1 -> $2"
    ollama pull "$1"
    ollama cp "$1" "$2"
  fi
}
freeze qwen3:8b          qwen3:8b-q4km-20261110
freeze llama3.1:8b       llama3.1:8b-q4km-20261110
freeze phi4-mini:latest  phi4-mini:3.8b-q4km-20261110
freeze deepseek-r1:7b    deepseek-r1:7b-q4km-20261110

echo
echo "setup done. run the matrix with:"
echo "  python scripts/reliability_matrix.py"
