"""Helper functions for Dali Gateway"""

from .const import DEVICE_TYPE_MAP


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
