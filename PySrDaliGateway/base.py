"""Base class for DALI Gateway objects."""

from abc import ABC
from typing import Callable

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

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
    ) -> Callable[[], None]:
        """Register a listener for events."""
        raise NotImplementedError
