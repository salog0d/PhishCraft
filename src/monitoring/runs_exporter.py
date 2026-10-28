"""Prometheus exporter for the PhishCraft variety experiment.

Serves ``/metrics`` with *gauges* derived at scrape time from the append-only
``runs.jsonl`` manifests and per-run ``llm_trace.jsonl`` files the experiment
harness writes. Gauges (not counters) because the experiment children are
short-lived subprocesses: nothing survives to keep counters, and the manifest
is the source of truth. PromQL rates come from ``delta()``.

Configuration (env):

- ``RUNS_EXPORTER_DIRS`` — comma-separated directories scanned recursively
  for ``runs.jsonl`` (default: ``experiment``). Each manifest becomes an
  ``experiment`` label (its parent directory name).
- ``RUNS_EXPORTER_PORT`` — listen port (default 9091).

Per-file parse results are cached by (mtime, size), so unchanged manifests
and traces are not re-read on every scrape.

Run directly on the host (needs the repo paths):

    venv/bin/python monitoring/runs_exporter.py

or as the compose service ``runs-exporter`` with ``./experiment`` mounted.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from prometheus_client import (
    CollectorRegistry,
    start_http_server,
)
from prometheus_client.core import GaugeMetricFamily

DEFAULT_DIRS = "experiment"
DEFAULT_PORT = 9091

QUANTILES = ("mean", "p50", "p95", "max")

# --------------------------------------------------------------------------- #
# Cached file reading
# --------------------------------------------------------------------------- #


class _Cache:
    """path -> (mtime_ns, size, value); hits skip re-reading unchanged files."""

    def __init__(self) -> None:
        self._files: dict[Path, tuple[int, int, object]] = {}

    def get(self, path: Path) -> tuple[object | None, bool]:
        try:
            st = path.stat()
        except OSError:
            return None, False
        hit = self._files.get(path)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2], True
        return None, False

    def put(self, path: Path, mtime_ns: int, size: int, value: object) -> None:
        self._files[path] = (mtime_ns, size, value)


def _read_jsonl(path: Path, cache: _Cache) -> list[dict] | None:
    """Parse one JSONL file (cached); None when missing/unparseable."""
    cached, hit = cache.get(path)
    if hit:
        return cached  # type: ignore[return-value]
    try:
        st = path.stat()
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        cache.put(path, st.st_mtime_ns, st.st_size, records)
        return records
    except OSError:
        cache.put(path, 0, 0, None)
        return None


# --------------------------------------------------------------------------- #
# Loading + aggregation
# --------------------------------------------------------------------------- #


def _quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {
        "mean": sum(s) / n,
        "p50": s[n // 2],
        "p95": s[min(n - 1, int(n * 0.95))],
        "max": s[-1],
    }


def _aggregate(dirs: list[str], cache: _Cache) -> dict:
    """Read every manifest + trace once and fold into per-(experiment, model)."""
    runs: dict[tuple[str, str], Counter] = defaultdict(Counter)
    durations: dict[tuple[str, str], list] = defaultdict(list)
    findings: dict[tuple[str, str], Counter] = defaultdict(Counter)
    flagged: dict[tuple[str, str], Counter] = defaultdict(Counter)
    contaminated: dict[tuple[str, str], Counter] = defaultdict(Counter)
    mismatches: dict[tuple[str, str], Counter] = defaultdict(Counter)
    unverifiable: dict[tuple[str, str], Counter] = defaultdict(Counter)
    coherence: dict[tuple[str, str], Counter] = defaultdict(Counter)
    attempts: dict[tuple[str, str], int] = defaultdict(int)
    refined: dict[tuple[str, str], int] = defaultdict(int)
    raw_violations: dict[tuple[str, str], int] = defaultdict(int)
    strip_messages: dict[tuple[str, str], int] = defaultdict(int)
    strip_chars: dict[tuple[str, str], int] = defaultdict(int)

    llm_calls: dict[tuple[str, str], int] = defaultdict(int)
    llm_errors: dict[tuple[str, str], int] = defaultdict(int)
    llm_tokens: dict[tuple[str, str, str], int] = defaultdict(int)
    llm_thinking: dict[tuple[str, str], int] = defaultdict(int)
    llm_durations: dict[tuple[str, str], list] = defaultdict(list)

    for base in dirs:
        root = Path(base).expanduser()
        if not root.is_dir():
            continue
        for manifest in sorted(root.rglob("runs.jsonl")):
            out_dir = manifest.parent
            experiment = out_dir.name
            lines = _read_jsonl(manifest, cache) or []
            # Dedupe by run_id — last manifest line wins (retries append).
            by_id: dict[str, dict] = {}
            for rec in lines:
                if rec.get("run_id"):
                    by_id[rec["run_id"]] = rec
            for rec in by_id.values():
                model = rec.get("model") or "unknown"
                key = (experiment, model)
                runs[key][rec.get("status") or "unknown"] += 1
                if rec.get("duration_ms"):
                    durations[key].append(float(rec["duration_ms"]) / 1000.0)

                run_info = rec.get("run_info") or {}
                if run_info.get("n_attempts"):
                    attempts[key] += int(run_info["n_attempts"])
                if run_info.get("refined"):
                    refined[key] += 1
                raw_violations[key] += int(rec.get("raw_link_violations") or 0)

                for check in rec.get("failing_checks") or []:
                    coherence[key][check] += 1

                quality = rec.get("quality") or {}
                for check, count in (rec.get("quality_counts") or {}).items():
                    findings[key][check] += int(count or 0)
                for check in quality.get("failing") or []:
                    flagged[key][check] += 1
                for check in quality.get("contamination") or []:
                    contaminated[key][check] += 1
                for label in quality.get("label_mismatches") or []:
                    mismatches[key][label] += 1
                for label, status in (quality.get("label_statuses") or {}).items():
                    if status == "unverifiable":
                        unverifiable[key][label] += 1
                strip_messages[key] += int(
                    quality.get("strip_affected_messages") or 0
                )
                strip_chars[key] += int(quality.get("strip_stripped_chars") or 0)

                if rec.get("status") == "ok" and rec.get("dir"):
                    trace_path = out_dir / rec["dir"] / "llm_trace.jsonl"
                    _fold_trace(
                        key, trace_path, cache,
                        llm_calls, llm_errors, llm_tokens, llm_thinking,
                        llm_durations,
                    )

    return {
        "runs": runs,
        "durations": durations,
        "findings": findings,
        "flagged": flagged,
        "contaminated": contaminated,
        "mismatches": mismatches,
        "unverifiable": unverifiable,
        "coherence": coherence,
        "attempts": attempts,
        "refined": refined,
        "raw_violations": raw_violations,
        "strip_messages": strip_messages,
        "strip_chars": strip_chars,
        "llm_calls": llm_calls,
        "llm_errors": llm_errors,
        "llm_tokens": llm_tokens,
        "llm_thinking": llm_thinking,
        "llm_durations": llm_durations,
    }


def _fold_trace(
    key: tuple[str, str],
    trace_path: Path,
    cache: _Cache,
    llm_calls: dict,
    llm_errors: dict,
    llm_tokens: dict,
    llm_thinking: dict,
    llm_durations: dict,
) -> None:
    """Fold one run's llm_trace.jsonl into the LLM aggregates."""
    lines = _read_jsonl(trace_path, cache)
    if not lines:
        return
    for rec in lines:
        llm_calls[key] += 1
        if rec.get("error"):
            llm_errors[key] += 1
        if rec.get("duration_s") is not None:
            llm_durations[key].append(float(rec["duration_s"]))
        usage = ((rec.get("response") or {}).get("usage")) or {}
        for token_type, field in (
            ("prompt", "prompt_tokens"),
            ("completion", "completion_tokens"),
            ("total", "total_tokens"),
        ):
            value = usage.get(field)
            if value:
                llm_tokens[(key[0], key[1], token_type)] += int(value)
        thought = (rec.get("response") or {}).get("thought")
        if thought:
            llm_thinking[key] += len(thought)


# --------------------------------------------------------------------------- #
# Collector
# --------------------------------------------------------------------------- #


class RunsCollector:
    def __init__(self, dirs: list[str]) -> None:
        self.dirs = dirs
        self.cache = _Cache()
        self.errors = 0

    def collect(self):  # noqa: PLR0912 — one family per metric by design
        try:
            data = _aggregate(self.dirs, self.cache)
        except Exception as exc:  # the exporter must never 500 on bad data
            self.errors += 1
            family = GaugeMetricFamily(
                "phishcraft_experiment_exporter_errors_total",
                "Aggregation failures in the runs exporter (1 = broken scrape).",
            )
            family.add_metric([], float(self.errors))
            yield family
            return

        family = GaugeMetricFamily(
            "phishcraft_experiment_exporter_errors_total",
            "Aggregation failures in the runs exporter (1 = broken scrape).",
        )
        family.add_metric([], float(self.errors))
        yield family

        def emit(
            name: str, help_text: str, labels: tuple[str, ...], rows
        ) -> None:
            fam = GaugeMetricFamily(
                f"phishcraft_experiment_{name}", help_text, labels=list(labels)
            )
            for label_values, value in rows:
                fam.add_metric(list(label_values), float(value))
            yield fam

        yield from emit(
            "runs_total", "Recorded campaigns by status.", ("experiment", "model", "status"),
            (((*key, status), count)
             for key, counter in data["runs"].items()
             for status, count in counter.items()),
        )
        yield from emit(
            "duration_seconds",
            "Campaign wall-clock seconds by quantile.",
            ("experiment", "model", "quantile"),
            (((*key, q), v)
             for key, values in data["durations"].items()
             for q, v in _quantiles(values).items()),
        )
        yield from emit(
            "quality_findings_total",
            "Accumulated quality findings per check.",
            ("experiment", "model", "check"),
            (((*key, check), count)
             for key, counter in data["findings"].items()
             for check, count in counter.items()),
        )
        yield from emit(
            "campaigns_flagged_total",
            "Campaigns with >= 1 finding of that check.",
            ("experiment", "model", "check"),
            (((*key, check), count)
             for key, counter in data["flagged"].items()
             for check, count in counter.items()),
        )
        yield from emit(
            "contaminated_total",
            "Campaigns failing a contamination check.",
            ("experiment", "model", "check"),
            (((*key, check), count)
             for key, counter in data["contaminated"].items()
             for check, count in counter.items()),
        )
        yield from emit(
            "label_mismatches_total",
            "Label-audit mismatches (spec label vs. implied label).",
            ("experiment", "model", "label"),
            (((*key, label), count)
             for key, counter in data["mismatches"].items()
             for label, count in counter.items()),
        )
        yield from emit(
            "label_unverifiable_total",
            "Label-audit deferred (unverifiable) verdicts.",
            ("experiment", "model", "label"),
            (((*key, label), count)
             for key, counter in data["unverifiable"].items()
             for label, count in counter.items()),
        )
        yield from emit(
            "coherence_failures_total",
            "Validator (coherence) failures per check.",
            ("experiment", "model", "check"),
            (((*key, check), count)
             for key, counter in data["coherence"].items()
             for check, count in counter.items()),
        )
        yield from emit(
            "attempts_total",
            "Total parse/refinement attempts across campaigns.",
            ("experiment", "model"),
            ((key, count) for key, count in data["attempts"].items()),
        )
        yield from emit(
            "refined_total",
            "Campaigns that went through a self-refinement round.",
            ("experiment", "model"),
            ((key, count) for key, count in data["refined"].items()),
        )
        yield from emit(
            "raw_link_violations_total",
            "Stale tracking tokens the LLM wrote (first-attempt evidence).",
            ("experiment", "model"),
            ((key, count) for key, count in data["raw_violations"].items()),
        )
        yield from emit(
            "strip_affected_messages_total",
            "Messages a stage-direction strip would touch.",
            ("experiment", "model"),
            ((key, count) for key, count in data["strip_messages"].items()),
        )
        yield from emit(
            "strip_chars_total",
            "Characters a stage-direction strip would remove.",
            ("experiment", "model"),
            ((key, count) for key, count in data["strip_chars"].items()),
        )

        yield from emit(
            "llm_calls_total", "LLM calls recorded in llm_trace.jsonl.",
            ("experiment", "model"),
            ((key, count) for key, count in data["llm_calls"].items()),
        )
        yield from emit(
            "llm_errors_total", "LLM calls that failed (error records).",
            ("experiment", "model"),
            ((key, count) for key, count in data["llm_errors"].items()),
        )
        yield from emit(
            "llm_tokens_total", "Tokens consumed, by type.",
            ("experiment", "model", "type"),
            ((key, count) for key, count in data["llm_tokens"].items()),
        )
        yield from emit(
            "llm_thinking_chars_total",
            "Characters of reasoning (thought parts) emitted.",
            ("experiment", "model"),
            ((key, count) for key, count in data["llm_thinking"].items()),
        )
        yield from emit(
            "llm_duration_seconds", "LLM call wall-clock seconds by quantile.",
            ("experiment", "model", "quantile"),
            (((*key, q), v)
             for key, values in data["llm_durations"].items()
             for q, v in _quantiles(values).items()),
        )


def main() -> None:
    dirs = [
        d.strip()
        for d in os.getenv("RUNS_EXPORTER_DIRS", DEFAULT_DIRS).split(",")
        if d.strip()
    ]
    port = int(os.getenv("RUNS_EXPORTER_PORT", DEFAULT_PORT))
    # CollectorRegistry() auto-registers the platform/process/GC collectors.
    registry = CollectorRegistry()
    registry.register(RunsCollector(dirs))
    start_http_server(port, registry=registry)
    print(f"runs exporter listening on :{port} (dirs: {', '.join(dirs)})",
          flush=True)
    import time

    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
