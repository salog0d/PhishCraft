"""Temperature-swept variety experiment across the local Ollama models.

Parent mode:

    python scripts/variety_experiment.py --pilot        # 2 runs per (model x temp)
    python scripts/variety_experiment.py                # the full run
    python scripts/variety_experiment.py --workers 2 \
        --out experiment/variety-demo

Child mode (internal; one child per model):

    python scripts/variety_experiment.py --child <out_dir> <model_index>

Design (deterministic, seeded, temperature-swept):

- **96 spec cells** = 8 pretexts x 4 tones x 3 difficulties.
- **12 internal recipients**, rotated so every cell and every recipient is
  well covered.
- **4 local models** (the reliable set that holds the enriched charter; see
  ``DEFAULT_MODELS``).
- **4 temperatures** (``TEMPERATURE_SWEEP``): 0.0 (reproducible baseline),
  0.5, 0.8, 1.2 — every (model, cell) pair is sampled at each temperature, so
  semantic variety is measured across the temperature axis, not only the
  seed-derived URL.
- Unique seed per run (1000 + run index): unique tracking tokens, and the
  seed is recorded so any run is reproducible (at temp 0.0 only — temp > 0
  breaks "same seed -> same output").

Every run goes through the real ADK pipeline (``agent.driver``) and the
post-run quality scan (``quality_agent.scan``); per-run artifacts land in
``<out>/models/<model>/<run_id>/`` and every outcome is appended to the
append-only ``<out>/runs.jsonl``. The run is **resumable**: on restart,
completed (ok) runs are skipped, failed ones are retried.

The aggregate report + matplotlib charts come from a separate step:

    python scripts/variety_report.py --out <out_dir>
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MISSION_PATH = REPO_ROOT / "config" / "q3-awareness-2026.mission.json"
sys.path.insert(0, str(REPO_ROOT))

# --------------------------------------------------------------------------- #
# Design constants
# --------------------------------------------------------------------------- #

PRETEXTS = (
    "password_reset",
    "account_suspension",
    "package_delivery",
    "it_support",
    "hr_notice",
    "executive_request",
    "shared_document",
    "invoice_payment",
)
TONES = ("urgent", "friendly", "authoritative", "neutral")
DIFFICULTIES = ("easy", "medium", "hard")
LANGUAGE = "en"
START_AT = "2026-08-20T09:00:00Z"
FOLLOWUP_MINUTES = 75

DEFAULT_TOTAL = 2000          # campaigns per full run (1920 base + 80 extras)
PILOT_PER_MODEL = 2           # --pilot default: runs per (model x temperature)
DESIGN_SEED = 20261026        # shuffles the extras, nothing else
DEFAULT_RUN_TIMEOUT_S = 600   # wall clock per campaign (reasoning models)
DEFAULT_WORKERS = 1           # model children running in parallel

# Temperature sweep — the experiment varies sampling temperature per run (not a
# single --temperature). 0.0 is the reproducible baseline; the rest trade
# seed-reproducibility for semantic variety. See DEFAULT_MODELS below.
TEMPERATURE_SWEEP = (0.0, 0.5, 0.8, 1.2)

# The default model set for the sweep. The small 4B models are excluded because
# they cannot hold the enriched v2 charter's 8-binding format (qwen3:4b drops
# the persona echo on every run; llama3.2:3b collapses to the few-shot
# example). gemma4:latest is included on request despite its 9.6 GB size.
DEFAULT_MODELS = (
    "qwen3:8b",
    "llama3.1:8b",
    "phi4-mini:latest",
    "gemma4:latest",
)

# Per-run sampling params (the spec's ``params`` block). ``None`` temperature
# means "adapter default" (0.0 in agent.config -> deterministic). Raise it to
# sweep semantic variety: temp > 0 breaks "same seed -> same output".
DEFAULT_TOP_P = None          # None -> provider default
DEFAULT_MAX_TOKENS = None     # None -> provider default


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize(name: str) -> str:
    """'qwen3:8b' -> 'qwen3-8b' (folder-safe model name)."""
    return name.replace(":", "-").replace("/", "-")


def ollama_models() -> list[str]:
    """Models currently available in the local Ollama instance."""
    try:
        out = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print(f"cannot query ollama: {exc}", file=sys.stderr)
        return []
    names = []
    for line in out.splitlines()[1:]:  # skip the header row
        fields = line.split()
        if fields:
            names.append(fields[0])
    return names


def internal_recipient_ids() -> list[str]:
    """The 12 internal employee ids, sorted (external personas never receive)."""
    from generator_agent.catalog import load_catalog

    return sorted(
        str(p["id"]) for p in load_catalog() if p["class"] == "internal"
    )


# --------------------------------------------------------------------------- #
# The deterministic run plan
# --------------------------------------------------------------------------- #

def build_plan(
    models: list[str],
    total: int = DEFAULT_TOTAL,
    seed: int = DESIGN_SEED,
    temperatures: tuple[float, ...] = TEMPERATURE_SWEEP,
    top_p: float | None = None,
    max_tokens: int | None = None,
) -> list[dict]:
    """The full run list: balanced coverage of model x cell x temperature.

    Pass 1: every (model, cell) pair once at each temperature
    (``len(models) * 96 * len(temperatures)`` runs).
    Pass 2: shuffled extra (model, cell) pairs at the *baseline* temperature
    (0.0), each with a different recipient than pass 1, up to ``total``.

    Each run carries its own ``params`` block with the sampled temperature so
    the sweep varies sampling semantics, not just the seed-derived URL.
    """
    cells = list(product(PRETEXTS, TONES, DIFFICULTIES))
    recipients = internal_recipient_ids()
    base = len(models) * len(cells) * len(temperatures)
    if not (base <= total <= 2 * base):
        raise SystemExit(
            f"total must be between {base} (one run per model x cell x "
            f"temperature) and {2 * base} (two); got {total}"
        )

    def params_for(temp: float) -> dict:
        p: dict = {"temperature": temp}
        if top_p is not None:
            p["top_p"] = top_p
        if max_tokens is not None:
            p["max_tokens"] = max_tokens
        return p

    runs: list[dict] = []
    for mi, model in enumerate(models):
        for ci, (pretext, tone, difficulty) in enumerate(cells):
            for temp in temperatures:
                runs.append(
                    {
                        "model": model,
                        "pretext": pretext,
                        "tone": tone,
                        "difficulty": difficulty,
                        "recipient_id": recipients[(ci + mi) % len(recipients)],
                        "params": params_for(temp),
                    }
                )

    rng = random.Random(seed)
    # Pass 2: extras spread evenly per model (each model gets an equal share,
    # +1 for the first models when it doesn't divide), shuffled per model so
    # the extra runs also cover every cell the model hasn't seen twice.
    extras: list[tuple[int, int]] = []
    per_model_extra, remainder = divmod(total - base, len(models))
    for mi in range(len(models)):
        order = list(range(len(cells)))
        rng.shuffle(order)
        take = per_model_extra + (1 if mi < remainder else 0)
        extras.extend((mi, ci) for ci in order[:take])
    # Interleave models so the tail of the run order keeps model variety too.
    by_model: dict[int, list[int]] = {mi: [] for mi in range(len(models))}
    for mi, ci in extras:
        by_model[mi].append(ci)
    interleaved: list[tuple[int, int]] = []
    for k in range(per_model_extra + 1):
        for mi in range(len(models)):
            if k < len(by_model[mi]):
                interleaved.append((mi, by_model[mi][k]))
    for mi, ci in interleaved:
        pretext, tone, difficulty = cells[ci]
        runs.append(
            {
                "model": models[mi],
                "pretext": pretext,
                "tone": tone,
                "difficulty": difficulty,
                "recipient_id": recipients[(ci + mi + 1) % len(recipients)],
                "params": params_for(temperatures[0]),  # baseline temp extras
            }
        )

    for i, run in enumerate(runs):
        run["run_id"] = f"V{i + 1:04d}"
        run["seed"] = 1000 + i + 1
    return runs


# --------------------------------------------------------------------------- #
# Child: one model, many campaigns (long-lived process, ADK imported once)
# --------------------------------------------------------------------------- #

class _RunTimeout(Exception):
    """Raised by the SIGALRM handler when a campaign exceeds its budget."""


def _alarm_handler(signum, frame):  # noqa: ARG001
    raise _RunTimeout()


def _load_completed(out: Path) -> set[str]:
    """Run ids already recorded as ok in runs.jsonl (resume support)."""
    completed: set[str] = set()
    manifest = out / "runs.jsonl"
    if not manifest.exists():
        return completed
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "ok":
            completed.add(rec["run_id"])
    return completed


def _append_manifest(out: Path, record: dict) -> None:
    """Append one JSON line to the shared manifest (O_APPEND, small writes)."""
    with (out / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()


def run_one(
    run: dict,
    mission: dict,
    model_dir: Path,
    out: Path,
    run_timeout: int,
    pipeline,
    profile_for,
    scan_campaign,
) -> dict:
    """One campaign: ADK pipeline + quality scan + artifacts + manifest line."""
    run_id = run["run_id"]
    spec = {
        "spec_id": run_id,
        "campaign_id": mission["campaign_id"],
        "pretext": run["pretext"],
        "tone": run["tone"],
        "difficulty": run["difficulty"],
        "language": LANGUAGE,
        "seed": run["seed"],
        "model": {
            "family": "local",
            "name": run["model"],
            "adapter_version": "1.0",
        },
        "recipient_id": run["recipient_id"],
        "start_at": START_AT,
        "followup_minutes": FOLLOWUP_MINUTES,
    }
    # Per-run sampling params (temperature/top_p/max_tokens) — only when the
    # parent set them; None keeps the adapter default (temperature 0.0).
    params = run.get("params")
    if params:
        spec["params"] = params
    record = {
        "run_id": run_id,
        "model": run["model"],
        "spec": spec,
        "status": "ok",
        "ran_at": utc_now(),
        "error": None,
        "duration_ms": 0,
        "run_info": None,
        "failing_checks": [],
        "raw_link_violations": 0,
        "quality": None,
    }
    run_dir = model_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # Per-run LLM trace: every call's prompt/answer/usage lands in
    # llm_trace.jsonl, which monitoring/runs_exporter.py folds into the
    # token/latency metrics. (ADK_MODEL_TRACE_FILE was primed in run_child so
    # the Ollama thinking shim installs before the agent imports.)
    os.environ["ADK_MODEL_TRACE_FILE"] = str(run_dir / "llm_trace.jsonl")

    profile = profile_for(spec["recipient_id"], pretext=spec["pretext"])
    t0 = time.monotonic()
    try:
        signal.alarm(run_timeout)
        try:
            campaign, report, info = pipeline(spec, mission, profile)
        finally:
            signal.alarm(0)
    except _RunTimeout:
        record.update(
            status="timeout",
            error=f"exceeded {run_timeout}s wall clock",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:  # parse/validation/provider failures
        record.update(
            status="generation_error",
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    else:
        quality = scan_campaign(campaign, spec=spec, mission=mission)
        record.update(
            duration_ms=int((time.monotonic() - t0) * 1000),
            run_info=info,
            failing_checks=[r.check.value for r in report.results if not r.passed],
            raw_link_violations=sum(len(m.link_fixes) for m in campaign.messages),
            quality={
                "n_flags": quality.n_flags,
                "any_flag": quality.any_flag,
                "failing": [r.check for r in quality.results if not r.passed],
                "contamination": [
                    r.check for r in quality.results
                    if not r.passed and "contamination" in r.check
                ],
                "label_mismatches": list(quality.label_audit.mismatches),
                "label_statuses": dict(quality.label_audit.statuses),
                "strip_affected_messages": quality.strip_stats.affected_messages,
                "strip_stripped_chars": quality.strip_stats.stripped_chars,
            },
            quality_counts={
                r.check: r.count for r in quality.results
            },
        )
        (run_dir / "generated_campaign.json").write_text(
            campaign.model_dump_json(indent=2), encoding="utf-8"
        )
        (run_dir / "coherence_report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        (run_dir / "quality_report.json").write_text(
            quality.model_dump_json(indent=2), encoding="utf-8"
        )

    (run_dir / "run.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    record["dir"] = str((run_dir).relative_to(out))
    _append_manifest(out, record)
    return record


def run_child(out: Path, model_index: int, run_timeout: int) -> int:
    """Child process: run every campaign assigned to one model."""
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    model = plan["models"][model_index]
    os.environ["ADK_MODEL"] = f"ollama/{model}"  # before agent imports
    # Enable the LLM call trace: one JSONL per run, read by the monitoring
    # runs-exporter (monitoring/runs_exporter.py) for token/latency metrics.
    # Set before the agent imports so the Ollama thinking shim installs.
    os.environ["ADK_MODEL_TRACE_FILE"] = \
        str(out / "models" / sanitize(model) / ".llm_trace.tmp.jsonl")

    from agent.driver import run_pipeline_with_info
    from generator_agent.catalog import profile_for
    from quality_agent.scan import scan_campaign

    mission = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
    mission = copy.deepcopy(mission)
    mission["scope"]["volume"] = plan["total"]

    signal.signal(signal.SIGALRM, _alarm_handler)  # SIGALRM only: main thread
    completed = _load_completed(out)
    todo = [
        r for r in plan["runs"]
        if r["model"] == model and r["run_id"] not in completed
    ]
    model_dir = out / "models" / sanitize(model)
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"[child] model={model} runs={len(todo)} "
          f"(skipped {len(completed)} already ok)", flush=True)
    t0 = time.monotonic()
    for k, run in enumerate(todo):
        record = run_one(
            run, mission, model_dir, out, run_timeout,
            run_pipeline_with_info, profile_for, scan_campaign,
        )
        elapsed = time.monotonic() - t0
        eta = elapsed / (k + 1) * (len(todo) - k - 1)
        print(
            f"[{record['run_id']}] {record['status']} "
            f"flags={record['quality']['n_flags'] if record['quality'] else '-'} "
            f"mismatch={record['quality']['label_mismatches'] if record['quality'] else '-'} "
            f"{record['duration_ms'] / 1000:.1f}s "
            f"(eta {eta / 60:.0f}m)", flush=True,
        )
    print(f"[child] {model}: {len(todo)} runs in "
          f"{(time.monotonic() - t0) / 60:.1f}m", flush=True)
    return 0


# --------------------------------------------------------------------------- #
# Parent: plan + launch children (one per model, --workers in parallel)
# --------------------------------------------------------------------------- #

def run_parent(
    out: Path,
    models: list[str],
    total: int,
    pilot: int,
    workers: int,
    run_timeout: int,
    temperatures: tuple[float, ...],
    top_p: float | None = None,
    max_tokens: int | None = None,
) -> int:
    out.mkdir(parents=True, exist_ok=True)
    runs = build_plan(
        models, total=total,
        temperatures=temperatures, top_p=top_p, max_tokens=max_tokens,
    )
    if pilot:
        # Pilot: keep ``pilot`` runs per (model, temperature) so the sweep is
        # sampled evenly across the temperature axis, not just per model.
        kept: list[dict] = []
        per_model_temp: dict[tuple[str, float], int] = {}
        for run in runs:
            key = (run["model"], run["params"]["temperature"])
            if per_model_temp.get(key, 0) < pilot:
                kept.append(run)
                per_model_temp[key] = per_model_temp.get(key, 0) + 1
        runs = kept

    (out / "plan.json").write_text(
        json.dumps(
            {
                "generated_at": utc_now(),
                "design": {
                    "pretexts": list(PRETEXTS),
                    "tones": list(TONES),
                    "difficulties": list(DIFFICULTIES),
                    "recipients": internal_recipient_ids(),
                    "language": LANGUAGE,
                    "start_at": START_AT,
                    "followup_minutes": FOLLOWUP_MINUTES,
                    "pilot": bool(pilot),
                    "design_seed": DESIGN_SEED,
                    "temperatures": list(temperatures),
                    "top_p": top_p,
                    "max_tokens": max_tokens,
                },
                "models": models,
                "total": len(runs),
                "runs": runs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    per_model = {m: sum(1 for r in runs if r["model"] == m) for m in models}
    print(f"out: {out}")
    print(f"models: {', '.join(models)}")
    print(f"runs: {len(runs)} total — " +
          ", ".join(f"{m}: {n}" for m, n in per_model.items()))
    print(f"workers: {workers} · run timeout: {run_timeout}s")
    print()

    children: list[tuple[str, subprocess.Popen, object]] = []
    try:
        for start in range(0, len(models), workers):
            batch = list(enumerate(models[start:start + workers], start=start))
            procs = []
            for model_index, model in batch:
                model_dir = out / "models" / sanitize(model)
                model_dir.mkdir(parents=True, exist_ok=True)
                log = (model_dir / "child.log").open("w", encoding="utf-8")
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--child",
                        str(out),
                        str(model_index),
                        "--run-timeout",
                        str(run_timeout),
                    ],
                    cwd=REPO_ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                procs.append((model, proc, log))
                children.append((model, proc, log))
            for model, proc, log in procs:
                rc = proc.wait()
                log.close()
                print(f"{model}: rc={rc} "
                      f"(log: models/{sanitize(model)}/child.log)")
                if rc != 0:
                    print(f"  -> last lines:", flush=True)
                    lines = (out / "models" / sanitize(model) / "child.log") \
                        .read_text(encoding="utf-8").splitlines()
                    for line in lines[-6:]:
                        print(f"     {line}")
    except KeyboardInterrupt:
        print("\ninterrupted — stopping children…", file=sys.stderr)
        for _model, proc, _log in children:
            proc.terminate()
        for _model, proc, _log in children:
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        return 130

    print(f"\ndone. aggregate + charts:")
    print(f"  python scripts/variety_report.py --out {out}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--child", nargs=2, metavar=("OUT", "MODEL_INDEX"),
        help="internal: run one model's campaigns in a subprocess",
    )
    parser.add_argument("--pilot", nargs="?", const=PILOT_PER_MODEL, type=int,
                        metavar="N",
                        help=f"run only N campaigns per (model x temperature) "
                             f"(default {PILOT_PER_MODEL})")
    parser.add_argument("--out", default=None,
                        help="output directory (default: experiment/variety-<ts>)")
    parser.add_argument("--models",
                        help="comma-separated model list (default: the default"
                             " capacity-matched set; omit to use it)")
    parser.add_argument("--runs", type=int, default=DEFAULT_TOTAL,
                        help=f"total campaigns (default {DEFAULT_TOTAL})")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="model children running in parallel")
    parser.add_argument("--run-timeout", type=int, default=DEFAULT_RUN_TIMEOUT_S,
                        help="wall-clock seconds per campaign")
    parser.add_argument("--temperatures", default=None,
                        help="comma-separated temperature sweep "
                             f"(default: {','.join(map(str, TEMPERATURE_SWEEP))})")
    parser.add_argument("--top-p", dest="top_p", type=float, default=DEFAULT_TOP_P,
                        help="nucleus top-p (default: provider default)")
    parser.add_argument("--max-tokens", dest="max_tokens", type=int,
                        default=DEFAULT_MAX_TOKENS,
                        help="max output tokens (default: provider default)")
    args = parser.parse_args()

    if args.child:
        out = Path(args.child[0])
        raise SystemExit(
            run_child(out, int(args.child[1]), args.run_timeout)
        )

    temperatures = (
        tuple(float(t) for t in args.temperatures.split(",") if t.strip())
        if args.temperatures
        else TEMPERATURE_SWEEP
    )
    if not temperatures:
        raise SystemExit("empty temperature sweep")

    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else list(DEFAULT_MODELS)
    )
    if not models:
        raise SystemExit("no models found — is the Ollama daemon running?")
    out = Path(
        args.out
        or f"experiment/variety-{'pilot-' if args.pilot else ''}"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    raise SystemExit(
        run_parent(out, models, args.runs, args.pilot, args.workers,
                   args.run_timeout, temperatures, args.top_p, args.max_tokens)
    )


if __name__ == "__main__":
    main()
