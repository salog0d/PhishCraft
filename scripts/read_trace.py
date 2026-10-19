"""Pretty-print an experiment's per-model LLM trace (experiment/output-*/llm_trace.jsonl).

Usage:
    python scripts/read_trace.py qwen3:4b            # whole trace for one model
    python scripts/read_trace.py qwen3:4b --thinking # only the thinking sections
    python scripts/read_trace.py output-qwen3-4b     # by output dir name

The trace records every LLM call of the pipeline: the rendered request
(system instruction + user contents), the model's thinking/reasoning, the
final answer, token usage, and wall-clock duration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT_DIR = REPO_ROOT / "experiment"


def resolve_trace(selector: str) -> Path:
    candidates = []
    if Path(selector).exists() and Path(selector).is_file():
        candidates.append(Path(selector))
    name = selector.replace(":", "-").replace("/", "-")
    if not name.startswith("output-"):
        name = f"output-{name}"
    candidates.append(EXPERIMENT_DIR / name / "llm_trace.jsonl")
    for path in candidates:
        if path.exists():
            return path
    raise SystemExit(
        f"no trace found for '{selector}' (tried {', '.join(str(c) for c in candidates)})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="model name (qwen3:4b) or output dir (output-qwen3-4b)")
    parser.add_argument(
        "--thinking", action="store_true", help="print only the thinking sections"
    )
    args = parser.parse_args()

    path = resolve_trace(args.model)
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"# {path} — {len(records)} LLM call(s)")

    for record in records:
        print()
        print("=" * 78)
        response = record.get("response", {})
        print(
            f"call #{record['seq']}  agent={record.get('agent')}  model={record.get('model')}  "
            f"duration={record.get('duration_s')}s  "
            f"usage={response.get('usage')}"
        )
        if record.get("error"):
            print(f"ERROR: {record['error']['type']}: {record['error']['message']}")
            continue
        thought = response.get("thought") or ""
        answer = response.get("text") or ""
        if args.thinking:
            if thought:
                print("-" * 78)
                print(thought)
            else:
                print("(this call carried no thinking/reasoning parts)")
            continue
        print("-" * 78)
        print("[THINKING]")
        print(thought if thought else "(none)")
        print("-" * 78)
        print("[ANSWER]")
        print(answer if answer else "(none)")


if __name__ == "__main__":
    main()
