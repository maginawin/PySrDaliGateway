"""Dali Gateway Device"""

import colorsys
import logging
from typing import Any, Callable, Dict, Iterable, List, Protocol, Tuple

from .const import COLOR_MODE_MAP
from .types import CallbackEventType, DeviceProperty, ListenerCallback

_LOGGER = logging.getLogger(__name__)


class SupportsDeviceCommands(Protocol):
    """Protocol exposing the gateway commands needed by Device instances."""

    @property
    def gw_sn(self) -> str:
        raise NotImplementedError

    def command_write_dev(
        self,
        dev_type: str,
        channel: int,
        address: int,
        properties: List[Dict[str, Any]],
    ) -> None:
        raise NotImplementedError

    def command_read_dev(self, dev_type: str, channel: int, address: int) -> None:
        raise NotImplementedError

    def command_get_energy(
        self, dev_type: str, channel: int, address: int, year: int, month: int, day: int
    ) -> None:
        raise NotImplementedError

    def command_set_sensor_on_off(
        self, dev_type: str, channel: int, address: int, value: bool
    ) -> None:
        raise NotImplementedError

    def command_get_sensor_on_off(
        self, dev_type: str, channel: int, address: int
    ) -> None:
        raise NotImplementedError

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
        dev_id: str,
    ) -> Callable[[], None]:
        """Register a listener for a specific event type."""
        raise NotImplementedError


class Device:
    """Dali Gateway Device"""

    def __init__(
        self,
        command_client: SupportsDeviceCommands,
        unique_id: str,
        dev_id: str,
        name: str,
        dev_type: str,
        channel: int,
        address: int,
        status: str,
        *,
        dev_sn: str,
        area_name: str,
        area_id: str,
        model: str,
        properties: Iterable[DeviceProperty] | None = None,
    ) -> None:
        self._client = command_client
        self.unique_id = unique_id
        self.dev_id = dev_id
        self.name = name
        self.dev_type = dev_type
        self.channel = channel
        self.address = address
        self.status = status
        self.dev_sn = dev_sn
        self.area_name = area_name
        self.area_id = area_id
        self.model = model
        self.properties: List[DeviceProperty] = list(properties or [])

    def __repr__(self) -> str:
        return f"Device(name={self.name}, unique_id={self.unique_id})"

    def __str__(self) -> str:
        return self.name

    @property
    def gw_sn(self) -> str:
        """Gateway serial number (delegated from client)."""
        return self._client.gw_sn

    @property
    def color_mode(self) -> str:
        """Computed color mode based on device type."""
        return COLOR_MODE_MAP.get(self.dev_type, "brightness")

    def _create_property(self, dpid: int, data_type: str, value: Any) -> Dict[str, Any]:
        return {"dpid": dpid, "dataType": data_type, "value": value}

    def _send_properties(self, properties: List[Dict[str, Any]]) -> None:
        for prop in properties:
            self._client.command_write_dev(
                self.dev_type, self.channel, self.address, [prop]
            )

    def turn_on(
        self,
        brightness: int | None = None,
        color_temp_kelvin: int | None = None,
        hs_color: Tuple[float, float] | None = None,
        rgbw_color: Tuple[float, float, float, float] | None = None,
    ) -> None:
        properties = [self._create_property(20, "bool", True)]

        if brightness:
            properties.append(
                self._create_property(22, "uint16", brightness * 1000 / 255)
            )

        if color_temp_kelvin:
            properties.append(self._create_property(23, "uint16", color_temp_kelvin))

        if hs_color:
            h, s = hs_color
            h_hex = f"{int(h):04x}"
            s_hex = f"{int(s * 1000 / 100):04x}"
            v_hex = f"{1000:04x}"
            properties.append(
                self._create_property(24, "string", f"{h_hex}{s_hex}{v_hex}")
            )

        if rgbw_color:
            r, g, b, w = rgbw_color
            if any([r, g, b]):
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                h_hex = f"{int(h * 360):04x}"
                s_hex = f"{int(s * 1000):04x}"
                v_hex = f"{int(v * 1000):04x}"
                properties.append(
                    self._create_property(24, "string", f"{h_hex}{s_hex}{v_hex}")
                )

            if w > 0:
                properties.append(self._create_property(21, "uint8", int(w)))

        self._send_properties(properties)
        _LOGGER.debug(
            "Device %s (%s) turned on with properties: %s",
            self.dev_id,
            self.name,
            properties,
        )

    def turn_off(self) -> None:
        properties = [self._create_property(20, "bool", False)]
        self._send_properties(properties)
        _LOGGER.debug("Device %s (%s) turned off", self.dev_id, self.name)

    def read_status(self) -> None:
        self._client.command_read_dev(self.dev_type, self.channel, self.address)
        _LOGGER.debug("Requesting status for device %s (%s)", self.dev_id, self.name)

    def press_button(self, button_id: int, event_type: int = 1) -> None:
        properties = [self._create_property(button_id, "uint8", event_type)]

        self._send_properties(properties)
        _LOGGER.debug(
            "Button %d pressed on device %s (%s) with event type %d",
            button_id,
            self.dev_id,
            self.name,
            event_type,
        )

    def set_sensor_enabled(self, enabled: bool) -> None:
        self._client.command_set_sensor_on_off(
            self.dev_type, self.channel, self.address, enabled
        )
        _LOGGER.debug(
            "Sensor %s (%s) enabled state set to %s",
            self.dev_id,
            self.name,
            enabled,
        )

    def get_sensor_enabled(self) -> None:
        self._client.command_get_sensor_on_off(
            self.dev_type, self.channel, self.address
        )
        _LOGGER.debug(
            "Requesting sensor %s (%s) enabled state",
            self.dev_id,
            self.name,
        )

    def get_energy(self, year: int, month: int, day: int) -> None:
        self._client.command_get_energy(
            self.dev_type,
            self.channel,
            self.address,
            year,
            month,
            day,
        )
        _LOGGER.debug(
            "Requesting energy data for device %s (%s)",
            self.dev_id,
            self.name,
        )

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
    ) -> Callable[[], None]:
        """Register a listener for this device's events."""
        return self._client.register_listener(event_type, listener, dev_id=self.dev_id)


class AllLightsController(Device):
    """Controller for all lights on a gateway using DALI broadcast address."""

    def __init__(
        self,
        command_client: SupportsDeviceCommands,
        devices: Iterable[Device],
    ) -> None:
        """Initialize the all lights controller."""
        super().__init__(
            command_client=command_client,
            unique_id=f"{command_client.gw_sn}_all_lights",
            dev_id=command_client.gw_sn,
            name="All Lights",
            dev_type="FFFF",
            channel=0,
            address=1,
            status="online",
            dev_sn=command_client.gw_sn,
            area_name="",
            area_id="",
            model="All Lights Controller",
            properties=[],
        )
        self.devices = devices
