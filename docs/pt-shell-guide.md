# PhishCraft — User Guide

**PhishCraft** is the **interactive harness** for the phishing-campaign
generator: a Claude-Code-style terminal REPL where you configure settings in-session,
generate synthetic email+SMS campaigns through the Google ADK pipeline, run
the deterministic validator, and measure reproducibility & reliability.

> **Responsible use.** This tool generates **synthetic, simulated** phishing
> content for **authorized security-awareness research** in isolated
> environments only. It never touches real people, real domains, or live
> infrastructure.

---

## 1. Prerequisites

- **Python 3.12+** and a virtual environment.
- **Dependencies** (install once, inside the venv):
  ```bash
  python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
  pip install -r requirements.txt
  ```
- **An API key for the model you want to use.** The default model is DeepSeek:
  put the key in the repo's gitignored `.env` file:
  ```dotenv
  DEEPSEEK_API_KEY=sk-...
  ```
  (or export it in your shell). Alternatives: `GOOGLE_API_KEY` for Gemini,
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` for the LiteLlm options. No key is
  needed at all in offline (stub) mode — see §7.

## 2. Launching the shell

From the repository root:

```bash
python -m ptshell          # or: ./venv/bin/python -m ptshell
```

You are greeted by the banner:

```
 mmmmm  m    m mmmmm   mmmm  m    m   mmm  mmmmm    mm   mmmmmmmmmmmmm
 #   "# #    #   #    #"   " #    # m"   " #   "#   ##   #        #
 #mmm#" #mmmm#   #    "#mmm  #mmmm# #      #mmmm"  #  #  #mmmmm   #
 #      #    #   #        "# #    # #      #   "m  #mm#  #        #
 #      #    # mm#mm  "mmm#" #    #  "mmm" #    " #    # #        #
           ><((((°>               ><((((°>
       ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~
╭─ PhishCraft ────────────────────────────────────────────╮
│  interactive harness for the phishing-campaign gener…   │
│  settings  /home/you/.pt-shell/config.json              │
│  model     deepseek/deepseek-chat  (adapter: adk)       │
│  recipient first non-executive  ·  pretext: …  seed: 42 │
│  type /help for commands · /quit to exit                │
╰─────────────────────────────────────────────────────────╯
phishcraft · deepseek/deepseek-chat · adk · seed 42 >
```

- The prompt shows your current **model · adapter · seed**.
- The bottom toolbar shows the active **pretext / tone / difficulty** and
  **recipient**.
- Every command works with or without the leading slash (`/help` or `help`).
- Press **Tab** for completion (commands, config keys, persona ids, models);
  use **↑/↓** for history; **Ctrl-D** or `/quit` to exit.

## 3. Your first run (60 seconds)

```bash
pt> /recipients          # see who can be targeted
pt> /recipient 40        # target Rebecca Stern (Staff Accountant)
pt> /generate            # call the model, build + validate the campaign
```

`/generate` calls DeepSeek through the ADK pipeline, then prints:

- a **campaign panel** — persona, EMAIL/SMS messages with subjects, bodies,
  and the seed-derived tracking link;
- a **validator report** — the five coherence checks with `✓ PASS` / `✗ FAIL`
  badges and the `all_passed` verdict;
- the paths where the campaign and report were saved
  (`data/shell/<campaign_id>/` by default).

## 4. Command reference

| Command | What it does |
|---|---|
| `/help [command]` | List all commands (or explain one). |
| `/config` | Show all settings and their valid options. |
| `/config <key> <value>` | Change a setting (persisted). Example: `/config seed 7`. |
| `/config <key>` | Show one setting. |
| `/config reset` | Restore every setting to its default. |
| `/model <id>` | Switch model. Applies to the **next** `/generate`. |
| `/models` | List known model ids. |
| `/recipients` | Table of the target catalog (12 internal + supplier/bank/carrier). |
| `/recipient <id>` | Set the default simulation target. The impersonated persona is derived automatically from the pretext + target (e.g. `executive_request` → the target's manager). |
| `/generate` | One ADK pipeline run: generate → assemble → validate. |
| `/validate [file.json]` | Run the 5 coherence checks on a campaign file (defaults to the last generated campaign). |
| `/measure [--runs=N]` | Run the 10-spec reliability suite; prints the failure-rate summary. |
| `/reproduce [all]` | Run the same spec twice and compare (default: spec S1, seed 42). |
| `/send` | Deliver the last campaign to the local MailHog inbox. |
| `/status` | Settings + summary of the last run. |
| `/quit` | Exit (also `/exit`, Ctrl-D). |

### Common workflows

```bash
# A supplier-invoice campaign against the accounting manager
pt> /recipient 24
pt> /config pretext invoice_payment
pt> /config tone authoritative
pt> /generate

# Re-check the committed evidence sample (the known cross-channel bug)
pt> /validate data/measurements/known-case/generated_campaign.json
# → [✗ FAIL] link_consistency: msg-0002 body token 'abc123' not in CTA tokens (d6db8064874a)

# The paper's two measurements
pt> /measure            # 10 specs → failure rate per coherence check
pt> /reproduce          # S1 twice → identical? (seed-42 reproducibility)
```

## 5. Configuration reference

Settings are stored in **`~/.pt-shell/config.json`** (created on the first
`/config` change; override the location with the `PTSHELL_CONFIG` env var).
Unknown keys and invalid values are rejected with the valid options listed.

| Key | Default | Valid values / notes |
|---|---|---|
| `model` | `deepseek/deepseek-chat` | any ADK model id (see §6) |
| `pretext` | `executive_request` | `password_reset`, `invoice_payment`, `package_delivery`, `it_support`, `hr_notice`, `executive_request`, `shared_document`, `account_suspension` |
| `tone` | `urgent` | `urgent`, `friendly`, `authoritative`, `neutral` |
| `difficulty` | `medium` | `easy`, `medium`, `hard` |
| `language` | `en` | BCP-47-ish locale, e.g. `en`, `es-MX` |
| `seed` | `42` | integer ≥ 0; drives the deterministic tracking link |
| `recipient_id` | *(empty)* | target catalog id (internal employee); empty = first non-executive. The impersonated persona is derived from this id + the pretext. |
| `start_at` | `2026-08-20T09:00:00Z` | ISO-8601 UTC campaign start |
| `followup_minutes` | `75` | SMS is scheduled this many minutes after the email |
| `adapter` | `adk` | `adk` (real ADK pipeline, needs a key) or `stub` (offline, §7) |
| `mission` | `config/q3-awareness-2026.mission.json` | mission file (authorization gate, model policy) |
| `output_dir` | `data/shell` | where `/generate` saves `generated_campaign.json` + `coherence_report.json` |

## 6. Models & API keys

`/model <id>` switches the generation model; the id is resolved by ADK:

| Model id | Needs | Notes |
|---|---|---|
| `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | **default**; temperature 0 |
| `deepseek/deepseek-reasoner` | `DEEPSEEK_API_KEY` | reasoning variant |
| `gemini-2.5-flash` | `GOOGLE_API_KEY` | Gemini via ADK |
| `anthropic/claude-opus-5` | `ANTHROPIC_API_KEY` | via LiteLlm |
| `openai/gpt-4.1` | `OPENAI_API_KEY` | via LiteLlm |

Switching models mid-session is fine — the change applies to the next
`/generate` (the pipeline re-resolves the model automatically).

## 7. Offline mode (no API key, no cost)

```bash
pt> /config adapter stub
```

With the stub adapter, `/generate`, `/measure`, and `/reproduce` run through
the same deterministic assembler + validator with fixed content — no LLM call,
no network, no key. Ideal for demos, CI, and learning the commands.

## 8. Measuring (the reproducibility & reliability results)

- **`/reproduce`** writes `data/measurements/reproduce-<adapter>/`:
  `reproducibility.json` plus one `run-NN.campaign.json` /
  `run-NN.report.json` pair per run. The report states whether the two runs
  are **identical** and whether the **deterministic layer** (ids, persona,
  URLs, references, schedule, provenance) matched.
- **`/measure`** writes `data/measurements/reliability-<adapter>-<timestamp>/`:
  `reliability.json` (machine-readable) and `summary.md` with **two**
  link-consistency numbers: the **raw (pre-assembler) violation rate** — the
  generator's *reliability* metric, from the stale tokens the LLM wrote before
  the assembler normalized them — and the **post-assembler failure rate**
  across all five checks, the *delivery guarantee* of the delivered artifact.
  **Both go in the paper; they are not the same thing.**

Both also exist as plain CLIs (no shell needed):

```bash
python -m measurement.reproduce   --adapter adk --spec-id S1 --runs 2
python -m measurement.reliability --adapter adk --runs 1
```

## 9. Sending a campaign to the sandbox inbox

```bash
# terminal 1 — start the SMTP sink (once)
docker compose up -d
# → MailHog SMTP on :1025, web inbox at http://localhost:8025

# terminal 2 — the shell
pt> /generate
pt> /send        # delivers the last campaign; open http://localhost:8025
```

Email messages arrive as email; SMS messages arrive tagged `[SMS]`.

## 10. Non-interactive use

If you prefer scripts over the REPL, the same pipeline is available as a CLI:

```bash
ADK_MODEL=deepseek/deepseek-chat python -m generator_agent.run \
    --pretext executive_request --difficulty medium --seed 42
```

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: ptshell` | Run from the repo root, or activate the venv (`source venv/bin/activate`). |
| Banner shows `adapter: adk` but `/generate` errors about a key | Set `DEEPSEEK_API_KEY` (or the matching provider key) in `.env` / env, or switch to `stub` (`/config adapter stub`). |
| `no SMTP sink — start it with: docker compose up -d` | MailHog isn't running (see §9). |
| `/config` says `'x' must be one of: …` | The value isn't in the valid set — the message lists the options. |
| Settings look wrong after an edit | `cat ~/.pt-shell/config.json`; fix by hand or run `/config reset`. |
| Startup warns `could not read … config.json` | The settings file is empty or corrupt. PhishCraft repairs it automatically: an empty file is refilled with defaults, a corrupt one is moved to `config.json.corrupt-<ts>` (nothing is lost) and defaults are used. |
| Want a different settings file | `PTSHELL_CONFIG=/path/config.json python -m ptshell`. |
| DeepSeek calls are slow / timing out | The adapter streams with a 120 s read timeout; retry or switch model with `/model gemini-2.5-flash`. |

## 12. File map (where things live)

| What | Where |
|---|---|
| PhishCraft shell code | `ptshell/` (`shell.py` = commands + UI, `config.py` = settings) |
| Settings / history | `~/.pt-shell/config.json` · `~/.pt-shell/history` |
| Generated campaigns (shell) | `data/shell/<campaign_id>/` |
| Reliability / reproducibility results | `data/measurements/…` |
| Mission config | `config/q3-awareness-2026.mission.json` |
| Personas | `org/fantazylabz_org.json` + `org/external_personas.json` |
| Design & contracts | `docs/architecture.md` · `docs/flow-schema.md` |
