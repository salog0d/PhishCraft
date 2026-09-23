"""ADK agent package: exposes the campaign pipeline as ``root_agent``."""

from . import pipeline
from .pipeline import root_agent

__all__ = ["pipeline", "root_agent"]
