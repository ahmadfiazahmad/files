"""
Central logging configuration.

Every module that swallows an exception to degrade gracefully (LLM fallback,
a research source timing out, a normalization failure, etc.) MUST log it
here instead of silently continuing - otherwise real failures become
invisible until a user reports a suspiciously empty report.

Usage in any module:
    import logging
    logger = logging.getLogger(__name__)
    ...
    logger.warning("Tavily search failed, falling back: %s", exc)
"""
import logging
import sys

from config import settings


def setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. re-imported under a test runner) - don't
        # add duplicate handlers.
        return

    root.setLevel(settings.log_level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)

    # Quiet down noisy third-party loggers unless we're at DEBUG.
    if settings.log_level.upper() != "DEBUG":
        for noisy in ("httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
