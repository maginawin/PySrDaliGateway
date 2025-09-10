#!/usr/bin/env python3
"""Modular test script for PySrDaliGateway with configurable test selection."""

import argparse
import asyncio
import logging
import sys
from typing import Any, Callable, Dict, List, Set, Tuple

from PySrDaliGateway.discovery import DaliGatewayDiscovery
from PySrDaliGateway.exceptions import DaliGatewayError
from PySrDaliGateway.gateway import DaliGateway
from PySrDaliGateway.types import (
    DaliGatewayType,
    DeviceParamType,
    DeviceType,
    GroupType,
    IlluminanceStatus,
    LightStatus,
    MotionStatus,
    PanelEventType,
    PanelStatus,
    SceneType,
)

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

_LOGGER = logging.getLogger(__name__)


class DaliGatewayTester:
    """Modular tester for DALI Gateway functionality."""

    def __init__(self):
        self.discovery: DaliGatewayDiscovery | None = None
        self.gateways: List[DaliGatewayType] = []
        self.gateway: DaliGateway | None = None
        self.gateway_config: DaliGatewayType | None = None
        self.devices: List[DeviceType] = []
        self.groups: List[GroupType] = []
        self.scenes: List[SceneType] = []
        self.is_connected = False
        # Track online status events
        self.online_status_events: List[Tuple[str, bool]] = []
        # Track callback events
        self.light_status_events: List[Tuple[str, LightStatus]] = []
        self.motion_status_events: List[Tuple[str, MotionStatus]] = []
        self.illuminance_status_events: List[Tuple[str, IlluminanceStatus]] = []
        self.panel_status_events: List[Tuple[str, PanelStatus]] = []

    async def test_discovery(self, gateway_sn: str | None = None) -> bool:
        """Step 1: Discover DALI gateways."""
        _LOGGER.info("=== Testing Gateway Discovery ===")

        # Preserve existing credentials if we have a specific gateway_sn
        existing_credentials = {}
        if (
            gateway_sn
            and self.gateway_config
            and self.gateway_config.get("gw_sn") == gateway_sn
        ):
            existing_credentials = {
                "username": self.gateway_config.get("username", ""),
                "passwd": self.gateway_config.get("passwd", ""),
            }
            _LOGGER.info("Preserving credentials for gateway %s", gateway_sn)

        if not self.discovery:
            self.discovery = DaliGatewayDiscovery()

        try:
            self.gateways = await self.discovery.discover_gateways(gateway_sn)
            _LOGGER.debug("Discovered gateways: %s", self.gateways)

            if not self.gateways:
                _LOGGER.error(
                    "No gateways discovered! "
                    "Check network connectivity and gateway power"
                )
                return False
        except DaliGatewayError as e:
            _LOGGER.error("Discovery failed: %s", e)
            return False

        # Apply preserved credentials if we have them and found the matching gateway
        if existing_credentials and gateway_sn:
            for gateway in self.gateways:
                if gateway["gw_sn"] == gateway_sn:
                    # Only overwrite if the discovered credentials are empty
                    if not gateway.get("username") and not gateway.get("passwd"):
                        gateway["username"] = existing_credentials.get("username", "")
                        gateway["passwd"] = existing_credentials.get("passwd", "")
                        _LOGGER.info(
                            "Applied preserved credentials to gateway %s", gateway_sn
                        )

        _LOGGER.info("✓ Found %d gateway(s)", len(self.gateways))

        for i, gw in enumerate(self.gateways):
            _LOGGER.info(
                "  Gateway %d: %s (%s) at %s:%s",
                i + 1,
                gw["name"],
                gw["gw_sn"],
                gw["gw_ip"],
                gw["port"],
            )
        return True

    async def test_connection(self, gateway_index: int = 0) -> bool:
        """Step 2: Connect to specified gateway."""
        if not self.gateways:
            _LOGGER.error("No gateways available! Run discovery first.")
            return False

        if gateway_index >= len(self.gateways):
            _LOGGER.error(
                "Gateway index %d out of range (0-%d)",
                gateway_index,
                len(self.gateways) - 1,
            )
            return False

        _LOGGER.info("=== Testing Gateway Connection ===")
        selected_gateway = self.gateways[gateway_index]
        self.gateway_config = {**selected_gateway}
        _LOGGER.info("Connecting to gateway '%s'...", self.gateway_config["name"])
        _LOGGER.info("Gateway config: %s", self.gateway_config)

        self.gateway = DaliGateway(self.gateway_config)

        # Set up online status callback to track gateway status
        self.gateway.on_online_status = self._on_online_status_callback

        try:
            await self.gateway.connect()
            self.is_connected = True
        except DaliGatewayError as e:
            _LOGGER.error("Connection error: %s", e)
            self.is_connected = False
            return False
        else:
            _LOGGER.info("✓ Successfully connected to gateway!")
            return True

    async def test_disconnect(self) -> bool:
        """Disconnect from gateway."""
        if not self.gateway or not self.is_connected:
            _LOGGER.warning("Not connected to any gateway")
            return True

        _LOGGER.info("=== Testing Gateway Disconnect ===")
        try:
            await self.gateway.disconnect()
            self.is_connected = False
        except DaliGatewayError as e:
            _LOGGER.error("Disconnect error: %s", e)
            return False
        else:
            _LOGGER.info("✓ Disconnected successfully")
            return True

    async def test_reconnection(self) -> bool:
        """Test disconnect and reconnect cycle."""
        _LOGGER.info("=== Testing Reconnection Cycle ===")

        # First disconnect
        if not await self.test_disconnect():
            return False

        # Re-discover to get updated gateway info
        if not self.gateway_config:
            _LOGGER.error("No gateway config available")
            return False

        # Preserve original credentials
        original_username = self.gateway_config.get("username", "")
        original_passwd = self.gateway_config.get("passwd", "")

        _LOGGER.info("Re-discovering gateway...")
        if not await self.test_discovery(self.gateway_config["gw_sn"]):
            return False

        # Update credentials from original config (preserve non-empty credentials)
        new_gateway = self.gateways[0]
        new_config: DaliGatewayType = {
            **new_gateway,
            "username": original_username,
            "passwd": original_passwd,
        }

        # Reconnect
        self.gateway_config = new_config
        self.gateway = DaliGateway(self.gateway_config)

        # Set up online status callback for reconnection test
        self.gateway.on_online_status = self._on_online_status_callback

        return await self.test_connection(0)

    async def test_version(self) -> bool:
        """Test gateway version retrieval."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Version Retrieval ===")
        try:
            gateway = self._assert_gateway()
            version = await gateway.get_version()
        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Version test failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Gateway version: %s", version)
            return True

    async def test_device_discovery(self) -> bool:
        """Test device discovery."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Device Discovery ===")
        try:
            gateway = self._assert_gateway()
            self.devices = await gateway.discover_devices()
        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Device discovery failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Found %d device(s)", len(self.devices))

            for device in self.devices[:5]:  # Show first 5 devices
                model_info = device.get("model", "N/A")
                _LOGGER.info(
                    "  Device: %s (%s) - Channel %s, Address %s, Model: %s",
                    device["name"],
                    device["dev_type"],
                    device["channel"],
                    device["address"],
                    model_info,
                )
            return True

    async def test_read_dev(self, device_limit: int | None = None) -> bool:
        """Test reading device status."""
        if not self._check_connection():
            return False

        if not self.devices:
            _LOGGER.error("No devices available! Run device discovery first.")
            return False

        _LOGGER.info("=== Testing ReadDev Commands ===")
        try:
            devices_to_test = self.devices
            if device_limit:
                devices_to_test = self.devices[:device_limit]

            for device in devices_to_test:
                model_info = device.get("model", "N/A")
                _LOGGER.info(
                    "Reading device: %s (Channel %s, Address %s, Model: %s)",
                    device["name"],
                    device["channel"],
                    device["address"],
                    model_info,
                )
                gateway = self._assert_gateway()
                gateway.command_read_dev(
                    device["dev_type"], device["channel"], device["address"]
                )

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("ReadDev test failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ ReadDev commands sent for %d devices", len(devices_to_test))
            return True

    async def test_set_dev_param(self) -> bool:
        """Test setting device parameters (maxBrightness) for channel 0 address 1."""
        if not self._check_connection():
            return False

        interval = 8  # seconds - reduced for faster testing

        _LOGGER.info("=== Testing SetDevParam Commands ===")

        # Track connection status throughout the test
        initial_connection_status = self.is_connected

        try:
            # Test with fixed channel 0, address 1, using Dimmer device type
            channel = 0
            address = 1
            dev_type = "0101"  # Dimmer device type
            _LOGGER.info(
                "Testing device: Channel %s, Address %s, Type %s",
                channel,
                address,
                dev_type,
            )

            gateway = self._assert_gateway()

            # Get current parameters
            _LOGGER.info("Getting current device parameters...")
            gateway.command_get_dev_param(dev_type, channel, address)

            # Use interruptible sleep that can detect connection status changes
            try:
                await asyncio.sleep(interval)
            except KeyboardInterrupt:
                _LOGGER.warning("Test interrupted during parameter read")
                return False

            # Set maxBrightness to 100
            _LOGGER.info("Setting maxBrightness to 100...")
            param_100: DeviceParamType = {"max_brightness": 100}
            gateway.command_set_dev_param("FFFF", 0, 1, param_100)

            try:
                await asyncio.sleep(interval)
            except KeyboardInterrupt:
                _LOGGER.warning("Test interrupted during maxBrightness setting")
                return False

            # Turn on all the lights to see effect
            _LOGGER.info("Turning on all light to see effect...")
            gateway.command_write_dev(
                "FFFF",
                0,
                1,
                [{"dpid": 20, "dataType": "bool", "value": True}],
            )

            # Read parameters after setting to 100
            _LOGGER.info("Reading parameters after setting to 100...")
            gateway.command_get_dev_param(dev_type, channel, address)

            try:
                await asyncio.sleep(interval)
            except KeyboardInterrupt:
                _LOGGER.warning("Test interrupted during parameter verification")
                return False

            # Set maxBrightness back to 1000 (default)
            _LOGGER.info("Setting maxBrightness back to 1000...")
            param_1000: DeviceParamType = {"max_brightness": 1000}
            gateway.command_set_dev_param("FFFF", 0, 1, param_1000)

            try:
                await asyncio.sleep(interval)
            except KeyboardInterrupt:
                _LOGGER.warning("Test interrupted during maxBrightness reset")
                return False

            # Read parameters after setting back to 1000
            _LOGGER.info("Reading parameters after setting back to 1000...")
            gateway.command_get_dev_param(dev_type, channel, address)

            try:
                await asyncio.sleep(interval)
            except KeyboardInterrupt:
                _LOGGER.warning("Test interrupted during final parameter read")
                return False

            # Check if connection status changed during test
            if initial_connection_status != self.is_connected:
                _LOGGER.warning(
                    "Connection status changed during test - may have experienced network issues"
                )
                # Don't fail the test if commands completed successfully

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("SetDevParam test failed: %s", e)
            return False
        except KeyboardInterrupt:
            _LOGGER.error("SetDevParam test interrupted by user")
            return False
        else:
            _LOGGER.info(
                "✓ SetDevParam commands completed for channel %s address %s",
                channel,
                address,
            )
            return True

    async def test_group_discovery(self) -> bool:
        """Test group discovery."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Group Discovery ===")
        try:
            gateway = self._assert_gateway()
            self.groups = await gateway.discover_groups()
        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Group discovery failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Found %d group(s)", len(self.groups))
            return True

    async def test_scene_discovery(self) -> bool:
        """Test scene discovery."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Scene Discovery ===")
        try:
            gateway = self._assert_gateway()
            self.scenes = await gateway.discover_scenes()
        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Scene discovery failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Found %d scene(s)", len(self.scenes))
            return True

    async def test_read_group(self) -> bool:
        """Test reading group details with devices."""
        if not self._check_connection():
            return False

        if not self.groups:
            _LOGGER.error("No groups available! Run group discovery first.")
            return False

        _LOGGER.info("=== Testing Read Group Commands ===")
        try:
            gateway = self._assert_gateway()
            
            # Test reading details for each discovered group
            for group in self.groups[:3]:  # Test up to 3 groups
                group_id = group["id"]
                channel = group["channel"]
                _LOGGER.info(
                    "Reading group: %s (ID: %s, Channel: %s)",
                    group["name"],
                    group_id,
                    channel,
                )
                
                # Read group details
                group_details = await gateway.read_group(group_id, channel)
                
                _LOGGER.info(
                    "✓ Group details - Name: '%s', Devices: %d",
                    group_details["name"],
                    len(group_details["devices"]),
                )
                
                # Show device details
                for i, device in enumerate(group_details["devices"][:5], 1):  # Show first 5 devices
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
                        len(group_details["devices"]) - 5
                    )

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Read group test failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Read group commands completed successfully")
            return True

    def _on_online_status_callback(self, device_id: str, status: bool) -> None:
        """Callback to track online status events."""
        self.online_status_events.append((device_id, status))
        if self.gateway_config and device_id == self.gateway_config["gw_sn"]:
            _LOGGER.info(
                "🔄 Gateway status changed: %s -> %s",
                device_id,
                "ONLINE" if status else "OFFLINE",
            )
        else:
            _LOGGER.info(
                "🔄 Device status: %s -> %s",
                device_id,
                "ONLINE" if status else "OFFLINE",
            )

    def _on_light_status_callback(self, device_id: str, status: LightStatus) -> None:
        """Callback to track light status events."""
        self.light_status_events.append((device_id, status))
        _LOGGER.info(
            "💡 Light status: %s -> %s",
            device_id,
            status,
        )

    def _on_motion_status_callback(self, device_id: str, status: MotionStatus) -> None:
        """Callback to track motion status events."""
        self.motion_status_events.append((device_id, status))
        _LOGGER.info(
            "🚶 Motion status: %s -> %s",
            device_id,
            status,
        )

    def _on_illuminance_status_callback(
        self, device_id: str, status: IlluminanceStatus
    ) -> None:
        """Callback to track illuminance status events."""
        self.illuminance_status_events.append((device_id, status))
        _LOGGER.info(
            "☀️ Illuminance status: %s -> %s lux (valid: %s)",
            device_id,
            status.get("illuminance_value", "Unknown"),
            status.get("is_valid", "Unknown"),
        )

    def _on_panel_status_callback(self, device_id: str, status: PanelStatus) -> None:
        """Callback to track panel status events."""
        self.panel_status_events.append((device_id, status))
        event_type = status["event_type"]
        rotate_info = ""
        if event_type == PanelEventType.ROTATE:
            rotate_info = f" (rotate: {status.get('rotate_value', 0)})"

        _LOGGER.info(
            "🎛️ Panel status: %s -> Key %s %s%s",
            device_id,
            status.get("key_no", "?"),
            event_type.value,
            rotate_info,
        )

    async def test_gateway_status_sync(self) -> bool:
        """Test gateway status synchronization through online_status callback."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Gateway Status Synchronization ===")

        if not self.gateway_config:
            _LOGGER.error("No gateway config available")
            return False

        gateway_sn = self.gateway_config["gw_sn"]

        # Clear previous events
        self.online_status_events.clear()

        try:
            gateway = self._assert_gateway()

            # Test disconnect - should trigger offline status
            _LOGGER.info("Testing disconnect status event...")
            await gateway.disconnect()
            self.is_connected = False

            # Wait a bit for callback to be called
            await asyncio.sleep(1)

            # Check if disconnect triggered offline status for gateway
            gateway_events = [
                event for event in self.online_status_events if event[0] == gateway_sn
            ]
            if not gateway_events:
                _LOGGER.error("❌ No gateway status events received on disconnect")
                return False

            last_event = gateway_events[-1]
            if last_event[1] is not False:
                _LOGGER.error(
                    "❌ Expected gateway offline status, got: %s", last_event[1]
                )
                return False

            _LOGGER.info("✓ Gateway offline status correctly received")

            # Test reconnect - should trigger online status
            _LOGGER.info("Testing reconnect status event...")
            await gateway.connect()
            self.is_connected = True

            # Wait a bit for callback to be called
            await asyncio.sleep(1)

            # Check if connect triggered online status for gateway
            gateway_events = [
                event for event in self.online_status_events if event[0] == gateway_sn
            ]
            if len(gateway_events) < 2:
                _LOGGER.error(
                    "❌ Expected at least 2 gateway status events (offline + online)"
                )
                return False

            last_event = gateway_events[-1]
            if last_event[1] is not True:
                _LOGGER.error(
                    "❌ Expected gateway online status, got: %s", last_event[1]
                )
                return False

            _LOGGER.info("✓ Gateway online status correctly received")

            # Log all gateway events for verification
            _LOGGER.info("Gateway status events:")
            for i, (dev_id, status) in enumerate(gateway_events):
                _LOGGER.info(
                    "  %d: %s -> %s", i + 1, dev_id, "ONLINE" if status else "OFFLINE"
                )

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Gateway status sync test failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Gateway status synchronization test completed successfully")
            return True

    async def test_callback_setup(self) -> bool:
        """Test callbacks by actively reading device status via ReadDev commands."""
        if not self._check_connection():
            return False

        if not self.devices:
            _LOGGER.error("No devices available! Run device discovery first.")
            return False

        _LOGGER.info("=== Testing Device Callbacks with ReadDev Commands ===")

        try:
            gateway = self._assert_gateway()

            # Set up all callback handlers
            gateway.on_light_status = self._on_light_status_callback
            gateway.on_motion_status = self._on_motion_status_callback
            gateway.on_illuminance_status = self._on_illuminance_status_callback
            gateway.on_panel_status = self._on_panel_status_callback

            # Clear previous events
            self.light_status_events.clear()
            self.motion_status_events.clear()
            self.illuminance_status_events.clear()
            self.panel_status_events.clear()

            _LOGGER.info("✓ All device callbacks set up successfully")

            # Find different device types to test
            light_devices = [
                d
                for d in self.devices
                if d["dev_type"] in ["0101", "0102", "0103", "0104", "0105"]
            ]
            motion_devices = [d for d in self.devices if d["dev_type"] == "0201"]
            illuminance_devices = [d for d in self.devices if d["dev_type"] == "0301"]
            panel_devices = [
                d
                for d in self.devices
                if d["dev_type"] in ["0401", "0402", "0403", "0404"]
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
                for device in light_devices[:3]:  # Test up to 3 light devices
                    model_info = device.get("model", "N/A")
                    _LOGGER.info(
                        "Reading light device: %s (Channel %s, Address %s, Model: %s)",
                        device["name"],
                        device["channel"],
                        device["address"],
                        model_info,
                    )
                    gateway.command_read_dev(
                        device["dev_type"], device["channel"], device["address"]
                    )
                    await asyncio.sleep(2)  # Wait for response

            # Test motion devices
            if motion_devices:
                _LOGGER.info("Testing motion sensor callbacks...")
                for device in motion_devices[:2]:  # Test up to 2 motion devices
                    model_info = device.get("model", "N/A")
                    _LOGGER.info(
                        "Reading motion device: %s (Channel %s, Address %s, Model: %s)",
                        device["name"],
                        device["channel"],
                        device["address"],
                        model_info,
                    )
                    gateway.command_read_dev(
                        device["dev_type"], device["channel"], device["address"]
                    )
                    await asyncio.sleep(2)  # Wait for response

            # Test illuminance devices
            if illuminance_devices:
                _LOGGER.info("Testing illuminance sensor callbacks...")
                for device in illuminance_devices[
                    :2
                ]:  # Test up to 2 illuminance devices
                    model_info = device.get("model", "N/A")
                    _LOGGER.info(
                        "Reading illuminance device: %s (Channel %s, Address %s, Model: %s)",
                        device["name"],
                        device["channel"],
                        device["address"],
                        model_info,
                    )
                    gateway.command_read_dev(
                        device["dev_type"], device["channel"], device["address"]
                    )
                    await asyncio.sleep(2)  # Wait for response

            # Test panel devices
            if panel_devices:
                _LOGGER.info("Testing panel callbacks...")
                for device in panel_devices[:2]:  # Test up to 2 panel devices
                    model_info = device.get("model", "N/A")
                    _LOGGER.info(
                        "Reading panel device: %s (Channel %s, Address %s, Model: %s)",
                        device["name"],
                        device["channel"],
                        device["address"],
                        model_info,
                    )
                    gateway.command_read_dev(
                        device["dev_type"], device["channel"], device["address"]
                    )
                    await asyncio.sleep(2)  # Wait for response

            # Wait a bit more for any delayed responses
            _LOGGER.info("Waiting 5 seconds for final responses...")
            await asyncio.sleep(5)

            # Report on received events
            total_events = (
                len(self.light_status_events)
                + len(self.motion_status_events)
                + len(self.illuminance_status_events)
                + len(self.panel_status_events)
            )

            _LOGGER.info("=== Callback Events Summary ===")
            _LOGGER.info("Light status events: %d", len(self.light_status_events))
            _LOGGER.info("Motion status events: %d", len(self.motion_status_events))
            _LOGGER.info(
                "Illuminance status events: %d", len(self.illuminance_status_events)
            )
            _LOGGER.info("Panel status events: %d", len(self.panel_status_events))
            _LOGGER.info("Total events received: %d", total_events)

            # Show some sample events
            if self.light_status_events:
                _LOGGER.info("Sample light event: %s", self.light_status_events[0])
            if self.motion_status_events:
                _LOGGER.info("Sample motion event: %s", self.motion_status_events[0])
            if self.illuminance_status_events:
                _LOGGER.info(
                    "Sample illuminance event: %s", self.illuminance_status_events[0]
                )
            if self.panel_status_events:
                _LOGGER.info("Sample panel event: %s", self.panel_status_events[0])

            if total_events > 0:
                _LOGGER.info(
                    "✓ Device callbacks working - received %d events from ReadDev commands",
                    total_events,
                )
            else:
                _LOGGER.warning("⚠️ No callback events received from ReadDev commands")

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Callback test failed: %s", e)
            return False

        return True

    def _check_connection(self) -> bool:
        """Check if gateway is connected."""
        if not self.gateway or not self.is_connected:
            _LOGGER.error("Not connected to gateway! Run connection test first.")
            return False
        return True

    def _assert_gateway(self) -> DaliGateway:
        """Assert gateway is connected and return it."""
        if not self.gateway or not self.is_connected:
            raise RuntimeError("Gateway not connected")
        return self.gateway

    async def run_all_tests(self) -> bool:
        """Run all tests in proper sequence."""
        _LOGGER.info("=== Starting Complete DALI Gateway Test Suite ===")

        tests: List[Tuple[str, Callable[[], Any]]] = [
            ("Discovery", self.test_discovery),
            ("Connection", lambda: self.test_connection(0)),
            ("Gateway Status Sync", self.test_gateway_status_sync),
            ("Version", self.test_version),
            ("Device Discovery", self.test_device_discovery),
            ("Callbacks", self.test_callback_setup),
            ("ReadDev", self.test_read_dev),
            ("SetDevParam", self.test_set_dev_param),
            ("Group Discovery", self.test_group_discovery),
            ("Read Group", self.test_read_group),
            ("Scene Discovery", self.test_scene_discovery),
            ("Reconnection", self.test_reconnection),
            ("Disconnect", self.test_disconnect),
        ]

        async def run_single_test(test_name: str, test_func: Callable[[], Any]) -> bool:
            try:
                result = await test_func()
            except KeyboardInterrupt:
                _LOGGER.error("❌ %s test interrupted by user", test_name)
                return False
            except (DaliGatewayError, RuntimeError, asyncio.TimeoutError) as e:
                _LOGGER.error("❌ %s test failed with exception: %s", test_name, e)
                return False
            else:
                if not result:
                    _LOGGER.error("❌ %s test failed", test_name)
                else:
                    _LOGGER.info("✅ %s test passed", test_name)
                return result

        results: Dict[str, bool] = {}
        for test_name, test_func in tests:
            results[test_name] = await run_single_test(test_name, test_func)

        passed = sum(1 for r in results.values() if r)
        total = len(results)

        _LOGGER.info("=== Test Summary ===")
        _LOGGER.info("Passed: %d/%d tests", passed, total)

        for test_name, result in results.items():
            status = "✅" if result else "❌"
            _LOGGER.info("%s %s", status, test_name)

        success = passed == total
        if success:
            _LOGGER.info("🎉 All tests completed successfully!")
        else:
            _LOGGER.error("❌ Some tests failed!")

        return success


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Modular DALI Gateway Testing Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Run all tests
  %(prog)s --tests discovery connection # Run only discovery and connection tests
  %(prog)s --list-tests                 # List available tests
  %(prog)s --device-limit 5             # Limit device operations to 5 devices
  %(prog)s --gateway-index 1            # Connect to second discovered gateway
        """,
    )

    parser.add_argument(
        "--tests",
        nargs="+",
        choices=[
            "discovery",
            "connection",
            "disconnect",
            "reconnection",
            "statusync",
            "version",
            "devices",
            "readdev",
            "setdevparam",
            "groups",
            "readgroup",
            "scenes",
            "callbacks",
            "all",
        ],
        default=["all"],
        help="Tests to run (default: all)",
    )

    parser.add_argument(
        "--list-tests", action="store_true", help="List available tests and exit"
    )

    parser.add_argument(
        "--gateway-index",
        type=int,
        default=0,
        help="Gateway index to connect to (default: 0)",
    )

    parser.add_argument(
        "--device-limit",
        type=int,
        help="Limit number of devices for testing (default: all devices)",
    )

    parser.add_argument(
        "--gateway-sn", type=str, help="Specific gateway serial number to discover"
    )

    return parser.parse_args()


async def run_selected_tests(tester: DaliGatewayTester, args: Any) -> bool:
    """Run selected tests with dependency management."""

    # Available tests with dependencies
    test_registry: Dict[str, Tuple[Callable[[], Any], List[str], str]] = {
        "discovery": (tester.test_discovery, [], "Gateway Discovery"),
        "connection": (
            lambda: tester.test_connection(args.gateway_index),
            ["discovery"],
            "Gateway Connection",
        ),
        "disconnect": (tester.test_disconnect, ["connection"], "Gateway Disconnect"),
        "reconnection": (
            tester.test_reconnection,
            ["connection"],
            "Reconnection Cycle",
        ),
        "statusync": (
            tester.test_gateway_status_sync,
            ["connection"],
            "Gateway Status Sync",
        ),
        "version": (tester.test_version, ["connection"], "Version Retrieval"),
        "devices": (tester.test_device_discovery, ["connection"], "Device Discovery"),
        "readdev": (
            lambda: tester.test_read_dev(args.device_limit),
            ["connection", "devices"],
            "ReadDev Commands",
        ),
        "setdevparam": (
            tester.test_set_dev_param,
            ["connection"],
            "SetDevParam Commands",
        ),
        "groups": (tester.test_group_discovery, ["connection"], "Group Discovery"),
        "readgroup": (tester.test_read_group, ["connection", "groups"], "Read Group Details"),
        "scenes": (tester.test_scene_discovery, ["connection"], "Scene Discovery"),
        "callbacks": (
            tester.test_callback_setup,
            ["connection", "devices"],
            "Device Callbacks",
        ),
    }

    # Determine which tests to run
    if "all" in args.tests:
        selected_tests = [
            "discovery",
            "connection",
            "statusync",
            "version",
            "devices",
            "callbacks",
            "readdev",
            "setdevparam",
            "groups",
            "readgroup",
            "scenes",
            "reconnection",
            "disconnect",
        ]
    else:
        selected_tests = args.tests

    # Build execution plan with dependencies
    execution_plan: List[Tuple[str, Callable[[], Any], str]] = []
    completed_tests: Set[str] = set()

    def add_test_with_deps(test_name: str):
        if test_name in completed_tests or test_name in [t[0] for t in execution_plan]:
            return

        if test_name not in test_registry:
            _LOGGER.error("Unknown test: %s", test_name)
            return

        test_func, dependencies, description = test_registry[test_name]

        # Add dependencies first
        for dep in dependencies:
            add_test_with_deps(dep)

        execution_plan.append((test_name, test_func, description))

    # Build execution plan
    for test_name in selected_tests:
        add_test_with_deps(test_name)

    # Execute tests
    _LOGGER.info("=== Test Execution Plan ===")
    for test_name, _, description in execution_plan:
        _LOGGER.info("- %s (%s)", description, test_name)

    results: Dict[str, bool] = {}
    for test_name, test_func, description in execution_plan:
        _LOGGER.info("\n🧪 Running: %s", description)
        try:
            # Special handling for discovery with gateway_sn parameter
            if test_name == "discovery" and args.gateway_sn:
                result = await tester.test_discovery(args.gateway_sn)
            else:
                result = await test_func()

            results[test_name] = result
            completed_tests.add(test_name)

            if result:
                _LOGGER.info("✅ %s completed successfully", description)
            else:
                _LOGGER.error("❌ %s failed", description)
                # Stop execution if critical test fails
                if test_name in ["discovery", "connection"]:
                    _LOGGER.error("Critical test failed, stopping execution")
                    break
        except KeyboardInterrupt:
            _LOGGER.error("❌ %s interrupted by user", description)
            results[test_name] = False
            # Always stop on user interrupt
            break
        except (DaliGatewayError, RuntimeError, asyncio.TimeoutError) as e:
            _LOGGER.error("❌ %s failed with exception: %s", description, e)
            results[test_name] = False
            # Stop on critical failures
            if test_name in ["discovery", "connection"]:
                break

    # Summary
    passed = sum(1 for r in results.values() if r)
    total = len(results)

    _LOGGER.info("\n=== Test Summary ===")
    _LOGGER.info("Executed: %d/%d planned tests", total, len(execution_plan))
    _LOGGER.info("Passed: %d/%d executed tests", passed, total)

    for test_name, result in results.items():
        status = "✅" if result else "❌"
        description = test_registry[test_name][2]
        _LOGGER.info("%s %s", status, description)

    success = passed == total == len(execution_plan)
    if success:
        _LOGGER.info("🎉 All requested tests completed successfully!")
    else:
        _LOGGER.error("❌ Some tests failed or were not executed!")

    return success


async def main() -> bool:
    """Main entry point."""
    args = parse_arguments()

    if args.list_tests:
        print("Available tests:")
        tests = {
            "discovery": "Discover DALI gateways on network",
            "connection": "Connect to discovered gateway",
            "disconnect": "Disconnect from gateway",
            "reconnection": "Test disconnect/reconnect cycle",
            "statusync": "Test gateway status synchronization via online_status callback",
            "version": "Get gateway firmware version",
            "devices": "Discover connected DALI devices",
            "readdev": "Read device status via MQTT",
            "setdevparam": "Set device parameters (maxBrightness)",
            "groups": "Discover DALI groups",
            "readgroup": "Read group details with device list",
            "scenes": "Discover DALI scenes",
            "callbacks": "Test device status callbacks (light, motion, illuminance, panel)",
            "all": "Run complete test suite",
        }

        for test_name, description in tests.items():
            print(f"  {test_name:<12} - {description}")
        return True

    try:
        tester = DaliGatewayTester()
        return await run_selected_tests(tester, args)

    except KeyboardInterrupt:
        _LOGGER.error("Testing interrupted by user")
        return False
    except (DaliGatewayError, RuntimeError, asyncio.TimeoutError) as e:
        _LOGGER.error("Unexpected error during testing: %s", e)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
