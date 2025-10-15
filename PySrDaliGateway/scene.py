"""Dali Gateway Scene"""

from typing import Protocol

from .helper import gen_scene_unique_id


class SupportsSceneCommands(Protocol):
    """Protocol exposing the minimum gateway interface required by Scene."""

    @property
    def gw_sn(self) -> str:
        raise NotImplementedError

    def command_write_scene(self, scene_id: int, channel: int) -> None:
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
        self._id = scene_id
        self._name = name
        self._channel = channel
        self._area_id = area_id

    def __str__(self) -> str:
        return f"{self._name} (Channel {self._channel}, Scene {self._id})"

    def __repr__(self) -> str:
        return f"Scene(name={self._name}, unique_id={self.unique_id})"

    @property
    def unique_id(self) -> str:
        return gen_scene_unique_id(self._id, self._channel, self._client.gw_sn)

    @property
    def scene_id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def gw_sn(self) -> str:
        return self._client.gw_sn

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def area_id(self) -> str:
        return self._area_id

    def activate(self) -> None:
        self._client.command_write_scene(self._id, self._channel)
