"""Centralised logging setup for TAT Guard recon pipeline.

Usage:
    from recon.logging_config import get_logger
    log = get_logger(__name__)
"""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure(level: str = "INFO") -> None:
    """Set up root logger with a consistent format across all modules."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring the root logger on first call."""
    configure()
    return logging.getLogger(name)
