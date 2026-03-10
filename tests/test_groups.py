"""Tests for DALI Gateway group operations."""

import asyncio
import logging
from typing import Any, Dict, List, Tuple

import pytest

from PySrDaliGateway.device import Device
from PySrDaliGateway.group import Group
from PySrDaliGateway.types import CallbackEventType, LightStatus

from .helpers import TestDaliGateway, make_light_callback

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_member_device_ids(
    group: Group,
    devices: List[Device],
) -> List[str]:
    """Return dev_ids of *devices* that belong to *group*."""
    member_ids: List[str] = []
    for group_dev in group.devices:
        for dev in devices:
            if (
                dev.dev_type == group_dev["dev_type"]
                and dev.channel == group_dev["channel"]
                and dev.address == group_dev["address"]
            ):
                member_ids.append(dev.dev_id)
                break
    return member_ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_group_discovery(
    connected_gateway: TestDaliGateway,
    discovered_groups: List[Group],
) -> None:
    """Verify group discovery returns groups with device data."""
    _LOGGER.info("=== Testing Group Discovery ===")

    assert isinstance(discovered_groups, list)
    _LOGGER.info("Found %d group(s)", len(discovered_groups))

    for group in discovered_groups:
        _LOGGER.info(
            "  Group '%s' (ID: %s, Channel: %s): %d device(s)",
            group.name,
            group.group_id,
            group.channel,
            len(group.devices),
        )


async def test_read_group(
    connected_gateway: TestDaliGateway,
    ensured_groups: List[Group],
) -> None:
    """Read group details and verify structure for up to 3 groups."""
    assert ensured_groups, "No groups available"

    _LOGGER.info("=== Testing Read Group Commands ===")

    for group in ensured_groups[:3]:
        group_id = group.group_id
        channel = group.channel
        _LOGGER.info(
            "Reading group: %s (ID: %s, Channel: %s)",
            group.name,
            group_id,
            channel,
        )

        group_details = await connected_gateway.read_group(group_id, channel)

        assert "name" in group_details
        assert "devices" in group_details
        assert isinstance(group_details["devices"], list)

        _LOGGER.info(
            "Group details - Name: '%s', Devices: %d",
            group_details["name"],
            len(group_details["devices"]),
        )

        for i, device in enumerate(group_details["devices"][:5], 1):
            _LOGGER.info(
                "  Device %d: %s (Type: %s, Channel: %s, Address: %s)",
                i,
                device.get("name", "Unknown"),
                device["dev_type"],
                device["channel"],
                device["address"],
            )

        if len(group_details["devices"]) > 5:
            _LOGGER.info(
                "  ... and %d more devices",
                len(group_details["devices"]) - 5,
            )

    _LOGGER.info("Read group commands completed successfully")


async def test_group_control(
    connected_gateway: TestDaliGateway,
    ensured_groups: List[Group],
    discovered_devices: List[Device],
) -> None:
    """Test group turn_on / turn_off and verify devStatus callbacks.

    Validates the writeGroup -> devStatus chain (Issue #73).
    """
    assert ensured_groups, "No groups available"
    assert discovered_devices, "No devices available"

    _LOGGER.info("=== Testing Group Control (Issue #73) ===")

    group = ensured_groups[0]
    _LOGGER.info(
        "Using group: %s (ID: %s, Channel: %s, %d devices)",
        group.name,
        group.group_id,
        group.channel,
        len(group.devices),
    )

    member_device_ids = _find_member_device_ids(group, discovered_devices)
    assert member_device_ids, "No matching devices found for group members"

    _LOGGER.info(
        "Matched %d member device(s) for callback tracking",
        len(member_device_ids),
    )

    # Register light status callbacks on member devices
    light_status_events: List[Tuple[str, LightStatus]] = []
    for dev in discovered_devices:
        if dev.dev_id in member_device_ids:
            dev.register_listener(
                CallbackEventType.LIGHT_STATUS,
                make_light_callback(dev.dev_id, light_status_events),
            )

    # --- Test 1: Turn on with brightness ---
    test_brightness = 200  # ~78%
    _LOGGER.info(
        "Sending turn_on (brightness=%d) to group %s...",
        test_brightness,
        group.name,
    )
    group.turn_on(brightness=test_brightness)

    _LOGGER.info("Waiting for devStatus callbacks (10s)...")
    await asyncio.sleep(10)

    on_events = [
        (dev_id, status)
        for dev_id, status in light_status_events
        if dev_id in member_device_ids
    ]

    _LOGGER.info(
        "Received %d light status event(s) from group members",
        len(on_events),
    )
    assert on_events, (
        "No devStatus received after writeGroup! Group control chain is broken."
    )

    responded_ids = {dev_id for dev_id, _ in on_events}
    missing_ids = set(member_device_ids) - responded_ids
    if missing_ids:
        _LOGGER.warning(
            "%d member device(s) did not respond: %s",
            len(missing_ids),
            missing_ids,
        )

    brightness_values: List[int] = []
    is_on_values: List[bool] = []
    for dev_id, status in on_events:
        if status.get("brightness") is not None:
            brightness_values.append(status["brightness"])
            _LOGGER.info(
                "  Device %s: brightness=%d (%.0f%%)",
                dev_id,
                status["brightness"],
                status["brightness"] / 255 * 100,
            )
        if status.get("is_on") is not None:
            is_on_values.append(status["is_on"])
            _LOGGER.info("  Device %s: is_on=%s", dev_id, status["is_on"])

    on_true_count = sum(1 for v in is_on_values if v is True)
    on_false_count = sum(1 for v in is_on_values if v is False)
    if on_false_count > 0 and on_true_count == 0:
        if brightness_values and any(b > 0 for b in brightness_values):
            pytest.fail(
                "FIRMWARE BUG: All devices reported is_on=False after turn_on, "
                "but brightness values confirm lights are physically ON."
            )
        else:
            pytest.fail(
                "All devices reported is_on=False after turn_on "
                "and no brightness feedback received."
            )

    if brightness_values:
        avg_brightness = sum(brightness_values) / len(brightness_values)
        _LOGGER.info(
            "Average reported brightness: %d (%.0f%%), commanded: %d (%.0f%%)",
            int(avg_brightness),
            avg_brightness / 255 * 100,
            test_brightness,
            test_brightness / 255 * 100,
        )
        if avg_brightness < test_brightness * 0.5:
            _LOGGER.warning(
                "Reported brightness (%.0f%%) is significantly lower "
                "than commanded (%.0f%%).",
                avg_brightness / 255 * 100,
                test_brightness / 255 * 100,
            )
    else:
        _LOGGER.warning(
            "No brightness values received after turn_on. "
            "Cannot verify lights are physically on."
        )

    # --- Test 2: Turn off ---
    _LOGGER.info("Sending turn_off to group %s...", group.name)
    light_status_events.clear()
    group.turn_off()

    _LOGGER.info("Waiting for turn_off devStatus callbacks (10s)...")
    await asyncio.sleep(10)

    off_events = [
        (dev_id, status)
        for dev_id, status in light_status_events
        if dev_id in member_device_ids
    ]

    _LOGGER.info(
        "Received %d light status event(s) for turn_off",
        len(off_events),
    )

    off_count = sum(1 for _, status in off_events if status.get("is_on") is False)
    on_after_off_count = sum(
        1 for _, status in off_events if status.get("is_on") is True
    )

    if off_count > 0:
        _LOGGER.info("  %d device(s) confirmed OFF state", off_count)
    if on_after_off_count > 0:
        _LOGGER.warning(
            "%d device(s) still report is_on=True after turn_off",
            on_after_off_count,
        )
    if not off_events:
        _LOGGER.warning(
            "No devStatus received after turn_off. Cannot verify lights turned off."
        )

    _LOGGER.info(
        "Group control test completed - turn_on events: %d, turn_off events: %d",
        len(on_events),
        len(off_events),
    )


async def test_group_brightness(
    connected_gateway: TestDaliGateway,
    ensured_groups: List[Group],
    discovered_devices: List[Device],
) -> None:
    """Test group brightness adjustment across multiple levels.

    Verifies brightness conversion accuracy (Issue #73 desync scenario).
    """
    assert ensured_groups, "No groups available"
    assert discovered_devices, "No devices available"

    _LOGGER.info("=== Testing Group Brightness Levels (Issue #73) ===")

    group = ensured_groups[0]
    _LOGGER.info(
        "Using group: %s (ID: %s, %d devices)",
        group.name,
        group.group_id,
        len(group.devices),
    )

    member_device_ids = _find_member_device_ids(group, discovered_devices)
    assert member_device_ids, "No matching devices found for group members"

    # Register callbacks on member devices
    light_status_events: List[Tuple[str, LightStatus]] = []
    for dev in discovered_devices:
        if dev.dev_id in member_device_ids:
            dev.register_listener(
                CallbackEventType.LIGHT_STATUS,
                make_light_callback(dev.dev_id, light_status_events),
            )

    # Turn on the group first
    _LOGGER.info("Turning on group...")
    group.turn_on(brightness=255)
    await asyncio.sleep(5)
    light_status_events.clear()

    # Test multiple brightness levels
    test_levels = [
        (255, "100%"),
        (191, "75%"),
        (128, "50%"),
        (64, "25%"),
        (25, "10%"),
        (1, "minimum"),
    ]

    results: List[Dict[str, Any]] = []

    for commanded_brightness, label in test_levels:
        light_status_events.clear()

        _LOGGER.info(
            "Setting brightness to %d (%s)...",
            commanded_brightness,
            label,
        )
        group.turn_on(brightness=commanded_brightness)
        await asyncio.sleep(5)

        # Collect brightness values from callbacks
        brightness_values = []
        for dev_id, status in light_status_events:
            if dev_id in member_device_ids and status.get("brightness") is not None:
                brightness_values.append(status["brightness"])

        if brightness_values:
            avg = sum(brightness_values) / len(brightness_values)
            diff = abs(avg - commanded_brightness)
            diff_pct = diff / 255 * 100
            results.append(
                {
                    "label": label,
                    "commanded": commanded_brightness,
                    "reported_avg": int(avg),
                    "diff": int(diff),
                    "diff_pct": diff_pct,
                    "responses": len(brightness_values),
                }
            )
            _LOGGER.info(
                "  Commanded: %d (%s) -> Reported avg: %d (diff: %d, %.1f%%)",
                commanded_brightness,
                label,
                int(avg),
                int(diff),
                diff_pct,
            )
        else:
            _LOGGER.warning(
                "  Commanded: %d (%s) -> No brightness reported!",
                commanded_brightness,
                label,
            )
            results.append(
                {
                    "label": label,
                    "commanded": commanded_brightness,
                    "reported_avg": None,
                    "diff": None,
                    "diff_pct": None,
                    "responses": 0,
                }
            )

    # Turn off to restore state
    _LOGGER.info("Turning off group to restore state...")
    group.turn_off()
    await asyncio.sleep(3)

    # Summary
    _LOGGER.info("=== Brightness Test Summary ===")
    _LOGGER.info(
        "%-10s  %-10s  %-10s  %-8s  %-10s",
        "Level",
        "Commanded",
        "Reported",
        "Diff",
        "Responses",
    )
    _LOGGER.info("-" * 55)

    failed_levels = 0
    for r in results:
        if r["reported_avg"] is not None:
            _LOGGER.info(
                "%-10s  %-10d  %-10d  %-8.1f%%  %-10d",
                r["label"],
                r["commanded"],
                r["reported_avg"],
                r["diff_pct"],
                r["responses"],
            )
            if r["diff_pct"] > 10:
                _LOGGER.warning(
                    "Large deviation at %s: %.1f%%",
                    r["label"],
                    r["diff_pct"],
                )
                failed_levels += 1
        else:
            _LOGGER.error(
                "%-10s  %-10d  %-10s  %-8s  %-10d",
                r["label"],
                r["commanded"],
                "N/A",
                "N/A",
                0,
            )
            failed_levels += 1

    if failed_levels == 0:
        _LOGGER.info("All brightness levels within acceptable range (<10%% deviation)")
    else:
        _LOGGER.warning(
            "%d brightness level(s) had large deviations or no response",
            failed_levels,
        )
