"""Shared Prometheus instrumentation for PhishCraft.

Every metric lives here under the ``phishcraft_`` namespace so the pipeline,
the app, and the exporters agree on names and labels. The module degrades to
no-ops when ``prometheus-client`` is not installed, so importing it never
breaks a generation run.

Two families coexist by design:

- **Process metrics** (``phishcraft_llm_*``, ``phishcraft_pipeline_*``,
  ``phishcraft_http_*``): counters/histograms recorded live inside the ADK
  callbacks, the driver, and the FastAPI app. Useful for long-lived processes
  (API service, interactive shell).

- **Experiment metrics** (``phishcraft_experiment_*``): served by
  ``monitoring/runs_exporter.py`` from the append-only ``runs.jsonl`` and
  ``llm_trace.jsonl`` files. These are *gauges* (derived from state at scrape
  time), because the experiment children are short-lived subprocesses whose
  in-process counters would never be scraped.
"""

from __future__ import annotations

try:
    from prometheus_client import Counter, Gauge, Histogram

    _HAS_PROMETHEUS = True
except ImportError:  # monitoring optional — never break the pipeline
    _HAS_PROMETHEUS = False


class _NoopMetric:
    """Accepts any chained call and does nothing (prometheus_client absent)."""

    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None


_NOOP = _NoopMetric()


def has_prometheus() -> bool:
    return _HAS_PROMETHEUS


def normalize_model(model: str | None) -> str:
    """'ollama/qwen3:8b' -> 'qwen3:8b' (single label across all exporters)."""
    if not model:
        return "unknown"
    for prefix in ("ollama/", "deepseek/", "openai/", "anthropic/"):
        if model.startswith(prefix):
            return model[len(prefix):]
    return model


# LLM call latency histogram buckets: sub-second responses up to
# multi-minute reasoning runs on the local GPU.
_LLM_BUCKETS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0)

if _HAS_PROMETHEUS:
    # --- live LLM call metrics (recorded in agent/model_trace.py) -----------
    LLM_CALLS = Counter(
        "phishcraft_llm_calls_total",
        "LLM calls completed, by outcome",
        ["model", "agent", "status"],  # status: ok | error
    )
    LLM_DURATION = Histogram(
        "phishcraft_llm_call_duration_seconds",
        "Wall-clock seconds per LLM call",
        ["model"],
        buckets=_LLM_BUCKETS,
    )
    LLM_TOKENS = Counter(
        "phishcraft_llm_tokens_total",
        "Tokens consumed by LLM calls",
        ["model", "type"],  # type: prompt | completion | total
    )
    LLM_THINKING_CHARS = Counter(
        "phishcraft_llm_thinking_chars_total",
        "Characters of reasoning (thought parts) emitted by the model",
        ["model"],
    )

    # --- pipeline-level metrics (recorded in agent/driver.py) --------------
    PIPELINE_RUNS = Counter(
        "phishcraft_pipeline_runs_total",
        "Campaign generation runs by outcome",
        ["model", "status"],  # status: ok | generation_error | timeout
    )
    PIPELINE_ATTEMPTS = Counter(
        "phishcraft_pipeline_attempts_total",
        "Parse/refinement attempts across all runs",
        ["model"],
    )
    PIPELINE_REFINEMENTS = Counter(
        "phishcraft_pipeline_refinements_total",
        "Self-refinement rounds across all runs",
        ["model"],
    )
    PIPELINE_DURATION = Histogram(
        "phishcraft_pipeline_duration_seconds",
        "Wall-clock seconds per campaign generation",
        ["model"],
        buckets=(2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 640.0, 900.0),
    )

    # --- HTTP API metrics (recorded in app/main.py) -------------------------
    HTTP_REQUESTS = Counter(
        "phishcraft_http_requests_total",
        "API requests by outcome",
        ["method", "route", "status"],
    )
    HTTP_DURATION = Histogram(
        "phishcraft_http_request_duration_seconds",
        "API request latency",
        ["method", "route", "status"],
    )
else:
    LLM_CALLS = LLM_DURATION = LLM_TOKENS = LLM_THINKING_CHARS = _NOOP
    PIPELINE_RUNS = PIPELINE_ATTEMPTS = PIPELINE_REFINEMENTS = _NOOP
    PIPELINE_DURATION = _NOOP
    HTTP_REQUESTS = HTTP_DURATION = _NOOP


def record_llm_call(
    *,
    model: str | None,
    agent: str | None,
    status: str,
    duration_s: float | None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    thinking_chars: int = 0,
) -> None:
    """Record one finished LLM call (both metrics families in one call)."""
    if not _HAS_PROMETHEUS:
        return
    model = model or "unknown"
    LLM_CALLS.labels(model=model, agent=agent or "unknown", status=status).inc()
    if duration_s is not None:
        LLM_DURATION.labels(model=model).observe(max(duration_s, 0.0))
    if prompt_tokens:
        LLM_TOKENS.labels(model=model, type="prompt").inc(prompt_tokens)
    if completion_tokens:
        LLM_TOKENS.labels(model=model, type="completion").inc(completion_tokens)
    if total_tokens:
        LLM_TOKENS.labels(model=model, type="total").inc(total_tokens)
    if thinking_chars:
        LLM_THINKING_CHARS.labels(model=model).inc(thinking_chars)


def record_pipeline_run(
    *,
    model: str,
    status: str,
    duration_s: float,
    n_attempts: int = 0,
    refined: bool = False,
) -> None:
    """Record one finished campaign-generation run."""
    if not _HAS_PROMETHEUS:
        return
    PIPELINE_RUNS.labels(model=model, status=status).inc()
    PIPELINE_DURATION.labels(model=model).observe(max(duration_s, 0.0))
    if n_attempts:
        PIPELINE_ATTEMPTS.labels(model=model).inc(n_attempts)
    if refined:
        PIPELINE_REFINEMENTS.labels(model=model).inc()
