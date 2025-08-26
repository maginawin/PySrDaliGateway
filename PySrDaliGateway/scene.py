"""Dali Gateway Scene"""

from .gateway import DaliGateway
from .helper import gen_scene_unique_id
from .types import SceneType


class Scene:
    """Dali Gateway Scene"""

    def __init__(self, gateway: DaliGateway, scene: SceneType) -> None:
        self._gateway = gateway
        self._id = scene["id"]
        self._name = scene["name"]
        self._channel = scene["channel"]
        self._area_id = scene["area_id"]

    def __str__(self) -> str:
        return f"{self._name} (Channel {self._channel}, Scene {self._id})"

    def __repr__(self) -> str:
        return f"Scene(name={self._name}, unique_id={self.unique_id})"

    @property
    def unique_id(self) -> str:
        return gen_scene_unique_id(self._id, self._channel, self._gateway.gw_sn)

    @property
    def scene_id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def gw_sn(self) -> str:
        return self._gateway.gw_sn

    def activate(self) -> None:
        self._gateway.command_write_scene(self._id, self._channel)
