"""The server's own messages (the mbs.* loggers) on standard error, each with its time, level and source; uvicorn
keeps its own lines. Without this, Python printed only the text of warnings and errors and dropped every message
below WARNING."""

from __future__ import annotations

import logging
from typing import TextIO

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
HANDLER = "mbs"


def configure(stream: TextIO | None = None) -> None:
    """Show the server's messages from INFO up on standard error, or on `stream`. A second call changes nothing."""
    logger = logging.getLogger("mbs")
    if not any(handler.get_name() == HANDLER for handler in logger.handlers):
        handler = logging.StreamHandler(stream)
        handler.set_name(HANDLER)
        handler.setFormatter(logging.Formatter(FORMAT))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
