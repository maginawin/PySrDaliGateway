#!/usr/bin/env python3
"""Configuration and argument parsing for DALI Gateway tests."""

import argparse
from typing import Any


def parse_arguments() -> Any:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Modular DALI Gateway Testing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Run all tests with discovery
  %(prog)s --tests discovery connection # Run only discovery and connection tests
  %(prog)s --list-tests                 # List available tests
  %(prog)s --device-limit 5             # Limit device operations to 5 devices
  %(prog)s --gateway-index 1            # Connect to second discovered gateway

  # Testing mode (skip discovery):
  %(prog)s --direct-sn GW123456 --direct-ip 192.168.1.100 --direct-username admin --direct-passwd password123
  %(prog)s --direct-sn GW789012 --direct-ip 192.168.1.101 --direct-port 8883 --direct-username user --direct-passwd secret --direct-tls
        """,
    )

    parser.add_argument(
        "--tests",
        nargs="+",
        choices=[
            "discovery",
            "connection",
            "disconnect",
            "reconnection",
            "statusync",
            "version",
            "devices",
            "readdev",
            "setdevparam",
            "groups",
            "readgroup",
            "scenes",
            "readscene",
            "callbacks",
            "identifygateway",
            "identifydevice",
            "restart",
            "all",
        ],
        default=["all"],
        help="Tests to run (default: all)",
    )

    parser.add_argument(
        "--list-tests", action="store_true", help="List available tests and exit"
    )

    parser.add_argument(
        "--gateway-index",
        type=int,
        default=0,
        help="Gateway index to connect to (default: 0)",
    )

    parser.add_argument(
        "--device-limit",
        type=int,
        help="Limit number of devices for testing (default: all devices)",
    )

    parser.add_argument(
        "--gateway-sn", type=str, help="Specific gateway serial number to discover"
    )

    # Testing mode arguments for skip discovery
    testing_group = parser.add_argument_group(
        "testing mode (skip discovery)",
        "Use these arguments to bypass discovery and connect directly",
    )
    testing_group.add_argument(
        "--direct-sn", type=str, help="Gateway serial number (testing mode)"
    )
    testing_group.add_argument(
        "--direct-ip", type=str, help="Gateway IP address (testing mode)"
    )
    testing_group.add_argument(
        "--direct-port",
        type=int,
        default=1883,
        help="Gateway MQTT port (testing mode, default: 1883)",
    )
    testing_group.add_argument(
        "--direct-username", type=str, help="Gateway username (testing mode)"
    )
    testing_group.add_argument(
        "--direct-passwd", type=str, help="Gateway password (testing mode)"
    )
    testing_group.add_argument(
        "--direct-tls", action="store_true", help="Use TLS connection (testing mode)"
    )
    testing_group.add_argument(
        "--direct-name", type=str, help="Gateway name (testing mode, optional)"
    )

    return parser.parse_args()


def list_available_tests() -> None:
    """Print list of available tests."""
    print("Available tests:")
    tests = {
        "discovery": "Discover DALI gateways on network",
        "connection": "Connect to discovered gateway",
        "disconnect": "Disconnect from gateway",
        "reconnection": "Test disconnect/reconnect cycle",
        "statusync": "Test gateway status synchronization via online_status callback",
        "version": "Get gateway firmware version",
        "devices": "Discover connected DALI devices",
        "readdev": "Read device status via MQTT",
        "setdevparam": "Set device parameters (maxBrightness)",
        "groups": "Discover DALI groups",
        "readgroup": "Read group details with device list",
        "scenes": "Discover DALI scenes",
        "readscene": "Read scene details with device list and property values",
        "callbacks": "Test device status callbacks (light, motion, illuminance, panel)",
        "identifygateway": "Identify gateway (makes gateway LED blink)",
        "identifydevice": "Identify devices (makes device LEDs blink)",
        "restart": "Restart gateway (WARNING: gateway will disconnect)",
        "all": "Run complete test suite",
    }

    for test_name, description in tests.items():
        print(f"  {test_name:<12} - {description}")
