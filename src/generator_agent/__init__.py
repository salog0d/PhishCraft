"""Standalone Generator-AG: the generation stage as a self-contained module.

- ``assemble`` — model-free construction of the ``GeneratedCampaign``: persona
  stamping, reference wiring, channel shaping, and provenance hashing. The
  process this agent represents, unit-testable without an API key.
- ``agent`` — the constrained LMQL query producing the text bindings. Imported
  lazily by ``run`` because it requires the ``lmql`` package.
- ``run`` — CLI entry point (``python -m generator_agent.run``).

The charter/spec for this stage is the ``CHARTER`` constant in
``generator_agent.assemble`` — the single source of truth.
"""

from generator_agent.assemble import assemble_campaign

__all__ = ["assemble_campaign"]
