#!/usr/bin/env python3
"""Logging setup for DALI Gateway tests with file and console output."""

from datetime import datetime
import logging
from pathlib import Path
import sys


def setup_test_logging(log_level: int = logging.DEBUG) -> Path:
    """Set up logging with both console and file output.

    Args:
        log_level: Logging level (default: DEBUG)

    Returns:
        Path to the log file
    """
    # Create logs directory
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # Generate timestamped log filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"test_{timestamp}.log"

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Log the start of the session
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("DALI Gateway Test Session Started")
    logger.info("Log file: %s", log_file)
    logger.info("=" * 60)

    return log_file
