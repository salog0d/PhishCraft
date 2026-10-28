"""Full LLM call tracing for the pipeline (prompt + answer + thinking trace).

ADK's ``LiteLlm`` wrapper converts the reasoning a model emits (Ollama's
``thinking`` field, litellm's ``reasoning_content``, ...) into response parts
with ``thought=True``. These callbacks capture, for every LLM call:

- the full rendered request (system instruction + user contents),
- the model's thought/reasoning parts and its final answer text, separately,
- usage metadata, error info, and wall-clock duration.

The trace is appended as one JSON object per line (JSONL) to the file named by
``ADK_MODEL_TRACE_FILE``. When that env var is unset the callbacks are no-ops,
so normal runs pay nothing and change nothing.

This is deliberately separate from the console transcript: the experiment
harness points ``ADK_MODEL_TRACE_FILE`` at ``output-<model>/llm_trace.jsonl``
and keeps ``run.log`` for the human-facing pipeline summary.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

try:
    from monitoring import metrics
except ImportError:  # pragma: no cover — metrics are optional
    metrics = None

_WRITE_LOCK = threading.Lock()

# invocation_id -> (seq, start_monotonic, start_utc, request_record)
_pending: dict[str, tuple[int, float, str, dict]] = {}
_seq = 0

_SHIM_INSTALLED = False


def _trace_file() -> str | None:
    return os.getenv("ADK_MODEL_TRACE_FILE") or None


def install_ollama_thinking_shim() -> None:
    """Preserve Ollama's top-level ``thinking`` field through litellm.

    litellm's non-streaming Ollama path (``/api/generate``) only extracts
    reasoning from ``<think>`` tags inside the response text and silently
    drops the separate ``thinking`` field that reasoning models (qwen3, ...)
    return. ADK's LiteLlm wrapper builds thought parts from litellm's
    ``reasoning_content``, so without this shim a traced Ollama run shows an
    empty thought section even though the model did think.

    Idempotent, process-local, and only active when ``ADK_MODEL_TRACE_FILE``
    is set — i.e. inside the experiment's per-model trace runs. The shim only
    copies data litellm already received; it never changes the request.
    """
    global _SHIM_INSTALLED
    if _SHIM_INSTALLED or not _trace_file():
        return
    try:
        from litellm.llms.ollama.completion.transformation import OllamaConfig

        original = OllamaConfig.transform_response
        if getattr(original, "_pt_thinking_shim", False):
            _SHIM_INSTALLED = True
            return

        def patched(self, model, raw_response, *args, **kwargs):
            response = original(self, model, raw_response, *args, **kwargs)
            try:
                payload = raw_response.json()
                thinking = payload.get("thinking") if isinstance(payload, dict) else None
                if not thinking:
                    return response
                message = response.choices[0].message
                existing = getattr(message, "reasoning_content", None)
                message.reasoning_content = (
                    f"{existing}\n{thinking}" if existing else thinking
                )
            except Exception:
                pass  # never break the pipeline over trace bookkeeping
            return response

        patched._pt_thinking_shim = True
        OllamaConfig.transform_response = patched
    except Exception:
        return  # litellm internals moved; trace simply won't carry thinking
    _SHIM_INSTALLED = True


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize_part(part) -> dict:
    """One google.genai.types.Part -> a JSON-safe dict (text/thought/fn-call)."""
    if part is None:
        return {"type": "none"}
    if getattr(part, "text", None):
        return {
            "type": "thought" if part.thought else "text",
            "text": part.text,
        }
    if getattr(part, "function_call", None):
        fc = part.function_call
        return {"type": "function_call", "name": fc.name}
    if getattr(part, "function_response", None):
        fr = part.function_response
        return {"type": "function_response", "name": fr.name}
    if getattr(part, "code_execution_result", None):
        return {"type": "code_execution_result"}
    return {"type": "other"}


def _serialize_contents(contents: list) -> list[dict]:
    """llm_request.contents -> JSON-safe list of {role, parts: [...]}."""
    out = []
    for content in contents or []:
        parts = [p for p in getattr(content, "parts", None) or []]
        if not parts:
            continue
        out.append(
            {
                "role": getattr(content, "role", None),
                "parts": [_serialize_part(p) for p in parts],
            }
        )
    return out


def _serialize_system_instruction(instruction) -> str | None:
    """GenerateContentConfig.system_instruction -> plain text (or None)."""
    if instruction is None:
        return None
    if isinstance(instruction, str):
        return instruction
    # Content, Part, list-of-those, ... — flatten to their text parts.
    items = instruction if isinstance(instruction, list) else [instruction]
    texts = []
    for item in items:
        for part in getattr(item, "parts", None) or []:
            if getattr(part, "text", None):
                texts.append(part.text)
        text = getattr(item, "text", None)
        if text and not texts:
            texts.append(text)
    return "\n".join(texts) if texts else str(instruction)


def before_model_callback(callback_context, llm_request):
    """Stash the call start (and the rendered request when tracing).

    The pending entry is always stashed — even without a trace file — so the
    response callback can record duration metrics for every LLM call.
    """
    key = str(getattr(callback_context, "invocation_id", None))
    path = _trace_file()
    if not path:
        _pending[key] = (None, time.monotonic(), None, None)
        return None
    global _seq
    with _WRITE_LOCK:
        _seq += 1
        seq = _seq
    record = {
        "seq": seq,
        "invocation_id": getattr(callback_context, "invocation_id", None),
        "agent": getattr(callback_context, "agent_name", None),
        "model": getattr(llm_request, "model", None),
        "request": {
            "system_instruction": _serialize_system_instruction(
                getattr(getattr(llm_request, "config", None), "system_instruction", None)
            ),
            "contents": _serialize_contents(getattr(llm_request, "contents", [])),
        },
    }
    _pending[key] = (
        seq,
        time.monotonic(),
        _now_utc(),
        record,
    )
    return None


def after_model_callback(callback_context, llm_response):
    """Pair the response (thinking separated from the answer) with its request.

    Metrics are recorded for every call; the trace line is only written when
    ``ADK_MODEL_TRACE_FILE`` is set.
    """
    key = str(getattr(callback_context, "invocation_id", None))
    pending = _pending.pop(key, None)
    if pending is None:
        return None
    seq, started_mono, started_utc, record = pending
    duration = round(time.monotonic() - started_mono, 3)

    content = getattr(llm_response, "content", None)
    parts = [p for p in getattr(content, "parts", None) or []]
    thoughts = [p.text for p in parts if getattr(p, "text", None) and p.thought]
    usage = getattr(llm_response, "usage_metadata", None)

    if metrics is not None:
        model = (record or {}).get("model") if record else None
        if model is None:
            model = getattr(llm_response, "model_version", None)
        metrics.record_llm_call(
            model=metrics.normalize_model(model),
            agent=(record or {}).get("agent"),
            status="ok",
            duration_s=duration,
            prompt_tokens=getattr(usage, "prompt_token_count", None),
            completion_tokens=getattr(usage, "candidates_token_count", None),
            total_tokens=getattr(usage, "total_token_count", None),
            thinking_chars=sum(len(t) for t in thoughts),
        )

    path = _trace_file()
    if not path:
        return None
    record["ts_utc"] = started_utc
    record["duration_s"] = duration

    answers = [p.text for p in parts if getattr(p, "text", None) and not p.thought]
    record["response"] = {
        "thought": "\n".join(thoughts) if thoughts else None,
        "text": "\n".join(answers) if answers else None,
        "all_parts": [_serialize_part(p) for p in parts],
        "error_code": getattr(llm_response, "error_code", None),
        "error_message": getattr(llm_response, "error_message", None),
    }
    record["response"]["usage"] = {
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "completion_tokens": getattr(usage, "candidates_token_count", None),
        "total_tokens": getattr(usage, "total_token_count", None),
    }
    _append(path, record)
    return None


def on_model_error_callback(callback_context, llm_request, error):
    """Record model-call failures (timeouts, provider errors, ...)."""
    key = str(getattr(callback_context, "invocation_id", None))
    pending = _pending.pop(key, None)
    duration = None
    if pending is not None:
        _seq_stash, started_mono, _started_utc, record = pending
        duration = round(time.monotonic() - started_mono, 3)

    if metrics is not None:
        metrics.record_llm_call(
            model=metrics.normalize_model(getattr(llm_request, "model", None)),
            agent=getattr(callback_context, "agent_name", None),
            status="error",
            duration_s=duration,
        )

    path = _trace_file()
    if not path:
        return None
    if pending is not None:
        seq, started_mono, started_utc, record = pending
        record["ts_utc"] = started_utc
        record["duration_s"] = duration
    else:
        global _seq
        with _WRITE_LOCK:
            _seq += 1
            seq = _seq
        record = {
            "seq": seq,
            "invocation_id": getattr(callback_context, "invocation_id", None),
            "agent": getattr(callback_context, "agent_name", None),
            "model": getattr(llm_request, "model", None),
            "ts_utc": _now_utc(),
            "duration_s": None,
            "request": {
                "system_instruction": _serialize_system_instruction(
                    getattr(
                        getattr(llm_request, "config", None),
                        "system_instruction",
                        None,
                    )
                ),
                "contents": _serialize_contents(getattr(llm_request, "contents", [])),
            },
        }
    record["error"] = {"type": type(error).__name__, "message": str(error)}
    _append(path, record)
    return None


def _append(path: str, record: dict) -> None:
    """Append one JSON line to the trace file (never raise on I/O errors)."""
    try:
        with _WRITE_LOCK, open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, indent=None) + "\n")
    except OSError:
        pass
