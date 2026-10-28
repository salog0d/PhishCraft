"""Cross-model experiment: one fixed spec through every local Ollama model.

Parent mode (no ``--single``):

    python scripts/ollama_experiment.py [--models qwen3:4b,phi4-mini,...]

lists the models available in Ollama (or takes an explicit list), then runs
itself once per model in a subprocess with ``ADK_MODEL=ollama/<model>`` so the
import-time model wiring in ``agent.pipeline`` sees the right model. Every
artifact and the full console transcript are saved under:

    experiment/output-<model>/generated_campaign.json
    experiment/output-<model>/coherence_report.json
    experiment/output-<model>/run_info.json
    experiment/output-<model>/llm_trace.jsonl
    experiment/output-<model>/run.log

plus an aggregate ``experiment/summary.json``.

Child mode (``--single <model>``) runs the actual pipeline. The spec is
identical for every model — same mission, pretext, tone, difficulty, language,
seed, recipient, and schedule; only the generation model changes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MISSION_PATH = REPO_ROOT / "config" / "q3-awareness-2026.mission.json"
EXPERIMENT_DIR = REPO_ROOT / "experiment"

# Make the repo packages importable when this script is run from anywhere.
sys.path.insert(0, str(REPO_ROOT / "src"))

# The one fixed spec every model must run (same defaults as the CLI).
FIXED_SPEC = {
    "pretext": "executive_request",
    "tone": "urgent",
    "difficulty": "medium",
    "language": "en",
    "seed": 42,
    "start_at": "2026-08-20T09:00:00Z",
    "followup_minutes": 75,
}

PER_MODEL_TIMEOUT_S = 45 * 60  # generous: slow models (R1 reasoning) can take a while


def sanitize(name: str) -> str:
    """'qwen3:4b' -> 'qwen3-4b' (folder-safe model name)."""
    return name.replace(":", "-").replace("/", "-")


def output_dir(model: str) -> Path:
    return EXPERIMENT_DIR / f"output-{sanitize(model)}"


def ollama_models() -> list[str]:
    """Models currently available in the local Ollama instance."""
    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, check=True
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"cannot query ollama: {exc}", file=sys.stderr)
        return []
    names = []
    for line in out.splitlines()[1:]:  # skip the header row
        name = line.split()[0].strip() if line.split() else ""
        if name:
            names.append(name)
    return names


def run_single(model: str) -> None:
    """Child process: one pipeline run with ADK_MODEL=ollama/<model>."""
    os.environ["ADK_MODEL"] = f"ollama/{model}"
    # Per-model LLM trace: every request/response including the model's
    # thinking/reasoning parts, saved next to the other artifacts. Must be set
    # before agent.pipeline is imported (the callbacks read it at call time,
    # but the output dir must exist first anyway).
    out = output_dir(model)
    out.mkdir(parents=True, exist_ok=True)
    # Fresh trace per run: the callbacks append, so a stale file would mix
    # records from an earlier run of the same model.
    (out / "llm_trace.jsonl").unlink(missing_ok=True)
    os.environ["ADK_MODEL_TRACE_FILE"] = str(out / "llm_trace.jsonl")

    mission = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
    spec = {
        "spec_id": "experiment",
        "campaign_id": mission["campaign_id"],
        "pretext": FIXED_SPEC["pretext"],
        "tone": FIXED_SPEC["tone"],
        "difficulty": FIXED_SPEC["difficulty"],
        "language": FIXED_SPEC["language"],
        "seed": FIXED_SPEC["seed"],
        "model": {"family": "local", "name": model, "adapter_version": "1.0"},
        "recipient_id": _default_recipient_id(),
        "start_at": FIXED_SPEC["start_at"],
        "followup_minutes": FIXED_SPEC["followup_minutes"],
    }

    from agent.driver import run_pipeline_with_info
    from generator_agent.catalog import profile_for

    profile = profile_for(spec["recipient_id"], pretext=spec["pretext"])
    print(
        f"pipeline: campaign={mission['campaign_id']} "
        f"recipient={profile['recipient']['full_name']} "
        f"pretext={spec['pretext']} tone={spec['tone']} "
        f"difficulty={spec['difficulty']} seed={spec['seed']} model=ollama/{model}"
    )
    campaign, report, info = run_pipeline_with_info(spec, mission, profile)

    (out / "generated_campaign.json").write_text(
        campaign.model_dump_json(indent=2), encoding="utf-8"
    )
    (out / "coherence_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    (out / "run_info.json").write_text(
        json.dumps(
            {
                "model": f"ollama/{model}",
                "spec": {k: spec[k] for k in FIXED_SPEC},
                "run_info": info,
                "ran_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved: {out / 'generated_campaign.json'}")
    print(f"saved: {out / 'coherence_report.json'}")
    print(f"saved: {out / 'run_info.json'}")
    print(f"saved: {out / 'llm_trace.jsonl'}")
    print(
        f"persona: {campaign.persona.display_name} <{campaign.persona.email}> — "
        f"{len(campaign.messages)} messages"
    )
    print(
        f"validator: all_passed={report.all_passed} "
        f"({', '.join(r.check.value + '=' + str(r.passed).lower() for r in report.results)})"
    )
    print(
        f"run_info: n_attempts={info['n_attempts']} refined={info['refined']} "
        f"first_attempt_raw_link_violations={info['first_attempt_raw_link_violations']}"
    )


def _default_recipient_id() -> str:
    """Same deterministic default recipient as generator_agent.run."""
    from generator_agent.catalog import load_catalog

    internal = [p for p in load_catalog() if p["class"] == "internal"]
    return str(next(p for p in internal if p["level"] != 1)["id"])


def run_parent(models: list[str]) -> None:
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for model in models:
        out = output_dir(model)
        out.mkdir(parents=True, exist_ok=True)
        print(f"=== model: {model} ===", flush=True)
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--single", model],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=PER_MODEL_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            proc = None
            transcript = f"TIMEOUT after {PER_MODEL_TIMEOUT_S}s\n\n{exc.stdout or ''}"
        transcript = proc.stdout + "\n" + proc.stderr if proc else transcript
        (out / "run.log").write_text(transcript, encoding="utf-8")
        status = "ok" if proc and proc.returncode == 0 else "failed"
        if proc is None:
            status = "timeout"
        row = {"model": model, "status": status, "output_dir": str(out.relative_to(REPO_ROOT))}
        if status == "ok":
            try:
                run_info = json.loads((out / "run_info.json").read_text(encoding="utf-8"))
                report = json.loads((out / "coherence_report.json").read_text(encoding="utf-8"))
                row["all_passed"] = report["all_passed"]
                row["checks"] = {
                    r["check"]: r["passed"] for r in report["results"]
                }
                row["n_attempts"] = run_info["run_info"]["n_attempts"]
                row["refined"] = run_info["run_info"]["refined"]
                row["first_attempt_raw_link_violations"] = run_info["run_info"][
                    "first_attempt_raw_link_violations"
                ]
            except (OSError, KeyError, json.JSONDecodeError):
                pass
        summary.append(row)
        print(f"=== {model}: {status} ===\n", flush=True)
    (EXPERIMENT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "fixed_spec": FIXED_SPEC,
                "results": summary,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"summary: {EXPERIMENT_DIR / 'summary.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single", metavar="MODEL", help="internal: run one model")
    parser.add_argument(
        "--models",
        help="comma-separated model list (default: every model in `ollama list`)",
    )
    args = parser.parse_args()

    if args.single:
        run_single(args.single)
        return
    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else ollama_models()
    )
    if not models:
        raise SystemExit("no models found — is the Ollama daemon running?")
    print(f"models: {', '.join(models)}")
    run_parent(models)


if __name__ == "__main__":
    main()
