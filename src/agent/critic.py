"""Self-refinement critic: an LLM that turns structural findings into a fix list.

The deterministic validator and quality scanner know *exactly* what is wrong
(the coherence failures and the stage-direction / meta-bleed findings). This
module hands that evidence to a critic LLM, which writes a *general* critique
the content agent can follow to regenerate the subject/body — the Reflexion
loop's "self-critique" step, without a hand-written heuristic per failure mode.

The critique is evidence-driven, never a repair: it is *appended to the next
generation prompt* so the model re-aims; the deterministic layer (persona,
tokens, schedule, provenance) is never touched.
"""

from __future__ import annotations

import json
import os
import time

from google.adk.models import LlmRequest
from google.genai import types

from agent.config import resolve_critic_model

# The structural quality checks worth feeding back (everything else — label
# audit, contamination, strip stats — is evidence the scanner records but the
# content agent cannot meaningfully re-aim at from a critique).
STRUCTURAL_CHECKS = ("stage_direction", "meta_bleed")

_CRITIQUE_SYSTEM = (
    "You are the critic in a Reflexion loop for a phishing-simulation campaign "
    "generator. You receive the structural problems a deterministic validator "
    "found in a generated email/SMS campaign. Write ONLY a short critique that "
    "tells the content generator what to fix and why, so it can rewrite the "
    "subject and bodies correctly. Never invent new problems, never suggest new "
    "content, never write a URL or tracking token. Keep it under 5 sentences."
)


def findings_summary(campaign, report, quality,
                     label_mismatches: list[str] | None = None) -> list[str]:
    """The structural problems to feed the critic, one line each.

    Coherence (validator) failures get their ``detail``; the quality scan's
    stage-direction and meta-bleed findings get their per-field evidence;
    ``label_mismatches`` (tone/difficulty) are re-aimable content problems the
    critic should tell the generator to fix. Returns [] when nothing is wrong.
    """
    problems: list[str] = []

    for result in report.results:
        if not result.passed:
            problems.append(f"[coherence:{result.check.value}] {result.detail}")

    if quality is not None:
        for result in quality.results:
            if result.check not in STRUCTURAL_CHECKS or result.passed:
                continue
            for finding in result.findings:
                loc = f"{finding.field}: {finding.detail}"
                if finding.excerpt:
                    loc += f" (e.g. {finding.excerpt!r})"
                problems.append(f"[{result.check}] {loc}")

    for label in label_mismatches or []:
        requested = (
            quality.label_audit.spec_labels.get(label) if quality is not None
            else None
        )
        predicted = (
            quality.label_audit.predicted_labels.get(label) if quality is not None
            else None
        )
        problems.append(
            f"[label_mismatch:{label}] requested '{requested}' but the prose "
            f"reads like '{predicted}' — rewrite to match the requested {label}."
        )

    return problems


def _critique_prompt(problems: list[str]) -> str:
    listing = "\n".join(f"- {p}" for p in problems)
    return (
        f"The generated campaign has these structural problems:\n{listing}\n\n"
        "Write the critique directly to the content generator: what to remove "
        "(stage directions, meta commentary), what to keep, and how to adjust "
        "the tone/difficulty so it matches the requested label. Never write "
        "URLs or bracket placeholders."
    )


async def critique_campaign(campaign, report, quality,
                            label_mismatches: list[str] | None = None) -> str | None:
    """Run the critic LLM; returns the critique text, or None when nothing to fix.

    The campaign is passed only so the critic can reference it if needed; it is
    never mutated. On any error the critic is skipped (the deterministic
    backstop — assembler normalization — still holds).
    ``label_mismatches`` feeds the tone/difficulty re-aimable problems into the
    critique so the critic can tell the generator to fix them.
    """
    problems = findings_summary(campaign, report, quality, label_mismatches)
    if not problems:
        return None
    model = resolve_critic_model()
    try:
        request = LlmRequest(
            model=getattr(model, "model", None),
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=_critique_prompt(problems))],
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=_CRITIQUE_SYSTEM, temperature=0.0
            ),
        )
        # generate_content_async is an async generator even when stream=False:
        # collect every yielded response and read the final content. Reasoning
        # models (deepseek-r1) split their thinking into ``thought=True`` parts;
        # keep only the answer — the critique must not carry the preamble.
        text = ""
        start = time.monotonic()
        final_response = None
        async for response in model.generate_content_async(llm_request=request):
            final_response = response
            content = getattr(response, "content", None)
            for part in getattr(content, "parts", None) or []:
                if getattr(part, "text", None) and not getattr(part, "thought", False):
                    text += part.text
    except Exception:
        return None  # never break the pipeline over critique bookkeeping
    _trace_critic(model, final_response, time.monotonic() - start)
    return text.strip() or None


def _trace_critic(model, response, duration_s: float) -> None:
    """Append the critic call to ``ADK_MODEL_TRACE_FILE`` (same shape as the
    generator's trace) so token/latency totals include the model that proposes
    corrections. No-op when tracing is disabled."""
    path = os.getenv("ADK_MODEL_TRACE_FILE")
    if not path:
        return
    usage = getattr(response, "usage_metadata", None) if response is not None else None
    record = {
        "seq": None,
        "agent": "critic",
        "model": getattr(model, "model", None),
        "duration_s": round(duration_s, 3),
        "response": {
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "completion_tokens": getattr(usage, "candidates_token_count", None),
                "total_tokens": getattr(usage, "total_token_count", None),
            },
        },
    }
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
