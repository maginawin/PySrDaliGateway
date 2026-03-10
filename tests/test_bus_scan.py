"""Tests for DALI Gateway bus scan operations."""

import asyncio
import logging
import time
from typing import List

import pytest

from PySrDaliGateway.device import Device
from PySrDaliGateway.exceptions import BusScanCancelledError
from PySrDaliGateway.helper import is_light_device

from .helpers import TestDaliGateway

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_raw_message_timeline(gateway: TestDaliGateway) -> None:
    """Log raw searchDevRes messages as a timeline table."""
    if not gateway.bus_scan_raw_messages:
        _LOGGER.info("No raw searchDevRes messages recorded")
        return

    _LOGGER.info("=== searchDevRes Timeline ===")
    _LOGGER.info(
        "%-12s %-14s %-14s %-8s %-12s %s",
        "Timestamp",
        "searchFlag",
        "searchStatus",
        "Channel",
        "Data Length",
        "First DevId",
    )
    _LOGGER.info("-" * 80)

    base_time = gateway.bus_scan_raw_messages[0][0]
    for ts, payload in gateway.bus_scan_raw_messages:
        relative_time = ts - base_time
        search_flag = payload.get("searchFlag", "")
        search_status = payload.get("searchStatus", "")
        channel = payload.get("channel", "")
        data = payload.get("data", [])
        data_len = len(data) if isinstance(data, list) else 0
        first_devid = ""
        if data_len > 0 and isinstance(data[0], dict):
            first_devid = str(data[0].get("devId", ""))

        _LOGGER.info(
            "%-12.2f %-14s %-14s %-8s %-12d %s",
            relative_time,
            search_flag,
            search_status,
            channel,
            data_len,
            first_devid,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_bus_scan_basic(
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Test basic bus scan and compare results with exited-mode discovery."""
    _LOGGER.info("=== Testing Bus Scan (Basic Flow) ===")

    exited_device_count = len(discovered_devices)
    exited_dev_ids = {dev.dev_id for dev in discovered_devices}
    _LOGGER.info("Devices from exited mode: %d", exited_device_count)

    # Wait for DALI bus to become idle
    _LOGGER.info("Waiting for DALI bus to become idle...")
    await asyncio.sleep(3.0)

    # Clear raw message history before scan
    connected_gateway.bus_scan_raw_messages.clear()

    start_time = time.time()

    _LOGGER.info("Starting bus scan on channels: %s", connected_gateway.channel_total)
    scanned_devices = await connected_gateway.scan_bus(connected_gateway.channel_total)

    elapsed = time.time() - start_time
    _LOGGER.info("Bus scan completed in %.2f seconds", elapsed)

    # Log raw message timeline
    _log_raw_message_timeline(connected_gateway)

    # Compare device counts
    scanned_dev_ids = {dev.dev_id for dev in scanned_devices}
    _LOGGER.info("Scanned devices: %d", len(scanned_devices))
    _LOGGER.info("Difference: %+d", len(scanned_devices) - exited_device_count)

    new_devices = scanned_dev_ids - exited_dev_ids
    missing_devices = exited_dev_ids - scanned_dev_ids

    if new_devices:
        _LOGGER.info("New devices found (not in exited): %s", new_devices)
    if missing_devices:
        _LOGGER.warning(
            "Devices missing (in exited but not scanned): %s",
            missing_devices,
        )
    if not new_devices and not missing_devices:
        _LOGGER.info("Device lists match perfectly")

    for i, device in enumerate(scanned_devices[:5]):
        _LOGGER.info(
            "  Device %d: %s (%s) - Ch %d, Addr %d",
            i + 1,
            device.name,
            device.dev_type,
            device.channel,
            device.address,
        )

    assert isinstance(scanned_devices, list)


@pytest.mark.slow
async def test_bus_scan_after_control(
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Test bus scan immediately after device control (bus busy handling)."""
    if not discovered_devices:
        _LOGGER.warning("No devices available, skipping bus busy test")
        return

    _LOGGER.info("=== Testing Bus Scan After Device Control ===")

    # Find a light device to control
    light_device = next(
        (dev for dev in discovered_devices if is_light_device(dev.dev_type)),
        None,
    )
    if not light_device:
        _LOGGER.warning("No light device available, skipping test")
        return

    # Send device control command (turn on at full brightness)
    _LOGGER.info(
        "Sending control command to device: %s (Ch %d, Addr %d)",
        light_device.name,
        light_device.channel,
        light_device.address,
    )
    connected_gateway.command_write_dev(
        light_device.dev_type,
        light_device.channel,
        light_device.address,
        [{"dpid": 20, "dataType": "bool", "value": True}],
    )

    # Immediately scan without waiting
    _LOGGER.info("Scanning immediately after control command (no wait)...")
    try:
        scanned_devices = await connected_gateway.scan_bus(
            connected_gateway.channel_total
        )
        _LOGGER.info(
            "Scan succeeded without waiting - found %d devices",
            len(scanned_devices),
        )
        _LOGGER.info("Note: Gateway may have queued the scan or bus was idle")
    except Exception:
        _LOGGER.warning("Scan without waiting failed, retrying with wait...")

        # Retry with wait
        await asyncio.sleep(3.0)
        scanned_devices = await connected_gateway.scan_bus(
            connected_gateway.channel_total
        )
        _LOGGER.info(
            "Scan succeeded after waiting - found %d devices",
            len(scanned_devices),
        )

    assert isinstance(scanned_devices, list)


@pytest.mark.slow
async def test_stop_scan(
    connected_gateway: TestDaliGateway,
) -> None:
    """Test stopping an in-progress bus scan."""
    _LOGGER.info("=== Testing Stop Bus Scan ===")

    # Clear raw message history before test
    connected_gateway.bus_scan_raw_messages.clear()

    # Wait for bus to be idle
    await asyncio.sleep(3.0)

    # Start scan in background
    _LOGGER.info("Starting bus scan in background...")
    scan_task = asyncio.create_task(
        connected_gateway.scan_bus(connected_gateway.channel_total)
    )

    # Wait for searchStatus: 2 (scanning in progress)
    _LOGGER.info("Waiting for scan to start (searchStatus: 2)...")
    await asyncio.sleep(2.0)

    # Stop scan
    _LOGGER.info("Sending stop signal...")
    await connected_gateway.stop_scan()

    # Observe gateway behavior after stop
    _LOGGER.info("Observing gateway behavior for 10 seconds after stop...")
    await asyncio.sleep(10.0)

    # Wait for scan task to complete
    try:
        result = await asyncio.wait_for(scan_task, timeout=5.0)
        _LOGGER.info("scan_bus() returned: %s", result)
        if not result:
            _LOGGER.info("Scan was cancelled (returned empty list)")
        else:
            _LOGGER.warning(
                "Scan returned %d devices despite being stopped",
                len(result),
            )
    except BusScanCancelledError:
        _LOGGER.info("scan_bus() raised BusScanCancelledError (expected after stop)")
    except asyncio.CancelledError:
        _LOGGER.info("scan_bus() task was cancelled")
    except asyncio.TimeoutError:
        _LOGGER.warning("scan_bus() did not complete after stop signal")
        assert False, "scan_bus() did not complete after stop signal"

    # Log raw message timeline for analysis
    _log_raw_message_timeline(connected_gateway)

    _LOGGER.info("Stop scan test completed")
