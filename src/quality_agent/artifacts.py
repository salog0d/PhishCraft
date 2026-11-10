"""Generation-artifact scanners (COVA-X §IV-A ``scan_generation_quality.py``).

Five artifact types, adapted to the email+SMS campaign domain:

- ``dialogue_collapse`` — role confusion: prose signed by, or addressed to,
  an identity that is neither the campaign persona nor the recipient (the
  paper's "victim writing attacker lines in their own turn").
- ``stage_direction`` — bracket/parenthetical stage directions and leftover
  ``{{cta-link}}`` / ``[EMAIL_SUBJECT]``-style placeholder artifacts in prose.
- ``turn_overflow`` — per-channel length anomalies: messages far past the
  expected size for the channel, or so short they are underdeveloped (the
  paper's minimum-turn-floor discard analogue).
- ``meta_bleed`` — model instruction echo: refusal/apology phrasing, "here is
  the message", or the prompt's own vocabulary leaking into content.
- ``loop_detection`` — repetition: duplicated lines, the subject restated
  verbatim in the body, or the SMS nearly duplicating the email.

Every scanner returns ``list[QualityFinding]`` — findings are data, never
exceptions, and the delivered campaign is never mutated.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.core.schemas import QualityFinding

from quality_agent.lexicon import (
    META_BLEED_PATTERNS,
    STAGE_DIRECTION_PATTERNS,
    compile_patterns,
    excerpt,
)

_META_BLEED = compile_patterns(META_BLEED_PATTERNS)
_STAGE_DIRECTION = compile_patterns(STAGE_DIRECTION_PATTERNS)

# Length thresholds (soft quality limits, not schema caps): email bodies in
# these simulations are short executive lures; SMS bodies are one or two
# sentences. Values far beyond these, or below the underdeveloped floor, are
# quality flags.
LIMITS = {
    "email_subject": {"soft_max": 120, "floor": 5},
    "email_body": {"soft_max": 2_000, "floor": 60},
    "sms_body": {"soft_max": 480, "floor": 15},
}

_GREETING = re.compile(
    r"(?im)^(?:hi|hello|dear|good\s+(?:morning|afternoon|evening))\s+([A-Z][A-Za-z.' -]{1,40})"
)
_SIGNOFF_DASH = re.compile(r"(?m)^\s*[-—–]\s*([A-Z][A-Za-z.' -]{1,40})\s*$")
_SIGNOFF_VALEDICTION = re.compile(
    r"(?im)^\s*(best regards|best|regards|sincerely|warm regards|thanks|"
    r"thank you),?\s*$\n^\s*([A-Z][A-Za-z.' -]{1,40})\s*$"
)
_DUPE_LINE = re.compile(r"(?m)^\s*(.+?)\s*$")


def _name_in(text: str, names: tuple[str, ...], exclude: set[str]) -> str | None:
    """The first known name in ``text`` that is not in ``exclude``, else None."""
    lowered = text.casefold()
    for name in sorted(names, key=len, reverse=True):
        if name.casefold() in exclude:
            continue
        pattern = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])",
                             re.IGNORECASE)
        if pattern.search(text):
            return name
    return None


def scan_dialogue_collapse(
    text: str,
    *,
    field: str,
    persona_name: str,
    recipient_name: str | None,
    known_names: tuple[str, ...],
) -> list[QualityFinding]:
    """Role confusion: prose speaks to / is signed by the wrong identity."""
    findings: list[QualityFinding] = []
    persona_first = persona_name.split()[0]
    recipient_first = recipient_name.split()[0] if recipient_name else ""
    exclude = {persona_name.casefold(), persona_first.casefold()}
    if recipient_name:
        exclude |= {recipient_name.casefold(), recipient_first.casefold()}

    for match in _SIGNOFF_DASH.finditer(text):
        name = match.group(1).strip()
        lowered = name.casefold()
        if lowered in exclude or name.split()[0].casefold() in exclude:
            continue
        if _name_in(name, known_names, set()):
            findings.append(QualityFinding(
                check="dialogue_collapse",
                field=field,
                excerpt=excerpt(text, match.span()),
                detail=f"message signed as '{name}', which is neither the "
                       f"persona nor the recipient",
            ))
    for match in _SIGNOFF_VALEDICTION.finditer(text):
        name = match.group(2).strip()
        if name.casefold() in exclude or name.split()[0].casefold() in exclude:
            continue
        if _name_in(name, known_names, set()):
            findings.append(QualityFinding(
                check="dialogue_collapse",
                field=field,
                excerpt=excerpt(text, match.span()),
                detail=f"valediction signed as '{name}', which is neither the "
                       f"persona nor the recipient",
            ))
    # Greetings that address a proper name are only valid when that name is the
    # recipient (or, in a reply-like echo, the persona). A greeting to anyone
    # else — including a name leaked from the few-shot examples, e.g. "Alex" —
    # is role confusion even though the name is not in the roster.
    for match in _GREETING.finditer(text):
        name = match.group(1).strip()
        lowered = name.casefold()
        # Strip an honorific so "Mr. Whitfield" matches recipient "Whitfield".
        tokens = [t for t in name.split() if t.rstrip(".").casefold()
                  not in {"mr", "mrs", "ms", "miss", "dr", "prof"}]
        first = tokens[0].casefold() if tokens else name.casefold()
        # Personal/collective salutations carry no wrong-identity name.
        if lowered in exclude or first in {
            "there", "sir", "madam", "ma'am", "customer", "team",
            "all", "colleague", "colleagues",
        }:
            continue
        # A shortened or surname-addressed recipient ("Greg", "Mr. Whitfield")
        # is still the recipient: compare against every name token of the
        # recipient, not just the first name.
        recip_tokens = set(
            t.casefold() for t in (recipient_name or "").split()
            if t
        )
        recip_first = recipient_first.casefold()
        if recip_tokens and any(
            first in rt or rt in first
            for rt in recip_tokens | {recip_first}
        ):
            continue
        who = "the impersonated persona" if lowered == persona_first.casefold() \
            else "someone other than the recipient"
        findings.append(QualityFinding(
            check="dialogue_collapse",
            field=field,
            excerpt=excerpt(text, match.span()),
            detail=f"greeting addresses '{name}' — {who}",
        ))
    return findings


def scan_stage_direction(text: str, *, field: str) -> list[QualityFinding]:
    """Bracket/parenthetical directions and leftover placeholder artifacts."""
    findings: list[QualityFinding] = []
    for pattern in _STAGE_DIRECTION:
        for match in pattern.finditer(text):
            findings.append(QualityFinding(
                check="stage_direction",
                field=field,
                excerpt=excerpt(text, match.span()),
                detail=f"stage-direction artifact {match.group(0)!r} in prose",
            ))
    return findings


def scan_turn_overflow(text: str, *, field: str) -> list[QualityFinding]:
    """Length anomalies per channel: overlong or underdeveloped prose."""
    limit = LIMITS[field]
    findings: list[QualityFinding] = []
    if len(text) > limit["soft_max"]:
        findings.append(QualityFinding(
            check="turn_overflow",
            field=field,
            excerpt=excerpt(text, (0, min(len(text), 80))),
            detail=f"{field} is {len(text)} chars (soft limit "
                   f"{limit['soft_max']})",
        ))
    if len(text) < limit["floor"]:
        findings.append(QualityFinding(
            check="turn_overflow",
            field=field,
            excerpt=excerpt(text, (0, len(text))),
            detail=f"{field} is {len(text)} chars — underdeveloped "
                   f"(floor {limit['floor']})",
        ))
    return findings


def scan_meta_bleed(text: str, *, field: str) -> list[QualityFinding]:
    """Model instruction echo: refusal phrasing or prompt vocabulary."""
    findings: list[QualityFinding] = []
    for pattern in _META_BLEED:
        for match in pattern.finditer(text):
            findings.append(QualityFinding(
                check="meta_bleed",
                field=field,
                excerpt=excerpt(text, match.span()),
                detail=f"instruction-echo pattern {match.group(0)!r} in prose",
            ))
    return findings


def scan_loop_detection(
    email_subject: str | None,
    email_body: str,
    sms_body: str,
) -> list[QualityFinding]:
    """Repetition: duplicated lines, subject-in-body, email≈SMS duplication."""
    findings: list[QualityFinding] = []

    def _duplicate_lines(text: str, field: str) -> None:
        lines = [m.group(1).strip() for m in _DUPE_LINE.finditer(text)]
        seen: dict[str, int] = {}
        for line in lines:
            if len(line) < 12:  # short fragments repeat legitimately
                continue
            seen[line.casefold()] = seen.get(line.casefold(), 0) + 1
        for line, count in seen.items():
            if count > 1:
                findings.append(QualityFinding(
                    check="loop_detection",
                    field=field,
                    excerpt=line[:80],
                    detail=f"line repeated {count} times within {field}",
                ))

    _duplicate_lines(email_body, "email_body")
    _duplicate_lines(sms_body, "sms_body")

    if email_subject and len(email_subject.strip()) >= 15:
        if email_subject.strip().casefold() in email_body.casefold():
            findings.append(QualityFinding(
                check="loop_detection",
                field="email_body",
                excerpt=email_subject[:80],
                detail="the email subject is restated verbatim in the body",
            ))

    # Cross-channel near-duplication: an SMS that just repeats the email is a
    # degenerate follow-up (the paper's repetition loops under pressure).
    ratio = SequenceMatcher(
        None, email_body.casefold(), sms_body.casefold()
    ).ratio()
    if ratio >= 0.8 and min(len(email_body), len(sms_body)) >= 40:
        findings.append(QualityFinding(
            check="loop_detection",
            field="sms_body",
            excerpt=sms_body[:80],
            detail=f"SMS body is {ratio:.0%} similar to the email body — "
                   f"degenerate cross-channel repetition",
        ))
    return findings
