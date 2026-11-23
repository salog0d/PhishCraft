"""Sensitivity matrix for generator reliability (David's design).

Evaluates how much constraint-compliance varies across models and temperatures
and how much effort the system needs to deliver a valid campaign.

Design:

- **Models** (exact versions recorded): ``qwen3:8b``, ``llama3.1:8b``,
  ``phi4-mini:latest``. ``--models`` accepts bare names (local Ollama) or a
  provider prefix ``provider/name`` (``ollama/qwen3:8b``,
  ``deepseek/deepseek-chat``). The Ollama *host* is resolved from
  ``OLLAMA_API_BASE`` — leave it unset for localhost, or point it at a remote
  Ollama (an Azure VM serving models) for cloud runs. The critic follows
  ``ADK_CRITIC_MODEL`` the same way.
- **Temperatures**: 0.0, 0.5, 1.0.
- **Cases**: 12 fixed specs (3 per pretext, from 4 base pretexts).
- **Repetitions**: 3 per combination, seeds 101/202/303, the same across
  conditions.
- **Output limit**: 4096 tokens per generator call.

So each (model, temperature, case) runs at 3 seeds → 3*3*12*3 = 324 executions.
The case is invariant: same recipient, context, entities, constraints and
content requirements. Only model, temperature and seed change; every execution
starts in a fresh session.

Every run goes through the real ADK pipeline (``agent.driver``) and the
post-run quality scan (``quality_agent.scan``). Besides the final artifacts,
the harness records — per run, from the per-run ``llm_trace.jsonl`` — the
**first raw model response** (even if it failed to parse), the number of LLM
calls, and total tokens including the critic model that proposes corrections.

Usage:

    # verify the provider actually receives temperature / max_tokens / seed
    python scripts/reliability_matrix.py --verify

    # run everything over a remote Ollama (e.g. an Azure VM):
    #   OLLAMA_API_BASE=http://<vm-ip>:11434 \
    #   python scripts/reliability_matrix.py \
    #     --models ollama/qwen3:14b,ollama/llama3.1:70b
    python scripts/reliability_matrix.py --out experiment/reliability-<ts>

    # regenerate the aggregate report + summaries from a finished/paused run
    python scripts/reliability_matrix.py --report experiment/reliability-<ts>
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MISSION_PATH = REPO_ROOT / "config" / "q3-awareness-2026.mission.json"
sys.path.insert(0, str(REPO_ROOT / "src"))

# --------------------------------------------------------------------------- #
# Design constants
# --------------------------------------------------------------------------- #

# Frozen model tags (see docs/reference/model-versions.md). Never ``latest``: these are
# immutable `ollama cp` snapshots so the whole matrix is reproducible.
DEFAULT_MODELS = (
    "qwen3:8b-q4km-20261110",        # 8.2B Q4_K_M — sha256 a3de86cd…
    "llama3.1:8b-q4km-20261110",     # 8.0B Q4_K_M — sha256 667b0c19…
    "phi4-mini:3.8b-q4km-20261110",  # 3.8B Q4_K_M — sha256 3c168af1…
)
TEMPERATURES = (0.0,)  # pilot: seed variability only, no temperature sweep
SEEDS = (101, 202, 303)
MAX_TOKENS = 4096
LANGUAGE = "en"
START_AT = "2026-08-20T09:00:00Z"
FOLLOWUP_MINUTES = 75
DEFAULT_RUN_TIMEOUT_S = 600
DEFAULT_WORKERS = 1

# 8 fixed cases: one representative spec per pretext (tono + difficulty + recipient).
# Recipients are fixed so every model receives the identical case and recipient.
CASES = (
    # executive_request (BEC — manager impersonation)
    ("C01", "executive_request", "urgent", "medium", 40),
    # invoice_payment (BEC — supplier)
    ("C02", "invoice_payment", "authoritative", "medium", 24),
    # account_suspension (consumer — bank)
    ("C03", "account_suspension", "urgent", "hard", 41),
    # password_reset (consumer — help desk)
    ("C04", "password_reset", "neutral", "medium", 25),
    # shared_document (BEC — manager impersonation)
    ("C05", "shared_document", "neutral", "medium", 40),
    # it_support (help desk)
    ("C06", "it_support", "authoritative", "medium", 41),
    # hr_notice (People Ops)
    ("C07", "hr_notice", "authoritative", "medium", 40),
    # package_delivery (carrier)
    ("C08", "package_delivery", "neutral", "medium", 24),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize(name: str) -> str:
    return name.replace(":", "-").replace("/", "-")


def model_slug(model: str) -> str:
    """A short, unique identifier for the run_id.

    The full frozen tag (e.g. ``phi4-mini:3.8b-q4km-20261110``) is too long for
    the ``spec_id`` field (40 chars) once prefixed with the case/temp/seed. The
    exact version is still recorded in ``spec.model.name`` and
    ``docs/model-versions.md``, so the run_id only needs a compact slug: the
    base name with the version suffix (``-q4km-YYYYMMDD``) stripped.
    """
    name = model_ref(model)[1]  # bare name, no provider/ prefix
    # Drop trailing version/quantization suffixes: `-q4km-20261110`, `-Q4_K_M`,
    # and the longer Minstral-style `-instruct-2512-q8_0`. Multi-pass so a name
    # with several stacked suffixes shrinks to its base (still unique per model).
    import re
    for _ in range(3):
        shorter = re.sub(
            r"-(?:instruct|q\d[_-]?k?_?m?|q\d_\d|fp16|f\d{8}|\d{8}|\d{4}-\d{2}-\d{2})"
            r"[A-Za-z0-9_-]*$", "", name)
        if shorter == name:
            break
        name = shorter
    return sanitize(name)


# Provider prefixes ``resolve_model`` understands (agent.config). A model entry
# may carry one (``ollama/qwen3:8b``, ``deepseek/deepseek-chat``); when absent it
# is a local Ollama model and ``ollama/`` is prepended. The Ollama *host* is
# resolved by LiteLLM from ``OLLAMA_API_BASE`` (localhost by default, or the
# remote Azure VM's ``http://<ip>:11434``), so the same ``ollama/`` prefix serves
# local and cloud models — only the env var changes.
KNOWN_PREFIXES = ("ollama", "deepseek", "gemini")


def model_ref(model: str) -> tuple[str, str]:
    """Split ``provider/name`` into a ``ADK_MODEL`` id and a folder-safe name.

    No prefix -> local Ollama (``ollama/<model>``).
    """
    if "/" in model:
        provider, name = model.split("/", 1)
        if provider in KNOWN_PREFIXES:
            return f"{provider}/{name}", name
    return f"ollama/{model}", model


# Ollama runs are recorded under the ``local`` family (the ModelFamily enum has
# no ``ollama`` member); API providers map to their own family members.
_FAMILY_BY_PREFIX = {
    "ollama": "local",
    "deepseek": "deepseek",
    "gemini": "openai",
}


def _family_for(model: str) -> str:
    """Enum-safe ``ModelSpec.family`` for a model entry's provider prefix."""
    prefix = model_ref(model)[0].split("/", 1)[0]
    return _FAMILY_BY_PREFIX.get(prefix, "local")


# --------------------------------------------------------------------------- #
# Provider verification (--verify): confirm temperature / max_tokens / seed
# actually reach the provider before the final run.
# --------------------------------------------------------------------------- #


def verify_provider(model: str) -> dict:
    """One bare /api/generate call against Ollama with seed+options, echoing
    back what the provider was asked, so we confirm the params are honoured
    rather than silently dropped. No pipeline import (this is a pre-check)."""
    import urllib.request

    # Same host resolution LiteLLM uses for `ollama/` models: OLLAMA_HOST (this
    # script's legacy name) then OLLAMA_API_BASE (what litellm reads) then local.
    url = (
        os.getenv("OLLAMA_HOST")
        or os.getenv("OLLAMA_API_BASE")
        or "http://localhost:11434"
    ).rstrip("/")
    payload = {
        "model": model,
        "prompt": "Reply with the single word: ok",
        "stream": False,
        "options": {"temperature": 0.0, "seed": 101, "num_predict": MAX_TOKENS},
    }
    req = urllib.request.Request(
        f"{url}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 — verification must never crash the run
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_verify() -> int:
    """Verify every model honours seed at temperature 0 (deterministic)."""
    print("Provider verification (temperature/max_tokens/seed reached Ollama):")
    ok = True
    for model in DEFAULT_MODELS:
        a = verify_provider(model)
        b = verify_provider(model)
        if "error" in a:
            print(f"  {model}: ERROR {a['error']}")
            ok = False
            continue
        same = a.get("response") == b.get("response")
        d = (a.get("done") and b.get("done"))
        print(f"  {model}: seed honoured at t=0 -> {'identical' if same else 'DIFFERENT'}"
              f" (prompt_eval_count={a.get('prompt_eval_count')}, "
              f"eval_count={a.get('eval_count')})")
        ok = ok and same
    print("verdict:", "PASS — params reach the provider" if ok
          else "WARN — see above; adjust before the run")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #


def build_plan(models: list[str]) -> dict:
    runs = []
    for model in models:
        for case_id, pretext, tone, difficulty, recipient_id in CASES:
            for temp in TEMPERATURES:
                for seed in SEEDS:
                    runs.append(
                        {
                            "model": model,
                            "case_id": case_id,
                            "pretext": pretext,
                            "tone": tone,
                            "difficulty": difficulty,
                            "recipient_id": recipient_id,
                            "temperature": temp,
                            "seed": seed,
                        }
                    )
    for i, run in enumerate(runs):
        run["run_id"] = f"{run['case_id']}-{model_slug(run['model'])}"
        run["run_id"] += f"-t{run['temperature']}-s{run['seed']}"
    return {
        "generated_at": utc_now(),
        "design": {
            "models": models,
            "temperatures": list(TEMPERATURES),
            "seeds": list(SEEDS),
            "max_tokens": MAX_TOKENS,
            "cases": [
                {"case_id": c, "pretext": p, "tone": t, "difficulty": d,
                 "recipient_id": r} for c, p, t, d, r in CASES
            ],
            "language": LANGUAGE,
            "start_at": START_AT,
            "followup_minutes": FOLLOWUP_MINUTES,
        },
        "total": len(runs),
        "runs": runs,
    }


# --------------------------------------------------------------------------- #
# Trace reading (first raw response, calls, tokens)
# --------------------------------------------------------------------------- #


def _read_trace(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def trace_summary(run_dir: Path) -> dict:
    """From llm_trace.jsonl: first raw response, call/token/latency totals.

    The *first* record is the generator's first reply — the raw text before any
    strict-format retry or refinement, saved even when unparseable. The critic
    records carry ``agent == "critic"`` and are folded into token totals.
    """
    records = _read_trace(run_dir / "llm_trace.jsonl")
    first_raw = None
    first_readable = None
    generator_calls = critic_calls = 0
    prompt_tokens = completion_tokens = total_tokens = 0
    total_s = 0.0
    for rec in records:
        response = rec.get("response") or {}
        agent = rec.get("agent") or "generator"
        if agent == "critic":
            critic_calls += 1
        else:
            generator_calls += 1
        usage = response.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        if rec.get("duration_s"):
            total_s += float(rec["duration_s"])
        text = response.get("text")
        if text and first_raw is None and agent != "critic":
            first_raw = text
    # first_readable is set by the runner from the parsed campaign; leave None.
    return {
        "first_raw_response": first_raw,
        "generator_calls": generator_calls,
        "critic_calls": critic_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "llm_duration_s": round(total_s, 3),
    }


# --------------------------------------------------------------------------- #
# Child: run every execution assigned to one model
# --------------------------------------------------------------------------- #


class _RunTimeout(Exception):
    pass


def _alarm_handler(signum, frame):  # noqa: ARG001
    raise _RunTimeout()


def _load_completed(out: Path) -> set[str]:
    completed = set()
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
    with (out / "runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()


def run_one(run: dict, mission: dict, out: Path, run_timeout: int,
            pipeline, profile_for, scan_campaign) -> dict:
    run_id = run["run_id"]
    params = {
        "temperature": run["temperature"],
        "max_tokens": MAX_TOKENS,
        "seed": run["seed"],
    }
    spec = {
        "spec_id": run_id,
        "campaign_id": mission["campaign_id"],
        "pretext": run["pretext"],
        "tone": run["tone"],
        "difficulty": run["difficulty"],
        "language": LANGUAGE,
        "seed": run["seed"],
        "model": {"family": _family_for(run["model"]),
                  "name": model_ref(run["model"])[1], "adapter_version": "1.0"},
        "recipient_id": run["recipient_id"],
        "start_at": START_AT,
        "followup_minutes": FOLLOWUP_MINUTES,
        "params": params,
    }
    model_dir = out / "models" / sanitize(run["model"])
    run_dir = model_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["ADK_MODEL_TRACE_FILE"] = str(run_dir / "llm_trace.jsonl")
    (run_dir / "llm_trace.jsonl").unlink(missing_ok=True)

    record = {
        "run_id": run_id,
        "case_id": run["case_id"],
        "model": run["model"],
        "temperature": run["temperature"],
        "seed": run["seed"],
        "pretext": run["pretext"],
        "tone": run["tone"],
        "difficulty": run["difficulty"],
        "recipient_id": run["recipient_id"],
        "config": spec,
        "status": "ok",
        "ran_at": utc_now(),
        "error": None,
        "duration_ms": 0,
        "run_info": None,
        "trace": None,
        "failing_checks": [],
        "raw_link_violations": 0,
        "quality": None,
        "dir": str(run_dir.relative_to(out)),
    }

    profile = profile_for(spec["recipient_id"], pretext=spec["pretext"])
    t0 = time.monotonic()
    try:
        signal.alarm(run_timeout)
        try:
            campaign, report, info = pipeline(spec, mission, profile)
        finally:
            signal.alarm(0)
    except _RunTimeout:
        record.update(status="timeout",
                      error=f"exceeded {run_timeout}s wall clock",
                      duration_ms=int((time.monotonic() - t0) * 1000))
        campaign = report = None
    except Exception as exc:  # noqa: BLE001 — every failure is a data point
        record.update(status="generation_error",
                      error=f"{type(exc).__name__}: {exc}",
                      duration_ms=int((time.monotonic() - t0) * 1000))
        campaign = report = None
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
                "label_mismatches": list(quality.label_audit.mismatches),
                "label_statuses": dict(quality.label_audit.statuses),
                # spec (requested) vs predicted (achieved) labels, for the
                # honest relabel: the dataset reports what the model actually
                # produced, not only what was requested.
                "label_spec": dict(quality.label_audit.spec_labels),
                "label_predicted": dict(quality.label_audit.predicted_labels),
            },
        )
        (run_dir / "generated_campaign.json").write_text(
            campaign.model_dump_json(indent=2), encoding="utf-8")
        (run_dir / "coherence_report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8")
        (run_dir / "quality_report.json").write_text(
            quality.model_dump_json(indent=2), encoding="utf-8")

    record["trace"] = trace_summary(run_dir)
    (run_dir / "run.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    _append_manifest(out, record)
    return record


def run_child(out: Path, model_index: int, run_timeout: int) -> int:
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    model = plan["design"]["models"][model_index]
    adk_model, _label = model_ref(model)
    os.environ["ADK_MODEL"] = adk_model
    # Prime the trace path so the Ollama thinking shim installs before import.
    os.environ["ADK_MODEL_TRACE_FILE"] = \
        str(out / "models" / sanitize(model) / ".llm_trace.tmp.jsonl")

    from agent.driver import run_pipeline_with_info
    from generator_agent.catalog import profile_for
    from quality_agent.scan import scan_campaign

    mission = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
    mission = copy.deepcopy(mission)

    signal.signal(signal.SIGALRM, _alarm_handler)
    completed = _load_completed(out)
    todo = [r for r in plan["runs"] if r["model"] == model and r["run_id"] not in completed]
    print(f"[child] model={model} adk_model={adk_model} runs={len(todo)} "
          f"(skipped {len(completed)} ok)", flush=True)
    t0 = time.monotonic()
    for k, run in enumerate(todo):
        record = run_one(run, mission, out, run_timeout,
                         run_pipeline_with_info, profile_for, scan_campaign)
        tr = record["trace"] or {}
        elapsed = time.monotonic() - t0
        eta = elapsed / (k + 1) * (len(todo) - k - 1)
        print(f"[{record['run_id']}] {record['status']} "
              f"calls={tr.get('generator_calls', '-')}+{tr.get('critic_calls', '-')} "
              f"tok={tr.get('total_tokens', '-')} "
              f"{record['duration_ms'] / 1000:.1f}s (eta {eta / 60:.0f}m)",
              flush=True)
    print(f"[child] {model}: {len(todo)} runs in "
          f"{(time.monotonic() - t0) / 60:.1f}m", flush=True)
    return 0


# --------------------------------------------------------------------------- #
# Parent
# --------------------------------------------------------------------------- #


def preflight(models: list[str]) -> tuple[bool, str]:
    """Fail loud *before* a multi-hour run: every matrix model must answer on
    the real host, and the critic must be reachable (or its absence declared).

    This is the guard for the class of silent failure that has cost whole runs:
    a model tag that does not resolve, a critic that falls back without anyone
    noticing. It makes the run refuse to start on an unreachable model instead
    of burning hours producing runs that are secretly degraded.

    Returns ``(all_models_ok, critic_status)``; ``critic_status`` is one of
    ``reachable`` / ``MISSING (will fall back to the generator)``.
    """
    print("preflight:")
    all_ok = True
    for model in models:
        result = verify_provider(model)
        if "error" in result:
            print(f"  model {model}: UNREACHABLE — {result['error']}")
            all_ok = False
        else:
            print(f"  model {model}: ok (eval_count={result.get('eval_count')})")

    from agent.config import DEFAULT_CRITIC_MODEL

    critic = os.getenv("ADK_CRITIC_MODEL", DEFAULT_CRITIC_MODEL)
    critic_status = "reachable"
    if critic.startswith("ollama/"):
        probe = verify_provider(critic[len("ollama/"):])
        if "error" in probe:
            critic_status = "MISSING (will fall back to the generator)"
    print(f"  critic {critic}: {critic_status}")
    return all_ok, critic_status


def run_parent(out: Path, models: list[str], workers: int, run_timeout: int,
               skip_preflight: bool = False) -> int:
    if not skip_preflight:
        models_ok, critic_status = preflight(models)
        if not models_ok:
            print("\nABORT: one or more models are unreachable on the configured "
                  "host. Fix the model tag / OLLAMA_API_BASE, or pass "
                  "--skip-preflight to run anyway.")
            return 2
        if critic_status != "reachable":
            print("  (proceeding; the critic fallback is now explicit, not silent)")
        print()
    out.mkdir(parents=True, exist_ok=True)
    plan = build_plan(models)
    (out / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"out: {out}")
    print(f"runs: {plan['total']} total")
    for m in models:
        n = sum(1 for r in plan["runs"] if r["model"] == m)
        print(f"  {m}: {n} runs")
    print()

    for start in range(0, len(models), workers):
        batch = list(enumerate(models[start:start + workers], start=start))
        procs = []
        for model_index, model in batch:
            (out / "models" / sanitize(model)).mkdir(parents=True, exist_ok=True)
            log = (out / "models" / sanitize(model) / "child.log").open("w", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--child",
                 str(out), str(model_index), "--run-timeout", str(run_timeout)],
                cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT)
            procs.append((model, proc, log))
        for model, proc, log in procs:
            rc = proc.wait()
            log.close()
            print(f"{model}: rc={rc}")
            if rc != 0:
                lines = (out / "models" / sanitize(model) / "child.log") \
                    .read_text(encoding="utf-8").splitlines()
                for line in lines[-6:]:
                    print(f"     {line}")
    print(f"\ndone. aggregate report:")
    print(f"  python scripts/reliability_matrix.py --report {out}")
    return 0


# --------------------------------------------------------------------------- #
# Report (--report): master table + 3 summaries
# --------------------------------------------------------------------------- #


def run_report(out: Path) -> int:
    manifest = out / "runs.jsonl"
    if not manifest.exists():
        raise SystemExit(f"no manifest at {manifest}")
    rows = [json.loads(l) for l in manifest.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    by_id = {}
    for r in rows:
        by_id[r["run_id"]] = r  # last line wins
    rows = list(by_id.values())

    # Master table
    master = []
    for r in rows:
        tr = r.get("trace") or {}
        master.append({
            "run_id": r["run_id"],
            "model": r["model"],
            "temperature": r["temperature"],
            "seed": r["seed"],
            "case_id": r["case_id"],
            "pretext": r["pretext"],
            "status": r["status"],
            "n_attempts": (r.get("run_info") or {}).get("n_attempts"),
            "refined": (r.get("run_info") or {}).get("refined"),
            "raw_link_violations": r.get("raw_link_violations"),
            "failing_checks": r.get("failing_checks"),
            "quality_flags": (r.get("quality") or {}).get("n_flags"),
            "generator_calls": tr.get("generator_calls"),
            "critic_calls": tr.get("critic_calls"),
            "total_tokens": tr.get("total_tokens"),
            "duration_ms": r["duration_ms"],
            "config_ref": f"{r['dir']}/run.json",
            "attempts_ref": f"{r['dir']}/llm_trace.jsonl",
            "result_ref": f"{r['dir']}/generated_campaign.json",
        })
    (out / "master_table.json").write_text(
        json.dumps(master, indent=2, ensure_ascii=False), encoding="utf-8")

    comp = analyze(rows)
    (out / "summary.json").write_text(
        json.dumps(comp, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "summary.md").write_text(markdown(comp, len(rows)), encoding="utf-8")

    print(f"master table: {out / 'master_table.json'}")
    print(f"summaries: {out / 'summary.json'}, {out / 'summary.md'}")
    return 0


def _key(r):
    return (r["model"], r["temperature"])


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a binomial proportion (None if n == 0).

    Wilson, not the normal approximation: with the 3-seeds-per-cell counts in
    this matrix the normal interval is wrong (it can exceed [0, 1] and badly
    under-covers near 0 and 1). The interval is what makes a between-model
    difference interpretable — two cells whose CIs overlap are *not* a
    distinguishable result at this sample size, no matter how far the point
    rates sit apart.
    """
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def _ci_str(ci: tuple[float, float] | None) -> str:
    """Render a CI tuple for a markdown cell."""
    return "—" if ci is None else f"[{ci[0]:.2f}–{ci[1]:.2f}]"


def analyze(rows: list[dict]) -> dict:
    # 1. Delivery guarantee by model x temperature (completed runs only).
    comp = defaultdict(lambda: {"total": 0, "ok": 0, "failed": 0,
                                "completed": 0, "all_passed": 0})
    errs_by_check = Counter()
    effort = defaultdict(lambda: Counter())
    # R6: two separate rates — spec compliance (label audit) vs structural flags.
    spec = defaultdict(lambda: defaultdict(Counter))  # per (model,temp): label -> Counter(status)
    flags = defaultdict(lambda: [0, 0])        # per (model,temp): [flagged, total]
    achieved = defaultdict(lambda: defaultdict(Counter))  # per (model,temp): label -> Counter(achieved value)
    for r in rows:
        k = _key(r)
        comp[k]["total"] += 1
        if r["status"] == "ok":
            comp[k]["ok"] += 1
            comp[k]["completed"] += 1
            if not r.get("failing_checks"):
                comp[k]["all_passed"] += 1
            for c in r.get("failing_checks") or []:
                errs_by_check[(k[0], k[1], c)] += 1
            effort[k]["runs"] += 1
            ri = r.get("run_info") or {}
            effort[k]["n_attempts"] += ri.get("n_attempts", 0) or 0
            effort[k]["n_parse_attempts"] += ri.get("n_parse_attempts", ri.get("n_attempts", 0)) or 0
            effort[k]["n_refine_rounds"] += ri.get("n_refine_rounds", 0) or 0
            effort[k]["refined"] += 1 if ri.get("refined") else 0
            effort[k]["refinement_improved"] += 1 if ri.get("refinement_improved") else 0
            effort[k]["total_tokens"] += (r.get("trace") or {}).get("total_tokens", 0) or 0
            effort[k]["duration_ms"] += r.get("duration_ms", 0)
            effort[k]["critic_calls"] += (r.get("trace") or {}).get("critic_calls", 0) or 0
            # R6 aggregations
            q = r.get("quality") or {}
            flags[k][1] += 1
            if q.get("any_flag"):
                flags[k][0] += 1
            for lab, status in (q.get("label_statuses") or {}).items():
                spec[k][lab][status] += 1
            for lab, val in (q.get("label_predicted") or {}).items():
                if val is not None:
                    achieved[k][lab][val] += 1
        else:
            comp[k]["failed"] += 1
    # 2. errors by constraint (model x temp x check)
    # 3. effort (done above)
    out = {
        "compliance": {
            f"{m} @ {t}": {
                "total": v["total"],
                "completed": v["completed"],
                "failed_or_timeout": v["failed"],
                "all_passed": v["all_passed"],
                "compliance_rate_among_completed": (
                    round(v["all_passed"] / v["completed"], 4) if v["completed"] else None
                ),
                "compliance_ci95": wilson_ci(v["all_passed"], v["completed"]),
            }
            for (m, t), v in sorted(comp.items())
        },
        "errors_by_constraint": {
            f"{m} @ {t} :: {c}": n
            for (m, t, c), n in sorted(errs_by_check.items())
        },
        "effort": {
            f"{m} @ {t}": {
                "runs": v["runs"],
                "mean_parse_attempts": round(v["n_parse_attempts"] / v["runs"], 2) if v["runs"] else None,
                "mean_refine_rounds": round(v["n_refine_rounds"] / v["runs"], 2) if v["runs"] else None,
                "refined_runs": v["refined"],
                "refinements_improved": v["refinement_improved"],
                "mean_total_tokens": round(v["total_tokens"] / v["runs"], 1) if v["runs"] else None,
                "mean_duration_s": round(v["duration_ms"] / v["runs"] / 1000, 1) if v["runs"] else None,
                "critic_calls": v["critic_calls"],
            }
            for (m, t), v in sorted(effort.items())
        },
        # R6: two separate rates, so structural flags and spec compliance are
        # never conflated into one "compliance" number.
        "structural_flags": {
            f"{m} @ {t}": {
                "flagged": v[0],
                "total": v[1],
                "flag_rate": round(v[0] / v[1], 4) if v[1] else None,
                "flag_rate_ci95": wilson_ci(v[0], v[1]),
            }
            for (m, t), v in sorted(flags.items())
        },
        "spec_compliance": {
            f"{m} @ {t}": {
                label: {
                    "ok": c.get("ok", 0),
                    "mismatch": c.get("mismatch", 0),
                    "unverifiable": c.get("unverifiable", 0),
                    "total": sum(c.values()),
                    "match_rate": round(c.get("ok", 0) / sum(c.values()), 4)
                    if sum(c.values()) else None,
                    "match_rate_ci95": wilson_ci(c.get("ok", 0), sum(c.values())),
                }
                for label, c in sorted(labels.items())
            }
            for (m, t), labels in sorted(spec.items())
        },
        # Honest relabel: what the labeler actually *achieved* per label,
        # independent of what was requested. This is the real distribution of
        # tone/difficulty/pretext in the delivered prose.
        "achieved_distribution": {
            f"{m} @ {t}": {
                label: dict(sorted(c.items()))
                for label, c in sorted(labels.items())
            }
            for (m, t), labels in sorted(achieved.items())
        },
    }
    return out


def markdown(comp: dict, n_total: int) -> str:
    lines = [
        f"# Reliability matrix — summary ({n_total} executions recorded)",
        "",
        "## 1 · Delivery guarantee (assembler baseline, not a model result)",
        "",
        "Every completed campaign passes all five coherence checks **by",
        "construction**: the deterministic assembler stamps persona, tracking",
        "token, schedule, references and provenance, so the model's prose cannot",
        "break structural coherence. A 100 % pass rate here is an invariant of the",
        "pipeline — it does **not** measure the LLM, only that the assembler holds.",
        "The real model signal is the *content* quality (label audit, quality",
        "flags) reported separately.",
        "",
        "Rates are computed **among completed campaigns**; failed/timeout runs are",
        "listed separately so a guarantee number never hides dropped executions.",
        "",
        "| model × temperature | total | completed | failed/timeout | all_passed | rate (completed) | 95% CI |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, v in comp["compliance"].items():
        rate = v["compliance_rate_among_completed"]
        lines.append(
            f"| {label} | {v['total']} | {v['completed']} | {v['failed_or_timeout']} "
            f"| {v['all_passed']} | {rate if rate is not None else '—'} "
            f"| {_ci_str(v.get('compliance_ci95'))} |"
        )
    lines += ["", "## 2 · Errors by constraint (model × temperature × check)", ""]
    if comp["errors_by_constraint"]:
        lines.append("| model × temperature :: check | count |")
        lines.append("|---|---|")
        for label, n in comp["errors_by_constraint"].items():
            lines.append(f"| {label} | {n} |")
    else:
        lines.append("(no coherence failures recorded)")
    lines += ["", "## 3 · Effort required (split: parse vs refinement)", "",
              "> `improved` counts refined runs whose quality flags actually",
              "> dropped after the critique — the real measure of whether",
              "> self-refinement helps.",
              "",
              "| model × temperature | runs | parse attempts | refine rounds | refined | improved | "
              "mean tokens | duration (s) | critic calls |",
              "|---|---|---|---|---|---|---|---|---|"]
    for label, v in comp["effort"].items():
        lines.append(
            f"| {label} | {v['runs']} | {v['mean_parse_attempts']} "
            f"| {v['mean_refine_rounds']} | {v['refined_runs']} "
            f"| {v['refinements_improved']} "
            f"| {v['mean_total_tokens']} | {v['mean_duration_s']} | {v['critic_calls']} |"
        )
    # R6 — two separate rates.
    lines += ["", "## 4 · Content quality: structural flags (quality scan)", "",
              "Share of completed campaigns with ≥1 quality-scan finding (the",
              "content-quality signal, independent of the structural guarantee).",
              "",
              "| model × temperature | flagged | total | flag rate | 95% CI |",
              "|---|---|---|---|---|"]
    for label, v in comp["structural_flags"].items():
        lines.append(
            f"| {label} | {v['flagged']} | {v['total']} | "
            f"{v['flag_rate'] if v['flag_rate'] is not None else '—'} | "
            f"{_ci_str(v.get('flag_rate_ci95'))} |"
        )
    lines += ["", "## 5 · Spec compliance (label audit) — separate from the guarantee", "",
              "`match_rate` = share of completed campaigns whose generated prose",
              "the deterministic labeler reads as matching the requested label.",
              "(`unverifiable` = no signal; not counted as a match.)",
              "",
              "> **Reading the CI:** two rows whose 95% CIs overlap are **not** a",
              "> distinguishable difference at this sample size — the point rates",
              "> can look far apart and still be noise. The CI also depends on the",
              "> labeler being calibrated (see the gold-label validation); it",
              "> quantifies sampling error, not the labeler's own bias.",
              "",
              "| model × temperature | label | ok | mismatch | unverifiable | match rate | 95% CI |",
              "|---|---|---|---|---|---|---|"]
    for label, labels in comp["spec_compliance"].items():
        for lab, v in labels.items():
            lines.append(
                f"| {label} | {lab} | {v['ok']} | {v['mismatch']} "
                f"| {v['unverifiable']} | "
                f"{v['match_rate'] if v['match_rate'] is not None else '—'} | "
                f"{_ci_str(v.get('match_rate_ci95'))} |"
            )
    lines += ["", "## 6 · Achieved distribution (honest relabel)", "",
              "What the labeler actually *detected* in the delivered prose,",
              "independent of what was requested. This is the corpus's real",
              "label distribution — a consumer should read this column, not only",
              "the requested `spec` label.",
              "",
              "| model × temperature | label | achieved distribution |",
              "|---|---|---|"]
    for label, labels in comp["achieved_distribution"].items():
        for lab, dist in labels.items():
            pretty = ", ".join(f"{val}:{n}" for val, n in dist.items()) or "(none)"
            lines.append(f"| {label} | {lab} | {pretty} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Reproducibility (--repro): re-run completed runs with the same config/seed
# --------------------------------------------------------------------------- #


def _deterministic_dump(campaign: dict) -> dict:
    """Campaign with the stochastic prose fields blanked, for a
    deterministic-layer hash (ids, persona, URLs, schedule, provenance)."""
    c = copy.deepcopy(campaign)
    for m in c.get("messages", []):
        if "subject" in m:
            m["subject"] = ""
        m["body"] = ""
    return c


def _hash(obj) -> str:
    from hashlib import sha256

    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run_repro(out: Path, model: str, run_timeout: int) -> int:
    """Re-run every completed run of one model with identical config/semilla and
    compare full hash vs deterministic-layer hash vs prose text."""
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    adk_model, _label = model_ref(model)
    os.environ["ADK_MODEL"] = adk_model
    os.environ["ADK_MODEL_TRACE_FILE"] = \
        str(out / "models" / sanitize(model) / ".llm_trace.repro.jsonl")

    from agent.driver import run_pipeline_with_info
    from generator_agent.catalog import profile_for
    from quality_agent.scan import scan_campaign

    mission = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
    signal.signal(signal.SIGALRM, _alarm_handler)

    by_id = {}
    manifest = out / "runs.jsonl"
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_id[rec["run_id"]] = rec

    todo = [r for r in plan["runs"] if r["model"] == model
            and by_id.get(r["run_id"], {}).get("status") == "ok"]
    rows = []
    for run in todo:
        original = by_id[run["run_id"]]
        rerun = dict(run)
        rerun["run_id"] = run["run_id"] + "-repro"
        record = run_one(rerun, mission, out, run_timeout,
                         run_pipeline_with_info, profile_for, scan_campaign)
        if record["status"] != "ok":
            rows.append({"run_id": run["run_id"], "status": record["status"],
                         "note": record["error"]})
            continue
        orig_campaign = json.loads(
            (out / original["dir"] / "generated_campaign.json").read_text())
        new_campaign = json.loads(
            (out / record["dir"] / "generated_campaign.json").read_text())
        orig_det = _deterministic_dump(orig_campaign)
        new_det = _deterministic_dump(new_campaign)

        def prose(c):
            parts = []
            for m in c.get("messages", []):
                subject = m.get("subject") or ""
                body = m.get("body") or ""
                parts.append(subject + "\n" + body)
            return parts

        rows.append({
            "run_id": run["run_id"],
            "status": "repro_ok",
            "full_hash_identical": _hash(orig_campaign) == _hash(new_campaign),
            "deterministic_hash_identical": _hash(orig_det) == _hash(new_det),
            "prose_identical": prose(orig_campaign) == prose(new_campaign),
        })
    (out / "reproducibility.json").write_text(
        json.dumps({"model": model, "runs": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    identical_det = sum(1 for r in rows if r.get("deterministic_hash_identical"))
    identical_text = sum(1 for r in rows if r.get("prose_identical"))
    print(f"[repro] {model}: {len(rows)} runs, deterministic-identical "
          f"{identical_det}/{len(rows)}, prose-identical "
          f"{identical_text}/{len(rows)}", flush=True)
    return 0


def run_repro_parent(out: Path, models: str | None, workers: int, run_timeout: int) -> int:
    """Launch one repro child per model (mirrors run_parent's subprocess shape)."""
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    model_list = ([m.strip() for m in models.split(",") if m.strip()]
                  if models else plan["design"]["models"])
    for start in range(0, len(model_list), workers):
        batch = model_list[start:start + workers]
        procs = []
        for model in batch:
            (out / "models" / sanitize(model)).mkdir(parents=True, exist_ok=True)
            log = (out / "models" / sanitize(model) / "repro.log").open("w", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--repro-child",
                 str(out), model, "--run-timeout", str(run_timeout)],
                cwd=REPO_ROOT, stdout=log, stderr=subprocess.STDOUT)
            procs.append((model, proc, log))
        for model, proc, log in procs:
            rc = proc.wait()
            log.close()
            print(f"{model}: rc={rc}")
            if rc != 0:
                lines = (out / "models" / sanitize(model) / "repro.log") \
                    .read_text(encoding="utf-8").splitlines()
                for line in lines[-6:]:
                    print(f"     {line}")
    return 0


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true",
                        help="verify provider receives temp/max_tokens/seed")
    parser.add_argument("--report", metavar="OUT",
                        help="aggregate a finished/paused run directory")
    parser.add_argument("--repro", metavar="OUT",
                        help="re-run completed runs at identical config/seed and "
                             "compare dominant vs prose hashes")
    parser.add_argument("--child", nargs=2, metavar=("OUT", "MODEL_INDEX"),
                        help="internal: run one model's executions")
    parser.add_argument("--repro-child", nargs=2, metavar=("OUT", "MODEL_INDEX"),
                        help="internal: reproducibility for one model")
    parser.add_argument("--out", default=None,
                        help="output directory (default: experiment/reliability-<ts>)")
    parser.add_argument("--models",
                        help="comma-separated model list (default: qwen3:8b, "
                             "llama3.1:8b, phi4-mini:latest)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="model children running in parallel")
    parser.add_argument("--run-timeout", type=int, default=DEFAULT_RUN_TIMEOUT_S,
                        help="wall-clock seconds per execution")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="skip the model/critic reachability check before the run")
    args = parser.parse_args()

    if args.verify:
        raise SystemExit(run_verify())
    if args.report:
        raise SystemExit(run_report(Path(args.report)))
    if args.child:
        raise SystemExit(run_child(Path(args.child[0]), int(args.child[1]),
                                   args.run_timeout))
    if args.repro_child:
        raise SystemExit(run_repro(Path(args.repro_child[0]),
                                   args.repro_child[1], args.run_timeout))
    if args.repro:
        raise SystemExit(run_repro_parent(Path(args.repro), args.models,
                                          args.workers, args.run_timeout))

    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models else list(DEFAULT_MODELS)
    )
    if not models:
        raise SystemExit("no models — is the Ollama daemon running?")
    out = Path(args.out or
               f"experiment/reliability-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    raise SystemExit(run_parent(out, models, args.workers, args.run_timeout,
                                skip_preflight=args.skip_preflight))


if __name__ == "__main__":
    main()
