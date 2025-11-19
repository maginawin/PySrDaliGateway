"""Dali Gateway Group"""

import colorsys
import logging
from typing import Any, Callable, Dict, List, Protocol, Tuple

from .helper import gen_group_unique_id
from .types import CallbackEventType, ListenerCallback

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

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
        dev_id: str,
    ) -> Callable[[], None]:
        """Register a listener for a specific event type."""
        raise NotImplementedError

    async def read_group(self, group_id: int, channel: int) -> Dict[str, Any]:
        """Read group information from gateway."""
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
        self.group_id = group_id
        self.name = name
        self.channel = channel
        self.area_id = area_id

    def __str__(self) -> str:
        return f"{self.name} (Channel {self.channel}, Group {self.group_id})"

    def __repr__(self) -> str:
        return f"Group(name={self.name}, unique_id={self.unique_id})"

    @property
    def unique_id(self) -> str:
        """Computed unique identifier for this group."""
        return gen_group_unique_id(self.group_id, self.channel, self._client.gw_sn)

    @property
    def gw_sn(self) -> str:
        """Gateway serial number (delegated from client)."""
        return self._client.gw_sn

    def _create_property(self, dpid: int, data_type: str, value: Any) -> Dict[str, Any]:
        return {"dpid": dpid, "dataType": data_type, "value": value}

    def _send_properties(self, properties: List[Dict[str, Any]]) -> None:
        for prop in properties:
            self._client.command_write_group(self.group_id, self.channel, [prop])

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
            self.group_id,
            self.name,
            properties,
        )

    def turn_off(self) -> None:
        properties: List[Dict[str, Any]] = [self._create_property(20, "bool", False)]
        self._send_properties(properties)
        _LOGGER.debug("Group %s (%s) turned off", self.group_id, self.name)

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
    ) -> Callable[[], None]:
        """Register a listener for this group's events."""
        return self._client.register_listener(event_type, listener, dev_id=self.gw_sn)

    async def read_group(self) -> Dict[str, Any]:
        """Read this group's information from the gateway."""
        return await self._client.read_group(self.group_id, self.channel)
