import sys
from pathlib import Path

from loguru import logger


def configure_logging(log_path: Path = Path("python.log")) -> None:
    """Configure Loguru sinks for console output and the app log file."""
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {message}",
    )
    logger.add(
        log_path,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} | {message}",
        backtrace=True,
        diagnose=False,
    )
