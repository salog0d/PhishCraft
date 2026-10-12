"""Generator-AG as a constrained LMQL query (the generation half).

Bindings produced here are handed to ``generator_agent.assemble``, which
builds the ``GeneratedCampaign``. Requires ``pip install lmql`` and a model
key (``LMQL_MODEL`` env var, default ``openai/gpt-4o``; provider key env vars
per LMQL docs).

Constraint design (per "Prompting is Programming"):
- persona identity is decided by the deterministic layer: when the profile
  carries a ``persona`` (see ``generator_agent.catalog.persona_for``) it is
  stamped into every message by ``assemble``; the bindings only echo it.
- ``EMAIL_TIME < SMS_TIME`` is a decode-time constraint.
- SMS body capped at 1600 characters in ``where``.
- link text: the prompt teaches the ``{{cta-link}}`` placeholder; ``assemble``
  expands it to the landing URL and normalizes any stale token the model wrote
  anyway (recorded per message as ``link_fixes``).
- the user segment here must mirror ``assemble.rendered_prompt`` exactly, or
  the provenance hash stops matching the prompt actually sent — it is built by
  ``assemble.user_prompt`` itself, so the two cannot drift.
"""

from __future__ import annotations

import os

import lmql

from generator_agent.assemble import CHARTER, assemble_campaign, user_prompt


@lmql.query
def generator_ag(
    mission_config: dict,
    profile: dict,
    pretext: str,
    tone: str,
    difficulty: str,
):
    user = user_prompt(mission_config, profile, pretext, tone, difficulty, "en")
    '''lmql
    argmax
        """system:
        {CHARTER}

        user: {user}
        """
    from
        lmql.model(os.environ.get("LMQL_MODEL", "openai/gpt-4o"))
    where
        len(PERSONA_NAME.strip()) > 0
        and len(PERSONA_ROLE.strip()) > 0
        and REGEX(PERSONA_EMAIL, r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        and len(EMAIL_SUBJECT.strip()) > 0
        and len(EMAIL_BODY.strip()) > 0
        and len(SMS_BODY.strip()) > 0
        and len(SMS_BODY) <= 1600
        and REGEX(EMAIL_TIME, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        and REGEX(SMS_TIME, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        and EMAIL_TIME < SMS_TIME
    '''
    bindings = {
        "PERSONA_NAME": PERSONA_NAME,
        "PERSONA_ROLE": PERSONA_ROLE,
        "PERSONA_EMAIL": PERSONA_EMAIL,
        "EMAIL_SUBJECT": EMAIL_SUBJECT,
        "EMAIL_BODY": EMAIL_BODY,
        "EMAIL_TIME": EMAIL_TIME,
        "SMS_BODY": SMS_BODY,
        "SMS_TIME": SMS_TIME,
    }
    return assemble_campaign(
        bindings, mission_config, profile, pretext, tone, difficulty,
        persona_override=profile.get("persona"),
    )
