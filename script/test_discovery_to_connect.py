#!/usr/bin/env python3
"""Test script for PySrDaliGateway discover-to-connect flow with SSL support."""

import asyncio
import logging

from PySrDaliGateway.discovery import DaliGatewayDiscovery
from PySrDaliGateway.gateway import DaliGateway
from PySrDaliGateway.exceptions import (
    DaliConnectionError,
    AuthenticationError,
    DiscoveryError,
    NetworkError,
    DaliTimeoutError
)
from PySrDaliGateway.error_codes import ErrorCodes

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
    except DiscoveryError as e:
        if e.error_code == ErrorCodes.DISCOVERY_NO_INTERFACES:
            _LOGGER.error(
                "No network interfaces available for discovery: %s", e)
        elif e.error_code == ErrorCodes.DISCOVERY_TIMEOUT:
            _LOGGER.error("Discovery timeout - no gateways responded: %s", e)
        else:
            _LOGGER.error("Discovery failed: %s", e)
        return False
    except NetworkError as e:
        _LOGGER.error("Network error during discovery: %s", e)
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
    try:
        await gateway.connect()
        _LOGGER.info("✓ Successfully connected to gateway!")
    except AuthenticationError as e:
        if e.error_code == ErrorCodes.AUTH_REQUIRED:
            _LOGGER.error(
                "Authentication required - "
                "please press the gateway button and retry. "
                "Gateway: %s, Error: %s", e.gateway_sn, e
            )
        elif e.error_code == ErrorCodes.AUTH_INVALID_CREDENTIALS:
            _LOGGER.error(
                "Invalid credentials for gateway %s: %s", e.gateway_sn, e
            )
        else:
            _LOGGER.error("Authentication failed: %s", e)
        return False
    except DaliConnectionError as e:
        if e.error_code == ErrorCodes.NETWORK_ERROR:
            _LOGGER.error(
                "Network error connecting to gateway %s - "
                "check connectivity: %s",
                e.gateway_sn, e
            )
        elif e.error_code == ErrorCodes.MQTT_BROKER_UNAVAILABLE:
            _LOGGER.error(
                "MQTT broker unavailable on gateway %s: %s", e.gateway_sn, e
            )
        elif e.error_code == ErrorCodes.SSL_CONFIG_ERROR:
            _LOGGER.error(
                "SSL configuration error for gateway %s: %s", e.gateway_sn, e
            )
        else:
            _LOGGER.error("Connection error: %s", e)
        return False
    except DaliTimeoutError as e:
        if e.error_code == ErrorCodes.CONNECTION_TIMEOUT:
            _LOGGER.error(
                "Connection timeout to gateway %s - gateway may be busy: %s",
                e.gateway_sn, e
            )
        else:
            _LOGGER.error("Timeout error: %s", e)
        return False

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
    try:
        await gateway.disconnect()
        _LOGGER.info("✓ Disconnected successfully")
    except DaliConnectionError as e:
        if e.error_code == ErrorCodes.DISCONNECT_ERROR:
            _LOGGER.warning(
                "Disconnect error for gateway %s "
                "(connection may already be closed): %s",
                e.gateway_sn, e
            )
        else:
            _LOGGER.error("Unexpected disconnect error: %s", e)

    _LOGGER.info("=== Test completed successfully! ===")
    return True


async def main():
    """Main test function."""
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
