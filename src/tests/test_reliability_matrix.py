"""Regression tests for the reliability-matrix helpers.

These pin the three silent-failure bugs that each cost real runs:

- ``model_slug`` must strip stacked version/quant suffixes (a tag like
  ``ministral:8b-instruct-2512-q8_0`` collided/leaked into the run_id and 24
  runs failed silently).
- ``wilson_ci`` must bound a small-sample rate inside [0, 1] and expose the
  overlap that makes a 3-seeds-per-cell "difference" non-significant.
- ``_ollama_has`` (agent.config) must query the configured host and degrade to
  False without raising when the host is unreachable — never a silent crash.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "reliability_matrix", REPO_ROOT / "scripts" / "reliability_matrix.py"
)
rm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rm)


def test_model_slug_strips_stacked_suffix():
    # The bug: this long tag did not shrink and leaked into the run_id.
    assert rm.model_slug("ministral:8b-instruct-2512-q8_0") == "ministral-8b"
    assert rm.model_slug("qwen3:8b-q4km-20261110") == "qwen3-8b"
    assert rm.model_slug("ollama/phi4-mini:3.8b-q4km-20261110") == "phi4-mini-3.8b"
    # A plain tag is left alone (minus the colon sanitization).
    assert rm.model_slug("qwen3:8b") == "qwen3-8b"


def test_wilson_ci_bounds_and_overlap():
    assert rm.wilson_ci(0, 0) is None
    # A perfect small sample must not produce an interval outside [0, 1].
    lo, hi = rm.wilson_ci(3, 3)
    assert 0.0 < lo < 1.0 and hi <= 1.0
    # The regression the CI exists to expose: 3/3 vs 2/3 overlap heavily, so
    # the "difference" is not distinguishable at 3 seeds.
    lo_a, hi_a = rm.wilson_ci(3, 3)
    lo_b, hi_b = rm.wilson_ci(2, 3)
    assert lo_a < hi_b and lo_b < hi_a  # intervals overlap


def test_provenance_prompt_hash_and_commit(tmp_path):
    # Rule 4: each run must carry a prompt hash; the plan carries git_commit.
    import json
    trace = tmp_path / "llm_trace.jsonl"
    rec = {"agent": "generator_content_agent",
           "request": {"system_instruction": "sys", "contents": ["hi"]},
           "response": {"text": "ok", "usage": {}}}
    trace.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    summary = rm.trace_summary(tmp_path)
    assert summary["prompt_sha256"] and len(summary["prompt_sha256"]) == 64
    # Same prompt -> same hash; critic-only traces -> no hash.
    assert rm.trace_summary(tmp_path)["prompt_sha256"] == summary["prompt_sha256"]
    assert rm.git_commit()  # never empty: a sha, "...-dirty", or "unknown"
    assert rm.build_plan(["qwen3:8b"])["git_commit"] == rm.git_commit()


def test_ollama_has_is_best_effort(monkeypatch):
    from agent import config

    # Point at a host that will refuse the connection; must return False, never
    # raise (the fallback decision depends on this not crashing).
    monkeypatch.setenv("OLLAMA_API_BASE", "http://127.0.0.1:1")
    assert config._ollama_has("anything:latest") is False
