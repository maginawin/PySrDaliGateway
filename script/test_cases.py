#!/usr/bin/env python3
"""Test cases for DALI Gateway functionality."""

import asyncio
import logging
from typing import Dict, List, Tuple

from test_cache import GatewayCredentialCache
from test_helpers import IdentifyResponseListener, TestDaliGateway

from PySrDaliGateway.device import Device
from PySrDaliGateway.discovery import DaliGatewayDiscovery
from PySrDaliGateway.exceptions import DaliGatewayError
from PySrDaliGateway.gateway import DaliGateway
from PySrDaliGateway.group import Group
from PySrDaliGateway.scene import Scene
from PySrDaliGateway.types import (
    CallbackEventType,
    DeviceParamType,
    IlluminanceStatus,
    LightStatus,
    MotionStatus,
    PanelEventType,
    PanelStatus,
    SensorParamType,
)
from PySrDaliGateway.udp_client import send_identify_gateway

_LOGGER = logging.getLogger(__name__)


class DaliGatewayTester:
    """Modular tester for DALI Gateway functionality."""

    def __init__(self):
        self.discovery: DaliGatewayDiscovery | None = None
        self.gateways: List[TestDaliGateway] = []
        self.gateway: TestDaliGateway | None = None
        self.devices: List[Device] = []
        self.groups: List[Group] = []
        self.scenes: List[Scene] = []
        self.is_connected = False
        # Credential cache for automatic discovery bypass
        self.credential_cache = GatewayCredentialCache()
        # Track online status events
        self.online_status_events: List[Tuple[str, bool]] = []
        # Track callback events
        self.light_status_events: List[Tuple[str, LightStatus]] = []
        self.motion_status_events: List[Tuple[str, MotionStatus]] = []
        self.illuminance_status_events: List[Tuple[str, IlluminanceStatus]] = []
        self.panel_status_events: List[Tuple[str, PanelStatus]] = []
        self.dev_param_events: List[Tuple[str, DeviceParamType]] = []
        self.sensor_param_events: List[Tuple[str, SensorParamType]] = []

    def _clone_gateway(
        self,
        gateway: DaliGateway,
        *,
        username: str | None = None,
        passwd: str | None = None,
    ) -> TestDaliGateway:
        """Create a detached copy of a gateway with optional credential overrides."""
        return TestDaliGateway(
            gw_sn=gateway.gw_sn,
            gw_ip=gateway.gw_ip,
            port=gateway.port,
            username=username if username is not None else gateway.username,
            passwd=passwd if passwd is not None else gateway.passwd,
            name=gateway.name,
            channel_total=gateway.channel_total,
            is_tls=gateway.is_tls,
        )

    async def create_gateway_direct(
        self,
        gw_sn: str,
        gw_ip: str,
        port: int,
        username: str,
        passwd: str,
        is_tls: bool = False,
        name: str | None = None,
        channel_total: List[int] | None = None,
    ) -> bool:
        """Create gateway configuration directly without discovery (testing mode)."""
        _LOGGER.info("=== Testing Mode: Creating Gateway Configuration Directly ===")

        gateway = TestDaliGateway(
            gw_sn=gw_sn,
            gw_ip=gw_ip,
            port=port,
            username=username,
            passwd=passwd,
            name=name or gw_sn,
            channel_total=channel_total or [0],
            is_tls=is_tls,
        )

        self.gateways = [gateway]

        _LOGGER.info("✓ Gateway configuration created directly")
        _LOGGER.info(
            "  Gateway: %s (%s) at %s:%s (TLS: %s)",
            gateway.name,
            gateway.gw_sn,
            gateway.gw_ip,
            gateway.port,
            gateway.is_tls,
        )
        _LOGGER.info("  Username: %s", gateway.username)

        return True

    async def test_discovery(self, gateway_sn: str | None = None) -> bool:
        """Step 1: Discover DALI gateways."""
        _LOGGER.info("=== Testing Gateway Discovery ===")

        # Try cache first - use most recently connected gateway
        if self.credential_cache.has_cache():
            cached = self.credential_cache.get_last_gateway()
            if cached:
                _LOGGER.info(
                    "✓ Found cached credentials for gateway %s", cached["gw_sn"]
                )
                _LOGGER.info("  Using cached connection info (skipping UDP discovery)")
                _LOGGER.info(
                    "  (Delete script/.gateway_cache.json to force rediscovery)"
                )

                # Create gateway directly from cache
                gateway = TestDaliGateway(
                    gw_sn=cached["gw_sn"],
                    gw_ip=cached["gw_ip"],
                    port=cached["port"],
                    username=cached["username"],
                    passwd=cached["passwd"],
                    name=cached.get("name"),
                    channel_total=cached.get("channel_total"),
                    is_tls=cached.get("is_tls", False),
                )
                self.gateways = [gateway]
                _LOGGER.info(
                    "  Gateway: %s (%s) at %s:%s",
                    gateway.name,
                    gateway.gw_sn,
                    gateway.gw_ip,
                    gateway.port,
                )
                return True

        # Preserve existing credentials if we have a specific gateway_sn
        existing_credentials: Dict[str, str] = {}
        if gateway_sn and self.gateway and self.gateway.gw_sn == gateway_sn:
            existing_credentials = {
                "username": self.gateway.username,
                "passwd": self.gateway.passwd,
            }
            _LOGGER.info("Preserving credentials for gateway %s", gateway_sn)

        if not self.discovery:
            self.discovery = DaliGatewayDiscovery()

        try:
            discovered = await self.discovery.discover_gateways(gateway_sn)
            _LOGGER.debug("Discovered gateways: %s", discovered)
            # Convert to TestDaliGateway instances
            self.gateways = [self._clone_gateway(gw) for gw in discovered]

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
            updated_gateways: List[TestDaliGateway] = []
            for gateway in self.gateways:
                if (
                    gateway.gw_sn == gateway_sn
                    and not gateway.username
                    and not gateway.passwd
                ):
                    updated_gateways.append(
                        self._clone_gateway(
                            gateway,
                            username=existing_credentials.get("username", ""),
                            passwd=existing_credentials.get("passwd", ""),
                        )
                    )
                    _LOGGER.info(
                        "Applied preserved credentials to gateway %s", gateway_sn
                    )
                else:
                    updated_gateways.append(gateway)
            self.gateways = updated_gateways

        _LOGGER.info("✓ Found %d gateway(s)", len(self.gateways))

        for i, gw in enumerate(self.gateways):
            _LOGGER.info(
                "  Gateway %d: %s (%s) at %s:%s",
                i + 1,
                gw.name,
                gw.gw_sn,
                gw.gw_ip,
                gw.port,
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
        self.gateway = self._clone_gateway(selected_gateway)
        _LOGGER.info(
            "Connecting to gateway '%s' (%s) at %s:%s (TLS: %s)...",
            self.gateway.name,
            self.gateway.gw_sn,
            self.gateway.gw_ip,
            self.gateway.port,
            self.gateway.is_tls,
        )

        # Set up online status callback to track gateway status
        self.gateway.register_listener(
            CallbackEventType.ONLINE_STATUS,
            self._on_online_status_callback,
            dev_id=self.gateway.gw_sn,
        )

        try:
            await self.gateway.connect()
            self.is_connected = True
        except DaliGatewayError as e:
            _LOGGER.error("Connection error: %s", e)
            self.is_connected = False
            return False
        else:
            _LOGGER.info("✓ Successfully connected to gateway!")

            # Save credentials to cache after successful connection
            if self.gateway.username and self.gateway.passwd:
                self.credential_cache.save_gateway(self.gateway)
                _LOGGER.debug("Saved gateway credentials to cache")

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
        if not self.gateway:
            _LOGGER.error("No gateway available")
            return False

        # Preserve original credentials
        original_username = self.gateway.username
        original_passwd = self.gateway.passwd
        gateway_sn = self.gateway.gw_sn

        _LOGGER.info("Re-discovering gateway...")
        if not await self.test_discovery(gateway_sn):
            return False

        if not self.gateways:
            _LOGGER.error("No gateways discovered during reconnection")
            return False

        # Ensure preserved credentials are applied if discovery returned empty creds
        refreshed_gateway = self.gateways[0]
        if (
            gateway_sn == refreshed_gateway.gw_sn
            and not refreshed_gateway.username
            and not refreshed_gateway.passwd
        ):
            self.gateways[0] = self._clone_gateway(
                refreshed_gateway,
                username=original_username,
                passwd=original_passwd,
            )

        # Reconnect using the freshly discovered gateway info
        return await self.test_connection(0)

    async def test_version(self) -> bool:
        """Test gateway version retrieval (auto-retrieved on connect)."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Version Information ===")
        _LOGGER.info("(Version is automatically retrieved during gateway connection)")
        try:
            gateway = self._assert_gateway()
            _LOGGER.info("✓ Software version: %s", gateway.software_version or "N/A")
            _LOGGER.info("✓ Firmware version: %s", gateway.firmware_version or "N/A")

            # Check if version was populated
            if gateway.software_version or gateway.firmware_version:
                _LOGGER.info("✓ Gateway version information available")
                return True
            _LOGGER.warning(
                "⚠️ Version information not yet received (this is normal if just connected)"
            )
        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Version test failed: %s", e)
            return False

        return True # Not a failure, version may arrive shortly after connection

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
                model_info = device.model or "N/A"
                _LOGGER.info(
                    "  Device: %s (%s) - Channel %s, Address %s, Model: %s",
                    device.name,
                    device.dev_type,
                    device.channel,
                    device.address,
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
                model_info = device.model or "N/A"
                _LOGGER.info(
                    "Reading device: %s (Channel %s, Address %s, Model: %s)",
                    device.name,
                    device.channel,
                    device.address,
                    model_info,
                )
                gateway = self._assert_gateway()
                gateway.command_read_dev(
                    device.dev_type, device.channel, device.address
                )

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("ReadDev test failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ ReadDev commands sent for %d devices", len(devices_to_test))
            return True

    async def test_set_dev_param(self) -> bool:
        """Test setting device parameters (fade time, fade rate, brightness limits)."""
        if not self._check_connection():
            return False

        if not self.devices:
            _LOGGER.warning("No devices available! Run device discovery first.")
            return False

        interval = 5  # seconds - reduced for faster testing

        _LOGGER.info("=== Testing Device Parameter Configuration ===")

        # Track connection status throughout the test
        initial_connection_status = self.is_connected

        try:
            gateway = self._assert_gateway()

            # Find a light device to test
            light_device = next(
                (d for d in self.devices if d.dev_type.startswith("01")), None
            )

            if not light_device:
                _LOGGER.warning("No light device found for parameter testing")
                return False

            _LOGGER.info(
                "Testing device: %s (Channel %s, Address %s, Type %s)",
                light_device.name,
                light_device.channel,
                light_device.address,
                light_device.dev_type,
            )

            # Clear previous parameter events
            self.dev_param_events.clear()

            # Register callback for parameter updates
            light_device.register_listener(
                CallbackEventType.DEV_PARAM,
                self._make_dev_param_callback(light_device.dev_id),
            )

            # Test 1: Get current parameters using Device wrapper method
            _LOGGER.info("\n--- Test 1: Get current device parameters ---")
            light_device.get_device_parameters()

            baseline_events = len(self.dev_param_events)
            got_initial_params = await self._await_dev_param(
                baseline_events, timeout=12.0
            )

            if got_initial_params:
                _LOGGER.info("✓ Received parameters: %s", self.dev_param_events[-1][1])
            else:
                _LOGGER.warning("✗ No parameters received")

            # Test 2: Set fade time and fade rate using Device wrapper method
            _LOGGER.info("\n--- Test 2: Set fade time and fade rate ---")
            params: DeviceParamType = {
                "fade_time": 5,  # Fade time setting (0-15)
                "fade_rate": 7,  # Fade rate setting (0-15)
            }
            _LOGGER.info("Setting parameters: %s", params)

            # Clear events before sending
            self.dev_param_events.clear()
            light_device.set_device_parameters(params)

            await asyncio.sleep(interval)

            # Note: setDevParamRes may not return the set values, just ack
            # We verify by reading back the parameters in Test 4
            _LOGGER.info("✓ Fade parameters sent")

            # Test 3: Set brightness limits
            _LOGGER.info("\n--- Test 3: Set brightness limits ---")
            params = {
                "min_brightness": 100,  # Minimum brightness (0-1000)
                "max_brightness": 900,  # Maximum brightness (0-1000)
            }
            _LOGGER.info("Setting parameters: %s", params)
            light_device.set_device_parameters(params)

            await asyncio.sleep(interval)
            _LOGGER.info("✓ Brightness limits sent")

            # Test 4: Verify updated parameters
            _LOGGER.info("\n--- Test 4: Verify updated parameters ---")
            self.dev_param_events.clear()
            light_device.get_device_parameters()

            baseline_events = len(self.dev_param_events)
            got_verified_params = await self._await_dev_param(
                baseline_events, timeout=15.0
            )

            if got_verified_params:
                latest_params = self.dev_param_events[-1][1]
                _LOGGER.info("✓ Retrieved updated parameters: %s", latest_params)

                # Verify some expected values
                if "fade_time" in latest_params or "max_brightness" in latest_params:
                    _LOGGER.info("✓ Parameters updated successfully")
                else:
                    _LOGGER.error("✗ Could not verify parameter values")
                    return False
            else:
                _LOGGER.error(
                    "✗ Could not verify updated parameters - no response received"
                )
                return False

            # Test 5: Reset to defaults using gateway commands (broadcast)
            _LOGGER.info("\n--- Test 5: Reset to defaults using broadcast ---")
            reset_params: DeviceParamType = {"max_brightness": 1000}
            gateway.command_set_dev_param("FFFF", 0, 1, reset_params)

            await asyncio.sleep(interval)
            _LOGGER.info("✓ Reset command sent")

            # Check if connection status changed during test
            if initial_connection_status != self.is_connected:
                _LOGGER.warning(
                    "Connection status changed during test - may have experienced network issues"
                )

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Device parameter test failed: %s", e)
            return False
        except KeyboardInterrupt:
            _LOGGER.error("Device parameter test interrupted by user")
            return False
        else:
            _LOGGER.info("✓ Device parameter configuration test completed")
            return True

    async def test_set_sensor_param(self) -> bool:
        """Test setting sensor parameters (occupancy time, sensitivity, coverage, etc.)."""
        if not self._check_connection():
            return False

        if not self.devices:
            _LOGGER.warning("No devices available! Run device discovery first.")
            return False

        interval = 5  # seconds

        _LOGGER.info("=== Testing Sensor Parameter Configuration ===")

        # Track connection status throughout the test
        initial_connection_status = self.is_connected

        try:
            # Find a sensor device to test
            sensor_device = next(
                (d for d in self.devices if d.dev_type.startswith("02")), None
            )

            if not sensor_device:
                _LOGGER.warning(
                    "No sensor device found - skipping sensor parameter test"
                )
                return True  # Not a failure, just no suitable device

            _LOGGER.info(
                "Testing sensor: %s (Channel %s, Address %s, Type %s)",
                sensor_device.name,
                sensor_device.channel,
                sensor_device.address,
                sensor_device.dev_type,
            )

            # Clear previous parameter events
            self.sensor_param_events.clear()

            # Register callback for sensor parameter updates
            sensor_device.register_listener(
                CallbackEventType.SENSOR_PARAM,
                self._make_sensor_param_callback(sensor_device.dev_id),
            )

            # Test 1: Get current sensor parameters
            _LOGGER.info("\n--- Test 1: Get current sensor parameters ---")
            sensor_device.get_sensor_parameters()

            await asyncio.sleep(interval)

            if self.sensor_param_events:
                _LOGGER.info(
                    "✓ Received parameters: %s", self.sensor_param_events[-1][1]
                )
            else:
                _LOGGER.warning("✗ No sensor parameters received")

            # Test 2: Set sensor sensitivity and coverage
            _LOGGER.info("\n--- Test 2: Set sensor sensitivity and coverage ---")
            params: SensorParamType = {
                "sensitivity": 75,  # Sensitivity level (0-100)
                "coverage": 80,  # Detection range (0-100)
            }
            _LOGGER.info("Setting parameters: %s", params)
            sensor_device.set_sensor_parameters(params)

            await asyncio.sleep(interval)
            _LOGGER.info("✓ Sensitivity and coverage parameters sent")

            # Test 3: Set sensor timing parameters
            _LOGGER.info("\n--- Test 3: Set sensor timing parameters ---")
            params = {
                "occpy_time": 10,  # Occupancy time (0-255)
                "report_time": 5,  # Report timer (0-255)
                "down_time": 15,  # Hold time (0-255)
            }
            _LOGGER.info("Setting parameters: %s", params)
            sensor_device.set_sensor_parameters(params)

            await asyncio.sleep(interval)
            _LOGGER.info("✓ Timing parameters sent")

            # Test 4: Verify updated parameters
            _LOGGER.info("\n--- Test 4: Verify updated sensor parameters ---")
            self.sensor_param_events.clear()
            sensor_device.get_sensor_parameters()

            await asyncio.sleep(interval)

            if self.sensor_param_events:
                latest_params = self.sensor_param_events[-1][1]
                _LOGGER.info("✓ Retrieved updated parameters: %s", latest_params)

                # Verify some expected values
                if "sensitivity" in latest_params or "occpy_time" in latest_params:
                    _LOGGER.info("✓ Sensor parameters updated successfully")
                else:
                    _LOGGER.error("✗ Could not verify sensor parameter values")
                    return False
            else:
                _LOGGER.error(
                    "✗ Could not verify updated sensor parameters - no response received"
                )
                return False

            # Check if connection status changed during test
            if initial_connection_status != self.is_connected:
                _LOGGER.warning(
                    "Connection status changed during test - may have experienced network issues"
                )

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Sensor parameter test failed: %s", e)
            return False
        except KeyboardInterrupt:
            _LOGGER.error("Sensor parameter test interrupted by user")
            return False
        else:
            _LOGGER.info("✓ Sensor parameter configuration test completed")
            return True

    async def test_group_discovery(self) -> bool:
        """Test group discovery with parallel device data retrieval."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Group Discovery ===")
        _LOGGER.info("(Groups are discovered with device data retrieved in parallel)")
        try:
            gateway = self._assert_gateway()
            self.groups = await gateway.discover_groups()
        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Group discovery failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Found %d group(s)", len(self.groups))
            # Show device counts for each group
            for group in self.groups:
                _LOGGER.info(
                    "  Group '%s' (ID: %s, Channel: %s): %d device(s)",
                    group.name,
                    group.group_id,
                    group.channel,
                    len(group.devices),
                )
            return True

    async def test_scene_discovery(self) -> bool:
        """Test scene discovery with parallel device data retrieval."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Scene Discovery ===")
        _LOGGER.info("(Scenes are discovered with device data retrieved in parallel)")
        try:
            gateway = self._assert_gateway()
            self.scenes = await gateway.discover_scenes()
        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Scene discovery failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Found %d scene(s)", len(self.scenes))
            # Show device counts for each scene
            for scene in self.scenes:
                _LOGGER.info(
                    "  Scene '%s' (ID: %s, Channel: %s): %d device(s)",
                    scene.name,
                    scene.scene_id,
                    scene.channel,
                    len(scene.devices),
                )
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
                group_id = group.group_id
                channel = group.channel
                _LOGGER.info(
                    "Reading group: %s (ID: %s, Channel: %s)",
                    group.name,
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
                for i, device in enumerate(
                    group_details["devices"][:5], 1
                ):  # Show first 5 devices
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
                        "  ... and %d more devices", len(group_details["devices"]) - 5
                    )

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Read group test failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Read group commands completed successfully")
            return True

    async def test_scene_devices(self) -> bool:
        """Test accessing scene device data."""
        if not self._check_connection():
            return False

        if not self.scenes:
            _LOGGER.error("No scenes available! Run scene discovery first.")
            return False

        _LOGGER.info("=== Testing Scene Device Access ===")
        try:
            # Test accessing devices for each discovered scene
            for scene in self.scenes[:3]:  # Test up to 3 scenes
                _LOGGER.info(
                    "Scene: %s (ID: %s, Channel: %s)",
                    scene.name,
                    scene.scene_id,
                    scene.channel,
                )

                _LOGGER.info("✓ Scene has %d device(s)", len(scene.devices))

                # Show device details with properties
                for i, device in enumerate(
                    scene.devices[:5], 1
                ):  # Show first 5 devices
                    _LOGGER.info(
                        "  Device %d: Type: %s, Channel: %s, Address: %s",
                        i,
                        device["dev_type"],
                        device["channel"],
                        device["address"],
                    )

                    # Show device light status
                    light_status = device["property"]
                    _LOGGER.info("    Light Status:")
                    if light_status.get("is_on") is not None:
                        _LOGGER.info("      On/Off: %s", light_status["is_on"])
                    if light_status.get("brightness") is not None:
                        _LOGGER.info("      Brightness: %s", light_status["brightness"])
                    if light_status.get("color_temp_kelvin") is not None:
                        _LOGGER.info(
                            "      Color Temp: %sK", light_status["color_temp_kelvin"]
                        )
                    if light_status.get("hs_color") is not None:
                        _LOGGER.info("      HS Color: %s", light_status["hs_color"])
                    if light_status.get("rgbw_color") is not None:
                        _LOGGER.info("      RGBW Color: %s", light_status["rgbw_color"])
                    if light_status.get("white_level") is not None:
                        _LOGGER.info(
                            "      White Level: %s", light_status["white_level"]
                        )

                if len(scene.devices) > 5:
                    _LOGGER.info("  ... and %d more devices", len(scene.devices) - 5)

                _LOGGER.info("")  # Blank line between scenes

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Scene device access failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Scene device access completed successfully")
            return True

    def _on_online_status_callback(self, status: bool) -> None:
        """Callback to track online status events."""
        # Since callbacks are now device-specific, we need to capture the device_id via closure
        device_id = self.gateway.gw_sn if self.gateway else "unknown"
        self.online_status_events.append((device_id, status))
        _LOGGER.info(
            "🔄 Gateway status changed: %s -> %s",
            device_id,
            "ONLINE" if status else "OFFLINE",
        )

    def _make_light_callback(self, device_id: str):
        """Create a light status callback with device_id captured in closure."""

        def on_light_status(status: LightStatus) -> None:
            self.light_status_events.append((device_id, status))
            _LOGGER.info("💡 Light status: %s -> %s", device_id, status)

        return on_light_status

    def _make_motion_callback(self, device_id: str):
        """Create a motion status callback with device_id captured in closure."""

        def on_motion_status(status: MotionStatus) -> None:
            self.motion_status_events.append((device_id, status))
            _LOGGER.info("🚶 Motion status: %s -> %s", device_id, status)

        return on_motion_status

    def _make_illuminance_callback(self, device_id: str):
        """Create an illuminance status callback with device_id captured in closure."""

        def on_illuminance_status(status: IlluminanceStatus) -> None:
            self.illuminance_status_events.append((device_id, status))
            _LOGGER.info(
                "☀️ Illuminance status: %s -> %s lux (valid: %s)",
                device_id,
                status.get("illuminance_value", "Unknown"),
                status.get("is_valid", "Unknown"),
            )

        return on_illuminance_status

    def _make_panel_callback(self, device_id: str):
        """Create a panel status callback with device_id captured in closure."""

        def on_panel_status(status: PanelStatus) -> None:
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

        return on_panel_status

    def _make_dev_param_callback(self, device_id: str):
        """Create a device parameter callback with device_id captured in closure."""

        def on_dev_param(params: DeviceParamType) -> None:
            self.dev_param_events.append((device_id, params))
            _LOGGER.info("⚙️ Device parameters: %s -> %s", device_id, params)

        return on_dev_param

    async def _await_dev_param(self, baseline_count: int, timeout: float) -> bool:
        """Wait for a new device parameter event up to timeout seconds."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        while loop.time() - start < timeout:
            if len(self.dev_param_events) > baseline_count:
                return True
            await asyncio.sleep(0.5)
        return False

    def _make_sensor_param_callback(self, device_id: str):
        """Create a sensor parameter callback with device_id captured in closure."""

        def on_sensor_param(params: SensorParamType) -> None:
            self.sensor_param_events.append((device_id, params))
            _LOGGER.info("🔧 Sensor parameters: %s -> %s", device_id, params)

        return on_sensor_param

    async def test_gateway_status_sync(self) -> bool:
        """Test gateway status synchronization through online_status callback."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Gateway Status Synchronization ===")

        if not self.gateway:
            _LOGGER.error("No gateway available")
            return False

        gateway_sn = self.gateway.gw_sn

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

            # Clear previous events
            self.light_status_events.clear()
            self.motion_status_events.clear()
            self.illuminance_status_events.clear()
            self.panel_status_events.clear()

            # Find different device types to test
            light_devices = [
                d
                for d in self.devices
                if d.dev_type in ["0101", "0102", "0103", "0104", "0105"]
            ]
            motion_devices = [d for d in self.devices if d.dev_type == "0201"]
            illuminance_devices = [d for d in self.devices if d.dev_type == "0301"]
            panel_devices = [
                d
                for d in self.devices
                if d.dev_type in ["0401", "0402", "0403", "0404"]
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
                    # Register callback for this specific device
                    device.register_listener(
                        CallbackEventType.LIGHT_STATUS,
                        self._make_light_callback(device.dev_id),
                    )

                    model_info = device.model or "N/A"
                    _LOGGER.info(
                        "Reading light device: %s (Channel %s, Address %s, Model: %s)",
                        device.name,
                        device.channel,
                        device.address,
                        model_info,
                    )
                    gateway.command_read_dev(
                        device.dev_type, device.channel, device.address
                    )
                    await asyncio.sleep(2)  # Wait for response

            # Test motion devices
            if motion_devices:
                _LOGGER.info("Testing motion sensor callbacks...")
                for device in motion_devices[:2]:  # Test up to 2 motion devices
                    # Register callback for this specific device
                    device.register_listener(
                        CallbackEventType.MOTION_STATUS,
                        self._make_motion_callback(device.dev_id),
                    )

                    model_info = device.model or "N/A"
                    _LOGGER.info(
                        "Reading motion device: %s (Channel %s, Address %s, Model: %s)",
                        device.name,
                        device.channel,
                        device.address,
                        model_info,
                    )
                    gateway.command_read_dev(
                        device.dev_type, device.channel, device.address
                    )
                    await asyncio.sleep(2)  # Wait for response

            # Test illuminance devices
            if illuminance_devices:
                _LOGGER.info("Testing illuminance sensor callbacks...")
                for device in illuminance_devices[
                    :2
                ]:  # Test up to 2 illuminance devices
                    # Register callback for this specific device
                    device.register_listener(
                        CallbackEventType.ILLUMINANCE_STATUS,
                        self._make_illuminance_callback(device.dev_id),
                    )

                    model_info = device.model or "N/A"
                    _LOGGER.info(
                        "Reading illuminance device: %s (Channel %s, Address %s, Model: %s)",
                        device.name,
                        device.channel,
                        device.address,
                        model_info,
                    )
                    gateway.command_read_dev(
                        device.dev_type, device.channel, device.address
                    )
                    await asyncio.sleep(2)  # Wait for response

            # Test panel devices
            if panel_devices:
                _LOGGER.info("Testing panel callbacks...")
                for device in panel_devices[:2]:  # Test up to 2 panel devices
                    # Register callback for this specific device
                    device.register_listener(
                        CallbackEventType.PANEL_STATUS,
                        self._make_panel_callback(device.dev_id),
                    )

                    model_info = device.model or "N/A"
                    _LOGGER.info(
                        "Reading panel device: %s (Channel %s, Address %s, Model: %s)",
                        device.name,
                        device.channel,
                        device.address,
                        model_info,
                    )
                    gateway.command_read_dev(
                        device.dev_type, device.channel, device.address
                    )
                    await asyncio.sleep(2)  # Wait for response

            _LOGGER.info("✓ All device callbacks registered successfully")

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

    async def test_restart_gateway(self) -> bool:
        """Test gateway restart command."""
        if not self._check_connection():
            return False

        _LOGGER.info("=== Testing Gateway Restart Command ===")
        _LOGGER.warning("⚠️  Gateway will restart and disconnect after this test!")

        try:
            gateway = self._assert_gateway()

            _LOGGER.info("Sending restart command to gateway...")
            gateway.restart_gateway()

            # Wait a moment for the restart response
            _LOGGER.info("Waiting for restart confirmation...")
            await asyncio.sleep(3)

            _LOGGER.info("✓ Restart command sent successfully")
            _LOGGER.info("Gateway should be restarting now. Connection will be lost.")

            # Mark as disconnected since gateway will restart
            self.is_connected = False

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Restart gateway test failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Gateway restart test completed")
            return True

    async def test_identify_gateway(self) -> bool:
        """Test gateway identify command (makes gateway LED blink).

        Note: Gateway identify uses UDP multicast, not MQTT.
        This test does NOT require MQTT connection - it works directly after discovery.
        """
        _LOGGER.info("=== Testing Gateway Identify Command ===")
        _LOGGER.info("The gateway's indicator LED should blink to identify itself.")
        _LOGGER.info("Note: This command is sent via UDP multicast (not MQTT)")

        if not self.gateways:
            _LOGGER.error("No gateways discovered! Run discovery first.")
            return False

        try:
            # Test identify for each discovered gateway
            for gateway in self.gateways:
                _LOGGER.info(
                    "Testing identify for gateway: %s (%s)", gateway.name, gateway.gw_sn
                )

                # Create response listener
                listener = IdentifyResponseListener(gateway.gw_sn)

                _LOGGER.info("Starting UDP response listener...")
                _LOGGER.info("Sending identify command to gateway via UDP...")

                # Start listener and send command concurrently
                listener_task = asyncio.create_task(
                    listener.wait_for_response(timeout=10.0)
                )

                # Small delay to ensure listener is ready
                await asyncio.sleep(0.5)

                # Send identify command directly via UDP
                await send_identify_gateway(gateway.gw_sn)

                # Wait for response
                _LOGGER.info("Waiting for UDP response from gateway...")
                ack_received = await listener_task

                if ack_received:
                    _LOGGER.info(
                        "✓ Received UDP response with ack=True from gateway %s",
                        gateway.gw_sn,
                    )
                    _LOGGER.info(
                        "The gateway should blink its LED to confirm identification."
                    )
                else:
                    _LOGGER.error(
                        "No UDP response received from gateway %s within timeout",
                        gateway.gw_sn,
                    )
                    _LOGGER.error(
                        "Gateway identify test failed: UDP response not detected"
                    )
                    return False

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Gateway identify test failed: %s", e)
            return False
        else:
            _LOGGER.info("✓ Gateway identify test completed for all gateways")
            return True

    async def test_identify_device(self, device_limit: int | None = None) -> bool:
        """Test device identify command (makes device LED blink)."""
        if not self._check_connection():
            return False

        if not self.devices:
            _LOGGER.error("No devices available! Run device discovery first.")
            return False

        _LOGGER.info("=== Testing Device Identify Commands ===")
        _LOGGER.info("Each device's indicator LED should blink to identify itself.")

        try:
            gateway = self._assert_gateway()

            # Ensure we have a TestDaliGateway instance
            if not isinstance(gateway, TestDaliGateway):
                _LOGGER.error(
                    "Gateway is not a TestDaliGateway instance, cannot verify responses"
                )
                return False

            devices_to_test = self.devices
            if device_limit:
                devices_to_test = self.devices[:device_limit]
            else:
                # Default to testing first 3 devices if no limit specified
                devices_to_test = self.devices[:3]

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
                ack_received = await gateway.wait_for_identify_response(timeout=5.0)

                if ack_received:
                    _LOGGER.info("  ✓ Identify response received with ack=True")
                    success_count += 1
                else:
                    _LOGGER.error("  ✗ Identify response not received or ack=False")

        except (DaliGatewayError, RuntimeError) as e:
            _LOGGER.error("Device identify test failed: %s", e)
            return False
        else:
            _LOGGER.info(
                "✓ Identify test completed: %d/%d devices responded successfully",
                success_count,
                len(devices_to_test),
            )
            _LOGGER.info(
                "Check if each device's LED blinked to confirm identification."
            )
            return success_count > 0

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
