"""
app/core/logging.py
-------------------
Structured JSON logging via structlog.
Call configure_logging() once at app startup.
"""

import logging
import structlog
from app.core.config import settings


def configure_logging() -> None:
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging so third-party libs are captured
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
    )


log = structlog.get_logger()
