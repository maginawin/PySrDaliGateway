#!/usr/bin/env python3
"""Modular test script for PySrDaliGateway with configurable test selection."""

import argparse
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PySrDaliGateway.discovery import DaliGatewayDiscovery
from PySrDaliGateway.exceptions import DaliGatewayError
from PySrDaliGateway.gateway import DaliGateway
from PySrDaliGateway.types import DaliGatewayType, DeviceType, GroupType, SceneType

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

_LOGGER = logging.getLogger(__name__)


class DaliGatewayTester:
    """Modular tester for DALI Gateway functionality."""

    def __init__(self):
        self.discovery: Optional[DaliGatewayDiscovery] = None
        self.gateways: List[DaliGatewayType] = []
        self.gateway: Optional[DaliGateway] = None
        self.gateway_config: Optional[DaliGatewayType] = None
        self.devices: List[DeviceType] = []
        self.groups: List[GroupType] = []
        self.scenes: List[SceneType] = []
        self.is_connected = False

    async def test_discovery(self, gateway_sn: Optional[str] = None) -> bool:
        """Step 1: Discover DALI gateways."""
        _LOGGER.info("=== Testing Gateway Discovery ===")

        if not self.discovery:
            self.discovery = DaliGatewayDiscovery()

        try:
            self.gateways = await self.discovery.discover_gateways(gateway_sn)
            _LOGGER.debug("Discovered gateways: %s", self.gateways)

            if not self.gateways:
                _LOGGER.error(
                    "No gateways discovered! "
                    "Check network connectivity and gateway power"
                )
                return False
        except DaliGatewayError as e:
            _LOGGER.error("Discovery failed: %s", e)
            return False

        _LOGGER.info("✓ Found %d gateway(s)", len(self.gateways))

        for i, gw in enumerate(self.gateways):
            _LOGGER.info(
                "  Gateway %d: %s (%s) at %s:%s",
                i + 1,
                gw["name"],
                gw["gw_sn"],
                gw["gw_ip"],
                gw["port"],
            )
        return True

    async def test_connection(self, gateway_index: int = 0) -> bool:
        """Step 2: Connect to specified gateway."""
        if not self.gateways:
            _LOGGER.error("No gateways available! Run discovery first.")
            return False

        if gateway_index >= len(self.gateways):
            _LOGGER.error(
                "Gateway index %d out of range (0-%d)",
                gateway_index,
                len(self.gateways) - 1,
            )
            return False

        _LOGGER.info("=== Testing Gateway Connection ===")
        selected_gateway = self.gateways[gateway_index]
        self.gateway_config = {**selected_gateway}
        _LOGGER.info("Connecting to gateway '%s'...",
                     self.gateway_config["name"])
        _LOGGER.info("Gateway config: %s", self.gateway_config)

        self.gateway = DaliGateway(self.gateway_config)

        try:
            await self.gateway.connect()
            self.is_connected = True
            _LOGGER.info("✓ Successfully connected to gateway!")
            return True
        except DaliGatewayError as e:
            _LOGGER.error("Connection error: %s", e)
            self.is_connected = False
            return False

    async def test_disconnect(self) -> bool:
        """Disconnect from gateway."""
        if not self.gateway or not self.is_connected:
            _LOGGER.warning("Not connected to any gateway")
            return True

        _LOGGER.info("=== Testing Gateway Disconnect ===")
        try:
            await self.gateway.disconnect()
            self.is_connected = False
            _LOGGER.info("✓ Disconnected successfully")
            return True
        except DaliGatewayError as e:
            _LOGGER.error("Disconnect error: %s", e)
            return False

    async def test_reconnection(self) -> bool:
        """Test disconnect and reconnect cycle."""
        _LOGGER.info("=== Testing Reconnection Cycle ===")

        # First disconnect
        if not await self.test_disconnect():
            return False

        # Re-discover to get updated gateway info
        if not self.gateway_config:
            _LOGGER.error("No gateway config available")
            return False

        _LOGGER.info("Re-discovering gateway...")
        if not await self.test_discovery(self.gateway_config["gw_sn"]):
            return False

        # Update credentials from original config
        new_gateway = self.gateways[0]
        new_config: DaliGatewayType = {
            **new_gateway,
            "username": self.gateway_config.get("username", ""),
            "passwd": self.gateway_config.get("passwd", ""),
        }

        # Reconnect
        self.gateway_config = new_config
        self.gateway = DaliGateway(self.gateway_config)

        return await self.test_connection(0)

    async def test_version(self) -> bool:
        """Test gateway version retrieval."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Version Retrieval ===")
        try:
            gateway = self._assert_gateway()
            version = await gateway.get_version()
            _LOGGER.info("✓ Gateway version: %s", version)
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Version test failed: %s", e)
            return False

    async def test_device_discovery(self) -> bool:
        """Test device discovery."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Device Discovery ===")
        try:
            gateway = self._assert_gateway()
            self.devices = await gateway.discover_devices()
            _LOGGER.info("✓ Found %d device(s)", len(self.devices))

            for device in self.devices[:5]:  # Show first 5 devices
                _LOGGER.info(
                    "  Device: %s (%s) - Channel %s, Address %s",
                    device["name"],
                    device["dev_type"],
                    device["channel"],
                    device["address"],
                )
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Device discovery failed: %s", e)
            return False

    async def test_read_dev(self, device_limit: Optional[int] = None) -> bool:
        """Test reading device status."""
        if not self._check_connection():
            return False

        if not self.devices:
            _LOGGER.error("No devices available! Run device discovery first.")
            return False

        _LOGGER.info("=== Testing ReadDev Commands ===")
        try:
            devices_to_test = self.devices
            if device_limit:
                devices_to_test = self.devices[:device_limit]

            for device in devices_to_test:
                _LOGGER.info(
                    "Reading device: %s (Channel %s, Address %s)",
                    device["name"],
                    device["channel"],
                    device["address"],
                )
                gateway = self._assert_gateway()
                gateway.command_read_dev(
                    device["dev_type"], device["channel"], device["address"]
                )

            _LOGGER.info("✓ ReadDev commands sent for %d devices",
                         len(devices_to_test))
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("ReadDev test failed: %s", e)
            return False

    async def test_get_dev_param(self, device_limit: int = 3) -> bool:
        """Test getting device parameters."""
        if not self._check_connection():
            return False

        if not self.devices:
            _LOGGER.error("No devices available! Run device discovery first.")
            return False

        _LOGGER.info("=== Testing GetDevParam Commands ===")
        try:
            devices_to_test = self.devices[:device_limit]

            for device in devices_to_test:
                _LOGGER.info(
                    "Getting device parameters for: %s (Channel %s, Address %s)",
                    device["name"],
                    device["channel"],
                    device["address"],
                )
                gateway = self._assert_gateway()
                gateway.command_get_dev_param(
                    device["dev_type"], device["channel"], device["address"]
                )

            # Test with special "FFFF" parameter
            _LOGGER.info("Testing special FFFF parameter...")
            gateway = self._assert_gateway()
            gateway.command_get_dev_param("FFFF", 0, 0)

            _LOGGER.info(
                "✓ GetDevParam commands sent for %d devices", len(
                    devices_to_test)
            )
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("GetDevParam test failed: %s", e)
            return False

    async def test_group_discovery(self) -> bool:
        """Test group discovery."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Group Discovery ===")
        try:
            gateway = self._assert_gateway()
            self.groups = await gateway.discover_groups()
            _LOGGER.info("✓ Found %d group(s)", len(self.groups))
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Group discovery failed: %s", e)
            return False

    async def test_scene_discovery(self) -> bool:
        """Test scene discovery."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Scene Discovery ===")
        try:
            gateway = self._assert_gateway()
            self.scenes = await gateway.discover_scenes()
            _LOGGER.info("✓ Found %d scene(s)", len(self.scenes))
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Scene discovery failed: %s", e)
            return False

    def _check_connection(self) -> bool:
        """Check if gateway is connected."""
        if not self.gateway or not self.is_connected:
            _LOGGER.error(
                "Not connected to gateway! Run connection test first.")
            return False
        return True

    def _assert_gateway(self) -> DaliGateway:
        """Assert gateway is connected and return it."""
        if not self.gateway or not self.is_connected:
            raise RuntimeError("Gateway not connected")
        return self.gateway

    async def run_all_tests(self) -> bool:
        """Run all tests in proper sequence."""
        _LOGGER.info("=== Starting Complete DALI Gateway Test Suite ===")

        tests: List[Tuple[str, Callable[[], Any]]] = [
            ("Discovery", self.test_discovery),
            ("Connection", lambda: self.test_connection(0)),
            ("Version", self.test_version),
            ("Device Discovery", self.test_device_discovery),
            ("ReadDev", self.test_read_dev),
            ("GetDevParam", lambda: self.test_get_dev_param(3)),
            ("Group Discovery", self.test_group_discovery),
            ("Scene Discovery", self.test_scene_discovery),
            ("Reconnection", self.test_reconnection),
            ("Disconnect", self.test_disconnect),
        ]

        results: Dict[str, bool] = {}
        for test_name, test_func in tests:
            try:
                result = await test_func()
                results[test_name] = result
                if not result:
                    _LOGGER.error("❌ %s test failed", test_name)
                else:
                    _LOGGER.info("✅ %s test passed", test_name)
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.error(
                    "❌ %s test failed with exception: %s", test_name, e)
                results[test_name] = False

        passed = sum(1 for r in results.values() if r)
        total = len(results)

        _LOGGER.info("=== Test Summary ===")
        _LOGGER.info("Passed: %d/%d tests", passed, total)

        for test_name, result in results.items():
            status = "✅" if result else "❌"
            _LOGGER.info("%s %s", status, test_name)

        success = passed == total
        if success:
            _LOGGER.info("🎉 All tests completed successfully!")
        else:
            _LOGGER.error("❌ Some tests failed!")

        return success


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Modular DALI Gateway Testing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Run all tests
  %(prog)s --tests discovery connection # Run only discovery and connection tests  
  %(prog)s --list-tests                 # List available tests
  %(prog)s --device-limit 5             # Limit device operations to 5 devices
  %(prog)s --gateway-index 1            # Connect to second discovered gateway
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
            "version",
            "devices",
            "readdev",
            "devparam",
            "groups",
            "scenes",
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
        "--devparam-limit",
        type=int,
        default=3,
        help="Limit number of devices for getDevParam test (default: 3)",
    )

    parser.add_argument(
        "--gateway-sn", type=str, help="Specific gateway serial number to discover"
    )

    return parser.parse_args()


async def run_selected_tests(tester: DaliGatewayTester, args: Any) -> bool:
    """Run selected tests with dependency management."""

    # Available tests with dependencies
    test_registry: Dict[str, Tuple[Callable[[], Any], List[str], str]] = {
        "discovery": (tester.test_discovery, [], "Gateway Discovery"),
        "connection": (
            lambda: tester.test_connection(args.gateway_index),
            ["discovery"],
            "Gateway Connection",
        ),
        "disconnect": (tester.test_disconnect, ["connection"], "Gateway Disconnect"),
        "reconnection": (
            tester.test_reconnection,
            ["connection"],
            "Reconnection Cycle",
        ),
        "version": (tester.test_version, ["connection"], "Version Retrieval"),
        "devices": (tester.test_device_discovery, ["connection"], "Device Discovery"),
        "readdev": (
            lambda: tester.test_read_dev(args.device_limit),
            ["connection", "devices"],
            "ReadDev Commands",
        ),
        "devparam": (
            lambda: tester.test_get_dev_param(args.devparam_limit),
            ["connection", "devices"],
            "GetDevParam Commands",
        ),
        "groups": (tester.test_group_discovery, ["connection"], "Group Discovery"),
        "scenes": (tester.test_scene_discovery, ["connection"], "Scene Discovery"),
    }

    # Determine which tests to run
    if "all" in args.tests:
        selected_tests = [
            "discovery",
            "connection",
            "version",
            "devices",
            "readdev",
            "devparam",
            "groups",
            "scenes",
            "reconnection",
            "disconnect",
        ]
    else:
        selected_tests = args.tests

    # Build execution plan with dependencies
    execution_plan: List[Tuple[str, Callable[[], Any], str]] = []
    completed_tests: Set[str] = set()

    def add_test_with_deps(test_name: str):
        if test_name in completed_tests or test_name in [t[0] for t in execution_plan]:
            return

        if test_name not in test_registry:
            _LOGGER.error("Unknown test: %s", test_name)
            return

        test_func, dependencies, description = test_registry[test_name]

        # Add dependencies first
        for dep in dependencies:
            add_test_with_deps(dep)

        execution_plan.append((test_name, test_func, description))

    # Build execution plan
    for test_name in selected_tests:
        add_test_with_deps(test_name)

    # Execute tests
    _LOGGER.info("=== Test Execution Plan ===")
    for test_name, _, description in execution_plan:
        _LOGGER.info("- %s (%s)", description, test_name)

    results: Dict[str, bool] = {}
    for test_name, test_func, description in execution_plan:
        _LOGGER.info("\n🧪 Running: %s", description)
        try:
            # Special handling for discovery with gateway_sn parameter
            if test_name == "discovery" and args.gateway_sn:
                result = await tester.test_discovery(args.gateway_sn)
            else:
                result = await test_func()

            results[test_name] = result
            completed_tests.add(test_name)

            if result:
                _LOGGER.info("✅ %s completed successfully", description)
            else:
                _LOGGER.error("❌ %s failed", description)
                # Stop execution if critical test fails
                if test_name in ["discovery", "connection"]:
                    _LOGGER.error("Critical test failed, stopping execution")
                    break
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("❌ %s failed with exception: %s", description, e)
            results[test_name] = False
            # Stop on critical failures
            if test_name in ["discovery", "connection"]:
                break

    # Summary
    passed = sum(1 for r in results.values() if r)
    total = len(results)

    _LOGGER.info("\n=== Test Summary ===")
    _LOGGER.info("Executed: %d/%d planned tests", total, len(execution_plan))
    _LOGGER.info("Passed: %d/%d executed tests", passed, total)

    for test_name, result in results.items():
        status = "✅" if result else "❌"
        description = test_registry[test_name][2]
        _LOGGER.info("%s %s", status, description)

    success = passed == total == len(execution_plan)
    if success:
        _LOGGER.info("🎉 All requested tests completed successfully!")
    else:
        _LOGGER.error("❌ Some tests failed or were not executed!")

    return success


async def main() -> bool:
    """Main entry point."""
    args = parse_arguments()

    if args.list_tests:
        print("Available tests:")
        tests = {
            "discovery": "Discover DALI gateways on network",
            "connection": "Connect to discovered gateway",
            "disconnect": "Disconnect from gateway",
            "reconnection": "Test disconnect/reconnect cycle",
            "version": "Get gateway firmware version",
            "devices": "Discover connected DALI devices",
            "readdev": "Read device status via MQTT",
            "devparam": "Get device parameters",
            "groups": "Discover DALI groups",
            "scenes": "Discover DALI scenes",
            "all": "Run complete test suite",
        }

        for test_name, description in tests.items():
            print(f"  {test_name:<12} - {description}")
        return True

    try:
        tester = DaliGatewayTester()
        success = await run_selected_tests(tester, args)
        return success

    except Exception as e:  # pylint: disable=broad-exception-caught
        _LOGGER.error("Unexpected error during testing: %s", e)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
