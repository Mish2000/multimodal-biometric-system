"""The server's own log: its messages carry their time, level and source, from INFO up, and no other library's."""

from __future__ import annotations

import io
import logging
import re

from mbs import logs

TIME = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}"


def test_the_servers_messages_carry_their_time_level_and_source():
    logger = logging.getLogger("mbs")
    handlers, level = list(logger.handlers), logger.level
    stream = io.StringIO()
    try:
        logs.configure(stream)
        logs.configure(stream)  # a second call adds nothing
        assert [handler.get_name() for handler in logger.handlers].count(logs.HANDLER) == 1
        logging.getLogger("mbs.scanner").info("the scanner is ready")
        logging.getLogger("mbs.face").warning("the face engine failed a request")
        logging.getLogger("elsewhere").warning("another library's message")
        lines = stream.getvalue().splitlines()
        assert len(lines) == 2, lines
        assert re.fullmatch(rf"{TIME} INFO mbs\.scanner: the scanner is ready", lines[0]), lines[0]
        assert re.fullmatch(rf"{TIME} WARNING mbs\.face: the face engine failed a request", lines[1]), lines[1]
    finally:
        logger.handlers[:] = handlers
        logger.setLevel(level)
