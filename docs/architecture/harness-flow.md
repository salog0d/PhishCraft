# Reliability Harness — Flow

This Mermaid diagram is the authoritative flow of the reliability harness
(`scripts/reliability_matrix.py`) and the ADK pipeline it drives, as of the
current build (with the split parse/refinement instrumentation and the
corrected quality detectors).

```mermaid
flowchart TD
    %% ============ PARENT (orchestration) ============
    subgraph PARENT["scripts/reliability_matrix.py — parent process"]
        ARGS["CLI args<br/>--out --models --workers --run-timeout"]
        PLAN["build_plan(models)<br/>3 models × 3 temps × 12 cases × 3 seeds = 324 runs"]
        PJ["write plan.json"]
        SP["spawn one --child subprocess per model<br/>(--workers in parallel, ADK_MODEL set per child)"]
        WAIT["wait children; collect rc + child.log"]
        ARGS --> PLAN --> PJ --> SP --> WAIT
    end

    %% ============ CHILD (one model) ============
    subgraph CHILD["child process — one model, N runs"]
        LOAD["load plan.json<br/>ADK_MODEL = ollama/&lt;model&gt;"]
        SKIP["_load_completed: skip run_ids already 'ok' (resumable)"]
        LOOP{"for each remaining run"}
        RUNONE["run_one()<br/>build spec (temp, seed, max_tokens, pretext, tone, difficulty) + profile_for()"]
        LOAD --> SKIP --> LOOP --> RUNONE
    end

    %% ============ run_one -> pipeline ============
    subgraph PIPELINE["run_pipeline_with_info → agent.driver._run_async"]
        P1["Phase 1 — parse rejection sampling<br/>up to MAX_ATTEMPTS=3"]
        PAT["_attempt(): seed session → Runner → content agent → assembler → validator"]
        PARSE_OK{"parsed a valid campaign?"}
        STRICT["retry with STRICT_FORMAT"]
        P2["Phase 2 — self-refinement<br/>up to REFINE_EXTRA_ATTEMPTS=2"]
        STRUCT["_structural_issues():<br/>coherence_fail OR stage_direction/meta_bleed"]
        RAW["raw_link_violations &gt; 0?"]
        NEED{"needs_refine?"}
        CRITIC{"critique source?"}
        CLLM["critic LLM (deepseek) → critique_campaign"]
        DLINK["deterministic build_refinement (link fixes)"]
        REATT["_attempt(strict=True, refinement=critique)"]
        NPARSE{"no valid campaign<br/>after all attempts?"}
        INFO["info dict →<br/>n_parse_attempts, n_refine_rounds, refine_reason, refinement_improved"]
        ERR["raise RuntimeError → generation_error"]
    end

    %% ============ assembler + validator (ADK stages) ============
    subgraph ADK["ADK SequentialAgent (one _attempt)"]
        CONTENT["generator_content_agent (LlmAgent)<br/>emits 8 content bindings"]
        ASSEMBLER["assembler_agent (deterministic)<br/>persona, token, schedule, references, provenance"]
        VALIDATOR["validator_agent (deterministic)<br/>5 coherence checks → CoherenceReport"]
        CONTENT --> ASSEMBLER --> VALIDATOR
    end

    %% ============ post-run ============
    subgraph POST["post-run (run_one)"]
        QSCAN["scan_campaign (quality scan)<br/>9 checks + label audit + strip stats"]
        TRACE["read llm_trace.jsonl<br/>first_raw_response, calls, tokens"]
        ART["write artifacts:<br/>generated_campaign / coherence_report / quality_report / run.json / llm_trace.jsonl"]
        MAN["append run record to runs.jsonl (manifest, append-only, resumable)"]
        QSCAN --> TRACE --> ART --> MAN
    end

    %% ============ report ============
    subgraph REPORT["report step (--report / --repro)"]
        MASTER["master_table.json (one row per execution)"]
        SUMMARY["summary.md / summary.json<br/>delivery guarantee · errors · effort (parse vs refinement)"]
        CHARTS["reliability_charts.py → PNGs"]
    end

    %% ---- edges ----
    PARENT --> CHILD
    RUNONE --> PIPELINE
    P1 --> PAT --> PARSE_OK
    PARSE_OK -- "no" --> STRICT --> P1
    PARSE_OK -- "yes" --> P2
    P2 --> STRUCT
    P2 --> RAW
    STRUCT --> NEED
    RAW --> NEED
    NEED -- "yes (link_violation)" --> DLINK
    NEED -- "yes (structural)" --> CLLM
    NEED -- "no" --> INFO
    DLINK --> REATT
    CLLM --> REATT
    REATT -- "re-scan quality; refinement_improved?" --> P2
    P2 --> INFO
    NPARSE -- "yes" --> ERR
    ERR --> POST

    PAT -.-> ADK
    PIPELINE --> POST
    POST --> REPORT
```

## Key flow notes

1. **Parent** only builds the 324-cell plan and spawns one child per model (in
   parallel batches of `--workers`). It never runs the pipeline itself.
2. **Child** fixes `ADK_MODEL` to the model's frozen tag, then iterates its runs,
   skipping any `run_id` already recorded `ok` in the manifest (re-sumable).
3. **`run_one`** builds the spec (temperature/seed/max_tokens + pretext/tone/
   difficulty) and calls the real ADK pipeline.
4. **Phase 1** retries parsing up to 3 times with `STRICT_FORMAT`.
5. **Phase 2** refines up to 2 rounds when there is a *real* signal — a stale
   link token or a genuine structural finding (stage-direction / meta-bleed).
   The critique is either the critic LLM (structural) or the deterministic link
   `build_refinement` (links). Each round re-measures quality flags to record
   `refinement_improved`.
6. **Post-run** runs the quality scan, folds the LLM trace, writes artifacts,
   and appends one line to the append-only `runs.jsonl` manifest.
7. **Report** summarizes from the manifest: delivery guarantee (coherence, a
   construction invariant), errors by constraint, and effort split into parse
   vs refinement rounds.
