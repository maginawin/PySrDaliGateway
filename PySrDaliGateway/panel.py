"""Dali Gateway Panel Device"""

from typing import Iterable, List

from .const import PANEL_CONFIGS
from .device import Device, SupportsDeviceCommands
from .types import DeviceProperty


class Panel(Device):
    """Dali Gateway Panel Device"""

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
        super().__init__(
            command_client,
            unique_id,
            dev_id,
            name,
            dev_type,
            channel,
            address,
            status,
            dev_sn=dev_sn,
            area_name=area_name,
            area_id=area_id,
            model=model,
            properties=properties,
        )
        self._panel_config = PANEL_CONFIGS.get(
            self._dev_type, {"button_count": 1, "events": ["press"]}
        )

    @property
    def button_count(self) -> int:
        """Get the number of buttons on this panel"""
        return self._panel_config.get("button_count", 1)

    @property
    def supported_events(self) -> List[str]:
        """Get supported events for this panel type"""
        return self._panel_config.get("events", ["press"])

    def get_available_event_types(self) -> List[str]:
        """Generate all possible event types for this panel device"""
        event_types: List[str] = []
        event_types.extend(
            f"button_{button_num}_{event}"
            for button_num in range(1, self.button_count + 1)
            for event in self.supported_events
        )
        return event_types
