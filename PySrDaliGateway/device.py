"""Dali Gateway Device"""

import logging
import colorsys
from typing import Optional, Tuple, Any

from .gateway import DaliGateway
from .types import DeviceType
from .const import COLOR_MODE_MAP

_LOGGER = logging.getLogger(__name__)


class Device:
    """Dali Gateway Device"""

    def __init__(self, gateway: DaliGateway, device: DeviceType) -> None:
        self._gateway = gateway
        self._dev_type = device["dev_type"]
        self._channel = device["channel"]
        self._address = device["address"]
        self._status = device["status"]
        self._dev_sn = device["dev_sn"]
        self._area_name = device["area_name"]
        self._area_id = device["area_id"]
        self._prop = device["prop"]
        self._id = device["id"]
        self._name = device["name"]

    def __repr__(self) -> str:
        return f"Device(name={self._name}, unique_id={self.unique_id})"

    def __str__(self) -> str:
        return self._name

    @property
    def gw_sn(self) -> str:
        return self._gateway.gw_sn

    @property
    def dev_id(self) -> str:
        return self._id

    @property
    def dev_type(self) -> str:
        return self._dev_type

    @property
    def status(self) -> str:
        return self._status

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._id

    @property
    def color_mode(self) -> str:
        return COLOR_MODE_MAP.get(self._dev_type, "brightness")

    def _create_property(self, dpid: int, data_type: str, value: Any) -> dict:
        return {
            "dpid": dpid,
            "dataType": data_type,
            "value": value
        }

    def _send_properties(self, properties: list[dict]) -> None:
        for prop in properties:
            self._gateway.command_write_dev(
                self._dev_type,
                self._channel,
                self._address,
                [prop]
            )

    def turn_on(
        self,
        brightness: Optional[int] = None,
        color_temp_kelvin: Optional[int] = None,
        hs_color: Optional[Tuple[float, float]] = None,
        rgbw_color: Optional[Tuple[float, float, float, float]] = None
    ) -> None:
        properties = [self._create_property(20, "bool", True)]

        if brightness:
            properties.append(
                self._create_property(22, "uint16", brightness * 1000 / 255)
            )

        if color_temp_kelvin:
            properties.append(
                self._create_property(23, "uint16", color_temp_kelvin)
            )

        if hs_color:
            h, s = hs_color
            h_hex = f"{int(h):04x}"
            s_hex = f"{int(s * 1000 / 100):04x}"
            v_hex = f"{1000:04x}"
            properties.append(
                self._create_property(
                    24,
                    "string",
                    f"{h_hex}{s_hex}{v_hex}"
                )
            )

        if rgbw_color:
            r, g, b, w = rgbw_color
            if any([r, g, b]):
                h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
                h_hex = f"{int(h*360):04x}"
                s_hex = f"{int(s*1000):04x}"
                v_hex = f"{int(v*1000):04x}"
                properties.append(
                    self._create_property(
                        24,
                        "string",
                        f"{h_hex}{s_hex}{v_hex}"
                    )
                )

            if w > 0:
                properties.append(
                    self._create_property(21, "uint8", int(w))
                )

        self._send_properties(properties)
        _LOGGER.debug(
            "Device %s (%s) turned on with properties: %s",
            self.dev_id, self.name, properties
        )

    def turn_off(self) -> None:
        properties = [self._create_property(20, "bool", False)]
        self._send_properties(properties)
        _LOGGER.debug("Device %s (%s) turned off", self.dev_id, self.name)

    def read_status(self) -> None:
        self._gateway.command_read_dev(
            self._dev_type,
            self._channel,
            self._address
        )
        _LOGGER.debug(
            "Requesting status for device %s (%s)",
            self.dev_id, self.name
        )

    def press_button(self, button_id: int, event_type: int = 1) -> None:
        properties = [self._create_property(
            button_id,
            "uint8",
            event_type
        )]

        self._send_properties(properties)
        _LOGGER.debug(
            "Button %d pressed on device %s (%s) with event type %d",
            button_id, self.dev_id, self.name, event_type
        )

    def set_sensor_enabled(self, enabled: bool) -> None:
        self._gateway.command_set_sensor_on_off(
            self._dev_type,
            self._channel,
            self._address,
            enabled
        )
        _LOGGER.debug(
            "Sensor %s (%s) enabled state set to %s",
            self.dev_id, self.name, enabled
        )

    def get_sensor_enabled(self) -> None:
        self._gateway.command_get_sensor_on_off(
            self._dev_type,
            self._channel,
            self._address
        )
        _LOGGER.debug(
            "Requesting sensor %s (%s) enabled state",
            self.dev_id, self.name
        )
