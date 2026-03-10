"""Hardware tests for DALI device operations.

Migrated from script/test_cases.py to pytest.
"""

import asyncio
import logging
from typing import List, Tuple

import pytest

from PySrDaliGateway.device import Device
from PySrDaliGateway.helper import is_cct_device, is_light_device, is_sensor_device
from PySrDaliGateway.types import CallbackEventType, DeviceParamType, SensorParamType

from .helpers import TestDaliGateway

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (ported from DaliGatewayTester private methods)
# ---------------------------------------------------------------------------


def _make_dev_param_callback(events: List[Tuple[str, DeviceParamType]], device_id: str):
    """Create a device parameter callback that appends to *events*."""

    def on_dev_param(params: DeviceParamType) -> None:
        events.append((device_id, params))
        _LOGGER.info("Device parameters: %s -> %s", device_id, params)

    return on_dev_param


def _make_sensor_param_callback(
    events: List[Tuple[str, SensorParamType]], device_id: str
):
    """Create a sensor parameter callback that appends to *events*."""

    def on_sensor_param(params: SensorParamType) -> None:
        events.append((device_id, params))
        _LOGGER.info("Sensor parameters: %s -> %s", device_id, params)

    return on_sensor_param


async def _await_dev_param(
    events: List[Tuple[str, DeviceParamType]],
    baseline_count: int,
    timeout: float,
) -> bool:
    """Wait for a new device parameter event up to *timeout* seconds."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    while loop.time() - start < timeout:
        if len(events) > baseline_count:
            return True
        await asyncio.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_discovery(
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Verify device discovery returns at least one device."""
    _LOGGER.info("=== Testing Device Discovery ===")

    assert len(discovered_devices) > 0, "Device discovery returned no devices"
    _LOGGER.info("Found %d device(s)", len(discovered_devices))

    for device in discovered_devices[:5]:  # Show first 5 devices
        model_info = device.model or "N/A"
        _LOGGER.info(
            "  Device: %s (%s) - Channel %s, Address %s, Model: %s",
            device.name,
            device.dev_type,
            device.channel,
            device.address,
            model_info,
        )


@pytest.mark.asyncio
async def test_read_dev(
    request: pytest.FixtureRequest,
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Read device status for each discovered device."""
    _LOGGER.info("=== Testing ReadDev Commands ===")

    assert discovered_devices, "No devices available"

    device_limit: int | None = request.config.getoption("--device-limit")
    devices_to_test = discovered_devices
    if device_limit:
        devices_to_test = discovered_devices[:device_limit]

    for device in devices_to_test:
        model_info = device.model or "N/A"
        _LOGGER.info(
            "Reading device: %s (Channel %s, Address %s, Model: %s)",
            device.name,
            device.channel,
            device.address,
            model_info,
        )
        connected_gateway.command_read_dev(
            device.dev_type, device.channel, device.address
        )

    _LOGGER.info("ReadDev commands sent for %d devices", len(devices_to_test))


@pytest.mark.asyncio
async def test_set_dev_param(
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Set device parameters (fade time, fade rate, brightness limits) on a light."""
    interval = 5  # seconds

    _LOGGER.info("=== Testing Device Parameter Configuration ===")

    # Find a light device to test
    light_device = next(
        (d for d in discovered_devices if is_light_device(d.dev_type)), None
    )
    assert light_device is not None, "No light device found for parameter testing"

    _LOGGER.info(
        "Testing device: %s (Channel %s, Address %s, Type %s)",
        light_device.name,
        light_device.channel,
        light_device.address,
        light_device.dev_type,
    )

    dev_param_events: List[Tuple[str, DeviceParamType]] = []

    # Register callback for parameter updates
    unsub = light_device.register_listener(
        CallbackEventType.DEV_PARAM,
        _make_dev_param_callback(dev_param_events, light_device.dev_id),
    )

    try:
        # Test 1: Get current parameters
        _LOGGER.info("--- Test 1: Get current device parameters ---")
        light_device.get_device_parameters()

        baseline_events = len(dev_param_events)
        got_initial_params = await _await_dev_param(
            dev_param_events, baseline_events, timeout=12.0
        )

        if got_initial_params:
            _LOGGER.info("Received parameters: %s", dev_param_events[-1][1])
        else:
            _LOGGER.warning("No parameters received")

        # Test 2: Set fade time and fade rate
        _LOGGER.info("--- Test 2: Set fade time and fade rate ---")
        params: DeviceParamType = {
            "fade_time": 5,
            "fade_rate": 7,
        }
        _LOGGER.info("Setting parameters: %s", params)

        dev_param_events.clear()
        light_device.set_device_parameters(params)

        await asyncio.sleep(interval)
        _LOGGER.info("Fade parameters sent")

        # Test 3: Set brightness limits
        _LOGGER.info("--- Test 3: Set brightness limits ---")
        params = {
            "min_brightness": 100,
            "max_brightness": 900,
        }
        _LOGGER.info("Setting parameters: %s", params)
        light_device.set_device_parameters(params)

        await asyncio.sleep(interval)
        _LOGGER.info("Brightness limits sent")

        # Test 4: Verify updated parameters
        _LOGGER.info("--- Test 4: Verify updated parameters ---")
        dev_param_events.clear()
        light_device.get_device_parameters()

        baseline_events = len(dev_param_events)
        got_verified_params = await _await_dev_param(
            dev_param_events, baseline_events, timeout=15.0
        )

        assert got_verified_params, (
            "Could not verify updated parameters - no response received"
        )

        latest_params = dev_param_events[-1][1]
        _LOGGER.info("Retrieved updated parameters: %s", latest_params)

        assert "fade_time" in latest_params or "max_brightness" in latest_params, (
            "Could not verify parameter values"
        )
        _LOGGER.info("Parameters updated successfully")

        # Test 5: Reset to defaults using broadcast
        _LOGGER.info("--- Test 5: Reset to defaults using broadcast ---")
        reset_params: DeviceParamType = {"max_brightness": 1000}
        connected_gateway.command_set_dev_param("FFFF", 0, 1, reset_params)

        await asyncio.sleep(interval)
        _LOGGER.info("Reset command sent")

    finally:
        unsub()

    _LOGGER.info("Device parameter configuration test completed")


@pytest.mark.asyncio
async def test_read_cct_range(
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Read CCT range for color temperature devices.

    Verifies that CCT devices (devType 0102) return cct_cool and cct_warm
    fields via getDevParam, and that non-CCT devices do not.
    """
    _LOGGER.info("=== Testing CCT Range Reading ===")

    # Split devices into CCT and non-CCT
    cct_devices = [d for d in discovered_devices if is_cct_device(d.dev_type)]
    non_cct_devices = [
        d
        for d in discovered_devices
        if not is_cct_device(d.dev_type) and is_light_device(d.dev_type)
    ]

    if not cct_devices:
        _LOGGER.warning("No CCT devices (devType 0102) found - skipping CCT test")
        pytest.skip("No CCT devices available")

    dev_param_events: List[Tuple[str, DeviceParamType]] = []

    # Test 1: CCT devices should return cct_cool and cct_warm (limit to 3)
    _LOGGER.info("--- Test 1: Read CCT range from CCT devices (up to 3) ---")
    for device in cct_devices[:3]:
        dev_param_events.clear()
        unsub = device.register_listener(
            CallbackEventType.DEV_PARAM,
            _make_dev_param_callback(dev_param_events, device.dev_id),
        )
        device.get_device_parameters()

        baseline = len(dev_param_events)
        got_params = await _await_dev_param(dev_param_events, baseline, timeout=12.0)
        unsub()

        assert got_params, f"No parameters received for CCT device {device.name}"

        params = dev_param_events[-1][1]
        _LOGGER.info("Device %s parameters: %s", device.name, params)

        # Verify CCT fields are present in response.
        assert "cct_cool" in params and "cct_warm" in params, (
            f"CCT device {device.name} response missing cct_cool/cct_warm keys"
        )

        cct_cool = params["cct_cool"]
        cct_warm = params["cct_warm"]

        if cct_cool == 0 and cct_warm == 0:
            _LOGGER.info(
                "Device %s CCT range: not configured (0/0, will use defaults)",
                device.name,
            )
        elif 1000 <= cct_warm <= 10000 and 1000 <= cct_cool <= 10000:
            _LOGGER.info(
                "Device %s CCT range: %dK - %dK",
                device.name,
                cct_warm,
                cct_cool,
            )
        else:
            _LOGGER.warning(
                "Device %s has unexpected CCT values: warm=%d, cool=%d",
                device.name,
                cct_warm,
                cct_cool,
            )

    # Test 2: Non-CCT devices should not have CCT fields (or they are 0)
    if non_cct_devices:
        _LOGGER.info("--- Test 2: Verify non-CCT devices lack CCT fields ---")
        test_device = non_cct_devices[0]
        dev_param_events.clear()
        unsub = test_device.register_listener(
            CallbackEventType.DEV_PARAM,
            _make_dev_param_callback(dev_param_events, test_device.dev_id),
        )
        test_device.get_device_parameters()

        baseline = len(dev_param_events)
        got_params = await _await_dev_param(dev_param_events, baseline, timeout=12.0)
        unsub()

        if got_params:
            params = dev_param_events[-1][1]
            cct_cool = params.get("cct_cool", 0)
            cct_warm = params.get("cct_warm", 0)
            _LOGGER.info(
                "Non-CCT device %s: cct_cool=%s, cct_warm=%s",
                test_device.name,
                cct_cool,
                cct_warm,
            )
            if cct_cool == 0 and cct_warm == 0:
                _LOGGER.info("Non-CCT device has no CCT fields (or zero values)")
            else:
                _LOGGER.warning("Non-CCT device unexpectedly has CCT values")
        else:
            _LOGGER.info(
                "Non-CCT device %s returned no parameters",
                test_device.name,
            )
    else:
        _LOGGER.info("No non-CCT light devices to test - skipping Test 2")

    _LOGGER.info("CCT range reading test completed")


@pytest.mark.asyncio
async def test_set_sensor_param(
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Set sensor parameters (occupancy time, sensitivity, coverage, etc.)."""
    interval = 5  # seconds

    _LOGGER.info("=== Testing Sensor Parameter Configuration ===")

    # Find a sensor device to test
    sensor_device = next(
        (d for d in discovered_devices if is_sensor_device(d.dev_type)), None
    )

    if not sensor_device:
        _LOGGER.warning("No sensor device found - skipping sensor parameter test")
        pytest.skip("No sensor device available")

    _LOGGER.info(
        "Testing sensor: %s (Channel %s, Address %s, Type %s)",
        sensor_device.name,
        sensor_device.channel,
        sensor_device.address,
        sensor_device.dev_type,
    )

    sensor_param_events: List[Tuple[str, SensorParamType]] = []

    # Register callback for sensor parameter updates
    unsub = sensor_device.register_listener(
        CallbackEventType.SENSOR_PARAM,
        _make_sensor_param_callback(sensor_param_events, sensor_device.dev_id),
    )

    try:
        # Test 1: Get current sensor parameters
        _LOGGER.info("--- Test 1: Get current sensor parameters ---")
        sensor_device.get_sensor_parameters()

        await asyncio.sleep(interval)

        if sensor_param_events:
            _LOGGER.info("Received parameters: %s", sensor_param_events[-1][1])
        else:
            _LOGGER.warning("No sensor parameters received")

        # Test 2: Set sensor sensitivity and coverage
        _LOGGER.info("--- Test 2: Set sensor sensitivity and coverage ---")
        params: SensorParamType = {
            "sensitivity": 75,
            "coverage": 80,
        }
        _LOGGER.info("Setting parameters: %s", params)
        sensor_device.set_sensor_parameters(params)

        await asyncio.sleep(interval)
        _LOGGER.info("Sensitivity and coverage parameters sent")

        # Test 3: Set sensor timing parameters
        _LOGGER.info("--- Test 3: Set sensor timing parameters ---")
        params = {
            "occpy_time": 10,
            "report_time": 5,
            "down_time": 15,
        }
        _LOGGER.info("Setting parameters: %s", params)
        sensor_device.set_sensor_parameters(params)

        await asyncio.sleep(interval)
        _LOGGER.info("Timing parameters sent")

        # Test 4: Verify updated parameters
        _LOGGER.info("--- Test 4: Verify updated sensor parameters ---")
        sensor_param_events.clear()
        sensor_device.get_sensor_parameters()

        await asyncio.sleep(interval)

        assert sensor_param_events, (
            "Could not verify updated sensor parameters - no response received"
        )

        latest_params = sensor_param_events[-1][1]
        _LOGGER.info("Retrieved updated parameters: %s", latest_params)

        assert "sensitivity" in latest_params or "occpy_time" in latest_params, (
            "Could not verify sensor parameter values"
        )
        _LOGGER.info("Sensor parameters updated successfully")

    finally:
        unsub()

    _LOGGER.info("Sensor parameter configuration test completed")


@pytest.mark.asyncio
async def test_identify_device(
    request: pytest.FixtureRequest,
    connected_gateway: TestDaliGateway,
    discovered_devices: List[Device],
) -> None:
    """Identify devices (LED blink) and verify ack responses."""
    _LOGGER.info("=== Testing Device Identify Commands ===")
    _LOGGER.info("Each device's indicator LED should blink to identify itself.")

    assert discovered_devices, "No devices available"

    device_limit: int | None = request.config.getoption("--device-limit")
    if device_limit:
        devices_to_test = discovered_devices[:device_limit]
    else:
        # Default to testing first 3 devices if no limit specified
        devices_to_test = discovered_devices[:3]

    success_count = 0
    for i, device in enumerate(devices_to_test, 1):
        model_info = device.model or "N/A"
        _LOGGER.info(
            "Identifying device %d/%d: %s (Channel %s, Address %s, Model: %s)",
            i,
            len(devices_to_test),
            device.name,
            device.channel,
            device.address,
            model_info,
        )

        # Send identify command
        device.identify()

        # Wait for response
        _LOGGER.info("  Waiting for identify response...")
        ack_received = await connected_gateway.wait_for_identify_response(timeout=5.0)

        if ack_received:
            _LOGGER.info("  Identify response received with ack=True")
            success_count += 1
        else:
            _LOGGER.error("  Identify response not received or ack=False")

    _LOGGER.info(
        "Identify test completed: %d/%d devices responded successfully",
        success_count,
        len(devices_to_test),
    )
    _LOGGER.info("Check if each device's LED blinked to confirm identification.")
    assert success_count > 0, (
        f"No devices responded to identify command ({len(devices_to_test)} tested)"
    )
