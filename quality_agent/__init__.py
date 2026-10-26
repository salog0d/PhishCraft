"""Deterministic post-run quality scanner (no LLM).

Implements the paper's dataset-quality lifecycle — generation-artifact scan,
contamination scan, stage-direction stripping, automated label audit — as
post-run checks over every generated campaign. See ``scan.scan_campaign``.
"""

from .scan import CHECK_NAMES, scan_campaign

__all__ = ["CHECK_NAMES", "scan_campaign"]
