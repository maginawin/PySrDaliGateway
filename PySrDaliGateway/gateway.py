"""Dali Gateway"""

import asyncio
from enum import Enum, auto
import json
import logging
import random
import ssl
import time
from typing import Any, Callable, Dict, List, Sequence, Tuple, Union, cast

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
    CallbackEventType,
    DeviceParamCommand,
    DeviceParamType,
    EnergyData,
    GroupDeviceType,
    IlluminanceStatus,
    LightStatus,
    MotionStatus,
    PanelStatus,
    SceneDeviceType,
    SensorParamType,
)
from .udp_client import send_identify_gateway

_LOGGER = logging.getLogger(__name__)

# Connection parameters
_CONNECTION_TIMEOUT = 30.0  # seconds - gateway broker may respond slowly

# Reconnection parameters
_RECONNECT_INITIAL_DELAY = 1.0  # seconds
_RECONNECT_MAX_DELAY = 60.0  # seconds
_RECONNECT_BACKOFF_MULTIPLIER = 2.0
_RECONNECT_JITTER = 0.1  # ±10%


class ConnectionState(Enum):
    """Connection state machine for gateway."""

    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    RECONNECTING = auto()


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
        loop: asyncio.AbstractEventLoop | None = None,
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
        self.software_version: str = ""
        self.firmware_version: str = ""

        # Event loop for thread-safe callback dispatch
        # Can be provided at __init__ or will be auto-detected in connect()
        self._loop: asyncio.AbstractEventLoop | None = loop

        # Connection state machine
        self._connection_state = ConnectionState.DISCONNECTED
        self._reconnect_task: asyncio.TimerHandle | None = None
        self._reconnect_delay = _RECONNECT_INITIAL_DELAY
        self._shutdown_requested = False

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

        self._scenes_result: list[Scene] = []
        self._groups_result: list[Group] = []
        self._devices_result: list[Device] = []
        self._read_group_events: Dict[Tuple[int, int], asyncio.Event] = {}
        self._read_group_results: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._read_scene_events: Dict[Tuple[int, int], asyncio.Event] = {}
        self._read_scene_results: Dict[Tuple[int, int], Dict[str, Any]] = {}

        # Device-specific listeners: {event_type: {dev_id: [listeners]}}
        self._device_listeners: Dict[
            CallbackEventType, Dict[str, List[Callable[..., None]]]
        ] = {
            CallbackEventType.ONLINE_STATUS: {},
            CallbackEventType.LIGHT_STATUS: {},
            CallbackEventType.MOTION_STATUS: {},
            CallbackEventType.ILLUMINANCE_STATUS: {},
            CallbackEventType.PANEL_STATUS: {},
            CallbackEventType.ENERGY_REPORT: {},
            CallbackEventType.ENERGY_DATA: {},
            CallbackEventType.SENSOR_ON_OFF: {},
            CallbackEventType.DEV_PARAM: {},
            CallbackEventType.SENSOR_PARAM: {},
        }

        self._window_ms = 100
        self._pending_requests: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._batch_timer: Dict[str, asyncio.TimerHandle] = {}  # cmd -> timer

    def _get_device_key(self, dev_type: str, channel: int, address: int) -> str:
        return f"{dev_type}_{channel}_{address}"

    def _build_paramer(self, param: DeviceParamType) -> Dict[str, Any]:
        param_mapping = {
            "address": "address",
            "fade_time": "fadeTime",
            "fade_rate": "fadeRate",
            "power_status": "powerStatus",
            "system_failure_status": "systemFailureStatus",
            "max_brightness": "maxBrightness",
            "min_brightness": "minBrightness",
            "standby_power": "standbyPower",
            "max_power": "maxPower",
            "cct_cool": "cctCool",
            "cct_warm": "cctWarm",
            "phy_cct_cool": "phyCctCool",
            "phy_cct_warm": "phyCctWarm",
            "step_cct": "stepCCT",
            "temp_thresholds": "tempThresholds",
            "runtime_thresholds": "runtimeThresholds",
            "waring_runtime_max": "waringRuntimeMax",
            "waring_temperature_max": "waringTemperatureMax",
        }

        param_dict = dict(param)
        paramer: Dict[str, Any] = {}
        for python_key, protocol_key in param_mapping.items():
            if python_key in param_dict:
                paramer[protocol_key] = param_dict[python_key]
        return paramer

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
    def is_connected(self) -> bool:
        """Return True if the gateway is connected."""
        return self._connection_state == ConnectionState.CONNECTED

    @property
    def connection_state(self) -> ConnectionState:
        """Return the current connection state."""
        return self._connection_state

    def _dispatch_callback(self, callback: Callable[..., Any], *args: Any) -> None:
        """Dispatch a callback in a thread-safe manner.

        If an event loop is configured, use call_soon_threadsafe to schedule
        the callback on the event loop thread. Otherwise, call the callback
        directly (for backward compatibility).
        """
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(callback, *args)
        else:
            callback(*args)

    def _set_event_threadsafe(self, event: asyncio.Event) -> None:
        """Set an asyncio.Event in a thread-safe manner."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(event.set)
        else:
            event.set()

    def register_listener(
        self,
        event_type: CallbackEventType,
        listener: Union[
            Callable[[bool], None],
            Callable[[LightStatus], None],
            Callable[[MotionStatus], None],
            Callable[[IlluminanceStatus], None],
            Callable[[PanelStatus], None],
            Callable[[float], None],
            Callable[[EnergyData], None],
            Callable[[DeviceParamType], None],
            Callable[[SensorParamType], None],
        ],
        dev_id: str,
    ) -> Callable[[], None]:
        """Register a listener for a specific event type.

        Args:
            event_type: The type of event to listen for
            listener: The callback function to invoke
            dev_id: Device ID to filter events for (required)
        """
        if event_type not in self._device_listeners:
            return lambda: None

        # Register device-specific listener
        if dev_id not in self._device_listeners[event_type]:
            self._device_listeners[event_type][dev_id] = []
        self._device_listeners[event_type][dev_id].append(listener)
        return lambda: self._device_listeners[event_type][dev_id].remove(listener)

    def _notify_listeners(
        self,
        event_type: CallbackEventType,
        dev_id: str,
        data: Union[
            bool,
            LightStatus,
            MotionStatus,
            IlluminanceStatus,
            PanelStatus,
            float,
            EnergyData,
            DeviceParamType,
            SensorParamType,
        ],
    ) -> None:
        """Notify all registered listeners for a specific event type.

        Uses thread-safe dispatch when an event loop is configured.
        """
        # Notify device-specific listeners - no dev_id parameter needed since filtered
        for listener in self._device_listeners.get(event_type, {}).get(dev_id, []):
            self._dispatch_callback(listener, data)

    def _on_connect(
        self,
        client: paho_mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: int,
        properties: Any = None,
    ) -> None:
        self._connect_result = rc
        # Thread-safe Event.set()
        self._set_event_threadsafe(self._connection_event)

        if rc == 0:
            # Update connection state
            self._connection_state = ConnectionState.CONNECTED
            self._reconnect_delay = _RECONNECT_INITIAL_DELAY  # Reset backoff

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

            # Notify gateway-level listeners (thread-safe via _notify_listeners)
            self._notify_listeners(CallbackEventType.ONLINE_STATUS, self._gw_sn, True)
            # Notify all device-specific listeners that gateway is online
            for device_id in self._device_listeners[CallbackEventType.ONLINE_STATUS]:
                if device_id != self._gw_sn:
                    for listener in self._device_listeners[
                        CallbackEventType.ONLINE_STATUS
                    ][device_id]:
                        # Use thread-safe dispatch
                        self._dispatch_callback(listener, True)
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

        was_connected = self._connection_state == ConnectionState.CONNECTED
        unexpected_disconnect = reason_code != 0 and was_connected

        if unexpected_disconnect:
            _LOGGER.warning(
                "Gateway %s: Unexpected MQTT disconnection (%s:%s) - Reason code: %s",
                self._gw_sn,
                self._gw_ip,
                self._port,
                reason_code,
            )
            # Set state to RECONNECTING if we should attempt reconnection
            if not self._shutdown_requested:
                self._connection_state = ConnectionState.RECONNECTING
                self._schedule_reconnect()
            else:
                self._connection_state = ConnectionState.DISCONNECTED
        else:
            _LOGGER.debug("Gateway %s: MQTT disconnection completed", self._gw_sn)
            self._connection_state = ConnectionState.DISCONNECTED

        # Notify gateway-level listeners (thread-safe via _notify_listeners)
        self._notify_listeners(CallbackEventType.ONLINE_STATUS, self._gw_sn, False)
        # Notify all device-specific listeners that gateway is offline
        for device_id in self._device_listeners[CallbackEventType.ONLINE_STATUS]:
            if device_id != self._gw_sn:
                for listener in self._device_listeners[CallbackEventType.ONLINE_STATUS][
                    device_id
                ]:
                    # Use thread-safe dispatch
                    self._dispatch_callback(listener, False)

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
                "setSensorArgvRes": self._process_set_sensor_argv_response,
                "getSensorArgvRes": self._process_get_sensor_argv_response,
                "setDevParamRes": self._process_set_dev_param_response,
                "getDevParamRes": self._process_get_dev_param_response,
                "identifyDevRes": self._process_identify_dev_response,
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
            self._notify_listeners(CallbackEventType.ONLINE_STATUS, dev_id, available)

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

        if dev_type and is_light_device(dev_type):
            light_status = parse_light_status(property_list)
            self._notify_listeners(CallbackEventType.LIGHT_STATUS, dev_id, light_status)
        elif dev_type and is_motion_sensor(dev_type):
            motion_statuses = parse_motion_status(property_list)
            for motion_status in motion_statuses:
                self._notify_listeners(
                    CallbackEventType.MOTION_STATUS, dev_id, motion_status
                )
        elif dev_type and is_illuminance_sensor(dev_type):
            illuminance_statuses = parse_illuminance_status(property_list)
            for illuminance_status in illuminance_statuses:
                self._notify_listeners(
                    CallbackEventType.ILLUMINANCE_STATUS, dev_id, illuminance_status
                )
        elif dev_type and is_panel_device(dev_type):
            panel_statuses = parse_panel_status(property_list)
            for panel_status in panel_statuses:
                self._notify_listeners(
                    CallbackEventType.PANEL_STATUS, dev_id, panel_status
                )
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

                    self._notify_listeners(
                        CallbackEventType.ENERGY_REPORT, dev_id, energy_value
                    )
                except (ValueError, TypeError) as e:
                    _LOGGER.error("Error converting energy value: %s", str(e))

    def _process_get_version_response(self, payload_json: Dict[str, Any]) -> None:
        self.software_version = payload_json.get("data", {}).get("swVersion", "")
        self.firmware_version = payload_json.get("data", {}).get("fwVersion", "")

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

            energy_data: EnergyData = {
                "yearEnergy": data.get("yearEnergy", {}),
                "monthEnergy": data.get("monthEnergy", {}),
                "dayEnergy": data.get("dayEnergy", {}),
                "hourEnergy": data.get("hourEnergy", []),
            }

            self._notify_listeners(CallbackEventType.ENERGY_DATA, dev_id, energy_data)

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
            self._set_event_threadsafe(self._devices_received)

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
                        devices=[],
                    )
                )

        self._set_event_threadsafe(self._scenes_received)

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
                        devices=[],
                    )
                )

        self._set_event_threadsafe(self._groups_received)

    def _process_read_group_response(self, payload: Dict[str, Any]) -> None:
        group_id = payload.get("groupId", 0)
        group_name = payload.get("name", "")
        channel = payload.get("channel", 0)
        group_key = (group_id, channel)
        raw_devices = payload.get("data", [])

        # Create GroupDeviceType objects from raw device data
        devices: List[GroupDeviceType] = []
        for device_data in raw_devices:
            dev_type = str(device_data.get("devType", ""))
            channel_id = int(device_data.get("channel", 0))
            address = int(device_data.get("address", 0))

            device: GroupDeviceType = {
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
            devices.append(device)

        self._read_group_results[group_key] = {
            "unique_id": gen_group_unique_id(group_id, channel, self._gw_sn),
            "id": group_id,
            "name": group_name,
            "channel": channel,
            "area_id": "",
            "devices": devices,
        }

        # Signal completion for this specific group
        if group_key in self._read_group_events:
            self._set_event_threadsafe(self._read_group_events[group_key])

    def _process_read_scene_response(self, payload: Dict[str, Any]) -> None:
        scene_id = payload.get("sceneId", 0)
        scene_name = payload.get("name", "")
        channel = payload.get("channel", 0)
        scene_key = (scene_id, channel)
        data: Dict[str, Any] | None = payload.get("data")

        if data is None:
            _LOGGER.error(
                "Gateway %s: Received readSceneRes with no data for scene %s channel %s",
                self._gw_sn,
                scene_id,
                channel,
            )
            # Mark as received even with error to unblock waiting coroutine
            if scene_key in self._read_scene_events:
                self._set_event_threadsafe(self._read_scene_events[scene_key])
            return

        raw_devices: List[Dict[str, Any]] = data.get("device", [])

        # Create SceneDeviceType objects from raw device data
        devices: List[SceneDeviceType] = []
        for device_data in raw_devices:
            # Convert raw property data to LightStatus using parse_light_status
            raw_properties = device_data.get("property", [])
            light_status = parse_light_status(raw_properties)

            dev_type = str(device_data.get("devType", ""))
            channel_id = int(device_data.get("channel", 0))
            address = int(device_data.get("address", 0))
            gw_sn_obj = str(device_data.get("gwSnObj", ""))
            if dev_type == "0401":
                unique_id = gen_group_unique_id(address, channel_id, self._gw_sn)
            else:
                unique_id = gen_device_unique_id(
                    dev_type, channel_id, address, self._gw_sn
                )

            device: SceneDeviceType = {
                "unique_id": unique_id,
                "dev_type": dev_type,
                "channel": channel_id,
                "address": address,
                "gw_sn_obj": gw_sn_obj,
                "property": light_status,
            }
            devices.append(device)

        self._read_scene_results[scene_key] = {
            "unique_id": gen_scene_unique_id(scene_id, channel, self._gw_sn),
            "id": scene_id,
            "name": scene_name,
            "channel": channel,
            "area_id": "",
            "devices": devices,
        }

        # Signal completion for this specific scene
        if scene_key in self._read_scene_events:
            self._set_event_threadsafe(self._read_scene_events[scene_key])

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

        self._notify_listeners(CallbackEventType.SENSOR_ON_OFF, dev_id, value)

    def _process_set_sensor_argv_response(self, payload: Dict[str, Any]) -> None:
        """Process setSensorArgv response."""
        dev_type = payload.get("devType", "")
        channel = payload.get("channel", 0)
        address = payload.get("address", 0)
        ack = payload.get("ack", False)

        _LOGGER.debug(
            "Gateway %s: Received setSensorArgvRes response, "
            "devType: %s, channel: %s, address: %s, ack: %s",
            self._gw_sn,
            dev_type,
            channel,
            address,
            ack,
        )

    def _process_get_sensor_argv_response(self, payload: Dict[str, Any]) -> None:
        """Process getSensorArgv response and emit parameters to listeners."""
        dev_type = payload.get("devType", "")
        channel = payload.get("channel", 0)
        address = payload.get("address", 0)
        data = payload.get("data", {})

        _LOGGER.debug(
            "Gateway %s: Received getSensorArgvRes response, "
            "devType: %s, channel: %s, address: %s, data: %s",
            self._gw_sn,
            dev_type,
            channel,
            address,
            data,
        )

        if not data:
            return

        # Convert camelCase protocol keys to snake_case Python keys
        protocol_to_python = {
            "enable": "enable",
            "occpyTime": "occpy_time",
            "reportTime": "report_time",
            "downTime": "down_time",
            "coverage": "coverage",
            "sensitivity": "sensitivity",
        }

        # Build SensorParamType from response
        sensor_param_dict: Dict[str, Any] = {}
        for protocol_key, value in data.items():
            python_key = protocol_to_python.get(protocol_key)
            if python_key:
                sensor_param_dict[python_key] = value

        # Cast to SensorParamType for type safety
        sensor_param = cast("SensorParamType", sensor_param_dict)

        # Emit to listeners
        dev_id = gen_device_unique_id(dev_type, channel, address, self._gw_sn)
        self._notify_listeners(CallbackEventType.SENSOR_PARAM, dev_id, sensor_param)

    def _process_set_dev_param_response(self, payload: Dict[str, Any]) -> None:
        """Process setDevParam response."""
        dev_type = payload.get("devType", "")
        channel = payload.get("channel", 0)
        address = payload.get("address", 0)
        ack = payload.get("ack", False)

        _LOGGER.debug(
            "Gateway %s: Received setDevParamRes response, "
            "devType: %s, channel: %s, address: %s, ack: %s",
            self._gw_sn,
            dev_type,
            channel,
            address,
            ack,
        )

    def _process_get_dev_param_response(self, payload: Dict[str, Any]) -> None:
        """Process getDevParam response and emit parameters to listeners."""
        dev_type = payload.get("devType", "")
        channel = payload.get("channel", 0)
        address = payload.get("address", 0)
        paramer = payload.get("paramer", {})

        _LOGGER.debug(
            "Gateway %s: Received getDevParamRes response, "
            "devType: %s, channel: %s, address: %s, paramer: %s",
            self._gw_sn,
            dev_type,
            channel,
            address,
            paramer,
        )

        if not paramer:
            return

        # Convert camelCase protocol keys to snake_case Python keys
        protocol_to_python = {
            "address": "address",
            "fadeTime": "fade_time",
            "fadeRate": "fade_rate",
            "powerStatus": "power_status",
            "systemFailureStatus": "system_failure_status",
            "maxBrightness": "max_brightness",
            "minBrightness": "min_brightness",
            "standbyPower": "standby_power",
            "maxPower": "max_power",
            "cctCool": "cct_cool",
            "cctWarm": "cct_warm",
            "phyCctCool": "phy_cct_cool",
            "phyCctWarm": "phy_cct_warm",
            "stepCCT": "step_cct",
            "tempThresholds": "temp_thresholds",
            "runtimeThresholds": "runtime_thresholds",
            "waringRuntimeMax": "waring_runtime_max",
            "waringTemperatureMax": "waring_temperature_max",
        }

        # Build DeviceParamType from response
        device_param_dict: Dict[str, Any] = {}
        for protocol_key, value in paramer.items():
            python_key = protocol_to_python.get(protocol_key)
            if python_key:
                device_param_dict[python_key] = value

        # Cast to DeviceParamType for type safety
        device_param = cast("DeviceParamType", device_param_dict)

        # Emit to listeners
        dev_id = gen_device_unique_id(dev_type, channel, address, self._gw_sn)
        self._notify_listeners(CallbackEventType.DEV_PARAM, dev_id, device_param)

    def _process_restart_gateway_response(self, payload: Dict[str, Any]) -> None:
        ack = payload.get("ack", False)
        _LOGGER.info(
            "Gateway %s: Received restart confirmation, ack: %s. Gateway will restart shortly.",
            self._gw_sn,
            ack,
        )

    def _process_identify_dev_response(self, payload: Dict[str, Any]) -> None:
        """Process identifyDev response."""
        msg_id = payload.get("msgId")
        ack = payload.get("ack", False)

        _LOGGER.debug(
            "Gateway %s: Received identify device response, msgId: %s, ack: %s",
            self._gw_sn,
            msg_id,
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
        self._mqtt_client.tls_set_context(context)  # pyright: ignore[reportUnknownMemberType]
        _LOGGER.debug("SSL/TLS configured with CA certificate: %s", CA_CERT_PATH)

    def get_credentials(self) -> tuple[str, str]:
        return self._username, self._passwd

    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt with exponential backoff.

        Called from paho-mqtt thread, so must be thread-safe.
        """
        if self._shutdown_requested:
            _LOGGER.debug(
                "Gateway %s: Shutdown requested, skipping reconnection", self._gw_sn
            )
            return

        # Add jitter to prevent thundering herd
        jitter = self._reconnect_delay * _RECONNECT_JITTER * (2 * random.random() - 1)
        delay = self._reconnect_delay + jitter

        _LOGGER.info(
            "Gateway %s: Scheduling reconnection in %.1f seconds",
            self._gw_sn,
            delay,
        )

        # Schedule reconnection on the event loop
        if self._loop is not None and self._loop.is_running():
            self._reconnect_task = self._loop.call_later(
                delay,
                lambda: asyncio.ensure_future(self._reconnect(), loop=self._loop),
            )
        else:
            _LOGGER.warning(
                "Gateway %s: No event loop available for reconnection",
                self._gw_sn,
            )

        # Increase delay for next attempt (exponential backoff)
        self._reconnect_delay = min(
            self._reconnect_delay * _RECONNECT_BACKOFF_MULTIPLIER,
            _RECONNECT_MAX_DELAY,
        )

    async def _reconnect(self) -> None:
        """Attempt to reconnect to the gateway."""
        if self._shutdown_requested:
            _LOGGER.debug(
                "Gateway %s: Shutdown requested, aborting reconnection", self._gw_sn
            )
            return

        _LOGGER.info("Gateway %s: Attempting reconnection...", self._gw_sn)

        try:
            # Reset connection state
            self._connection_event.clear()
            self._connect_result = None

            # Attempt reconnection
            self._mqtt_client.reconnect()

            # Wait for connection result
            await asyncio.wait_for(self._connection_event.wait(), timeout=10)

            if self._connect_result == 0:  # pyright: ignore[reportUnnecessaryComparison]
                _LOGGER.info(
                    "Gateway %s: Reconnection successful",
                    self._gw_sn,
                )
                # Request version information
                self._request_version()
            else:
                _LOGGER.warning(
                    "Gateway %s: Reconnection failed with code %s",
                    self._gw_sn,
                    self._connect_result,
                )
                # Schedule another reconnection attempt
                if not self._shutdown_requested:
                    self._connection_state = ConnectionState.RECONNECTING
                    self._schedule_reconnect()

        except (asyncio.TimeoutError, OSError, ConnectionRefusedError) as err:
            _LOGGER.warning(
                "Gateway %s: Reconnection attempt failed: %s",
                self._gw_sn,
                err,
            )
            # Schedule another reconnection attempt
            if not self._shutdown_requested:
                self._connection_state = ConnectionState.RECONNECTING
                self._schedule_reconnect()

    def stop_reconnection(self) -> None:
        """Stop any pending reconnection attempts.

        Should be called before disconnect() to prevent auto-reconnection.
        """
        self._shutdown_requested = True
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None
            _LOGGER.debug("Gateway %s: Cancelled pending reconnection", self._gw_sn)

    async def connect(self) -> None:
        # Auto-detect event loop if not provided at __init__
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        self._connection_event.clear()
        self._connect_result = None
        self._shutdown_requested = False  # Reset shutdown flag for new connection
        self._reconnect_delay = _RECONNECT_INITIAL_DELAY  # Reset backoff
        self._connection_state = ConnectionState.CONNECTING
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
            await asyncio.wait_for(
                self._connection_event.wait(), timeout=_CONNECTION_TIMEOUT
            )

            if self._connect_result is not None and self._connect_result == 0:
                _LOGGER.info(
                    "Successfully connected to gateway %s at %s:%s",
                    self._gw_sn,
                    self._gw_ip,
                    self._port,
                )
                # Request version information
                self._request_version()
                return

        except asyncio.TimeoutError as err:
            # Critical: Stop the paho loop to prevent leaked background threads
            # that could cause duplicate message processing if a new gateway
            # instance is created later with the same client_id.
            self._mqtt_client.loop_stop()
            self._connection_state = ConnectionState.DISCONNECTED

            _LOGGER.error(
                "Connection timeout to gateway %s at %s:%s after %.0f seconds - check network connectivity",
                self._gw_sn,
                self._gw_ip,
                self._port,
                _CONNECTION_TIMEOUT,
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

        # Connection failed - clean up the paho loop before raising
        self._mqtt_client.loop_stop()
        self._connection_state = ConnectionState.DISCONNECTED

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
        # Stop any pending reconnection attempts first
        self.stop_reconnection()

        try:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            self._connection_event.clear()
            self._connection_state = ConnectionState.DISCONNECTED
            _LOGGER.info("Successfully disconnected from gateway %s", self._gw_sn)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Error during disconnect from gateway %s: %s", self._gw_sn, exc
            )
            raise DaliGatewayError(
                f"Failed to disconnect from gateway {self._gw_sn}: {exc}"
            ) from exc

    def _request_version(self) -> None:
        """Request gateway version information via MQTT."""
        payload = {
            "cmd": "getVersion",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
        }
        _LOGGER.debug("Gateway %s: Requesting version information", self._gw_sn)
        self._mqtt_client.publish(self._pub_topic, json.dumps(payload))

    async def identify_gateway(self) -> None:
        """Make the gateway's indicator light blink to identify it physically.

        This command is sent via UDP multicast (not MQTT) according to the protocol specification.
        """
        _LOGGER.debug("Sending identify command to gateway %s via UDP", self._gw_sn)
        await send_identify_gateway(self._gw_sn)

    async def read_group(self, group_id: int, channel: int = 0) -> Dict[str, Any]:
        group_key = (group_id, channel)

        # Create event for this specific group read
        self._read_group_events[group_key] = asyncio.Event()
        self._read_group_results.pop(group_key, None)  # Clear any previous result

        payload: Dict[str, Any] = {
            "cmd": "readGroup",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "channel": channel,
            "groupId": group_id,
        }

        _LOGGER.debug(
            "Gateway %s: Sending read group command for group %s channel %s",
            self._gw_sn,
            group_id,
            channel,
        )
        self._mqtt_client.publish(self._pub_topic, json.dumps(payload))

        try:
            await asyncio.wait_for(
                self._read_group_events[group_key].wait(), timeout=30.0
            )
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Gateway %s: Timeout waiting for read group response for group %s channel %s",
                self._gw_sn,
                group_id,
                channel,
            )
            # Cleanup
            self._read_group_events.pop(group_key, None)
            self._read_group_results.pop(group_key, None)
            raise DaliGatewayError(
                f"Timeout reading group {group_id} channel {channel} from gateway {self._gw_sn}",
                self._gw_sn,
            ) from err

        # Get result
        result = self._read_group_results.get(group_key)

        # Cleanup
        self._read_group_events.pop(group_key, None)
        self._read_group_results.pop(group_key, None)

        if not result:
            _LOGGER.error(
                "Gateway %s: Failed to read group %s channel %s - group may not exist",
                self._gw_sn,
                group_id,
                channel,
            )
            raise DaliGatewayError(
                f"Group {group_id} channel {channel} not found on gateway {self._gw_sn}",
                self._gw_sn,
            )

        _LOGGER.info(
            "Gateway %s: Group read completed - ID: %s, Channel: %s, Name: %s, Devices: %d",
            self._gw_sn,
            result["id"],
            result["channel"],
            result["name"],
            len(result["devices"]),
        )
        return result

    async def read_scene(self, scene_id: int, channel: int = 0) -> Dict[str, Any]:
        scene_key = (scene_id, channel)

        # Create event for this specific scene read
        self._read_scene_events[scene_key] = asyncio.Event()
        self._read_scene_results.pop(scene_key, None)  # Clear any previous result

        payload: Dict[str, Any] = {
            "cmd": "readScene",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "channel": channel,
            "sceneId": scene_id,
        }

        _LOGGER.debug(
            "Gateway %s: Sending read scene command for scene %s channel %s",
            self._gw_sn,
            scene_id,
            channel,
        )
        self._mqtt_client.publish(self._pub_topic, json.dumps(payload))

        try:
            await asyncio.wait_for(
                self._read_scene_events[scene_key].wait(), timeout=30.0
            )
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Gateway %s: Timeout waiting for read scene response for scene %s channel %s",
                self._gw_sn,
                scene_id,
                channel,
            )
            # Cleanup
            self._read_scene_events.pop(scene_key, None)
            self._read_scene_results.pop(scene_key, None)
            raise DaliGatewayError(
                f"Timeout reading scene {scene_id} channel {channel} from gateway {self._gw_sn}",
                self._gw_sn,
            ) from err

        # Get result
        result = self._read_scene_results.get(scene_key)

        # Cleanup
        self._read_scene_events.pop(scene_key, None)
        self._read_scene_results.pop(scene_key, None)

        if not result:
            _LOGGER.error(
                "Gateway %s: Failed to read scene %s channel %s - scene may not exist",
                self._gw_sn,
                scene_id,
                channel,
            )
            raise DaliGatewayError(
                f"Scene {scene_id} channel {channel} not found on gateway {self._gw_sn}",
                self._gw_sn,
            )

        _LOGGER.info(
            "Gateway %s: Scene read completed - ID: %s, Channel: %s, Name: %s, Devices: %d",
            self._gw_sn,
            result["id"],
            result["channel"],
            result["name"],
            len(result["devices"]),
        )
        return result

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
        """Discover all groups and read their detailed configuration with limited concurrency.

        Uses a semaphore to limit parallel read_group() calls, preventing MQTT message
        storms that can overload the event loop during multi-gateway startup.

        Returns only groups that were successfully read. Groups that fail to read
        (timeout, errors, etc.) are logged but not included in the result.
        """
        # Phase 1: Discover basic group list
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
            return []

        if not self._groups_result:
            _LOGGER.info("Gateway %s: No groups found", self._gw_sn)
            return []

        _LOGGER.info(
            "Gateway %s: Found %d group(s), reading details with limited concurrency...",
            self._gw_sn,
            len(self._groups_result),
        )

        # Phase 2: Read detailed group data with limited concurrency
        # Limit concurrent reads to avoid MQTT message storms
        read_semaphore = asyncio.Semaphore(3)

        async def read_group_with_limit(group_id: int, channel: int) -> Dict[str, Any]:
            async with read_semaphore:
                return await self.read_group(group_id, channel)

        # Store basic group info for reconstruction
        basic_groups: List[Tuple[int, str, int, str]] = [
            (group.group_id, group.name, group.channel, group.area_id)
            for group in self._groups_result
        ]

        # Create read tasks with semaphore limit
        read_tasks = [
            read_group_with_limit(group_id, channel)
            for group_id, _, channel, _ in basic_groups
        ]

        # Execute all reads with exception handling
        results = await asyncio.gather(*read_tasks, return_exceptions=True)

        # Phase 3: Construct Group objects with device data
        groups_with_devices: list[Group] = []
        for (group_id, name, channel, area_id), result in zip(basic_groups, results):
            if isinstance(result, Exception):
                _LOGGER.error(
                    "Gateway %s: Failed to read group %s (channel %s): %s",
                    self._gw_sn,
                    group_id,
                    channel,
                    result,
                )
                continue

            # Successfully read group data - result is Dict[str, Any]
            result_dict = cast("Dict[str, Any]", result)
            try:
                group = Group(
                    command_client=self,
                    group_id=group_id,
                    name=result_dict.get("name", name),
                    channel=channel,
                    area_id=result_dict.get("area_id", area_id),
                    devices=result_dict.get("devices", []),
                )
                groups_with_devices.append(group)
            except (KeyError, TypeError, ValueError) as e:
                _LOGGER.error(
                    "Gateway %s: Failed to create Group object for group %s: %s",
                    self._gw_sn,
                    group_id,
                    e,
                )

        _LOGGER.info(
            "Gateway %s: Group discovery completed, %d/%d group(s) successfully read",
            self._gw_sn,
            len(groups_with_devices),
            len(basic_groups),
        )
        return groups_with_devices

    async def discover_scenes(self) -> list[Scene]:
        """Discover all scenes and read their detailed configuration with limited concurrency.

        Uses a semaphore to limit parallel read_scene() calls, preventing MQTT message
        storms that can overload the event loop during multi-gateway startup.

        Returns only scenes that were successfully read. Scenes that fail to read
        (timeout, errors, etc.) are logged but not included in the result.
        """
        # Phase 1: Discover basic scene list
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
            return []

        if not self._scenes_result:
            _LOGGER.info("Gateway %s: No scenes found", self._gw_sn)
            return []

        _LOGGER.info(
            "Gateway %s: Found %d scene(s), reading details with limited concurrency...",
            self._gw_sn,
            len(self._scenes_result),
        )

        # Phase 2: Read detailed scene data with limited concurrency
        # Limit concurrent reads to avoid MQTT message storms
        read_semaphore = asyncio.Semaphore(3)

        async def read_scene_with_limit(scene_id: int, channel: int) -> Dict[str, Any]:
            async with read_semaphore:
                return await self.read_scene(scene_id, channel)

        # Store basic scene info for reconstruction
        basic_scenes: List[Tuple[int, str, int, str]] = [
            (scene.scene_id, scene.name, scene.channel, scene.area_id)
            for scene in self._scenes_result
        ]

        # Create read tasks with semaphore limit
        read_tasks = [
            read_scene_with_limit(scene_id, channel)
            for scene_id, _, channel, _ in basic_scenes
        ]

        # Execute all reads with exception handling
        results = await asyncio.gather(*read_tasks, return_exceptions=True)

        # Phase 3: Construct Scene objects with device data
        scenes_with_devices: list[Scene] = []
        for (scene_id, name, channel, area_id), result in zip(basic_scenes, results):
            if isinstance(result, Exception):
                _LOGGER.error(
                    "Gateway %s: Failed to read scene %s (channel %s): %s",
                    self._gw_sn,
                    scene_id,
                    channel,
                    result,
                )
                continue

            # Successfully read scene data - result is Dict[str, Any]
            result_dict = cast("Dict[str, Any]", result)
            try:
                scene = Scene(
                    command_client=self,
                    scene_id=scene_id,
                    name=result_dict.get("name", name),
                    channel=channel,
                    area_id=result_dict.get("area_id", area_id),
                    devices=result_dict.get("devices", []),
                )
                scenes_with_devices.append(scene)
            except (KeyError, TypeError, ValueError) as e:
                _LOGGER.error(
                    "Gateway %s: Failed to create Scene object for scene %s: %s",
                    self._gw_sn,
                    scene_id,
                    e,
                )

        _LOGGER.info(
            "Gateway %s: Scene discovery completed, %d/%d scene(s) successfully read",
            self._gw_sn,
            len(scenes_with_devices),
            len(basic_scenes),
        )
        return scenes_with_devices

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

    def command_set_sensor_argv(
        self, dev_type: str, channel: int, address: int, param: SensorParamType
    ) -> None:
        """Set sensor parameters.

        Args:
            dev_type: Sensor device type code (e.g., "0201")
            channel: DALI channel number
            address: Device address
            param: Dictionary of sensor parameters to set (only provided fields will be set)
        """
        # Build data dict dynamically from provided fields
        # Convert snake_case Python keys to camelCase protocol keys
        param_mapping = {
            "enable": "enable",
            "occpy_time": "occpyTime",
            "report_time": "reportTime",
            "down_time": "downTime",
            "coverage": "coverage",
            "sensitivity": "sensitivity",
        }

        # Convert TypedDict to regular dict for iteration
        param_dict = dict(param)
        data: Dict[str, Any] = {}
        for python_key, protocol_key in param_mapping.items():
            if python_key in param_dict:
                data[protocol_key] = param_dict[python_key]

        if not data:
            _LOGGER.warning(
                "Gateway %s: No valid parameters provided for setSensorArgv",
                self._gw_sn,
            )
            return

        command: Dict[str, Any] = {
            "cmd": "setSensorArgv",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "devType": dev_type,
            "channel": channel,
            "address": address,
            "data": data,
        }
        command_json = json.dumps(command)
        _LOGGER.debug(
            "Gateway %s: Sending setSensorArgv command: %s", self._gw_sn, command
        )
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_get_sensor_argv(
        self, dev_type: str, channel: int, address: int
    ) -> None:
        """Get sensor parameters.

        Args:
            dev_type: Sensor device type code (e.g., "0201")
            channel: DALI channel number
            address: Device address
        """
        command: Dict[str, Any] = {
            "cmd": "getSensorArgv",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "devType": dev_type,
            "channel": channel,
            "address": address,
        }
        command_json = json.dumps(command)
        _LOGGER.debug(
            "Gateway %s: Sending getSensorArgv command: %s", self._gw_sn, command
        )
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_identify_dev(self, dev_type: str, channel: int, address: int) -> None:
        command: Dict[str, Any] = {
            "cmd": "identifyDev",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "data": {
                "devType": dev_type,
                "channel": channel,
                "address": address,
            },
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
            "fromBus": False,
        }
        command_json = json.dumps(command)
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_set_dev_param(
        self, dev_type: str, channel: int, address: int, param: DeviceParamType
    ) -> None:
        """Set device parameters.

        Args:
            dev_type: Device type code (e.g., "0101")
            channel: DALI channel number
            address: Device address
            param: Dictionary of device parameters to set (only provided fields will be set)
        """
        paramer = self._build_paramer(param)
        if not paramer:
            _LOGGER.warning(
                "Gateway %s: No valid parameters provided for setDevParam", self._gw_sn
            )
            return

        command: Dict[str, Any] = {
            "cmd": "setDevParam",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "data": [
                {
                    "devType": dev_type,
                    "channel": channel,
                    "address": address,
                    "paramer": paramer,
                }
            ],
        }
        command_json = json.dumps(command)
        _LOGGER.debug(
            "Gateway %s: Sending setDevParam command: %s", self._gw_sn, command
        )
        self._mqtt_client.publish(self._pub_topic, command_json)

    def command_set_dev_params(self, items: Sequence[DeviceParamCommand]) -> None:
        """Set parameters for multiple targets in one MQTT message."""
        data: List[Dict[str, Any]] = []

        for item in items:
            paramer = self._build_paramer(item["param"])
            if not paramer:
                _LOGGER.warning(
                    "Gateway %s: No valid parameters provided for %s",
                    self._gw_sn,
                    item,
                )
                continue

            data.append(
                {
                    "devType": item["dev_type"],
                    "channel": item["channel"],
                    "address": item["address"],
                    "paramer": paramer,
                }
            )

        if not data:
            _LOGGER.warning(
                "Gateway %s: No valid setDevParam payloads provided for batch send",
                self._gw_sn,
            )
            return

        command: Dict[str, Any] = {
            "cmd": "setDevParam",
            "msgId": str(int(time.time())),
            "gwSn": self._gw_sn,
            "data": data,
        }
        command_json = json.dumps(command)
        _LOGGER.debug(
            "Gateway %s: Sending batch setDevParam command: %s",
            self._gw_sn,
            command,
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
