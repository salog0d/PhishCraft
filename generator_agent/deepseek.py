"""Generator-AG over the DeepSeek API (stdlib only, no lmql).

Runs the same process as ``agent.py`` — same charter, same user prompt, same
constraints — against DeepSeek's OpenAI-compatible chat API. LMQL itself needs
``logit_bias``/batching on the endpoint, which DeepSeek does not expose, so
the decode-time constraints of the query are approximated here with
request-level rejection sampling: a response that violates a rule is rejected
and the request retried with a stricter format instruction (max 3 attempts).

Usage:
    python -m generator_agent.deepseek [same flags as generator_agent.run]

Requires DEEPSEEK_API_KEY in the environment or in the repo ``.env``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from generator_agent.assemble import CHARTER, assemble_campaign, user_prompt
from generator_agent.run import DEMO_MISSION, _demo_profile, _load_org

REPO_ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"
MAX_ATTEMPTS = 3

# Expected binding order in the model's reply (mirrors agent.py's query).
LABELS = (
    ("PERSONA_NAME", "display name"),
    ("PERSONA_ROLE", "role"),
    ("PERSONA_EMAIL", "from address"),
    ("EMAIL_SUBJECT", "subject"),
    ("EMAIL_BODY", "body"),  # first body
    ("EMAIL_TIME", "scheduled at"),
    ("SMS_BODY", "body"),  # second body
    ("SMS_TIME", "scheduled at"),
)

STRICT_FORMAT = """\n\nAnswer with EXACTLY these 8 lines, one per line, no markdown, no extra text:
- display name: <value>
- role: <value>
- from address: <value>
- subject: <value>
- body: <value>
- scheduled at: <value>
- body: <value>
- scheduled at: <value>"""


def _load_api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "DEEPSEEK_API_KEY":
                return value.strip().strip('"').strip("'")
    raise SystemExit("DEEPSEEK_API_KEY not found in environment or .env")


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(f"[deepseek] {msg}", flush=True)


def _chat(system: str, user: str, api_key: str, verbose: bool = False) -> str:
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,  # argmax-like determinism
            "max_tokens": 1024,
            "stream": True,  # tokens arrive as generated instead of one buffered blob
        }
    ).encode()
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    _log(verbose, f"POST {API_URL} (model={MODEL}, streaming, read timeout=120s)...")
    start = time.perf_counter()
    parts: list[str] = []
    try:
        # timeout is per-read: a stalled stream still fails, a slow one keeps going.
        with urllib.request.urlopen(request, timeout=120) as response:
            for raw_line in response:  # server-sent events: 'data: {json}\n'
                line = raw_line.decode().strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                delta = json.loads(data)["choices"][0]["delta"].get("content")
                if delta:
                    parts.append(delta)
                    if verbose and len(parts) % 25 == 0:
                        _log(verbose, f"  ...{sum(map(len, parts))} chars ({time.perf_counter()-start:.0f}s)")
    except urllib.error.HTTPError as exc:  # auth/balance/rate errors come back non-streamed
        raise SystemExit(f"DeepSeek API error {exc.code}: {exc.read().decode()[:400]}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"DeepSeek API unreachable after {time.perf_counter()-start:.1f}s: {exc}")
    content = "".join(parts)
    if not content:
        raise SystemExit("DeepSeek returned an empty response (check API key / balance)")
    _log(verbose, f"reply in {time.perf_counter()-start:.1f}s, {len(content)} chars")
    return content


def _parse_bindings(text: str) -> dict[str, str] | None:
    """Extract the 8 bindings from the reply, in label order. None on failure."""
    lines = [
        re.sub(r"^[\s\-*•>]+", "", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]
    bindings: dict[str, str] = {}
    cursor = 0
    for key, label in LABELS:
        while cursor < len(lines) and f"{label}:" not in lines[cursor].lower():
            cursor += 1
        if cursor >= len(lines):
            return None
        bindings[key] = lines[cursor].split(":", 1)[-1].strip()
        cursor += 1
    return bindings


def _satisfies(bindings: dict[str, str]) -> bool:
    """The query's `where` clause, evaluated per attempt (rejection sampling)."""
    time_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    return all(
        [
            len(bindings["PERSONA_NAME"]) > 0,
            len(bindings["PERSONA_ROLE"]) > 0,
            bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", bindings["PERSONA_EMAIL"])),
            len(bindings["EMAIL_SUBJECT"]) > 0,
            len(bindings["EMAIL_BODY"]) > 0,
            len(bindings["SMS_BODY"]) > 0,
            len(bindings["SMS_BODY"]) <= 1600,
            bool(time_re.fullmatch(bindings["EMAIL_TIME"])),
            bool(time_re.fullmatch(bindings["SMS_TIME"])),
            bindings["EMAIL_TIME"] < bindings["SMS_TIME"],
        ]
    )


def generate(
    mission: dict,
    profile: dict,
    pretext: str,
    tone: str,
    difficulty: str,
    verbose: bool = False,
):
    api_key = _load_api_key()
    _log(verbose, "API key loaded")
    user = user_prompt(mission, profile, pretext, tone, difficulty)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _log(verbose, f"attempt {attempt}/{MAX_ATTEMPTS}")
        reply = _chat(CHARTER, user, api_key, verbose)
        bindings = _parse_bindings(reply)
        if bindings is None or not _satisfies(bindings):
            _log(verbose, f"parsed_ok={bindings is not None} constraints_ok=False")
            print(f"attempt {attempt}: reply failed constraints, retrying")
            user = user_prompt(mission, profile, pretext, tone, difficulty) + STRICT_FORMAT
            continue
        _log(verbose, "constraints satisfied, assembling campaign")
        return assemble_campaign(
            bindings,
            mission,
            profile,
            pretext,
            tone,
            difficulty,
            # Provenance honesty: the charter records the model actually used.
            actual_model={"family": "deepseek", "name": MODEL, "adapter_version": "1.0"},
            runtime={"sdk": "deepseek-api"},
        )
    raise SystemExit(f"no constraint-satisfying reply after {MAX_ATTEMPTS} attempts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", help="path to a mission_config.json")
    parser.add_argument("--recipient-id", type=int, help="org employee id to target")
    parser.add_argument("--pretext", default="executive_request")
    parser.add_argument("--tone", default="urgent")
    parser.add_argument("--difficulty", default="medium")
    parser.add_argument("--output")
    parser.add_argument(
        "--send", action="store_true", help="also deliver the campaign to MailHog"
    )
    parser.add_argument("--smtp-host", default="localhost")
    parser.add_argument("--smtp-port", type=int, default=1025)
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log API calls and timing"
    )
    args = parser.parse_args()

    mission = (
        json.loads(Path(args.mission).read_text(encoding="utf-8"))
        if args.mission
        else DEMO_MISSION
    )
    profile = _demo_profile(_load_org(), args.recipient_id)

    print(
        f"Generator-AG (deepseek): campaign={mission['campaign_id']} "
        f"recipient={profile['recipient']['full_name']} "
        f"pretext={args.pretext} tone={args.tone} difficulty={args.difficulty}"
    )
    campaign = generate(
        mission, profile, args.pretext, args.tone, args.difficulty, args.verbose
    )

    out = Path(args.output or f"data/{mission['campaign_id']}/generated_campaign.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(campaign.model_dump_json(indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(
        f"persona: {campaign.persona.display_name} <{campaign.persona.email}> — "
        f"{len(campaign.messages)} messages"
    )

    if args.send:
        from generator_agent.send import send_campaign  # deliver to the SMTP sink

        to_addr = profile["recipient"]["email"]
        try:
            n = send_campaign(str(out), to_addr, args.smtp_host, args.smtp_port)
        except ConnectionRefusedError:
            raise SystemExit(
                f"no SMTP sink at {args.smtp_host}:{args.smtp_port} — "
                "start MailHog: docker compose up -d"
            )
        print(f"delivered {n} messages — open http://localhost:8025")


if __name__ == "__main__":
    main()
