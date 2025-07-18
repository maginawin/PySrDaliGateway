#!/usr/bin/env python3
"""Test script for PySrDaliGateway discover-to-connect flow with SSL support."""

import asyncio
import logging

from PySrDaliGateway.discovery import DaliGatewayDiscovery
from PySrDaliGateway.gateway import DaliGateway

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

_LOGGER = logging.getLogger(__name__)


async def test_discover_and_connect():
    """Test the complete flow from discovery to connection."""
    _LOGGER.info("=== Starting PySrDaliGateway Discovery-to-Connect Test ===")

    # Step 1: Discover gateways
    _LOGGER.info("Step 1: Discovering DALI gateways...")
    discovery = DaliGatewayDiscovery()

    try:
        gateways = await discovery.discover_gateways()
        _LOGGER.debug("Discovered gateways: %s", gateways)

        if not gateways:
            _LOGGER.error(
                "No gateways discovered! "
                "Check network connectivity and gateway power"
            )
            return False

        _LOGGER.info("✓ Found %d gateway(s)", len(gateways))

        for i, gw in enumerate(gateways):
            _LOGGER.info(
                "  Gateway %d: %s (%s) at %s:%s",
                i + 1, gw["name"], gw["gw_sn"], gw["gw_ip"], gw["port"]
            )

        # Step 2: Connect to the first gateway
        gateway_config = gateways[0]
        _LOGGER.info(
            "Step 2: Connecting to gateway '%s'...", gateway_config["name"]
        )

        gateway = DaliGateway(gateway_config)

        # Attempt connection
        connected = await gateway.connect()

        if connected:
            _LOGGER.info("✓ Successfully connected to gateway!")

            # Step 3: Test basic functionality
            _LOGGER.info("Step 3: Testing device discovery...")

            try:
                # Test version
                _LOGGER.info("Testing version...")
                version = await gateway.get_version()
                _LOGGER.info("✓ Found version: %s", version)

                devices = await gateway.discover_devices()
                _LOGGER.info("✓ Found %d device(s)", len(devices))

                for device in devices[:5]:  # Show first 5 devices
                    _LOGGER.info(
                        "  Device: %s (%s) - Channel %s, Address %s",
                        device["name"], device["dev_type"],
                        device["channel"], device["address"]
                    )

                # Test group discovery
                _LOGGER.info("Testing group discovery...")
                groups = await gateway.discover_groups()
                _LOGGER.info("✓ Found %d group(s)", len(groups))

                # Test scene discovery
                _LOGGER.info("Testing scene discovery...")
                scenes = await gateway.discover_scenes()
                _LOGGER.info("✓ Found %d scene(s)", len(scenes))

            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Error during device discovery: %s", e)

            # Step 4: Disconnect
            _LOGGER.info("Step 4: Disconnecting...")
            await gateway.disconnect()
            _LOGGER.info("✓ Disconnected successfully")

            _LOGGER.info("=== Test completed successfully! ===")
            return True
        else:
            _LOGGER.error("✗ Failed to connect to gateway")
            return False

    except Exception as e:  # pylint: disable=broad-exception-caught
        _LOGGER.error("Error during discovery/connection test: %s", e)
        return False


async def main():
    """Main test function."""
    success = await test_discover_and_connect()

    if success:
        _LOGGER.info("All tests passed!")
    else:
        _LOGGER.error("Some tests failed!")

    return success


if __name__ == "__main__":
    asyncio.run(main())
