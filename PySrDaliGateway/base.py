"""Base class for DALI Gateway objects."""

from abc import ABC
from typing import Any, Callable, Dict

from .types import CallbackEventType, ListenerCallback


class DaliObjectBase(ABC):
    """Abstract base class for DALI objects (Device, Scene, etc.).

    Subclasses must provide:
    - unique_id: str (as attribute or property)
    - gw_sn: str (as attribute or property)
    - register_listener method
    """

    # These are defined as attributes that subclasses must provide
    # They can be implemented as instance attributes or properties
    unique_id: str
    gw_sn: str

    @staticmethod
    def _create_property(dpid: int, data_type: str, value: Any) -> Dict[str, Any]:
        """Create a property dict for DALI protocol commands."""
        return {"dpid": dpid, "dataType": data_type, "value": value}

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
    ) -> Callable[[], None]:
        """Register a listener for events."""
        raise NotImplementedError
