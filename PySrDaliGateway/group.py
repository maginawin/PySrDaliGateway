"""Dali Gateway Group"""

import colorsys
import logging
from typing import Any, Dict, List, Protocol, Tuple

from .helper import gen_group_unique_id

_LOGGER = logging.getLogger(__name__)


class SupportsGroupCommands(Protocol):
    """Protocol exposing the minimum gateway interface required by Group."""

    @property
    def gw_sn(self) -> str:
        raise NotImplementedError

    def command_write_group(
        self, group_id: int, channel: int, properties: List[Dict[str, Any]]
    ) -> None:
        raise NotImplementedError


class Group:
    """Dali Gateway Group"""

    def __init__(
        self,
        command_client: SupportsGroupCommands,
        group_id: int,
        name: str,
        channel: int,
        area_id: str,
    ) -> None:
        self._client = command_client
        self._id = group_id
        self._name = name
        self._channel = channel
        self._area_id = area_id

    def __str__(self) -> str:
        return f"{self._name} (Channel {self._channel}, Group {self._id})"

    def __repr__(self) -> str:
        return f"Group(name={self._name}, unique_id={self.unique_id})"

    @property
    def group_id(self) -> int:
        return self._id

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return gen_group_unique_id(self._id, self._channel, self._client.gw_sn)

    @property
    def gw_sn(self) -> str:
        return self._client.gw_sn

    @property
    def area_id(self) -> str:
        return self._area_id

    def _create_property(self, dpid: int, data_type: str, value: Any) -> Dict[str, Any]:
        return {"dpid": dpid, "dataType": data_type, "value": value}

    def _send_properties(self, properties: List[Dict[str, Any]]) -> None:
        for prop in properties:
            self._client.command_write_group(self._id, self._channel, [prop])

    def turn_on(
        self,
        brightness: int | None = None,
        color_temp_kelvin: int | None = None,
        rgbw_color: Tuple[float, float, float, float] | None = None,
    ) -> None:
        properties: List[Dict[str, Any]] = [self._create_property(20, "bool", True)]

        if brightness:
            properties.append(
                self._create_property(22, "uint16", brightness * 1000 / 255)
            )

        if color_temp_kelvin:
            properties.append(self._create_property(23, "uint16", color_temp_kelvin))

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
            "Group %s (%s) turned on with properties: %s",
            self._id,
            self.name,
            properties,
        )

    def turn_off(self) -> None:
        properties: List[Dict[str, Any]] = [self._create_property(20, "bool", False)]
        self._send_properties(properties)
        _LOGGER.debug("Group %s (%s) turned off", self._id, self.name)
