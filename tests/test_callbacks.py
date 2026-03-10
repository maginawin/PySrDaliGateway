"""Tests for DALI Gateway device callback registration and events."""

import asyncio
import logging
from typing import List, Tuple

from PySrDaliGateway.device import Device
from PySrDaliGateway.types import (
    CallbackEventType,
    IlluminanceStatus,
    LightStatus,
    MotionStatus,
    PanelEventType,
    PanelStatus,
)

from .helpers import TestDaliGateway

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Callback factories
# ---------------------------------------------------------------------------


def _make_light_callback(
    device_id: str,
    events: List[Tuple[str, LightStatus]],
):
    """Create a light status callback that appends to *events*."""

    def on_light_status(status: LightStatus) -> None:
        events.append((device_id, status))
        _LOGGER.info("Light status: %s -> %s", device_id, status)

    return on_light_status


def _make_motion_callback(
    device_id: str,
    events: List[Tuple[str, MotionStatus]],
):
    """Create a motion status callback that appends to *events*."""

    def on_motion_status(status: MotionStatus) -> None:
        events.append((device_id, status))
        _LOGGER.info("Motion status: %s -> %s", device_id, status)

    return on_motion_status


def _make_illuminance_callback(
    device_id: str,
    events: List[Tuple[str, IlluminanceStatus]],
):
    """Create an illuminance status callback that appends to *events*."""

    def on_illuminance_status(status: IlluminanceStatus) -> None:
        events.append((device_id, status))
        _LOGGER.info(
            "Illuminance status: %s -> %s lux (valid: %s)",
            device_id,
            status.get("illuminance_value", "Unknown"),
            status.get("is_valid", "Unknown"),
        )

    return on_illuminance_status


def _make_panel_callback(
    device_id: str,
    events: List[Tuple[str, PanelStatus]],
):
    """Create a panel status callback that appends to *events*."""

    def on_panel_status(status: PanelStatus) -> None:
        events.append((device_id, status))
        event_type = status["event_type"]
        rotate_info = ""
        if event_type == PanelEventType.ROTATE:
            rotate_info = f" (rotate: {status.get('rotate_value', 0)})"
        _LOGGER.info(
            "Panel status: %s -> Key %s %s%s",
            device_id,
            status.get("key_no", "?"),
            event_type.value,
            rotate_info,
        )

    return on_panel_status


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_callback_setup(
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Register callbacks and trigger ReadDev for each device type."""
    assert discovered_devices, "No devices available"

    _LOGGER.info("=== Testing Device Callbacks with ReadDev Commands ===")

    # Event accumulators
    light_status_events: List[Tuple[str, LightStatus]] = []
    motion_status_events: List[Tuple[str, MotionStatus]] = []
    illuminance_status_events: List[Tuple[str, IlluminanceStatus]] = []
    panel_status_events: List[Tuple[str, PanelStatus]] = []

    # Classify devices by type
    light_devices = [
        d
        for d in discovered_devices
        if d.dev_type in ["0101", "0102", "0103", "0104", "0105"]
    ]
    motion_devices = [d for d in discovered_devices if d.dev_type == "0201"]
    illuminance_devices = [d for d in discovered_devices if d.dev_type == "0301"]
    panel_devices = [
        d for d in discovered_devices if d.dev_type in ["0401", "0402", "0403", "0404"]
    ]

    _LOGGER.info(
        "Found devices - Light: %d, Motion: %d, Illuminance: %d, Panel: %d",
        len(light_devices),
        len(motion_devices),
        len(illuminance_devices),
        len(panel_devices),
    )

    # Test light devices
    if light_devices:
        _LOGGER.info("Testing light device callbacks...")
        for device in light_devices[:3]:
            device.register_listener(
                CallbackEventType.LIGHT_STATUS,
                _make_light_callback(device.dev_id, light_status_events),
            )
            model_info = device.model or "N/A"
            _LOGGER.info(
                "Reading light device: %s (Channel %s, Address %s, Model: %s)",
                device.name,
                device.channel,
                device.address,
                model_info,
            )
            connected_gateway.command_read_dev(
                device.dev_type, device.channel, device.address
            )
            await asyncio.sleep(2)

    # Test motion devices
    if motion_devices:
        _LOGGER.info("Testing motion sensor callbacks...")
        for device in motion_devices[:2]:
            device.register_listener(
                CallbackEventType.MOTION_STATUS,
                _make_motion_callback(device.dev_id, motion_status_events),
            )
            model_info = device.model or "N/A"
            _LOGGER.info(
                "Reading motion device: %s (Channel %s, Address %s, Model: %s)",
                device.name,
                device.channel,
                device.address,
                model_info,
            )
            connected_gateway.command_read_dev(
                device.dev_type, device.channel, device.address
            )
            await asyncio.sleep(2)

    # Test illuminance devices
    if illuminance_devices:
        _LOGGER.info("Testing illuminance sensor callbacks...")
        for device in illuminance_devices[:2]:
            device.register_listener(
                CallbackEventType.ILLUMINANCE_STATUS,
                _make_illuminance_callback(device.dev_id, illuminance_status_events),
            )
            model_info = device.model or "N/A"
            _LOGGER.info(
                "Reading illuminance device: %s (Channel %s, Address %s, Model: %s)",
                device.name,
                device.channel,
                device.address,
                model_info,
            )
            connected_gateway.command_read_dev(
                device.dev_type, device.channel, device.address
            )
            await asyncio.sleep(2)

    # Test panel devices
    if panel_devices:
        _LOGGER.info("Testing panel callbacks...")
        for device in panel_devices[:2]:
            device.register_listener(
                CallbackEventType.PANEL_STATUS,
                _make_panel_callback(device.dev_id, panel_status_events),
            )
            model_info = device.model or "N/A"
            _LOGGER.info(
                "Reading panel device: %s (Channel %s, Address %s, Model: %s)",
                device.name,
                device.channel,
                device.address,
                model_info,
            )
            connected_gateway.command_read_dev(
                device.dev_type, device.channel, device.address
            )
            await asyncio.sleep(2)

    _LOGGER.info("All device callbacks registered successfully")

    # Wait for delayed responses
    _LOGGER.info("Waiting 5 seconds for final responses...")
    await asyncio.sleep(5)

    # Report
    total_events = (
        len(light_status_events)
        + len(motion_status_events)
        + len(illuminance_status_events)
        + len(panel_status_events)
    )

    _LOGGER.info("=== Callback Events Summary ===")
    _LOGGER.info("Light status events: %d", len(light_status_events))
    _LOGGER.info("Motion status events: %d", len(motion_status_events))
    _LOGGER.info("Illuminance status events: %d", len(illuminance_status_events))
    _LOGGER.info("Panel status events: %d", len(panel_status_events))
    _LOGGER.info("Total events received: %d", total_events)

    if light_status_events:
        _LOGGER.info("Sample light event: %s", light_status_events[0])
    if motion_status_events:
        _LOGGER.info("Sample motion event: %s", motion_status_events[0])
    if illuminance_status_events:
        _LOGGER.info("Sample illuminance event: %s", illuminance_status_events[0])
    if panel_status_events:
        _LOGGER.info("Sample panel event: %s", panel_status_events[0])

    if total_events > 0:
        _LOGGER.info(
            "Device callbacks working - received %d events from ReadDev commands",
            total_events,
        )
    else:
        _LOGGER.warning("No callback events received from ReadDev commands")
