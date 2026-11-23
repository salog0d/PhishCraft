"""Run one spec, validate, and record — never crash on a bad generation.

Every run also gets the post-run **quality scan** (``quality_agent.scan`` —
the COVA-X-style lifecycle: generation artifacts, contamination, automated
label audit, stage-direction stripping stats). Quality findings are recorded
alongside the coherence results as data, never used to repair the artifact.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field


@dataclass
class RunRecord:
    spec_id: str
    run_index: int
    adapter: str
    model: str
    seed: int
    status: str  # "ok" | "generation_error"
    campaign_hash: str | None = None
    failing_checks: list = field(default_factory=list)
    raw_link_violations: int = 0  # stale tokens in the final (delivered) artifact
    report: dict | None = None
    error: str | None = None
    duration_ms: int = 0
    # Self-refinement metadata (from the driver's run_info):
    n_attempts: int | None = None
    refined: bool = False  # at least one refinement round ran
    first_attempt_raw_link_violations: int | None = None  # pre-refinement raw metric
    # Post-run quality scan (quality_agent.scan — the paper's lifecycle):
    quality_flags: int = 0                # total findings across all checks
    quality_failing: list = field(default_factory=list)  # check categories hit
    contamination: list = field(default_factory=list)    # contamination categories hit
    label_mismatches: list = field(default_factory=list)  # labels disagreeing with spec
    strip_affected_messages: int = 0      # messages a strip pass would touch
    strip_stripped_chars: int = 0         # chars a strip pass would remove
    quality_report: dict | None = None
    prose: str | None = None              # subjects+bodies, for inter-run diversity


def canonical_hash(campaign) -> str:
    data = json.dumps(
        campaign.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(data.encode()).hexdigest()


def deterministic_layer_hash(campaign) -> str:
    """Hash of the campaign with the stochastic (LLM-written) fields blanked.

    The deterministic layer — ids, persona, recipient, URLs, references,
    schedule, provenance — must reproduce byte-for-byte; only subject/body
    (and the fields that capture them: generated_at, adapter_latency_ms,
    link_fixes) are allowed to differ.
    """
    data = campaign.model_dump(mode="json")
    for m in data["messages"]:
        m["subject"] = None
        m["body"] = None
        m["link_fixes"] = None
        m["provenance"]["generated_at"] = None
        m["provenance"]["adapter_latency_ms"] = None
    dumped = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(dumped.encode()).hexdigest()


def run_spec(spec, adapter, run_index: int, mission: dict) -> RunRecord:
    start = time.perf_counter()
    try:
        run_with_info = getattr(adapter, "run_with_info", None)
        if run_with_info is not None:
            campaign, report, info = run_with_info(spec.to_dict(), mission)
        else:
            campaign, report = adapter.run(spec.to_dict(), mission)
            info = {}
    except Exception as exc:  # ValidationError, timeouts, provider errors...
        return RunRecord(
            spec_id=spec.spec_id,
            run_index=run_index,
            adapter=adapter.name,
            model=spec.model["name"],
            seed=spec.seed,
            status="generation_error",
            error=f"{type(exc).__name__}: {exc}",
            duration_ms=int((time.perf_counter() - start) * 1000),
        )
    record = RunRecord(
        spec_id=spec.spec_id,
        run_index=run_index,
        adapter=adapter.name,
        model=spec.model["name"],
        seed=spec.seed,
        status="ok",
        campaign_hash=canonical_hash(campaign),
        failing_checks=[r.check.value for r in report.results if not r.passed],
        # Raw link violations on the delivered (post-refinement) artifact.
        raw_link_violations=sum(len(m.link_fixes) for m in campaign.messages),
        report=report.model_dump(),
        duration_ms=int((time.perf_counter() - start) * 1000),
        n_attempts=info.get("n_attempts"),
        refined=bool(info.get("refined", False)),
        first_attempt_raw_link_violations=info.get(
            "first_attempt_raw_link_violations"
        ),
    )

    # Post-run quality scan (the paper's lifecycle, on every run). The scan is
    # deterministic and never raises; if it ever did, the run must still be
    # recorded — a scanner bug is not a generation failure.
    try:
        from quality_agent.scan import scan_campaign

        quality = scan_campaign(campaign, spec=spec.to_dict(), mission=mission)
    except Exception as exc:  # pragma: no cover — defensive
        record.error = f"quality_scan_error: {type(exc).__name__}: {exc}"
        return record
    record.quality_flags = quality.n_flags
    record.quality_failing = [r.check for r in quality.results if not r.passed]
    record.contamination = [
        r.check for r in quality.results
        if not r.passed and "contamination" in r.check
    ]
    record.label_mismatches = list(quality.label_audit.mismatches)
    record.strip_affected_messages = quality.strip_stats.affected_messages
    record.strip_stripped_chars = quality.strip_stats.stripped_chars
    record.quality_report = quality.model_dump()
    record.prose = "\n".join(
        part for m in campaign.messages
        for part in ((m.subject or ""), m.body) if part
    )
    return record
