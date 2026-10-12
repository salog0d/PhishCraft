# Orchestrator — ADK SequentialAgent (non-executable design note)

> The Orchestrator is **not** an LLM agent anymore. It is the ADK
> `SequentialAgent` defined in `agent/pipeline.py`, which runs the three
> pipeline stages in a fixed order with no autonomy. The only feedback edge
> is the **driver-level self-refinement loop** (`agent/driver.py`): when a
> parsed campaign carries stale link tokens (`link_fixes`), the driver
> re-runs the whole pipeline with a critique built from those fixes — up to
> two extra rounds, content-only, no victim feedback:

1. `generator_content_agent` (`LlmAgent`) — emits the 8 content bindings.
2. `assembler_agent` (`BaseAgent`, deterministic) — builds the
   `GeneratedCampaign`.
3. `validator_agent` (`BaseAgent`, deterministic) — emits the `CoherenceReport`.

The `MissionConfig` is loaded from a file (`config/`) and seeded into session
state before the run; nothing about the flow is decided by a model.
