# Orchestrator — ADK SequentialAgent (non-executable design note)

> The Orchestrator is **not** an LLM agent anymore. It is the ADK
> `SequentialAgent` defined in `agent/pipeline.py`, which runs the three
> pipeline stages in a fixed order with no autonomy and no feedback edge:

1. `generator_content_agent` (`LlmAgent`) — emits the 8 content bindings.
2. `assembler_agent` (`BaseAgent`, deterministic) — builds the
   `GeneratedCampaign`.
3. `validator_agent` (`BaseAgent`, deterministic) — emits the `CoherenceReport`.

The `MissionConfig` is loaded from a file (`config/`) and seeded into session
state before the run; nothing about the flow is decided by a model.
