"""Dali Gateway Panel Device"""

from typing import List

from .const import PANEL_CONFIGS
from .device import Device
from .gateway import DaliGateway
from .types import DeviceType


class Panel(Device):
    """Dali Gateway Panel Device"""

    def __init__(self, gateway: DaliGateway, device: DeviceType) -> None:
        super().__init__(gateway, device)
        self._panel_config = PANEL_CONFIGS[self._dev_type]

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
