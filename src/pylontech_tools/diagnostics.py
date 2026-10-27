"""Metadata diagnostics and separately enabled, potentially private serial traces."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Below DEBUG so configuring ordinary library debug logging never enables raw I/O.
SERIAL_TRACE = 5
logging.addLevelName(SERIAL_TRACE, "TRACE")
serial_logger = logging.getLogger("pylontech_tools.serial")


def command_label(command: str) -> str:
    """Keep known protocol arguments; omit identity-bearing or arbitrary values."""
    parts = command.split()
    if not parts:
        return "<enter>"
    known = {
        "info",
        "stat",
        "time",
        "log",
        "config",
        "login",
        "pwr",
        "getpwr",
        "pwrsys",
        "datalist",
        "data",
        "eepe",
        "trst",
        "setlowcfg",
        "tbar",
        "cmdquit",
        "totalcoul",
        "tcycle",
        "emptyvolt",
        "ctrl",
        "prot",
        "euro",
        "trdagevolt",
        "soh",
    }
    if parts[0] not in known:
        return "<command>"
    if parts[0] == "tbar":
        return "tbar <redacted>"
    safe_words = {"debug", "event", "history", "misc", "dtls"}
    return " ".join(
        [parts[0]]
        + [
            p if p in safe_words or p.isascii() and p.isdecimal() else "<redacted>"
            for p in parts[1:]
        ]
    )


@contextmanager
def configure_logging(
    *,
    debug: bool = False,
    trace_serial: bool = False,
    log_file: Path | None = None,
) -> Iterator[None]:
    """Configure only our CLI logger, restoring embedding applications' state."""
    if not (debug or trace_serial or log_file):
        yield
        return
    logger = logging.getLogger("pylontech_tools")
    previous = logger.level, logger.propagate, logger.handlers[:], serial_logger.level
    handler = (
        logging.FileHandler(log_file, mode="x", encoding="utf-8")
        if log_file is not None
        else logging.StreamHandler()
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    try:
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        serial_logger.setLevel(SERIAL_TRACE if trace_serial else logging.INFO)
        logger.debug("Diagnostics enabled; serial tracing=%s", trace_serial)
        yield
    finally:
        logger.setLevel(previous[0])
        logger.propagate = previous[1]
        logger.handlers = previous[2]
        serial_logger.setLevel(previous[3])
        handler.close()


def failure_diagnostic(exc: BaseException | None) -> str:
    """Format only the failed exchange, never a history of successful traffic."""
    if exc is None:
        return ""
    # Reset wraps the wire error with recovery instructions.
    while not hasattr(exc, "response") and exc.__cause__ is not None:
        exc = exc.__cause__
    context = getattr(exc, "context", {})
    if not context and not hasattr(exc, "response"):
        return ""
    fields = " ".join(f"{key}={value!r}" for key, value in context.items())
    response = getattr(exc, "response", "").encode("utf-8")
    tail = response[-4096:].decode("utf-8", errors="replace")
    detail = repr(tail) if response else "<nothing received>"
    if len(response) > 4096:
        detail = "[truncated to last 4096 bytes] " + detail
    return f"Last communication: {fields}\nResponse: {detail}"
