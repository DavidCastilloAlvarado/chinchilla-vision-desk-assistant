"""Logging to the state directory, also visible on stderr."""

from __future__ import annotations

import logging
import logging.handlers

from . import paths

_configured = False


def setup(level: int = logging.INFO) -> logging.Logger:
    global _configured
    logger = logging.getLogger("chinchilla")
    if _configured:
        return logger
    paths.ensure_dirs()
    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.handlers.RotatingFileHandler(
        paths.log_path(), maxBytes=512_000, backupCount=3
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(stream)
    _configured = True
    return logger


def get(name: str) -> logging.Logger:
    return setup().getChild(name)
