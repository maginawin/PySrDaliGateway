#!/usr/bin/env python3
"""Test script for PySrDaliGateway discover-to-connect flow with SSL support."""

import asyncio
import logging

from PySrDaliGateway.discovery import DaliGatewayDiscovery
from PySrDaliGateway.gateway import DaliGateway
from PySrDaliGateway.exceptions import DaliGatewayError

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
    except DaliGatewayError as e:
        _LOGGER.error("Discovery failed: %s", e)
        return False

    _LOGGER.info("✓ Found %d gateway(s)", len(gateways))

    for i, gw in enumerate(gateways):
        _LOGGER.info(
            "  Gateway %d: %s (%s) at %s:%s, username: %s, password: %s",
            i + 1, gw["name"], gw["gw_sn"], gw["gw_ip"], gw["port"],
            gw.get("username", "N/A"), gw.get("passwd", "N/A")
        )

    # Step 2: Connect to the first gateway
    gateway_config = gateways[0]
    _LOGGER.info(
        "Step 2: Connecting to gateway '%s'...", gateway_config["name"]
    )

    gateway = DaliGateway(gateway_config)

    # Attempt connection
    try:
        await gateway.connect()
        _LOGGER.info("✓ Successfully connected to gateway!")
    except DaliGatewayError as e:
        _LOGGER.error("Connection error: %s", e)
        return False

    # Step 2.1: Disconnect if already connected
    try:
        await gateway.disconnect()
        _LOGGER.info("✓ Disconnected from gateway before re-connecting")
    except DaliGatewayError as e:
        _LOGGER.error("Disconnect error: %s", e)
        return False

    # Step 2.2: Re research connection
    _LOGGER.info("Reconnecting to gateway...")
    gateways = await discovery.discover_gateways(gateway_config["gw_sn"])
    for i, gw in enumerate(gateways):
        _LOGGER.info(
            "  Gateway %d: %s (%s) at %s:%s, username: %s, password: %s",
            i + 1, gw["name"], gw["gw_sn"], gw["gw_ip"], gw["port"],
            gw.get("username", "N/A"), gw.get("passwd", "N/A")
        )

    if not gateways:
        _LOGGER.error(
            "No gateways found after re-discovery! "
            "Check network connectivity and gateway power"
        )
        return False

    new_gateway_config = gateways[0]
    _LOGGER.info(
        "Reconnecting to gateway '%s'...", new_gateway_config["name"]
    )

    new_gateway_config["username"] = gateway_config.get("username", "")
    new_gateway_config["passwd"] = gateway_config.get("passwd", "")
    _LOGGER.info("new_gateway_config: %s", new_gateway_config)

    gateway = DaliGateway(new_gateway_config)

    # Step 3: Test basic functionality
    _LOGGER.info("Step 3: Testing device discovery...")
    try:
        await gateway.connect()
        _LOGGER.info("✓ Successfully re-connected to gateway!")
    except DaliGatewayError as e:
        _LOGGER.error("Re-connection error: %s", e)
        return False
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

        # Test readDev
        _LOGGER.info("Testing readDev...")
        for device in devices:
            gateway.command_read_dev(
                device["dev_type"], device["channel"], device["address"]
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
    try:
        await gateway.disconnect()
        _LOGGER.info("✓ Disconnected successfully")
    except DaliGatewayError as e:
        _LOGGER.error("Disconnect error: %s", e)
        return False

    _LOGGER.info("=== Test completed successfully! ===")
    return True


async def main():
    try:
        success = await test_discover_and_connect()

        if success:
            _LOGGER.info("All tests passed!")
        else:
            _LOGGER.error("Some tests failed!")

        return success
    except Exception as e:  # pylint: disable=broad-exception-caught
        _LOGGER.error(
            "Unexpected error during discovery/connection test: %s", e)
        return False


if __name__ == "__main__":
    asyncio.run(main())
