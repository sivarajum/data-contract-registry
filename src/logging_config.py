"""Logging configuration for the Data Contract Registry.

Call ``setup_logging()`` once at application startup (in ``main.py``)
to apply a consistent format and level across all modules.
"""

import logging

from src.settings import LOG_LEVEL


def setup_logging() -> None:
    """Configure the root logger with a consistent format and level.

    Safe to call multiple times; ``force=True`` ensures handlers are
    replaced rather than duplicated.
    """
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
