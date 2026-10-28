# PhishCraft Observability — Grafana + Prometheus + Alertmanager

The LLM-ops stack for the project: every campaign generation, every LLM call
(latency, tokens, thinking volume), every quality/coherence/label-audit
finding, and the GPU/VRAM state of the Ollama host.

```
experiment (runs.jsonl + llm_trace.jsonl) ──> runs-exporter (:9091) ──┐
GPU (nvidia-smi)                            ──> gpu-exporter  (:9400) ──┤
FastAPI app (:8000, /metrics)               ────────────────────────────┤
host (node-exporter :9100)                  ────────────────────────────┤
                                                                        v
                                                              Prometheus (:9099)
                                                                        │  rules → alerts
                                                                        v
                                                              Alertmanager (:9093)
                                                                        │  email via SMTP
                                                                        v
                                                              MailHog sink (:1025, UI :8025)
Grafana (:3000) ←── provisioned dashboards: LLM Operations, Experiment
                     Health, GPU & Host
```

## Start / stop

```bash
# 1. The container stack (prometheus, alertmanager, grafana, node-exporter,
#    runs-exporter):
docker compose -f monitoring/compose.yaml up -d

# 2. The GPU exporter (host process — needs nvidia-smi):
venv/bin/python monitoring/gpu_exporter.py            # foreground
nohup venv/bin/python monitoring/gpu_exporter.py &    # or background

# Convenience: both steps
./monitoring/start.sh

# Stop
docker compose -f monitoring/compose.yaml down
```

- **Grafana** — http://localhost:3000 (admin / admin), folder `PhishCraft`
- **Prometheus** — http://localhost:9099 (host port 9090 is taken by a
  system-level Prometheus on this machine, so the stack publishes on 9099)
- **Alertmanager** — http://localhost:9093
- **Alerts** land as emails in the MailHog sink (http://localhost:8025,
  started via the repo-root `compose.yaml`).

## What is measured

### Process metrics (live, `phishcraft_*`)

| metric | labels | recorded by |
|---|---|---|
| `phishcraft_llm_calls_total` | model, agent, status | `agent/model_trace.py` ADK callbacks |
| `phishcraft_llm_call_duration_seconds` (histogram) | model | same |
| `phishcraft_llm_tokens_total` | model, type (prompt/completion/total) | same |
| `phishcraft_llm_thinking_chars_total` | model | same |
| `phishcraft_pipeline_runs_total` | model, status | `agent/driver.py` |
| `phishcraft_pipeline_attempts_total` / `_refinements_total` | model | same |
| `phishcraft_pipeline_duration_seconds` (histogram) | model | same |
| `phishcraft_http_requests_total` / `_duration_seconds` | method, route, status | `app/main.py` middleware + `/metrics` |

### Experiment metrics (`phishcraft_experiment_*`, served by the runs-exporter)

Gauges derived at scrape time from the append-only `runs.jsonl` (deduped by
`run_id`, last line wins) and each run's `llm_trace.jsonl`. Per-file parse
results are cached by mtime, so scrapes are cheap even mid-experiment.

- `runs_total{experiment, model, status}` — ok / generation_error / timeout
- `duration_seconds{experiment, model, quantile}` — mean, p50, p95, max
- `quality_findings_total` / `campaigns_flagged_total{..., check}` — all 9 checks
- `contaminated_total{..., check}` · `label_mismatches_total{..., label}` ·
  `label_unverifiable_total{..., label}`
- `coherence_failures_total{..., check}` — the 5 validator checks
- `attempts_total` · `refined_total` · `raw_link_violations_total` ·
  `strip_affected_messages_total` · `strip_chars_total`
- `llm_calls_total` · `llm_errors_total` · `llm_tokens_total{..., type}` ·
  `llm_thinking_chars_total` · `llm_duration_seconds{..., quantile}`

Rates in dashboards/alerts use `delta()` (the metrics are cumulative gauges,
not counters, because the experiment children are short-lived subprocesses).

### GPU & host

- `phishcraft_gpu_*` (host `gpu_exporter.py`): VRAM used/total bytes,
  utilization, temperature, power draw — the "is Ollama spilling to CPU"
  early-warning signals.
- `node_*` (node-exporter): CPU, memory, load, disk, network of the host.

## Alerts

Defined in `monitoring/prometheus/alerts/llm.yml` (12 rules, validated with
`promtool check rules`):

| alert | severity | meaning |
|---|---|---|
| `LLMGenerationErrors` | warning | > 2 generation errors / 10 min on a model |
| `LLMTimeouts` | critical | a campaign hit the per-run wall-clock budget |
| `LLMCallLatencyHigh` | warning | p95 LLM call > 4 min (VRAM spill signature) |
| `LLMHighRetryRate` | warning | mean attempts per campaign > 1.5 |
| `LLMErrorCalls` | critical | > 3 failed LLM calls / 10 min |
| `CoherenceFailures` | critical | any validator failure (should be 0 by construction) |
| `ContaminationDetected` | warning | contamination flags on generated copy |
| `QualityFlagSpike` | warning | > 20 new flagged campaigns / 30 min |
| `LabelMismatchRateHigh` | info | label-audit mismatches > 2 per campaign |
| `GPUVRAMHigh` | warning | VRAM > 90 % |
| `GPUTemperatureHigh` | warning | GPU > 85 °C |
| `PhishcraftExporterDown` | critical | runs/gpu exporter unreachable |

Alertmanager routes everything to the MailHog sink by SMTP
(`host.docker.internal:1025`) — open http://localhost:8025 to read alerts.
Swap `route.receiver` to `webhook` (URL placeholder in
`monitoring/alertmanager/alertmanager.yml`) to route to Slack/Discord.

## Wiring notes

- **LLM callbacks are always on**: `agent/model_trace.py` stashes call timing
  for every ADK model call even when `ADK_MODEL_TRACE_FILE` is unset; the
  trace file (prompt/answer/usage JSONL) is only written when the env var is
  set. The variety experiment sets it per run
  (`scripts/variety_experiment.py`), so every run gets its own
  `llm_trace.jsonl` that the runs-exporter folds into metrics.
- **No metrics code can break generation**: every `prometheus_client` import
  is guarded; `monitoring/metrics.py` degrades to no-ops without the package.
- **The exporters are scrape-driven**: they hold no state beyond a parse
  cache, so restarting them (or Prometheus) loses nothing; mid-run scrapes
  see the manifest as it grows.
- **Two Prometheuses**: a system-level Prometheus (apt, `/etc/prometheus/`)
  already owns host port 9090 on this machine — the project stack publishes
  on 9099. Consolidate only if you know what that instance is for.

## Tests & validation

```bash
# configs
docker run --rm --entrypoint promtool -v $PWD/monitoring/prometheus:/etc/prometheus:ro \
  prom/prometheus:v3.2.0 check rules /etc/prometheus/alerts/llm.yml
docker run --rm --entrypoint amtool -v $PWD/monitoring/alertmanager:/etc/alertmanager:ro \
  prom/alertmanager:v0.28.0 check-config /etc/alertmanager/alertmanager.yml

# exporters
RUNS_EXPORTER_DIRS=experiment venv/bin/python monitoring/runs_exporter.py
curl -s localhost:9091/metrics | grep phishcraft_experiment

# end-to-end alert loop
docker run --rm --add-host host.docker.internal:host-gateway \
  --entrypoint amtool prom/alertmanager:v0.28.0 alert add \
  --alertmanager.url=http://host.docker.internal:9093 \
  alertname=PhishCraftTestAlert severity=info
# → http://localhost:8025 shows the [FIRING:1] email
```
