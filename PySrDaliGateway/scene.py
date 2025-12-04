"""Dali Gateway Scene"""

from typing import Callable, List, Protocol

from .base import DaliObjectBase
from .helper import gen_scene_unique_id
from .types import CallbackEventType, ListenerCallback, SceneDeviceType


class SupportsSceneCommands(Protocol):
    """Protocol exposing the minimum gateway interface required by Scene."""

    @property
    def gw_sn(self) -> str:
        raise NotImplementedError

    def command_write_scene(self, scene_id: int, channel: int) -> None:
        raise NotImplementedError

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
        dev_id: str,
    ) -> Callable[[], None]:
        """Register a listener for a specific event type."""
        raise NotImplementedError


class Scene(DaliObjectBase):
    """Dali Gateway Scene"""

    def __init__(
        self,
        command_client: SupportsSceneCommands,
        scene_id: int,
        name: str,
        channel: int,
        area_id: str,
        devices: List[SceneDeviceType],
    ) -> None:
        self._client = command_client
        self.scene_id = scene_id
        self.name = name
        self.channel = channel
        self.area_id = area_id
        self.devices = devices
        self.unique_id = gen_scene_unique_id(scene_id, channel, command_client.gw_sn)
        self.gw_sn = command_client.gw_sn

    def __str__(self) -> str:
        return f"{self.name} (Channel {self.channel}, Scene {self.scene_id})"

    def __repr__(self) -> str:
        return f"Scene(name={self.name}, unique_id={self.unique_id})"

    def activate(self) -> None:
        self._client.command_write_scene(self.scene_id, self.channel)

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
    ) -> Callable[[], None]:
        """Register a listener for this scene's events."""
        return self._client.register_listener(event_type, listener, dev_id=self.gw_sn)
