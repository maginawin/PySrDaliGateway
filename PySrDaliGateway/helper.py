"""Helper functions for Dali Gateway"""

import colorsys
from typing import Any, Dict, List

from .const import BUTTON_EVENTS, DEVICE_TYPE_MAP
from .types import (
    IlluminanceStatus,
    LightStatus,
    MotionState,
    MotionStatus,
    PanelEventType,
    PanelStatus,
)


def is_light_device(dev_type: str) -> bool:
    return dev_type.startswith("01")


def is_motion_sensor(dev_type: str) -> bool:
    return dev_type.startswith("0201")


def is_illuminance_sensor(dev_type: str) -> bool:
    return dev_type == "0202"


def is_panel_device(dev_type: str) -> bool:
    return dev_type.startswith("03")


def is_sensor_device(dev_type: str) -> bool:
    return is_motion_sensor(dev_type) or is_illuminance_sensor(dev_type)


def gen_device_unique_id(dev_type: str, channel: int, address: int, gw_sn: str) -> str:
    return f"{dev_type}{channel:04d}{address:02d}{gw_sn}"


def gen_device_name(dev_type: str, channel: int, address: int) -> str:
    if dev_type in DEVICE_TYPE_MAP:
        type_name = DEVICE_TYPE_MAP[dev_type]
        return f"{type_name} {channel:04d}-{address:02d}"
    if dev_type:
        return f"Device {dev_type} {channel:04d}-{address:02d}"
    raise ValueError(f"Invalid device type: {dev_type}")


def gen_group_unique_id(group_id: int, channel: int, gw_sn: str) -> str:
    return f"group_{group_id:04d}_{channel:04d}_{gw_sn}"


def gen_scene_unique_id(scene_id: int, channel: int, gw_sn: str) -> str:
    return f"scene_{scene_id:04d}_{channel:04d}_{gw_sn}"


def parse_light_status(property_list: List[Dict[str, Any]]) -> LightStatus:
    """Parse raw property list into LightStatus object for light devices"""

    props: Dict[int, Any] = {}
    for prop in property_list:
        prop_id = prop.get("id") or prop.get("dpid")
        value = prop.get("value")
        if prop_id is not None and value is not None:
            props[prop_id] = value

    light_status: LightStatus = {
        "is_on": None,
        "brightness": None,
        "color_temp_kelvin": None,
        "hs_color": None,
        "rgbw_color": None,
        "white_level": None,
    }

    if 20 in props:
        light_status["is_on"] = bool(props[20])

    if 21 in props:
        white_level = int(props[21])
        light_status["white_level"] = min(255, max(0, white_level))
        if light_status["rgbw_color"] is not None:
            r, g, b, _ = light_status["rgbw_color"]
            light_status["rgbw_color"] = (r, g, b, white_level)

    if 22 in props:
        brightness_value = float(props[22])
        if brightness_value == 0 and light_status["brightness"] is None:
            light_status["brightness"] = 255
        else:
            light_status["brightness"] = int(brightness_value / 1000 * 255)

    if 23 in props:
        light_status["color_temp_kelvin"] = int(props[23])

    if 24 in props:
        hsv_str = str(props[24])

        h = int(hsv_str[0:4], 16)
        s = int(hsv_str[4:8], 16)

        if len(hsv_str) == 8:
            s_percentage = s / 10
            light_status["hs_color"] = (float(h), float(s_percentage))

        elif len(hsv_str) >= 12:
            v = int(hsv_str[8:12], 16)

            h_norm = max(0, min(360, h)) / 360.0
            s_norm = max(0, min(1000, s)) / 1000.0
            v_norm = max(0, min(1000, v)) / 1000.0

            if v_norm == 0:
                v_norm = 1

            rgb = colorsys.hsv_to_rgb(h_norm, s_norm, v_norm)
            w = (
                light_status["white_level"]
                if light_status["white_level"] is not None
                else 0
            )

            light_status["rgbw_color"] = (
                int(rgb[0] * 255),
                int(rgb[1] * 255),
                int(rgb[2] * 255),
                w,
            )

    return light_status


def parse_panel_status(property_list: List[Dict[str, Any]]) -> List[PanelStatus]:
    """Parse raw property list into PanelStatus objects for panel devices"""

    panel_events: List[PanelStatus] = []

    for prop in property_list:
        dpid = prop.get("dpid")
        key_no = prop.get("keyNo")
        value = prop.get("value")

        if dpid is None or key_no is None:
            continue

        event_type_str = BUTTON_EVENTS.get(dpid)
        if not event_type_str:
            continue

        # Convert string to enum
        try:
            event_type = PanelEventType(event_type_str)
        except ValueError:
            continue

        event_name = f"button_{key_no}_{event_type_str}"

        panel_status: PanelStatus = {
            "event_name": event_name,
            "key_no": key_no,
            "event_type": event_type,
            "rotate_value": value if event_type == PanelEventType.ROTATE else None,
        }

        panel_events.append(panel_status)

    return panel_events


def parse_motion_status(property_list: List[Dict[str, Any]]) -> List[MotionStatus]:
    """Parse raw property list into MotionStatus objects for motion sensor devices"""

    motion_events: List[MotionStatus] = []

    # Motion state mapping based on dpid values
    motion_map = {
        1: MotionState.NO_MOTION,
        2: MotionState.MOTION,
        3: MotionState.VACANT,
        4: MotionState.OCCUPANCY,
        5: MotionState.PRESENCE,
    }

    for prop in property_list:
        dpid = prop.get("dpid")

        if dpid is None:
            continue

        motion_state = motion_map.get(dpid)
        if motion_state is None:
            # Default to no_motion for unknown dpid values
            motion_state = MotionState.NO_MOTION

        motion_status: MotionStatus = {
            "motion_state": motion_state,
            "dpid": dpid,
        }

        motion_events.append(motion_status)

    return motion_events


def parse_illuminance_status(
    property_list: List[Dict[str, Any]],
) -> List[IlluminanceStatus]:
    """Parse raw property list into IlluminanceStatus objects for illuminance sensor devices"""

    illuminance_events: List[IlluminanceStatus] = []

    for prop in property_list:
        dpid = prop.get("dpid")
        value = prop.get("value")

        # Handle illuminance sensor status (dpid 4 for illuminance value)
        if dpid == 4 and value is not None:
            try:
                illuminance_value = float(value)
                # Check if value is within valid range
                is_valid = not (illuminance_value > 1000 or illuminance_value <= 0)

                illuminance_status: IlluminanceStatus = {
                    "illuminance_value": illuminance_value,
                    "is_valid": is_valid,
                }

                illuminance_events.append(illuminance_status)
            except (ValueError, TypeError):
                # Skip invalid values
                continue

    return illuminance_events
