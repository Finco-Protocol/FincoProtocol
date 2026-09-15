"""FINCO Model logging configuration — structured text logging for ops visibility."""
import logging
import os
import sys


LOG_LEVEL = os.getenv("FINCO_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def configure_logging():
    """
    Configure application-wide logging for FINCO Model.
    
    Output: structured text logs to stdout (captured by systemd journal).
    
    Loggers:
        finco.requests  — HTTP request/response logging
        finco.exceptions — exception logging
        finco.waterfall — model run logging (INFO for starts, WARN for errors)
        finco.auth      — auth events (login attempts, rate limits)
    """
    root = logging.getLogger("finco")
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        root.addHandler(handler)

    # Silence noisy third-party loggers
    for noisy in ["uvicorn.access", "uvicorn.asgi", "httpx", "httpcore"]:
        logger = logging.getLogger(noisy)
        logger.setLevel(logging.WARNING)
        logger.handlers.clear()
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(h)

    return root


def get_logger(name: str) -> logging.Logger:
    """Get a named logger under the finco hierarchy."""
    return logging.getLogger(f"finco.{name}")