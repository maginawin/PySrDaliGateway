"""Dali Gateway"""

import asyncio
import json
import logging
import ssl
import time
from typing import Any, Callable, Dict, List, Sequence

import paho.mqtt.client as paho_mqtt

# Backward compatibility with paho-mqtt < 2.0.0
try:
    from paho.mqtt.enums import CallbackAPIVersion

    HAS_CALLBACK_API_VERSION = True
except ImportError:
    # paho-mqtt < 2.0.0 doesn't have CallbackAPIVersion
    HAS_CALLBACK_API_VERSION = False  # pyright: ignore[reportConstantRedefinition]

from .const import CA_CERT_PATH, DEVICE_MODEL_MAP
from .device import Device
from .exceptions import DaliGatewayError
from .group import Group
from .helper import (
    gen_device_name,
    gen_device_unique_id,
    gen_group_unique_id,
    gen_scene_unique_id,
    is_illuminance_sensor,
    is_light_device,
    is_motion_sensor,
    is_panel_device,
    parse_illuminance_status,
    parse_light_status,
    parse_motion_status,
    parse_panel_status,
)
from .scene import Scene
from .types import (
    DeviceParamType,
    IlluminanceStatus,
    LightStatus,
    MotionStatus,
    PanelStatus,
    SceneDeviceType,
    VersionType,
)

_LOGGER = logging.getLogger(__name__)


class DaliGateway:
    """Dali Gateway"""

    def __init__(
        self,
        gw_sn: str,
        gw_ip: str,
        port: int,
        username: str,
        passwd: str,
        *,
        name: str | None = None,
        channel_total: Sequence[int] | None = None,
        is_tls: bool = False,
    ) -> None:
        # Gateway information
        self._gw_sn = gw_sn
        self._gw_ip = gw_ip
        self._port = port
        self._name = name or gw_sn
        self._username = username
        self._passwd = passwd
        self._is_tls = is_tls
        self._channel_total = (
            [int(ch) for ch in channel_total] if channel_total else [0]
        )

        # MQTT topics
        self._sub_topic = f"/{self._gw_sn}/client/reciver/"
        self._pub_topic = f"/{self._gw_sn}/server/publish/"

        # MQTT client - handle compatibility between paho-mqtt versions
        if HAS_CALLBACK_API_VERSION:
            # paho-mqtt >= 2.0.0
            self._mqtt_client = paho_mqtt.Client(
                CallbackAPIVersion.VERSION2,  # pyright: ignore[reportPossiblyUnboundVariable]
                client_id=f"ha_dali_center_{self._gw_sn}",
                protocol=paho_mqtt.MQTTv311,
            )
        else:
            # paho-mqtt < 2.0.0
            self._mqtt_client = paho_mqtt.Client(
                client_id=f"ha_dali_center_{self._gw_sn}",
                protocol=paho_mqtt.MQTTv311,
            )

        self._mqtt_client.enable_logger()

        # Connection result
        self._connect_result: int | None = None
        self._connection_event = asyncio.Event()

        # Set up client callbacks
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message

        # Scene/Group/Device Received
        self._scenes_received = asyncio.Event()
        self._groups_received = asyncio.Event()
        self._devices_received = asyncio.Event()
        self._version_received = asyncio.Event()

        self._scenes_result: list[Scene] = []
        self._groups_result: list[Group] = []
        self._devices_result: list[Device] = []
        self._version_result: VersionType | None = None
        self._read_group_received = asyncio.Event()
        self._read_group_result: Dict[str, Any] | None = None
        self._read_scene_received = asyncio.Event()
        self._read_scene_result: Dict[str, Any] | None = None

        # Callbacks
        self._on_online_status: Callable[[str, bool], None] | None = None
        self._on_light_status: Callable[[str, LightStatus], None] | None = None
        self._on_motion_status: Callable[[str, MotionStatus], None] | None = None
        self._on_illuminance_status: Callable[[str, IlluminanceStatus], None] | None = (
            None
        )
        self._on_panel_status: Callable[[str, PanelStatus], None] | None = None
        self._on_energy_report: Callable[[str, float], None] | None = None
        self._on_sensor_on_off: Callable[[str, bool], None] | None = None
        self._on_energy: Callable[[str, Dict[str, Any]], None] | None = None

        self._window_ms = 100
        self._pending_requests: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._batch_timer: Dict[str, asyncio.TimerHandle] = {}  # cmd -> timer

    def _get_device_key(self, dev_type: str, channel: int, address: int) -> str:
        return f"{dev_type}_{channel}_{address}"

    def add_request(
        self, cmd: str, dev_type: str, channel: int, address: int, data: Dict[str, Any]
    ) -> None:
        if cmd not in self._pending_requests:
            self._pending_requests[cmd] = {}

        device_key = self._get_device_key(dev_type, channel, address)

        # Merge properties instead of overwriting the entire data
        if device_key in self._pending_requests[cmd]:
            existing_data = self._pending_requests[cmd][device_key]
            if "property" in existing_data and "property" in data:
                # Merge properties, avoiding duplicates by dpid
                existing_properties = {
                    prop["dpid"]: prop for prop in existing_data["property"]
                }
                new_properties = {prop["dpid"]: prop for prop in data["property"]}
                existing_properties.update(new_properties)
                data["property"] = list(existing_properties.values())

        self._pending_requests[cmd][device_key] = data

        if self._batch_timer.get(cmd) is None:
            self._batch_timer[cmd] = asyncio.get_event_loop().call_later(
                self._window_ms / 1000.0, self._flush_batch, cmd
            )

    def _flush_batch(self, cmd: str) -> None:
        if not self._pending_requests.get(cmd):
            return

        batch_data: List[Dict[str, Any]] = list(self._pending_requests[cmd].values())

        command: Dict[str, Any] = {
            "cmd": cmd,
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "data": batch_data,
        }

        self._mqtt_client.publish(self._pub_topic, json.dumps(command))

        _LOGGER.debug(
            "Gateway %s: Sent batch %s %s", self._gw_sn, cmd, json.dumps(command)
        )

        self._pending_requests[cmd].clear()
        self._batch_timer.pop(cmd)

    def __repr__(self) -> str:
        return (
            f"DaliGateway(gw_sn={self._gw_sn}, gw_ip={self._gw_ip}, "
            f"port={self._port}, name={self._name})"
        )

    @property
    def gw_sn(self) -> str:
        return self._gw_sn

    @property
    def gw_ip(self) -> str:
        return self._gw_ip

    @property
    def port(self) -> int:
        return self._port

    @property
    def username(self) -> str:
        return self._username

    @property
    def passwd(self) -> str:
        return self._passwd

    @property
    def channel_total(self) -> List[int]:
        return list(self._channel_total)

    @property
    def is_tls(self) -> bool:
        return self._is_tls

    @property
    def name(self) -> str:
        return self._name

    @property
    def on_online_status(self) -> Callable[[str, bool], None] | None:
        return self._on_online_status

    @on_online_status.setter
    def on_online_status(self, callback: Callable[[str, bool], None]) -> None:
        self._on_online_status = callback

    @property
    def on_light_status(self) -> Callable[[str, LightStatus], None] | None:
        return self._on_light_status

    @on_light_status.setter
    def on_light_status(self, callback: Callable[[str, LightStatus], None]) -> None:
        self._on_light_status = callback

    @property
    def on_motion_status(self) -> Callable[[str, MotionStatus], None] | None:
        return self._on_motion_status

    @on_motion_status.setter
    def on_motion_status(self, callback: Callable[[str, MotionStatus], None]) -> None:
        self._on_motion_status = callback

    @property
    def on_illuminance_status(
        self,
    ) -> Callable[[str, IlluminanceStatus], None] | None:
        return self._on_illuminance_status

    @on_illuminance_status.setter
    def on_illuminance_status(
        self, callback: Callable[[str, IlluminanceStatus], None]
    ) -> None:
        self._on_illuminance_status = callback

    @property
    def on_panel_status(self) -> Callable[[str, PanelStatus], None] | None:
        return self._on_panel_status

    @on_panel_status.setter
    def on_panel_status(self, callback: Callable[[str, PanelStatus], None]) -> None:
        self._on_panel_status = callback

    @property
    def on_energy_report(self) -> Callable[[str, float], None] | None:
        return self._on_energy_report

    @on_energy_report.setter
    def on_energy_report(self, callback: Callable[[str, float], None]) -> None:
        self._on_energy_report = callback

    @property
    def on_sensor_on_off(self) -> Callable[[str, bool], None] | None:
        return self._on_sensor_on_off

    @on_sensor_on_off.setter
    def on_sensor_on_off(self, callback: Callable[[str, bool], None]) -> None:
        self._on_sensor_on_off = callback

    @property
    def on_energy(self) -> Callable[[str, Dict[str, Any]], None] | None:
        return self._on_energy

    @on_energy.setter
    def on_energy(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        self._on_energy = callback

    def _on_connect(
        self,
        client: paho_mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: int,
        properties: Any = None,
    ) -> None:
        self._connect_result = rc
        self._connection_event.set()

        if rc == 0:
            _LOGGER.debug(
                "Gateway %s: MQTT connection established to %s:%s",
                self._gw_sn,
                self._gw_ip,
                self._port,
            )
            self._mqtt_client.subscribe(self._sub_topic)
            _LOGGER.debug(
                "Gateway %s: Subscribed to MQTT topic %s", self._gw_sn, self._sub_topic
            )

            # Trigger online_status callback with gateway SN as device ID and True status
            if self._on_online_status:
                self._on_online_status(self._gw_sn, True)
        else:
            _LOGGER.error(
                "Gateway %s: MQTT connection failed with code %s", self._gw_sn, rc
            )

    def _on_disconnect(
        self,
        client: paho_mqtt.Client,
        userdata: Any,
        *args: Any,
    ) -> None:
        # Handle different paho-mqtt versions:
        # v1.6.x: (client, userdata, rc)
        # v2.0.0+: (client, userdata, disconnect_flags, reason_code, properties)
        if HAS_CALLBACK_API_VERSION and len(args) >= 2:
            # paho-mqtt >= 2.0.0
            reason_code = args[1]  # disconnect_flags, reason_code, properties
        elif len(args) >= 1:
            # paho-mqtt < 2.0.0
            reason_code = args[0]  # rc
        else:
            reason_code = 0

        if reason_code != 0:
            _LOGGER.warning(
                "Gateway %s: Unexpected MQTT disconnection (%s:%s) - Reason code: %s",
                self._gw_sn,
                self._gw_ip,
                self._port,
                reason_code,
            )
        else:
            _LOGGER.debug("Gateway %s: MQTT disconnection completed", self._gw_sn)

        # Trigger online_status callback with gateway SN as device ID and False status
        if self._on_online_status:
            self._on_online_status(self._gw_sn, False)

    def _on_message(
        self, client: paho_mqtt.Client, userdata: Any, msg: paho_mqtt.MQTTMessage
    ) -> None:
        try:
            payload_json = json.loads(msg.payload.decode("utf-8", errors="replace"))
            _LOGGER.debug(
                "Gateway %s: Received MQTT message on topic %s: %s",
                self._gw_sn,
                msg.topic,
                payload_json,
            )

            cmd = payload_json.get("cmd")
            if not cmd:
                _LOGGER.warning(
                    "Gateway %s: Received MQTT message without cmd field", self._gw_sn
                )
                return

            command_handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {
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
                "getVersionRes": self._process_get_version_response,
                "readGroupRes": self._process_read_group_response,
                "readSceneRes": self._process_read_scene_response,
                "restartGatewayRes": self._process_restart_gateway_response,
                "getEnergyRes": self._process_get_energy_response,
                "setSensorOnOffRes": self._process_set_sensor_on_off_response,
                "getSensorOnOffRes": self._process_get_sensor_on_off_response,
                "setDevParamRes": self._process_write_response,
                "getDevParamRes": self._process_get_dev_param_response,
            }

            handler = command_handlers.get(cmd)
            if handler:
                handler(payload_json)
            else:
                _LOGGER.debug(
                    "Gateway %s: Unhandled MQTT command '%s', payload: %s",
                    self._gw_sn,
                    cmd,
                    payload_json,
                )

        except json.JSONDecodeError:
            _LOGGER.error(
                "Gateway %s: Failed to decode MQTT message payload: %s",
                self._gw_sn,
                msg.payload,
            )
        except (ValueError, KeyError, TypeError) as e:
            _LOGGER.error(
                "Gateway %s: Error processing MQTT message: %s", self._gw_sn, str(e)
            )

    def _process_online_status(self, payload: Dict[str, Any]) -> None:
        data_list = payload.get("data")
        if not data_list:
            _LOGGER.warning(
                "Gateway %s: Received onlineStatus with no data: %s",
                self._gw_sn,
                payload,
            )
            return

        for data in data_list:
            dev_id = gen_device_unique_id(
                data.get("devType"),
                data.get("channel"),
                data.get("address"),
                self._gw_sn,
            )

            available: bool = data.get("status", False)

            if self._on_online_status:
                self._on_online_status(dev_id, available)

    def _process_device_status(self, payload: Dict[str, Any]) -> None:
        data = payload.get("data")
        if not data:
            _LOGGER.warning(
                "Gateway %s: Received devStatus with no data: %s", self._gw_sn, payload
            )
            return

        dev_id = gen_device_unique_id(
            data.get("devType"), data.get("channel"), data.get("address"), self._gw_sn
        )

        if not dev_id:
            _LOGGER.warning("Failed to generate device ID from data: %s", data)
            return

        property_list = data.get("property", [])
        dev_type = data.get("devType")

        if dev_type and is_light_device(dev_type) and self._on_light_status:
            light_status = parse_light_status(property_list)
            self._on_light_status(dev_id, light_status)
        elif dev_type and is_motion_sensor(dev_type) and self._on_motion_status:
            motion_statuses = parse_motion_status(property_list)
            for motion_status in motion_statuses:
                self._on_motion_status(dev_id, motion_status)
        elif (
            dev_type and is_illuminance_sensor(dev_type) and self._on_illuminance_status
        ):
            illuminance_statuses = parse_illuminance_status(property_list)
            for illuminance_status in illuminance_statuses:
                self._on_illuminance_status(dev_id, illuminance_status)
        elif dev_type and is_panel_device(dev_type) and self._on_panel_status:
            panel_statuses = parse_panel_status(property_list)
            for panel_status in panel_statuses:
                self._on_panel_status(dev_id, panel_status)
        else:
            # Warn if no callback handler exists for this device type
            _LOGGER.warning(
                "Gateway %s: No callback handler for device type %s (device: %s). "
                "Property data: %s",
                self._gw_sn,
                dev_type,
                dev_id,
                property_list,
            )

    def _process_write_response(self, payload: Dict[str, Any]) -> None:
        msg_id = payload.get("msgId")
        ack = payload.get("ack", False)

        _LOGGER.debug(
            "Gateway %s: Received write device response, "
            "msgId: %s, ack: %s, payload: %s",
            self._gw_sn,
            msg_id,
            ack,
            payload,
        )

    def _process_energy_report(self, payload: Dict[str, Any]) -> None:
        data = payload.get("data")
        if not data:
            _LOGGER.warning(
                "Gateway %s: Received reportEnergy with no data: %s",
                self._gw_sn,
                payload,
            )
            return

        dev_id = gen_device_unique_id(
            data.get("devType"), data.get("channel"), data.get("address"), self._gw_sn
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
                    _LOGGER.error("Error converting energy value: %s", str(e))

    def _process_get_version_response(self, payload_json: Dict[str, Any]) -> None:
        self._version_result = VersionType(
            software=payload_json.get("data", {}).get("swVersion", ""),
            firmware=payload_json.get("data", {}).get("fwVersion", ""),
        )
        self._version_received.set()

    def _process_get_energy_response(self, payload_json: Dict[str, Any]) -> None:
        data_list = payload_json.get("data")
        if not data_list:
            _LOGGER.warning(
                "Gateway %s: Received getEnergyRes with no data: %s",
                self._gw_sn,
                payload_json,
            )
            return

        for data in data_list:
            dev_id = gen_device_unique_id(
                data.get("devType"),
                data.get("channel"),
                data.get("address"),
                self._gw_sn,
            )

            if not dev_id:
                _LOGGER.warning("Failed to generate device ID from data: %s", data)
                continue

            energy_data = {
                "yearEnergy": data.get("yearEnergy", {}),
                "monthEnergy": data.get("monthEnergy", {}),
                "dayEnergy": data.get("dayEnergy", {}),
                "hourEnergy": data.get("hourEnergy", []),
            }

            if self._on_energy:
                self._on_energy(dev_id, energy_data)

    def _process_search_device_response(self, payload_json: Dict[str, Any]) -> None:
        for raw_device_data in payload_json.get("data", []):
            dev_type = str(raw_device_data.get("devType", ""))
            channel = int(raw_device_data.get("channel", 0))
            address = int(raw_device_data.get("address", 0))

            unique_id = gen_device_unique_id(dev_type, channel, address, self._gw_sn)
            dev_id = str(raw_device_data.get("devId") or unique_id)
            name = str(
                raw_device_data.get("name")
                or gen_device_name(dev_type, channel, address)
            )

            device = Device(
                self,
                unique_id=unique_id,
                dev_id=dev_id,
                name=name,
                dev_type=dev_type,
                channel=channel,
                address=address,
                status=str(raw_device_data.get("status", "")),
                dev_sn=str(raw_device_data.get("devSn", "")),
                area_name=str(raw_device_data.get("areaName", "")),
                area_id=str(raw_device_data.get("areaId", "")),
                model=DEVICE_MODEL_MAP.get(dev_type, "Unknown"),
                properties=[],
            )

            if not any(
                existing.unique_id == device.unique_id
                for existing in self._devices_result
            ):
                self._devices_result.append(device)

        search_status = payload_json.get("searchStatus")
        if search_status in {0, 1}:
            self._devices_received.set()

    def _process_get_scene_response(self, payload_json: Dict[str, Any]) -> None:
        self._scenes_result.clear()
        for channel_scenes in payload_json.get("scene", []):
            channel = channel_scenes.get("channel", 0)

            for scene_data in channel_scenes.get("data", []):
                scene_id = int(scene_data.get("sceneId", 0))
                name = str(scene_data.get("name", ""))
                area_id = str(scene_data.get("areaId", ""))

                if any(
                    existing.unique_id
                    == gen_scene_unique_id(scene_id, channel, self._gw_sn)
                    for existing in self._scenes_result
                ):
                    continue

                self._scenes_result.append(
                    Scene(
                        self,
                        scene_id=scene_id,
                        name=name,
                        channel=channel,
                        area_id=area_id,
                    )
                )

        self._scenes_received.set()

    def _process_get_group_response(self, payload_json: Dict[str, Any]) -> None:
        self._groups_result.clear()
        for channel_groups in payload_json.get("group", []):
            channel = channel_groups.get("channel", 0)

            for group_data in channel_groups.get("data", []):
                group_id = int(group_data.get("groupId", 0))
                name = str(group_data.get("name", ""))
                area_id = str(group_data.get("areaId", ""))

                if any(
                    existing.unique_id
                    == gen_group_unique_id(group_id, channel, self._gw_sn)
                    for existing in self._groups_result
                ):
                    continue

                self._groups_result.append(
                    Group(
                        self,
                        group_id=group_id,
                        name=name,
                        channel=channel,
                        area_id=area_id,
                    )
                )

        self._groups_received.set()

    def _process_read_group_response(self, payload: Dict[str, Any]) -> None:
        group_id = payload.get("groupId", 0)
        group_name = payload.get("name", "")
        channel = payload.get("channel", 0)
        raw_devices = payload.get("data", [])

        devices: List[Dict[str, Any]] = []
        for device_data in raw_devices:
            dev_type = str(device_data.get("devType", ""))
            channel_id = int(device_data.get("channel", 0))
            address = int(device_data.get("address", 0))

            devices.append(
                {
                    "unique_id": gen_device_unique_id(
                        dev_type, channel_id, address, self._gw_sn
                    ),
                    "id": str(device_data.get("devId", "")),
                    "name": gen_device_name(dev_type, channel_id, address),
                    "dev_type": dev_type,
                    "channel": channel_id,
                    "address": address,
                    "status": "",
                    "dev_sn": "",
                    "area_name": "",
                    "area_id": "",
                    "model": DEVICE_MODEL_MAP.get(dev_type, "Unknown"),
                    "prop": [],
                }
            )

        self._read_group_result = {
            "unique_id": gen_group_unique_id(group_id, channel, self._gw_sn),
            "id": group_id,
            "name": group_name,
            "channel": channel,
            "area_id": "",
            "devices": devices,
        }
        self._read_group_received.set()

    def _process_read_scene_response(self, payload: Dict[str, Any]) -> None:
        scene_id = payload.get("sceneId", 0)
        scene_name = payload.get("name", "")
        channel = payload.get("channel", 0)
        data: Dict[str, Any] | None = payload.get("data")

        if data is None:
            _LOGGER.error(
                "Gateway %s: Received readSceneRes with no data: %s",
                self._gw_sn,
                payload,
            )
            self._read_scene_received.set()
            return

        raw_devices: List[Dict[str, Any]] = data.get("device", [])

        # Create SceneDeviceType objects from raw device data
        devices: List[SceneDeviceType] = []
        for device_data in raw_devices:
            # Convert raw property data to LightStatus using parse_light_status
            raw_properties = device_data.get("property", [])
            light_status = parse_light_status(raw_properties)

            device: SceneDeviceType = {
                "dev_type": device_data.get("devType", ""),
                "channel": device_data.get("channel", 0),
                "address": device_data.get("address", 0),
                "gw_sn_obj": device_data.get("gwSnObj", ""),
                "property": light_status,
            }
            devices.append(device)

        self._read_scene_result = {
            "unique_id": gen_scene_unique_id(scene_id, channel, self._gw_sn),
            "id": scene_id,
            "name": scene_name,
            "channel": channel,
            "area_id": "",
            "devices": devices,
        }
        self._read_scene_received.set()

    def _process_set_sensor_on_off_response(self, payload: Dict[str, Any]) -> None:
        _LOGGER.debug(
            "Gateway %s: Received setSensorOnOffRes response, payload: %s",
            self._gw_sn,
            payload,
        )

    def _process_get_sensor_on_off_response(self, payload: Dict[str, Any]) -> None:
        dev_id = gen_device_unique_id(
            payload.get("devType", ""),
            payload.get("channel", 0),
            payload.get("address", 0),
            self._gw_sn,
        )

        value = payload.get("value", False)

        if self._on_sensor_on_off:
            self._on_sensor_on_off(dev_id, value)

    def _process_get_dev_param_response(self, payload: Dict[str, Any]) -> None:
        _LOGGER.debug(
            "Gateway %s: Received getDevParamRes response, payload: %s",
            self._gw_sn,
            payload,
        )

    def _process_restart_gateway_response(self, payload: Dict[str, Any]) -> None:
        ack = payload.get("ack", False)
        _LOGGER.info(
            "Gateway %s: Received restart confirmation, ack: %s. Gateway will restart shortly.",
            self._gw_sn,
            ack,
        )

    async def _setup_ssl(self) -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._setup_ssl_sync)
        except Exception as e:
            _LOGGER.error("Failed to configure SSL/TLS: %s", str(e))
            raise DaliGatewayError(
                f"SSL/TLS configuration failed: {e}", self._gw_sn
            ) from e

    def _setup_ssl_sync(self) -> None:
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations(str(CA_CERT_PATH))
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        self._mqtt_client.tls_set_context(context)
        _LOGGER.debug("SSL/TLS configured with CA certificate: %s", CA_CERT_PATH)

    def get_credentials(self) -> tuple[str, str]:
        return self._username, self._passwd

    async def connect(self) -> None:
        self._connection_event.clear()
        self._connect_result = None
        self._mqtt_client.username_pw_set(self._username, self._passwd)

        if self._is_tls:
            await self._setup_ssl()

        try:
            _LOGGER.info(
                "Attempting connection to gateway %s at %s:%s (TLS: %s)",
                self._gw_sn,
                self._gw_ip,
                self._port,
                self._is_tls,
            )
            self._mqtt_client.connect(self._gw_ip, self._port)
            self._mqtt_client.loop_start()
            await asyncio.wait_for(self._connection_event.wait(), timeout=10)

            if self._connect_result is not None and self._connect_result == 0:
                _LOGGER.info(
                    "Successfully connected to gateway %s at %s:%s",
                    self._gw_sn,
                    self._gw_ip,
                    self._port,
                )
                return

        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Connection timeout to gateway %s at %s:%s after 10 seconds - check network connectivity",
                self._gw_sn,
                self._gw_ip,
                self._port,
            )
            raise DaliGatewayError(
                f"Connection timeout to gateway {self._gw_sn}", self._gw_sn
            ) from err
        except (ConnectionRefusedError, OSError) as err:
            _LOGGER.error(
                "Network error connecting to gateway %s at %s:%s: %s - check if gateway is powered on and accessible",
                self._gw_sn,
                self._gw_ip,
                self._port,
                str(err),
            )
            raise DaliGatewayError(
                f"Network error connecting to gateway {self._gw_sn}: {err}", self._gw_sn
            ) from err

        if self._connect_result is not None and self._connect_result in (4, 5):
            _LOGGER.error(
                "Authentication failed for gateway %s (code %s) with credentials user='%s'. "
                "Please press the gateway button and retry",
                self._gw_sn,
                self._connect_result,
                self._username,
            )
            raise DaliGatewayError(
                f"Authentication failed for gateway {self._gw_sn}. "
                "Please press the gateway button and retry",
                self._gw_sn,
            )
        _LOGGER.error(
            "Connection failed for gateway %s with result code %s",
            self._gw_sn,
            self._connect_result,
        )
        raise DaliGatewayError(
            f"Connection failed for gateway {self._gw_sn} "
            f"with code {self._connect_result}"
        )

    async def disconnect(self) -> None:
        try:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            self._connection_event.clear()
            _LOGGER.info("Successfully disconnected from gateway %s", self._gw_sn)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Error during disconnect from gateway %s: %s", self._gw_sn, exc
            )
            raise DaliGatewayError(
                f"Failed to disconnect from gateway {self._gw_sn}: {exc}"
            ) from exc

    async def get_version(self) -> VersionType | None:
        self._version_received = asyncio.Event()
        payload = {
            "cmd": "getVersion",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
        }

        _LOGGER.debug("Gateway %s: Sending get version command", self._gw_sn)
        self._mqtt_client.publish(self._pub_topic, json.dumps(payload))

        try:
            await asyncio.wait_for(self._version_received.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Gateway %s: Timeout waiting for version response", self._gw_sn
            )

        _LOGGER.info(
            "Gateway %s: Version retrieved - SW: %s, FW: %s",
            self._gw_sn,
            self._version_result["software"] if self._version_result else "N/A",
            self._version_result["firmware"] if self._version_result else "N/A",
        )
        return self._version_result

    async def read_group(self, group_id: int, channel: int = 0) -> Dict[str, Any]:
        self._read_group_received = asyncio.Event()
        payload: Dict[str, Any] = {
            "cmd": "readGroup",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "channel": channel,
            "groupId": group_id,
        }

        _LOGGER.debug("Gateway %s: Sending read group command", self._gw_sn)
        self._mqtt_client.publish(self._pub_topic, json.dumps(payload))

        try:
            await asyncio.wait_for(self._read_group_received.wait(), timeout=30.0)
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Gateway %s: Timeout waiting for read group response for group %s",
                self._gw_sn,
                group_id,
            )
            raise DaliGatewayError(
                f"Timeout reading group {group_id} from gateway {self._gw_sn}",
                self._gw_sn,
            ) from err

        if not self._read_group_result:
            _LOGGER.error(
                "Gateway %s: Failed to read group %s - group may not exist",
                self._gw_sn,
                group_id,
            )
            raise DaliGatewayError(
                f"Failed to read group {group_id} from gateway {self._gw_sn}. Group may not exist.",
                self._gw_sn,
            )

        _LOGGER.info(
            "Gateway %s: Group read completed - ID: %s, Name: %s, Devices: %d",
            self._gw_sn,
            self._read_group_result["id"],
            self._read_group_result["name"],
            len(self._read_group_result["devices"]),
        )
        return self._read_group_result

    async def read_scene(self, scene_id: int, channel: int = 0) -> Dict[str, Any]:
        self._read_scene_received = asyncio.Event()
        payload: Dict[str, Any] = {
            "cmd": "readScene",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "channel": channel,
            "sceneId": scene_id,
        }

        _LOGGER.debug("Gateway %s: Sending read scene command", self._gw_sn)
        self._mqtt_client.publish(self._pub_topic, json.dumps(payload))

        try:
            await asyncio.wait_for(self._read_scene_received.wait(), timeout=30.0)
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Gateway %s: Timeout waiting for read scene response for scene %s",
                self._gw_sn,
                scene_id,
            )
            raise DaliGatewayError(
                f"Timeout reading scene {scene_id} from gateway {self._gw_sn}",
                self._gw_sn,
            ) from err

        if not self._read_scene_result:
            _LOGGER.error(
                "Gateway %s: Failed to read scene %s - scene may not exist",
                self._gw_sn,
                scene_id,
            )
            raise DaliGatewayError(
                f"Scene {scene_id} not found on gateway {self._gw_sn}", self._gw_sn
            )

        _LOGGER.info(
            "Gateway %s: Scene read completed - ID: %s, Name: %s, Devices: %d",
            self._gw_sn,
            self._read_scene_result["id"],
            self._read_scene_result["name"],
            len(self._read_scene_result["devices"]),
        )
        return self._read_scene_result

    async def discover_devices(self) -> list[Device]:
        self._devices_received = asyncio.Event()
        self._devices_result.clear()
        search_payload = {
            "cmd": "searchDev",
            "searchFlag": "exited",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
        }

        _LOGGER.debug("Gateway %s: Sending device discovery command", self._gw_sn)
        self._mqtt_client.publish(self._pub_topic, json.dumps(search_payload))

        try:
            await asyncio.wait_for(self._devices_received.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Gateway %s: Timeout waiting for device discovery response", self._gw_sn
            )

        _LOGGER.info(
            "Gateway %s: Device discovery completed, found %d device(s)",
            self._gw_sn,
            len(self._devices_result),
        )
        return self._devices_result

    async def discover_groups(self) -> list[Group]:
        self._groups_received = asyncio.Event()
        self._groups_result.clear()
        search_payload = {
            "cmd": "getGroup",
            "msgId": str(int(time.time())),
            "getFlag": "exited",
            "gwSn": self._gw_sn,
        }

        _LOGGER.debug("Gateway %s: Sending group discovery command", self._gw_sn)
        self._mqtt_client.publish(self._pub_topic, json.dumps(search_payload))

        try:
            await asyncio.wait_for(self._groups_received.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Gateway %s: Timeout waiting for group discovery response", self._gw_sn
            )

        _LOGGER.info(
            "Gateway %s: Group discovery completed, found %d group(s)",
            self._gw_sn,
            len(self._groups_result),
        )
        return self._groups_result

    async def discover_scenes(self) -> list[Scene]:
        self._scenes_received = asyncio.Event()
        self._scenes_result.clear()
        search_payload = {
            "cmd": "getScene",
            "msgId": str(int(time.time())),
            "getFlag": "exited",
            "gwSn": self._gw_sn,
        }

        _LOGGER.debug("Gateway %s: Sending scene discovery command", self._gw_sn)
        self._mqtt_client.publish(self._pub_topic, json.dumps(search_payload))

        try:
            await asyncio.wait_for(self._scenes_received.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Gateway %s: Timeout waiting for scene discovery response", self._gw_sn
            )

        _LOGGER.info(
            "Gateway %s: Scene discovery completed, found %d scene(s)",
            self._gw_sn,
            len(self._scenes_result),
        )
        return self._scenes_result

    def command_write_dev(
        self,
        dev_type: str,
        channel: int,
        address: int,
        properties: List[Dict[str, Any]],
    ) -> None:
        self.add_request(
            "writeDev",
            dev_type,
            channel,
            address,
            {
                "devType": dev_type,
                "channel": channel,
                "address": address,
                "property": properties,
            },
        )

    def command_read_dev(self, dev_type: str, channel: int, address: int) -> None:
        self.add_request(
            "readDev",
            dev_type,
            channel,
            address,
            {"devType": dev_type, "channel": channel, "address": address},
        )

    def command_get_energy(
        self, dev_type: str, channel: int, address: int, year: int, month: int, day: int
    ) -> None:
        self.add_request(
            "getEnergy",
            dev_type,
            channel,
            address,
            {
                "devType": dev_type,
                "channel": channel,
                "address": address,
                "condition": {"year": year, "month": month, "day": day, "hour": []},
            },
        )

    def command_write_group(
        self, group_id: int, channel: int, properties: List[Dict[str, Any]]
    ) -> None:
        command: Dict[str, Any] = {
            "cmd": "writeGroup",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "channel": channel,
            "groupId": group_id,
            "data": properties,
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_write_scene(self, scene_id: int, channel: int) -> None:
        command: Dict[str, Any] = {
            "cmd": "writeScene",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "channel": channel,
            "sceneId": scene_id,
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_set_sensor_on_off(
        self, dev_type: str, channel: int, address: int, value: bool
    ) -> None:
        command: Dict[str, Any] = {
            "cmd": "setSensorOnOff",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "devType": dev_type,
            "channel": channel,
            "address": address,
            "value": value,
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_get_sensor_on_off(
        self, dev_type: str, channel: int, address: int
    ) -> None:
        command: Dict[str, Any] = {
            "cmd": "getSensorOnOff",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "devType": dev_type,
            "channel": channel,
            "address": address,
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_get_dev_param(self, dev_type: str, channel: int, address: int) -> None:
        command: Dict[str, Any] = {
            "cmd": "getDevParam",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "devType": dev_type,
            "channel": channel,
            "address": address,
            "fromBus": True,
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_set_dev_param(
        self, dev_type: str, channel: int, address: int, param: DeviceParamType
    ) -> None:
        command: Dict[str, Any] = {
            "cmd": "setDevParam",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "data": [
                {
                    "devType": dev_type,
                    "channel": channel,
                    "address": address,
                    "paramer": {
                        "maxBrightness": param["max_brightness"],
                    },
                }
            ],
        }
        command_json = json.dumps(command)
        _LOGGER.debug(
            "Gateway %s: Sending setDevParam command: %s", self._gw_sn, command
        )
        self._mqtt_client.publish(self._pub_topic, command_json)

    def restart_gateway(self) -> None:
        """Restart the gateway."""
        command: Dict[str, Any] = {
            "cmd": "restartGateway",
            "msgId": str(int(time.time())),
        }
        command_json = json.dumps(command)
        _LOGGER.debug("Gateway %s: Sending restart command", self._gw_sn)
        self._mqtt_client.publish(self._pub_topic, command_json)
