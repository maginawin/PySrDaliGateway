"""Dali Gateway Group"""

import colorsys
import logging
from typing import Any, Dict, List, Optional, Tuple

from .gateway import DaliGateway
from .helper import gen_group_unique_id
from .types import GroupType

_LOGGER = logging.getLogger(__name__)


class Group:
    """Dali Gateway Group"""

    def __init__(self, gateway: DaliGateway, group: GroupType) -> None:
        self._gateway = gateway
        self._id = group["id"]
        self._name = group["name"]
        self._channel = group["channel"]
        self._area_id = group["area_id"]

    def __str__(self) -> str:
        return f"{self._name} (Channel {self._channel}, Group {self._id})"

    def __repr__(self) -> str:
        return f"Group(name={self._name}, unique_id={self.unique_id})"

    @property
    def group_id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return gen_group_unique_id(self._id, self._channel, self._gateway.gw_sn)

    @property
    def gw_sn(self) -> str:
        return self._gateway.gw_sn

    def _create_property(self, dpid: int, data_type: str, value: Any) -> Dict[str, Any]:
        return {"dpid": dpid, "dataType": data_type, "value": value}

    def _send_properties(self, properties: List[Dict[str, Any]]) -> None:
        for prop in properties:
            self._gateway.command_write_group(self._id, self._channel, [prop])

    def turn_on(
        self,
        brightness: Optional[int] = None,
        color_temp_kelvin: Optional[int] = None,
        rgbw_color: Optional[Tuple[float, float, float, float]] = None,
    ) -> None:
        properties: List[Dict[str, Any]] = [self._create_property(20, "bool", True)]

        if brightness:
            properties.append(self._create_property(22, "uint16", brightness))

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
