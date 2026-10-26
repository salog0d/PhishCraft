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
| `/models` | List known model ids (cloud providers + local Ollama models). |
| `/recipients` | Table of the target catalog (12 internal + supplier/bank/carrier). |
| `/recipient <id>` | Set the default simulation target. The impersonated persona is derived automatically from the pretext + target (e.g. `executive_request` → the target's manager). |
| `/generate` | One ADK pipeline run: generate → assemble → validate → quality scan. |
| `/validate [file.json]` | Run the 5 coherence checks on a campaign file (defaults to the last generated campaign). |
| `/quality [file.json]` | Show the last campaign's quality check (9 checks + label audit + strip stats + evidence excerpts). Resolves the campaign from an explicit path, the in-session last run, or the run manifest — works right after restarting the shell. |
| `/measure [--runs=N]` | Run the 10-spec reliability suite; prints the failure-rate summary. |
| `/reproduce [all]` | Run the same spec twice and compare (default: spec S1, seed 42). |
| `/replay` | Re-run the last execution recorded in the run manifest (same spec, adapter, and model as the recorded run) and show it again. |
| `/replay-logs [run_id]` | Show the manifest entry + provenance log of the most recent replay (or of any recorded run) in the terminal. |
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

# Re-run and audit the last execution
pt> /replay             # re-executes the run recorded in data/shell/runs.json
pt> /replay-logs        # manifest entry + provenance log of the replay
```

## 5. Configuration reference

Settings are stored in **`~/.pt-shell/config.json`** (created on the first
`/config` change; override the location with the `PTSHELL_CONFIG` env var).
Unknown keys and invalid values are rejected with the valid options listed.

| Key | Default | Valid values / notes |
|---|---|---|
| `model` | `deepseek/deepseek-chat` | any ADK model id (see §6) |
| `pretext` | `executive_request` | consumer: `password_reset`, `account_suspension`, `package_delivery` · BEC: `executive_request`, `invoice_payment`, `shared_document`, `hr_notice`, `it_support` |
| `tone` | `urgent` | `urgent`, `friendly`, `authoritative`, `neutral` |
| `difficulty` | `medium` | `easy`, `medium`, `hard` |
| `language` | `en` | BCP-47-ish locale, e.g. `en`, `es-MX` |
| `seed` | `42` | integer ≥ 0; drives the deterministic tracking link |
| `recipient_id` | *(empty)* | target catalog id (internal employee); empty = first non-executive. The impersonated persona is derived from this id + the pretext. |
| `start_at` | `2026-08-20T09:00:00Z` | ISO-8601 UTC campaign start |
| `followup_minutes` | `75` | SMS is scheduled this many minutes after the email |
| `adapter` | `adk` | `adk` (real ADK pipeline, needs a key) or `stub` (offline, §7) |
| `mission` | `config/q3-awareness-2026.mission.json` | mission file (authorization gate, model policy) |
| `output_dir` | `data/shell` | where `/generate` and `/replay` save `generated_campaign.json`, `coherence_report.json`, `provenance.json`, and `quality_report.json` per campaign, plus the `runs.json` run manifest (§8) |

## 6. Models & API keys

`/model <id>` switches the generation model; the id is resolved by ADK:

| Model id | Needs | Notes |
|---|---|---|
| `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | **default**; runs at temperature 0.0 (the value provenance logs); the seed drives the deterministic layer and is not passed to the provider |
| `deepseek/deepseek-reasoner` | `DEEPSEEK_API_KEY` | reasoning variant |
| `gemini-2.5-flash` | `GOOGLE_API_KEY` | Gemini via ADK |
| `anthropic/claude-opus-5` | `ANTHROPIC_API_KEY` | via LiteLlm |
| `openai/gpt-4.1` | `OPENAI_API_KEY` | via LiteLlm |
| `ollama/<name>` | none — local | any model pulled into the local Ollama instance, e.g. `ollama/qwen3:8b` |

**Local Ollama models are discovered live.** `/models` and the `/model`
Tab-completion list every model in `ollama list`, prefixed `ollama/` (the
LiteLlm id). A bare name also works — `/model qwen3:8b` sets
`ollama/qwen3:8b`. Pull a model first:

```bash
ollama pull qwen3:8b     # ~5.4 GB; see the README for a model shortlist
python -m ptshell
pt> /model qwen3:8b      # tab-completes; runs fully offline on the GPU
```

Switching models mid-session is fine — the change applies to the next
`/generate` (the pipeline re-resolves the model automatically).

## 7. Offline mode (no API key, no cost)

```bash
pt> /config adapter stub
```

With the stub adapter, `/generate`, `/replay`, `/measure`, and `/reproduce`
run through the same deterministic assembler + validator with fixed content —
no LLM call, no network, no key. Ideal for demos, CI, and learning the
commands. A replay always re-runs with the adapter **recorded in the
manifest**, so replaying a stub run stays offline even if you switched the
config to `adk` afterwards.

## 8. Run manifest & provenance logging

Every execution — `/generate` **and** `/replay` — writes the run artifacts
into `data/shell/` (the `output_dir`):

- **`runs.json` — the run manifest** (append-only). One entry per execution:
  `run_id`, `kind` (`generate` | `replay`), `parent_run_id` (which run a
  replay re-ran), timestamp, adapter, model, the full spec, the written file
  paths, the refinement metadata (`n_attempts`, `refined`,
  `first_attempt_raw_link_violations`), the validator verdict, and the
  quality-scan summary (flag counts, contamination, label mismatches, strip
  stats).
- **`<campaign_id>/provenance.json` — the provenance log.** The campaign's
  persona plus every message's `GenerationProvenance` (model, params, seed,
  prompt template id, prompt hash, runtime) and its `link_fixes`.
- **`<campaign_id>/quality_report.json` — the post-run quality scan.** The
  full `QualityReport`: findings per check category (5 generation-artifact
  checks + 4 contamination checks), the automated label audit, and the
  stage-direction stripping statistics.

```bash
pt> /generate
pt> /replay               # re-runs the run recorded as the last manifest entry
pt> /replay-logs          # prints the replay's manifest entry + provenance log
pt> /replay-logs run-001-091523   # or any recorded run_id
```

`/replay` re-executes the last entry as it was recorded — same spec, adapter,
and model — even if you changed the settings in the meantime, then appends a
new `replay` entry linking back to it. The manifest is plain JSON, so it can
be diffed or archived as audit evidence alongside the campaigns.

## 9. Measuring (the reproducibility & reliability results)

- **`/reproduce`** writes `data/measurements/reproduce-<adapter>/`:
  `reproducibility.json` plus one `run-NN.campaign.json` /
  `run-NN.report.json` pair per run. The report states whether the two runs
  are **identical** and whether the **deterministic layer** (ids, persona,
  URLs, references, schedule, provenance) matched.
- **`/measure`** writes `data/measurements/reliability-<adapter>-<timestamp>/`:
  `reliability.json` (machine-readable) and `summary.md` with **three**
  link-consistency numbers: the **first-attempt raw violation rate** — the
  generator's *reliability* metric, from the stale tokens the LLM wrote before
  any refinement round — the **post-refinement raw violation rate** on the
  delivered artifact, and the **post-assembler failure rate**
  across all five checks, the *delivery guarantee* of the delivered artifact.
  Refinement activity (attempts, success rate) is reported alongside.
  **They all go in the paper; they are not the same thing.**

Both also exist as plain CLIs (no shell needed):

```bash
python -m measurement.reproduce   --adapter adk --spec-id S1 --runs 2
python -m measurement.reliability --adapter adk --runs 1
```

## 10. Sending a campaign to the sandbox inbox

```bash
# terminal 1 — start the SMTP sink (once)
docker compose up -d
# → MailHog SMTP on :1025, web inbox at http://localhost:8025

# terminal 2 — the shell
pt> /generate
pt> /send        # delivers the last campaign; open http://localhost:8025
```

Email messages arrive as email; SMS messages arrive tagged `[SMS]`.

## 11. Non-interactive use

If you prefer scripts over the REPL, the same pipeline is available as a CLI:

```bash
ADK_MODEL=deepseek/deepseek-chat python -m generator_agent.run \
    --pretext executive_request --difficulty medium --seed 42
```

## 12. Troubleshooting

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

## 13. File map (where things live)

| What | Where |
|---|---|
| PhishCraft shell code | `ptshell/` (`shell.py` = commands + UI, `config.py` = settings, `runlog.py` = manifest + provenance logging) |
| Settings / history | `~/.pt-shell/config.json` · `~/.pt-shell/history` |
| Generated campaigns (shell) | `data/shell/<campaign_id>/` |
| Run manifest / provenance logs | `data/shell/runs.json` · `data/shell/<campaign_id>/provenance.json` |
| Reliability / reproducibility results | `data/measurements/…` |
| Mission config | `config/q3-awareness-2026.mission.json` |
| Personas | `org/fantazylabz_org.json` + `org/external_personas.json` |
| Design & contracts | `docs/architecture.md` · `docs/flow-schema.md` |
