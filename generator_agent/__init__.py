"""Standalone Generator-AG: the generation stage as a self-contained module.

- ``assemble`` — model-free construction of the ``GeneratedCampaign``: persona
  stamping, reference wiring, channel shaping, and provenance hashing. The
  process this agent represents, unit-testable without an API key.
- ``agent`` — the constrained LMQL query producing the text bindings. Imported
  lazily by ``run`` because it requires the ``lmql`` package.
- ``run`` — CLI entry point (``python -m generator_agent.run``).

The spec for this stage lives in ``prompts/generator_ag.md``; the constants
here mirror it and must be kept in sync.
"""

from generator_agent.assemble import assemble_campaign

__all__ = ["assemble_campaign"]
