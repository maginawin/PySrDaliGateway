"""Dali Gateway Scene"""

from typing import Any, Callable, Dict, Protocol

from .helper import gen_scene_unique_id
from .types import CallbackEventType, ListenerCallback


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

    async def read_scene(self, scene_id: int, channel: int) -> Dict[str, Any]:
        """Read scene information from gateway."""
        raise NotImplementedError


class Scene:
    """Dali Gateway Scene"""

    def __init__(
        self,
        command_client: SupportsSceneCommands,
        scene_id: int,
        name: str,
        channel: int,
        area_id: str,
    ) -> None:
        self._client = command_client
        self.scene_id = scene_id
        self.name = name
        self.channel = channel
        self.area_id = area_id

    def __str__(self) -> str:
        return f"{self.name} (Channel {self.channel}, Scene {self.scene_id})"

    def __repr__(self) -> str:
        return f"Scene(name={self.name}, unique_id={self.unique_id})"

    @property
    def unique_id(self) -> str:
        """Computed unique identifier for this scene."""
        return gen_scene_unique_id(self.scene_id, self.channel, self._client.gw_sn)

    @property
    def gw_sn(self) -> str:
        """Gateway serial number (delegated from client)."""
        return self._client.gw_sn

    def activate(self) -> None:
        self._client.command_write_scene(self.scene_id, self.channel)

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: ListenerCallback,
    ) -> Callable[[], None]:
        """Register a listener for this scene's events."""
        return self._client.register_listener(event_type, listener, dev_id=self.gw_sn)

    async def read_scene(self) -> Dict[str, Any]:
        """Read this scene's information from the gateway."""
        return await self._client.read_scene(self.scene_id, self.channel)
