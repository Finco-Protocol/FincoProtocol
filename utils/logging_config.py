"""Structured logging configuration for Generic Solar Reference financial model.

Provides consistent logging across all modules.
"""
import logging
import sys
from typing import Optional


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Get or create a logger with consistent formatting.

    Args:
        name: Logger name (typically __name__ of the module)
        level: Logging level (default INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Only add handler if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(level)

    return logger


def log_exception(logger: logging.Logger, exc: Exception, context: str) -> None:
    """Log an exception with context and continue.

    Args:
        logger: Logger instance
        exc: Exception that was caught
        context: Description of what was happening when error occurred
    """
    logger.error(f"{context}: {type(exc).__name__}: {exc}")


def log_warning(logger: logging.Logger, message: str) -> None:
    """Log a warning with consistent formatting."""
    logger.warning(message)


def log_info(logger: logging.Logger, message: str) -> None:
    """Log an info message."""
    logger.info(message)