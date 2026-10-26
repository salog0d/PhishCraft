"""Shared deterministic lexicons and pattern sets for the quality scanner.

Everything in this module is static data: term lists for the pretext and
tone labelers, meta-bleed and stage-direction patterns, difficulty markers,
and the known brands. The org-chart names are loaded lazily from
``org/fantazylabz_org.json`` and cached.

No LLM, no randomness, no I/O on import (names load on first use).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORG_FILE = REPO_ROOT / "org" / "fantazylabz_org.json"

# --------------------------------------------------------------------------- #
# Pretext lexicons (tight terms, phrase-level where possible)
# --------------------------------------------------------------------------- #
#
# Used twice: (1) by the contamination scan — terms belonging to a *different*
# pretext appearing in a campaign's prose are cross-pretext contamination
# (the paper's grandparent-opener bleed analogue); (2) by the labeler, which
# predicts the pretext from the argmax of term hits.

PRETEXT_TERMS: dict[str, tuple[str, ...]] = {
    "password_reset": (
        "password", "reset", "credentials", "log in", "login", "two-factor",
        "2fa", "sign in", "sign-in",
    ),
    "account_suspension": (
        "suspended", "suspension", "reactivate", "unusual activity",
        "security alert", "deactivate", "locked out", "account closed",
    ),
    "package_delivery": (
        "package", "parcel", "shipment", "delivery", "tracking number",
        "carrier", "freight", "courier",
    ),
    "it_support": (
        "helpdesk", "help desk", "service desk", "it support", "vpn",
        "ticket", "workstation", "antivirus", "it team",
    ),
    "hr_notice": (
        "payroll", "benefits", "performance review", "onboarding",
        "people operations", "open enrollment", "pto", "401k",
    ),
    "executive_request": (
        "sign-off", "sign off", "board meeting", "confidential", "executive",
        "ceo", "chief executive",
    ),
    "shared_document": (
        "shared document", "shared file", "document", "attachment",
        "download", "folder", "edit access", "drive",
    ),
    "invoice_payment": (
        "invoice", "payment", "remittance", "past due", "wire transfer",
        "ach", "bank details", "overdue", "purchase order", "po number",
    ),
}

# --------------------------------------------------------------------------- #
# Tone markers (labeler)
# --------------------------------------------------------------------------- #

TONE_MARKERS: dict[str, tuple[str, ...]] = {
    "urgent": (
        "urgent", "urgently", "immediately", "asap", "right away",
        "before end of day", "eod", "today", "final notice", "expires",
        "deadline", "act now", "time-sensitive", "action needed",
    ),
    "friendly": (
        "hope you're", "hope you are", "thanks", "thank you", "appreciate",
        "have a great", "warm regards", "cheers", "hi there", "how are you",
    ),
    "authoritative": (
        "required", "must", "mandatory", "policy", "compliance",
        "on behalf of", "directive", "in accordance", "failure to",
        "obligated", "per company policy",
    ),
    "neutral": (
        "please", "review", "update", "confirm", "let me know", "fyi",
        "for your information",
    ),
}

# --------------------------------------------------------------------------- #
# Difficulty markers (labeler): groups weighted by pressure level
# --------------------------------------------------------------------------- #

DIFFICULTY_MARKERS: dict[str, tuple[str, ...]] = {
    # weight 1 — time pressure
    "urgency": (
        "urgent", "urgently", "immediately", "asap", "before end of day",
        "eod", "today", "right away", "deadline", "act now", "final notice",
        "action needed",
    ),
    # weight 2 — consequences/threats
    "threat": (
        "suspended", "terminated", "legal action", "penalty", "fine",
        "lost access", "account closed", "fraud", "investigation",
        "lock you out", "deleted",
    ),
    # weight 1 — requested actions
    "ask": (
        "review", "confirm", "click", "log in", "login", "verify", "open the",
        "download", "sign in", "credentials", "password", "payment", "wire",
        "approve", "send the",
    ),
    # weight 1 — impersonation/authority cues
    "impersonation": (
        "on behalf of", "ceo", "executive", "security team", "chief financial",
        "cfo", "management",
    ),
}

DIFFICULTY_BANDS = ((0, 3, "easy"), (4, 6, "medium"), (7, 10_000, "hard"))

# --------------------------------------------------------------------------- #
# Meta bleed (model instruction echo / refusal leakage into prose)
# --------------------------------------------------------------------------- #

META_BLEED_PATTERNS: tuple[str, ...] = (
    r"here (is|are) the (message|email|sms|8 lines|eight lines)",
    r"here's the (message|email|response)",
    r"the following (message|email|response|content)",
    r"as an (ai|artificial intelligence)",
    r"(i am|i'm) (an ai|a language model)",
    r"as a language model",
    r"i('m| am) sorry",
    r"i apologize",
    r"apologize for",
    r"i am unable to",
    r"i refuse to",
    r"i won't be able to",
    r"cannot (assist|comply|generate|help|write|produce)",
    r"not allowed",
    r"against my (policies|guidelines|instructions)",
    r"this is (a |an )?(test|simulation|synthetic|placeholder|example) "
    r"(message|email|sms|output|content|text)",
    r"the (8|eight) lines",
    r"\bbindings?\b",
    r"<[a-z][a-z _-]{1,20}>",
    r"\b(phishing|smishing|social engineering)\b",
)

# --------------------------------------------------------------------------- #
# Stage-direction artifacts (bracket/parenthetical directions, placeholders)
# --------------------------------------------------------------------------- #

STAGE_DIRECTION_PATTERNS: tuple[str, ...] = (
    # Prompt-placeholder echo: the 8-line contract's bracketed labels leaking
    # into prose (the assembler rejects these in the bindings themselves; a
    # leftover in delivered prose is a body-level artifact).
    r"\[(email_subject|sms_body|persona_name|persona_role|persona_email|"
    r"email_time|sms_time|your name|insert[^\]]*|click here|link|url|"
    r"content|value|recipient[^\]]*)\]",
    # Structural tags of the [HOSTAGE VOICE] family.
    r"\[[A-Z][A-Z _-]{2,}\]",
    # Parenthetical writing directions: "(insert urgency here)", "(tone: ...)".
    r"\((insert|mention|note|state|write|add|replace|use|tone|"
    r"urgent tone|friendly tone)[^)]{0,60}\)",
    # Leftover placeholder variants of the {{cta-link}} convention.
    r"\{+\s*cta[-_ ]link\s*\}+",
    # Bare-colon speech tag at line start (the paper's bare-colon artifact).
    r"(?m)^:\s",
)

# --------------------------------------------------------------------------- #
# Known brands (external personas) — wrong-brand mentions are contamination
# --------------------------------------------------------------------------- #

KNOWN_BRANDS: tuple[str, ...] = ("northwind", "meridian", "swiftship")

# Typographic characters that are legitimately non-ASCII (not script bleed).
_TYPOGRAPHIC_OK = set('\u2018\u2019\u201c\u201d\u2013\u2014\u2026\u00b7\u2022'
                      '\u00a0\u00b0\u00ae\u00a9\u2122')


def is_latin_typo(char: str) -> bool:
    """True for ASCII or common typographic punctuation (not script bleed)."""
    return ord(char) < 128 or char in _TYPOGRAPHIC_OK


# --------------------------------------------------------------------------- #
# Org-chart names (lazy, cached) — cross-conversation name drift evidence
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def catalog_names() -> tuple[str, ...]:
    """Full names + first names of the internal roster (12 employees).

    Used by the name-contamination scan and the dialogue-collapse check: any
    of these names appearing in prose that does not belong to the campaign's
    own persona or recipient is cross-conversation name drift.
    """
    try:
        org = json.loads(ORG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    names: set[str] = set()
    for employee in org.get("employees", []):
        full = str(employee.get("name", "")).strip()
        if full:
            names.add(full)
            first = full.split()[0]
            if first:
                names.add(first)
    return tuple(sorted(names))


def compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    """Compile the pattern strings once (case-insensitive)."""
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


def term_hits(text: str, terms: tuple[str, ...]) -> dict[str, int]:
    """Count whole-word/whole-phrase hits of each term in ``text``.

    Returns ``{term: count}`` for the terms that appear at least once.
    """
    lowered = text.casefold()
    hits: dict[str, int] = {}
    for term in terms:
        pattern = re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])",
                             re.IGNORECASE)
        count = len(pattern.findall(text))
        if count:
            hits[term] = count
    return hits
