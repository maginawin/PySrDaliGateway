#!/usr/bin/env python3
"""Main entry point for DALI Gateway testing.

This script provides modular testing for PySrDaliGateway functionality including
discovery, connection, device control, and real-time status updates.

All test results are logged to both console and timestamped log files in the
script/logs/ directory.
"""

import asyncio
import logging
import sys

from test_cases import DaliGatewayTester
from test_config import list_available_tests, parse_arguments
from test_logger import setup_test_logging
from test_runner import run_selected_tests

from PySrDaliGateway.exceptions import DaliGatewayError

_LOGGER = logging.getLogger(__name__)


async def main() -> bool:
    """Main entry point."""
    args = parse_arguments()

    if args.list_tests:
        list_available_tests()
        return True

    # Set up logging with file output
    log_file = setup_test_logging()
    _LOGGER.info("Test results will be saved to: %s", log_file)

    # Validate testing mode arguments
    testing_mode_args = [
        args.direct_sn,
        args.direct_ip,
        args.direct_username,
        args.direct_passwd,
    ]
    partial_testing_mode = any(testing_mode_args) and not all(testing_mode_args)

    if partial_testing_mode:
        _LOGGER.error(
            "Testing mode requires all of: --direct-sn, --direct-ip, --direct-username, --direct-passwd"
        )
        return False

    if all(testing_mode_args):
        _LOGGER.info("Running in testing mode (skip discovery)")
        _LOGGER.info(
            "Gateway: %s at %s:%s", args.direct_sn, args.direct_ip, args.direct_port
        )

    try:
        tester = DaliGatewayTester()
        success = await run_selected_tests(tester, args)

        # Log session end
        _LOGGER.info("=" * 60)
        _LOGGER.info("DALI Gateway Test Session Ended")
        _LOGGER.info("Log file: %s", log_file)
        _LOGGER.info("=" * 60)

        return success

    except KeyboardInterrupt:
        _LOGGER.error("Testing interrupted by user")
        return False
    except (DaliGatewayError, RuntimeError, asyncio.TimeoutError) as e:
        _LOGGER.error("Unexpected error during testing: %s", e)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
