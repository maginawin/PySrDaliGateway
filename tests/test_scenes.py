"""Tests for DALI Gateway scene operations."""

import logging
from typing import List

from PySrDaliGateway.scene import Scene

from .helpers import TestDaliGateway

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_scene_discovery(
    connected_gateway: TestDaliGateway,
    discovered_scenes: List[Scene],
) -> None:
    """Verify scene discovery returns scenes with device data."""
    _LOGGER.info("=== Testing Scene Discovery ===")

    assert isinstance(discovered_scenes, list)
    _LOGGER.info("Found %d scene(s)", len(discovered_scenes))

    for scene in discovered_scenes:
        _LOGGER.info(
            "  Scene '%s' (ID: %s, Channel: %s): %d device(s)",
            scene.name,
            scene.scene_id,
            scene.channel,
            len(scene.devices),
        )


async def test_read_scene(
    connected_gateway: TestDaliGateway,
    ensured_scenes: List[Scene],
) -> None:
    """Read scene details and verify device data structure for up to 3 scenes."""
    assert ensured_scenes, "No scenes available"

    _LOGGER.info("=== Testing Read Scene (Scene Device Access) ===")

    for scene in ensured_scenes[:3]:
        _LOGGER.info(
            "Scene: %s (ID: %s, Channel: %s)",
            scene.name,
            scene.scene_id,
            scene.channel,
        )

        assert isinstance(scene.devices, list)
        _LOGGER.info("Scene has %d device(s)", len(scene.devices))

        for i, device in enumerate(scene.devices[:5], 1):
            assert "dev_type" in device
            assert "channel" in device
            assert "address" in device
            assert "property" in device

            _LOGGER.info(
                "  Device %d: Type: %s, Channel: %s, Address: %s",
                i,
                device["dev_type"],
                device["channel"],
                device["address"],
            )

            light_status = device["property"]
            _LOGGER.info("    Light Status:")
            if light_status.get("is_on") is not None:
                _LOGGER.info("      On/Off: %s", light_status["is_on"])
            if light_status.get("brightness") is not None:
                _LOGGER.info("      Brightness: %s", light_status["brightness"])
            if light_status.get("color_temp_kelvin") is not None:
                _LOGGER.info(
                    "      Color Temp: %sK",
                    light_status["color_temp_kelvin"],
                )
            if light_status.get("hs_color") is not None:
                _LOGGER.info("      HS Color: %s", light_status["hs_color"])
            if light_status.get("rgbw_color") is not None:
                _LOGGER.info("      RGBW Color: %s", light_status["rgbw_color"])
            if light_status.get("white_level") is not None:
                _LOGGER.info(
                    "      White Level: %s",
                    light_status["white_level"],
                )

        if len(scene.devices) > 5:
            _LOGGER.info("  ... and %d more devices", len(scene.devices) - 5)

    _LOGGER.info("Scene device access completed successfully")


async def test_scene_devices(
    connected_gateway: TestDaliGateway,
    ensured_scenes: List[Scene],
) -> None:
    """Verify scene device data is accessible and well-formed."""
    assert ensured_scenes, "No scenes available"

    _LOGGER.info("=== Testing Scene Device Access ===")

    for scene in ensured_scenes[:3]:
        _LOGGER.info(
            "Scene: %s (ID: %s, Channel: %s)",
            scene.name,
            scene.scene_id,
            scene.channel,
        )

        assert isinstance(scene.devices, list)
        _LOGGER.info("Scene has %d device(s)", len(scene.devices))

        for i, device in enumerate(scene.devices[:5], 1):
            _LOGGER.info(
                "  Device %d: Type: %s, Channel: %s, Address: %s",
                i,
                device["dev_type"],
                device["channel"],
                device["address"],
            )

            light_status = device["property"]
            _LOGGER.info("    Light Status:")
            if light_status.get("is_on") is not None:
                _LOGGER.info("      On/Off: %s", light_status["is_on"])
            if light_status.get("brightness") is not None:
                _LOGGER.info("      Brightness: %s", light_status["brightness"])
            if light_status.get("color_temp_kelvin") is not None:
                _LOGGER.info(
                    "      Color Temp: %sK",
                    light_status["color_temp_kelvin"],
                )
            if light_status.get("hs_color") is not None:
                _LOGGER.info("      HS Color: %s", light_status["hs_color"])
            if light_status.get("rgbw_color") is not None:
                _LOGGER.info("      RGBW Color: %s", light_status["rgbw_color"])
            if light_status.get("white_level") is not None:
                _LOGGER.info(
                    "      White Level: %s",
                    light_status["white_level"],
                )

        if len(scene.devices) > 5:
            _LOGGER.info("  ... and %d more devices", len(scene.devices) - 5)

    _LOGGER.info("Scene device access completed successfully")
