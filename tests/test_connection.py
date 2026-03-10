"""Tests for DALI gateway discovery, connection, disconnect, and reconnection."""

import asyncio
import logging

import pytest

from .helpers import TestDaliGateway

_LOGGER = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio


async def test_discovery(connected_gateway: TestDaliGateway) -> None:
    """Verify that at least one gateway is discovered.

    The ``connected_gateway`` fixture already performs discovery (or uses
    cache / direct params) and connects.  If we reach this test the
    discovery step succeeded.
    """
    _LOGGER.info("=== Testing Gateway Discovery ===")

    # The fixture guarantees a connected gateway exists.
    assert connected_gateway is not None
    assert connected_gateway.gw_sn, "Gateway serial number must not be empty"
    assert connected_gateway.gw_ip, "Gateway IP address must not be empty"

    _LOGGER.info(
        "Gateway discovered: %s (%s) at %s:%s",
        connected_gateway.name,
        connected_gateway.gw_sn,
        connected_gateway.gw_ip,
        connected_gateway.port,
    )


async def test_connection(connected_gateway: TestDaliGateway) -> None:
    """Verify that the gateway is connected and has valid credentials."""
    _LOGGER.info("=== Testing Gateway Connection ===")

    assert connected_gateway is not None
    assert connected_gateway.gw_sn, "Gateway serial number must not be empty"
    assert connected_gateway.username, "Gateway username must not be empty"
    assert connected_gateway.passwd, "Gateway password must not be empty"

    _LOGGER.info(
        "Connected to gateway '%s' (%s) at %s:%s (TLS: %s)",
        connected_gateway.name,
        connected_gateway.gw_sn,
        connected_gateway.gw_ip,
        connected_gateway.port,
        connected_gateway.is_tls,
    )


async def test_disconnect(connected_gateway: TestDaliGateway) -> None:
    """Disconnect from the gateway and verify no errors are raised."""
    _LOGGER.info("=== Testing Gateway Disconnect ===")

    # Clone the gateway so we don't break the session-scoped fixture.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    gateway = TestDaliGateway(
        gw_sn=connected_gateway.gw_sn,
        gw_ip=connected_gateway.gw_ip,
        port=connected_gateway.port,
        username=connected_gateway.username,
        passwd=connected_gateway.passwd,
        name=connected_gateway.name,
        channel_total=connected_gateway.channel_total,
        is_tls=connected_gateway.is_tls,
        loop=loop,
    )

    # Connect the clone first.
    await gateway.connect()
    _LOGGER.info("Clone connected, now disconnecting...")

    await gateway.disconnect()
    _LOGGER.info("Disconnected successfully")


async def test_reconnection(connected_gateway: TestDaliGateway) -> None:
    """Disconnect and then reconnect to the gateway."""
    _LOGGER.info("=== Testing Reconnection Cycle ===")

    # Clone the gateway so we don't break the session-scoped fixture.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    gateway = TestDaliGateway(
        gw_sn=connected_gateway.gw_sn,
        gw_ip=connected_gateway.gw_ip,
        port=connected_gateway.port,
        username=connected_gateway.username,
        passwd=connected_gateway.passwd,
        name=connected_gateway.name,
        channel_total=connected_gateway.channel_total,
        is_tls=connected_gateway.is_tls,
        loop=loop,
    )

    # Connect, disconnect, then reconnect.
    await gateway.connect()
    _LOGGER.info("Initial connection established")

    await gateway.disconnect()
    _LOGGER.info("Disconnected, now reconnecting...")

    # Create a fresh instance for reconnection (matches SDK design — paho
    # MQTT client may not reconnect reliably after loop_stop + disconnect).
    reconnect_gw = TestDaliGateway(
        gw_sn=connected_gateway.gw_sn,
        gw_ip=connected_gateway.gw_ip,
        port=connected_gateway.port,
        username=connected_gateway.username,
        passwd=connected_gateway.passwd,
        name=connected_gateway.name,
        channel_total=connected_gateway.channel_total,
        is_tls=connected_gateway.is_tls,
        loop=loop,
    )

    await reconnect_gw.connect()
    _LOGGER.info("Reconnected successfully")

    # Clean up.
    await reconnect_gw.disconnect()
    _LOGGER.info("Reconnection cycle completed")
