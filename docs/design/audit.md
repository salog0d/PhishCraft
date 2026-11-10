# Repository Audit — PhishCraft

> **Status: findings applied.** Items #2, #3, #5, #6, #7, #8, #9, #11 (and the
> incidental `del spec` dead-line in `quality_agent/scan.py`) have been
> implemented; #1 (rotate the key) and #4 (exporter read cache) and #10 (compose
> lifecycle docs) are left to the owner because they touch secrets/infra outside
> code. 123 tests still pass.

## What this repo does

PhishCraft is a configurable, reproducible generator of **synthetic**
phishing-simulation campaigns (email + SMS) for authorized security-awareness
research. A Google ADK pipeline runs three stages — an LLM writes prose, a
deterministic assembler builds the campaign (persona, tracking token, schedule,
provenance), and a deterministic validator runs five coherence checks. A
post-run "quality scan" (artifacts, contamination, label audit) records
findings as data. There are three front-doors to the same engine — a CLI
(`generator_agent.run`), an interactive shell (`ptshell`), and a FastAPI stub
(`app`), plus three measurement harnesses (`measurement.reproduce/reliability/quality`)
and a 1000-campaign "variety experiment" (`scripts/variety_experiment.py`).
A `monitoring/` Prometheus/Grafana stack exposes metrics.

**Load I assumed:** one operator on one workstation (RTX 3070, local Ollama).
The pipeline is strictly sequential (one LLM call at a time); the variety
experiment parallelizes up to `--workers` model children, each writing to a
shared append-only `runs.jsonl`. The API is a research stub returning a 202
ack, not a real multi-user service. No database, no authn, no money path — the
only "user input" is CLI flags / a JSON request body, the only "network write"
is a local MailHog SMTP sink, and the only "secrets" are provider API keys in a
gitignored `.env`.

---

## Must fix

### 1. A real API key sits in `.env`, and any source of it would be served — `.env:1`, `agent/config.py:9-22`
- **What this is:** The repo-root `.env` holds `DEEPSEEK_API_KEY=sk-84c7...`
  (a live-looking key). `agent/config.py` loads it into the process env on
  import.
- **Problem:** It is gitignored so it is not *committed*, but it is present on
  disk as plaintext and would be picked up by **any** code that imports the
  agent. The key is real (not a placeholder), so if this box is shared or the
  file leaks via backup/scratch, someone can spend your DeepSeek quota. This is
  the only credential in the tree; it deserves explicit treatment, not a casual
  gitignore.
- **Fix:** Rotate the key if it has ever left this machine, and either remove
  it from `.env` (rely on the shell env) or confirm it is a scoped/test key.
  Add `.env` to any backup exclusion, and keep it out of screenshots/docs.
- **If we skip it:** low *immediate* risk (single-user box, gitignored), but it
  is the one thing in the repo that costs real money if it leaks.

### 2. Ctrl-C in the variety experiment never kills the child processes — `scripts/variety_experiment.py:486-495`
- **What this is:** `run_parent` builds `procs` (the live `Popen` list) but the
  `KeyboardInterrupt` handler loops over `children` — a separate list that is
  declared at line 451 and **never appended to**.
- **Problem:** On interrupt the handler calls `proc.terminate()` on an empty
  list and returns 130, while the model children keep running and writing
  `runs.jsonl` in the background. A user who hits Ctrl-C to "stop the run"
  actually leaves up to `--workers` Ollama processes consuming the GPU.
- **Fix:** Change the two `for ... in children:` loops to `procs` (and use the
  proc objects from `procs`, not just `_model, proc, _log`). Three lines.
- **If we skip it:** background GPU/LLM processes run unattended after every
  interrupted experiment; only annoying on this box, but a real footgun.

### 3. `_metrics`/`metrics.py` is fine, but the `HTTP_DURATION`/`HTTP_REQUESTS` pair is inconsistent — `app/main.py:44-60`
- **What this is:** `metrics_middleware` labels `HTTP_REQUESTS` with
  `(method, route, status)` but `HTTP_DURATION` with only `(method, route)`.
- **Problem:** You can count slow 500s but cannot separate their latency from
  fast 200s on the same route, so a latency SLO mixes healthy and failing
  traffic. Minor, but it makes the one dashboard that matters (error latency)
  misleading.
- **Fix:** Add `status` to the `HTTP_DURATION` histogram labels in
  `monitoring/metrics.py` and pass it in `main.py`.
- **If we skip it:** latency numbers are averaged across outcomes; cosmetic for
  a research stub.

---

## Should fix

### 4. `requests`-level tokenization re-reads the whole manifest every run — `scripts/variety_experiment.py:209-232`, `monitoring/runs_exporter.py:49-88`
- **What this is:** `_load_completed` re-reads and re-parses all of `runs.jsonl`
  on every child start, and the exporter's `_read_jsonl` cache is keyed by
  `(mtime, size)` so a *growing* manifest is re-parsed in full on every 15 s
  scrape.
- **Problem:** For 1000 runs this is O(n²) total reads over the experiment's
  life (each append invalidates the whole file), and the exporter holds every
  parsed record in `_Cache` with no eviction — memory grows for the exporter's
  lifetime.
- **Fix:** For the exporter, cache by byte offset and parse only the tail; for
  `_load_completed`, read once per child (already the case) — the real cost is
  the exporter. At minimum cap the exporter cache or key it without `size`.
- **If we skip it:** fine for a one-off 1000-run experiment; degrades only if
  the exporter runs continuously across many experiments.

### 5. Report/visualization scripts need `numpy`, `scikit-learn`, `matplotlib`, `graphviz`, but none are declared — `requirements.txt`, `scripts/analyze_token_chains.py:38-44`
- **What this is:** `analyze_token_chains.py` imports `matplotlib`, `numpy`,
  `sklearn`; `generate_diagrams.py` needs `graphviz`; `variety_report.py` and
  `experiment_report.py` need `matplotlib`. `requirements.txt` lists none of
  them.
- **Problem:** A fresh `pip install -r requirements.txt` (as the README
  instructs) cannot run the report, charts, or diagrams the README advertises
  as part of the experiment workflow. They happen to work here only because
  they were installed ad hoc into `venv`.
- **Fix:** Add the four to `requirements.txt` (or a
  `requirements-visualization.txt` the README points to). Pinning them is
  optional; declaring them is not.
- **If we skip it:** first-time setup on another machine fails at the report
  step, not the generation step.

### 6. Two copy-pasted `_excerpt` helpers and a per-call regex compile — `quality_agent/artifacts.py:57-65`, `quality_agent/contamination.py:170-185`, `quality_agent/lexicon.py:228-231`
- **What this is:** `artifacts.py` and `contamination.py` each define a nearly
  identical `_excerpt` (trim + center + elide). `lexicon.term_hits` compiles a
  fresh regex per term per call, and `_name_in`/`scan_name_contamination` do
  the same, so a single scan recompiles dozens of identical patterns.
- **Problem:** The duplicate `_excerpt` is textbook near-copy to merge; the
  per-call `re.compile` costs a little on every one of the 1000 campaign scans
  (each scan runs the labeler against many terms). Not a crash, just avoidable
  work and drift risk.
- **Fix:** Move `_excerpt` to `lexicon.py` (or `scan.py`) and import it in both;
  hoist the term patterns to module-level or use `re.compile` once per term in
  a cached dict.
- **If we skip it:** two divergent helpers and a small per-scan CPU cost; no
  correctness impact.

### 7. `scan_script_contamination` truncates its own count — `quality_agent/contamination.py:153-166`
- **What this is:** The loop stops after collecting 8 distinct offenders
  (`if len(offenders) == 8: break`) but reports `({len(offenders)}+ distinct)`.
- **Problem:** The "+" is honest about the truncation, but the reported count
  is capped at 8 regardless of the true number, so a text full of non-Latin
  script reports the same "8+" as one with exactly 8. It under-reports the
  magnitude the metric is meant to capture.
- **Fix:** Count distinct offenders to the end (drop the early `break`, or keep
  8 for the excerpt and count separately).
- **If we skip it:** the finding is still flagged (just the count is capped);
  only affects the detail string, not the pass/fail.

### 8. `generator_agent/agent.py` is dead code kept "for documentation" — `generator_agent/agent.py:1-19`, `README.md:287`
- **What this is:** The old LMQL query, superseded by the ADK content agent.
  The README documents it as legacy. Nothing imports it (grep confirms no
  `generator_agent.agent` reference anywhere in source or tests).
- **Problem:** It imports `lmql` (not in `requirements.txt`), so it is not even
  importable on a fresh install; it claims to mirror `assemble.rendered_prompt`
  "so the two cannot drift" — a promise that is now stale. Keeping a dead,
  unimportable module invites someone to "fix" it or believe it is authoritative.
- **Fix:** Delete it (its history lives in git). If the few-shot charter is
  still wanted, `prompts/generator_ag.md` and `generate_agent/assemble.CHARTER`
  are the live copies.
- **If we skip it:** harmless but misleading; a maintenance trap.

---

## Nice to have

### 9. Empty "hex/clean architecture" layer packages — `app/application/`, `app/domain/`, `app/infra/`, `app/services/` (all 0 bytes)
- **What this is:** Four empty `__init__.py` markers plus `app/presentation`
  and a typo'd `app/core/__init.py__.py` (note the extra `.py`) that the README
  describes as "placeholders for the hex/clean architecture layers".
- **Problem:** They communicate a layered design that does not exist — the
  actual code is one router + one schema module. The `__init.py__.py` filename
  is a typo (`__init__.py` typo'd to `__init.py__.py`), so `app.core` is
  *not* a package even though `app/core/schemas.py` is imported as one via
  namespace packages.
- **Fix:** Delete the four empty placeholder packages and the typo'd file; keep
  only `app/core/__init__.py` (rename `__init.py__.py`).
- **If we skip it:** no runtime effect, but the typo alone will confuse any IDE
  or future maintainer who expects `app.core` to behave like a package.

### 10. Two independent compose files (root `compose.yaml` = MailHog, `monitoring/compose.yaml` = full stack) — root `compose.yaml`, `monitoring/compose.yaml`
- **What this is:** The root `compose.yaml` runs only MailHog; the
  monitoring stack (Prometheus/Grafana/Alertmanager + runs-exporter) has its own
  `compose.yaml` under `monitoring/` with different ports.
- **Problem:** `docker compose up -d` from the root and `./monitoring/start.sh`
  are two separate lifecycles; the README's "alerts land in MailHog" depends on
  both being up. It is easy to run one without the other and wonder why alerts
  never arrive.
- **Fix:** Either document the two-lifecycle setup clearly in one place (it is
  split across the README and `monitoring/README.md`) or make the root compose
  reference MailHog as a dependency. No code change strictly needed.
- **If we skip it:** on-ramp friction for a developer, not a bug.

### 11. `color_for` uses `hash()` for a stable-looking color, but Python `hash` is salted per process — `scripts/analyze_token_chains.py:61-64`
- **What this is:** `_FALLBACK[abs(hash(model)) % len(_FALLBACK)]` assigns fallback
  colors for models not in the hardcoded `COLORS` map.
- **Problem:** `hash(str)` is randomized per interpreter run (PYTHONHASHSEED),
  so the same "unknown" model gets a different color from run to run; a
  reproducibility tool should not have non-deterministic color assignment.
- **Fix:** Hash deterministically (`sum(map(ord, model))`) or just iterate
  `_FALLBACK` in order.
- **If we skip it:** only affects chart cosmetics for models not in the six
  known names; the known six are stable.

---

## Verdict

The core is healthy: the deterministic layer is genuinely deterministic and
well unit-tested (123 tests pass, including the cross-channel link bug and the
sender-recipient regression). The schemas are the single source of truth and
the "findings are data, never repairs" discipline is consistently honored. The
two real bugs worth fixing now are **#2 (Ctrl-C leaves children running)** and
**#1 (live key on disk)**. Everything else is scale-bounded to a one-operator
experiment and cosmetic. Ship-daily quality; this is research code that is
unusually careful about its invariants.

**Lean: -1 file, ~-30 lines, -0 dependencies possible.** Delete
`generator_agent/agent.py` (dead LMQL, ~150 lines incl. its unused query) and
the four empty `app/*` placeholder packages (`-1` for the typo'd
`__init.py__.py`). Merge the duplicate `_excerpt` and remove ~4 per-call
`re.compile` sites. No dependency can be removed today (all pinned deps are
used), but 4 are *missing* from `requirements.txt` (finding #5), which is a
declaration gap, not a reduction.

## Not checked

I did not run the ADK pipeline end-to-end against a live model (no GPU/model in
this session), so the Ollama thinking shim and the `before/after/on_error`
callback metrics are validated only by reading the code, not by a real call. I
did not start the Grafana/Prometheus/Alertmanager stack, so the dashboard
queries' label-set correctness against the emitted metric names is unverified.
I did not inspect every one of the ~1000 committed experiment JSON artifacts
under `experiment/variety-1000/` (they are generated output, only spot-checked).
