"""Tests for DALI gateway version, status sync, and restart."""

import asyncio
import logging
from typing import List, Tuple

import pytest

from PySrDaliGateway.types import CallbackEventType

from .helpers import TestDaliGateway

_LOGGER = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio


async def test_version(connected_gateway: TestDaliGateway) -> None:
    """Get firmware / software version (auto-retrieved on connect)."""
    _LOGGER.info("=== Testing Version Information ===")
    _LOGGER.info("(Version is automatically retrieved during gateway connection)")

    sw = connected_gateway.software_version
    fw = connected_gateway.firmware_version

    _LOGGER.info("Software version: %s", sw or "N/A")
    _LOGGER.info("Firmware version: %s", fw or "N/A")

    # At least one version string should be populated after connection.
    assert sw or fw, (
        "Neither software_version nor firmware_version available on the gateway"
    )

    _LOGGER.info("Gateway version information available")


async def test_gateway_status_sync(connected_gateway: TestDaliGateway) -> None:
    """Verify online_status callback fires on disconnect and reconnect.

    A fresh gateway clone is used so the session-scoped fixture is not
    disrupted.  After disconnect the callback must report ``False``; after
    reconnect it must report ``True``.
    """
    _LOGGER.info("=== Testing Gateway Status Synchronization ===")

    gateway_sn = connected_gateway.gw_sn
    online_status_events: List[Tuple[str, bool]] = []

    def on_online_status(status: bool) -> None:
        """Capture online-status events."""
        online_status_events.append((gateway_sn, status))
        _LOGGER.info(
            "Gateway status changed: %s -> %s",
            gateway_sn,
            "ONLINE" if status else "OFFLINE",
        )

    # Create a disposable clone.
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

    gateway.register_listener(
        CallbackEventType.ONLINE_STATUS,
        on_online_status,
        dev_id=gateway.gw_sn,
    )

    await gateway.connect()
    _LOGGER.info("Clone connected, testing disconnect status event...")

    # -- Disconnect: expect offline callback --------------------------------
    online_status_events.clear()
    await gateway.disconnect()
    await asyncio.sleep(1)

    gw_events = [e for e in online_status_events if e[0] == gateway_sn]
    assert gw_events, "No gateway status events received on disconnect"
    assert gw_events[-1][1] is False, (
        f"Expected gateway offline status (False), got: {gw_events[-1][1]}"
    )
    _LOGGER.info("Gateway offline status correctly received")

    # -- Reconnect: expect online callback ----------------------------------
    _LOGGER.info("Testing reconnect status event...")
    new_gateway = TestDaliGateway(
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

    new_gateway.register_listener(
        CallbackEventType.ONLINE_STATUS,
        on_online_status,
        dev_id=new_gateway.gw_sn,
    )

    await new_gateway.connect()
    await asyncio.sleep(1)

    gw_events = [e for e in online_status_events if e[0] == gateway_sn]
    assert len(gw_events) >= 2, (
        f"Expected at least 2 gateway status events (offline + online), got {len(gw_events)}"
    )
    assert gw_events[-1][1] is True, (
        f"Expected gateway online status (True), got: {gw_events[-1][1]}"
    )
    _LOGGER.info("Gateway online status correctly received")

    # Log all captured events for verification.
    _LOGGER.info("Gateway status events:")
    for i, (dev_id, status) in enumerate(gw_events):
        _LOGGER.info("  %d: %s -> %s", i + 1, dev_id, "ONLINE" if status else "OFFLINE")

    # Clean up the reconnected clone.
    await new_gateway.disconnect()
    _LOGGER.info("Gateway status synchronization test completed successfully")


@pytest.mark.destructive
async def test_restart_gateway(connected_gateway: TestDaliGateway) -> None:
    """Send a restart command to the gateway.

    Marked ``destructive`` because the gateway will reboot and the MQTT
    connection will be lost.
    """
    _LOGGER.info("=== Testing Gateway Restart Command ===")
    _LOGGER.warning("Gateway will restart and disconnect after this test!")

    connected_gateway.restart_gateway()

    # Give time for the restart response to arrive.
    _LOGGER.info("Waiting for restart confirmation...")
    await asyncio.sleep(3)

    _LOGGER.info("Restart command sent successfully")
    _LOGGER.info("Gateway should be restarting now. Connection will be lost.")
