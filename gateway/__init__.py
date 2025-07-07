"""Dali Gateway"""

from .__version__ import __version__

import time
import asyncio
import logging
from typing import Any, Optional, Callable
import json
import paho.mqtt.client as paho_mqtt

from .helper import (
    gen_device_unique_id,
    gen_group_unique_id,
    gen_scene_unique_id,
    gen_device_name
)
from .types import SceneType, GroupType, DeviceType, DaliGatewayType
from .device import Device
from .group import Group
from .scene import Scene

_LOGGER = logging.getLogger(__name__)


class DaliGateway:
    """Dali Gateway"""

    def __init__(self, gateway: DaliGatewayType) -> None:

        # Gateway information
        self._gw_sn = gateway["gw_sn"]
        self._gw_ip = gateway["gw_ip"]
        self._port = gateway["port"]
        self._name = gateway["name"]
        self._username = gateway["username"]
        self._passwd = gateway["passwd"]
        self._channel_total = gateway["channel_total"]

        # MQTT topics
        self._sub_topic = f"/{self._gw_sn}/client/reciver/"
        self._pub_topic = f"/{self._gw_sn}/server/publish/"

        # MQTT client
        self._mqtt_client = paho_mqtt.Client(
            client_id=f"ha_dali_center_{self._gw_sn}"
        )

        # Connection result
        self._connect_result: Optional[int] = None
        self._connection_event = asyncio.Event()

        # Set up client callbacks
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message

        # Scene/Group/Device Received
        self._scenes_received = asyncio.Event()
        self._groups_received = asyncio.Event()
        self._devices_received = asyncio.Event()

        self._scenes_result: list[SceneType] = []
        self._groups_result: list[GroupType] = []
        self._devices_result: list[DeviceType] = []

        # Callbacks
        self._on_online_status: Optional[Callable[[str, bool], None]] = None
        self._on_device_status: Optional[Callable[[str, list], None]] = None
        self._on_energy_report: Optional[Callable[[str, float], None]] = None

    def to_dict(self) -> DaliGatewayType:
        """Convert DaliGateway to dictionary"""
        return {
            "gw_sn": self._gw_sn,
            "gw_ip": self._gw_ip,
            "port": self._port,
            "name": self._name,
            "username": self._username,
            "passwd": self._passwd,
            "channel_total": self._channel_total
        }

    def __repr__(self) -> str:
        return (
            f"DaliGateway(gw_sn={self._gw_sn}, gw_ip={self._gw_ip}, "
            f"port={self._port}, name={self._name})"
        )

    @property
    def gw_sn(self) -> str:
        return self._gw_sn

    @property
    def name(self) -> str:
        return self._name

    @property
    def on_online_status(self) -> Optional[Callable[[str, bool], None]]:
        return self._on_online_status

    @on_online_status.setter
    def on_online_status(self, callback: Callable[[str, bool], None]) -> None:
        self._on_online_status = callback

    @property
    def on_device_status(self) -> Optional[Callable[[str, list], None]]:
        return self._on_device_status

    @on_device_status.setter
    def on_device_status(self, callback: Callable[[str, list], None]) -> None:
        self._on_device_status = callback

    @property
    def on_energy_report(self) -> Optional[Callable[[str, float], None]]:
        return self._on_energy_report

    @on_energy_report.setter
    def on_energy_report(self, callback: Callable[[str, float], None]) -> None:
        self._on_energy_report = callback

    def _on_connect(
        self, client: paho_mqtt.Client,
        userdata: Any, flags: Any, rc: int
    ) -> None:
        # pylint: disable=unused-argument
        self._connect_result = rc
        self._connection_event.set()

        if rc == 0:
            _LOGGER.debug(
                "Connected to MQTT broker successfully %s:%s",
                self._gw_ip, self._port
            )
            self._mqtt_client.subscribe(self._sub_topic)
            _LOGGER.debug("Subscribed to topic: %s", self._sub_topic)
        else:
            _LOGGER.error("Failed to connect to MQTT broker: %s", rc)

    def _on_disconnect(
        self, client: paho_mqtt.Client,
        userdata: Any, rc: int
    ) -> None:
        # pylint: disable=unused-argument
        if rc != 0:
            _LOGGER.warning("Unexpected MQTT disconnection: %s", rc)

    def _on_message(
        self, client: paho_mqtt.Client,
        userdata: Any, msg: paho_mqtt.MQTTMessage
    ) -> None:
        # pylint: disable=unused-argument
        try:
            payload_json = json.loads(msg.payload.decode())
            _LOGGER.debug(
                "Received MQTT message on topic %s: %s",
                msg.topic, payload_json
            )

            cmd = payload_json.get("cmd")
            if not cmd:
                _LOGGER.debug(
                    "Received MQTT message without cmd: %s", msg.payload)
                return

            command_handlers = {
                "devStatus": self._process_device_status,
                "readDevRes": self._process_device_status,
                "writeDevRes": self._process_write_response,
                "writeGroupRes": self._process_write_response,
                "writeSceneRes": self._process_write_response,
                "onlineStatus": self._process_online_status,
                "reportEnergy": self._process_energy_report,
                "searchDevRes": self._process_search_device_response,
                "getSceneRes": self._process_get_scene_response,
                "getGroupRes": self._process_get_group_response,
            }

            handler = command_handlers.get(cmd)
            if handler:
                handler(payload_json)
            else:
                _LOGGER.debug(
                    "Unhandled MQTT command %s, payload: %s",
                    cmd, payload_json
                )

        except json.JSONDecodeError:
            _LOGGER.error("Failed to decode MQTT message payload")
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error processing MQTT message: %s", str(e))

    def _process_online_status(self, payload: dict) -> None:
        data_list = payload.get("data")
        if not data_list:
            _LOGGER.warning("Received onlineStatus with no data: %s", payload)
            return

        for data in data_list:
            dev_id = gen_device_unique_id(
                data.get("devType"),
                data.get("channel"),
                data.get("address"),
                self._gw_sn
            )

            available: bool = data.get("status", False)

            if self._on_online_status:
                self._on_online_status(dev_id, available)

    def _process_device_status(self, payload: dict) -> None:
        data = payload.get("data")
        if not data:
            _LOGGER.warning("Received devStatus with no data: %s", payload)
            return

        dev_id = gen_device_unique_id(
            data.get("devType"),
            data.get("channel"),
            data.get("address"),
            self._gw_sn
        )

        if not dev_id:
            _LOGGER.warning("Failed to generate device ID from data: %s", data)
            return

        property_list = data.get("property", [])
        if self._on_device_status:
            self._on_device_status(dev_id, property_list)

    def _process_write_response(self, payload: dict) -> None:
        msg_id = payload.get("msgId")
        ack = payload.get("ack", False)

        _LOGGER.debug(
            "Received write device response, msgId: %s, ack: %s, payload: %s",
            msg_id, ack, payload
        )

    def _process_energy_report(self, payload: dict) -> None:
        data = payload.get("data")
        if not data:
            _LOGGER.warning("Received reportEnergy with no data: %s", payload)
            return

        dev_id = gen_device_unique_id(
            data.get("devType"),
            data.get("channel"),
            data.get("address"),
            self._gw_sn
        )

        if not dev_id:
            _LOGGER.warning("Failed to generate device ID from data: %s", data)
            return

        property_list = data.get("property", [])
        for prop in property_list:
            if prop.get("dpid") == 30:
                try:
                    energy_value = float(prop.get("value", "0"))

                    if self._on_energy_report:
                        self._on_energy_report(dev_id, energy_value)
                except (ValueError, TypeError) as e:
                    _LOGGER.error(
                        "Error converting energy value: %s", str(e)
                    )

    def _process_search_device_response(self, payload_json: dict) -> None:
        for raw_device_data in payload_json["data"]:

            device = DeviceType(
                dev_type=raw_device_data.get("devType", ""),
                channel=raw_device_data.get("channel", 0),
                address=raw_device_data.get("address", 0),
                status=raw_device_data.get("status", ""),
                name=raw_device_data.get("name") or gen_device_name(
                    raw_device_data.get("devType", ""),
                    raw_device_data.get("channel", 0),
                    raw_device_data.get("address", 0)
                ),
                dev_sn=raw_device_data.get("devSn", ""),
                area_name=raw_device_data.get("areaName", ""),
                area_id=raw_device_data.get("areaId", ""),
                prop=[],
                id=raw_device_data.get("devId") or gen_device_unique_id(
                    raw_device_data.get("devType", ""),
                    raw_device_data.get("channel", 0),
                    raw_device_data.get("address", 0),
                    self._gw_sn
                ),
                unique_id=gen_device_unique_id(
                    raw_device_data.get("devType", ""),
                    raw_device_data.get("channel", 0),
                    raw_device_data.get("address", 0),
                    self._gw_sn
                )
            )

            if device not in self._devices_result:
                self._devices_result.append(device)

        self._devices_received.set()

    def _process_get_scene_response(self, payload_json: dict) -> None:
        for channel_scenes in payload_json["scene"]:
            channel = channel_scenes.get("channel", 0)

            if "data" not in channel_scenes:
                continue

            self._scenes_result.clear()
            for scene_data in channel_scenes["data"]:
                scene = SceneType(
                    channel=channel,
                    id=scene_data.get("sceneId", 0),
                    name=scene_data.get("name", ""),
                    area_id=scene_data.get("areaId", ""),
                    unique_id=gen_scene_unique_id(
                        scene_data.get("sceneId", 0),
                        channel,
                        self._gw_sn
                    )
                )

                if scene not in self._scenes_result:
                    self._scenes_result.append(scene)

        self._scenes_received.set()

    def _process_get_group_response(self, payload_json: dict) -> None:
        for channel_groups in payload_json["group"]:
            channel = channel_groups.get("channel", 0)

            if "data" not in channel_groups:
                continue

            self._groups_result.clear()
            for group_data in channel_groups["data"]:
                group = GroupType(
                    id=group_data.get("groupId", 0),
                    name=group_data.get("name", ""),
                    channel=channel,
                    area_id=group_data.get("areaId", ""),
                    unique_id=gen_group_unique_id(
                        group_data.get("groupId", 0),
                        channel,
                        self._gw_sn
                    )
                )

                if group not in self._groups_result:
                    self._groups_result.append(group)

        self._groups_received.set()


    def get_credentials(self) -> tuple[str, str]:
        return self._username, self._passwd

    async def connect(self) -> bool:
        self._connection_event.clear()
        self._connect_result = None
        self._mqtt_client.username_pw_set(
            self._username, self._passwd
        )

        try:
            self._mqtt_client.connect(
                self._gw_ip, self._port
            )
            self._mqtt_client.loop_start()
            await asyncio.wait_for(self._connection_event.wait(), timeout=10)

            if self._connect_result == 0:
                return True
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as err:
            _LOGGER.error("Failed to connect to MQTT broker: %s", str(err))
            return False

        # Connection failed - log error and return False
        if self._connect_result in (4, 5):
            _LOGGER.error(
                "Connection failed due to authentication error (code %s). "
                "Please press the gateway button and retry the connection",
                self._connect_result
            )
        else:
            _LOGGER.error(
                "Connection failed with result code %s. "
                "Please check network connectivity and gateway status",
                self._connect_result
            )
        return False

    async def disconnect(self) -> bool:
        try:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            self._connection_event.clear()
            _LOGGER.debug("Disconnected from MQTT broker")
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error during disconnect: %s", exc)
            return False

    async def discover_devices(self) -> list[DeviceType]:
        self._devices_received = asyncio.Event()
        search_payload = {
            "cmd": "searchDev",
            "searchFlag": "exited",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn
        }

        _LOGGER.debug("Sending search devices command: %s", search_payload)
        self._mqtt_client.publish(self._pub_topic, json.dumps(search_payload))

        try:
            await asyncio.wait_for(self._devices_received.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for devices list")

        _LOGGER.info(
            "Device search completed, found %d devices", len(
                self._devices_result)
        )
        return self._devices_result

    async def discover_groups(self) -> list[GroupType]:
        self._groups_received = asyncio.Event()
        search_payload = {
            "cmd": "getGroup",
            "msgId": str(int(time.time())),
            "getFlag": "exited",
            "gwSn": self._gw_sn
        }

        _LOGGER.debug("Sending search groups command: %s", search_payload)
        self._mqtt_client.publish(self._pub_topic, json.dumps(search_payload))

        try:
            await asyncio.wait_for(self._groups_received.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for groups list")

        _LOGGER.info(
            "Group search completed, found %d groups", len(self._groups_result)
        )
        return self._groups_result

    async def discover_scenes(self) -> list[SceneType]:
        self._scenes_received = asyncio.Event()
        search_payload = {
            "cmd": "getScene",
            "msgId": str(int(time.time())),
            "getFlag": "exited",
            "gwSn": self._gw_sn
        }

        _LOGGER.debug("Sending search scenes command: %s", search_payload)
        self._mqtt_client.publish(self._pub_topic, json.dumps(search_payload))

        try:
            await asyncio.wait_for(self._scenes_received.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for scenes list")

        _LOGGER.info(
            "Scene search completed, found %d scenes", len(self._scenes_result)
        )
        return self._scenes_result

    def command_write_dev(
        self, dev_type: str, channel: int,
        address: int, properties: list
    ) -> None:
        command = {
            "cmd": "writeDev",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "data": [{
                "devType": dev_type,
                "channel": channel,
                "address": address,
                "property": properties
            }]
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_read_dev(
        self, dev_type: str, channel: int,
        address: int
    ) -> None:
        command = {
            "cmd": "readDev",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "data": [{
                "devType": dev_type,
                "channel": channel,
                "address": address,
            }]
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_write_group(
        self, group_id: int, channel: int,
        properties: list
    ) -> None:
        command = {
            "cmd": "writeGroup",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "channel": channel,
            "groupId": group_id,
            "data": properties
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_write_scene(
        self, scene_id: int, channel: int
    ) -> None:
        command = {
            "cmd": "writeScene",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "channel": channel,
            "sceneId": scene_id
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)


__all__ = [
    "__version__",
    "DaliGateway",
    "Device",
    "Group",
    "Scene",
    "DeviceType",
    "GroupType",
    "SceneType",
    "DaliGatewayType",
]
