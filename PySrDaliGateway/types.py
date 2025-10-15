"""Dali Gateway Types"""

from enum import Enum
from typing import Callable, List, Tuple, TypedDict


class PanelEventType(Enum):
    """Panel button event types"""

    PRESS = "press"
    HOLD = "hold"
    DOUBLE_PRESS = "double_press"
    ROTATE = "rotate"
    RELEASE = "release"


class MotionState(Enum):
    """Motion sensor state types"""

    NO_MOTION = "no_motion"
    MOTION = "motion"
    VACANT = "vacant"
    OCCUPANCY = "occupancy"
    PRESENCE = "presence"


class DeviceProperty:
    dpid: int
    data_type: str


class SceneDeviceProperty(TypedDict):
    dpid: int
    data_type: str
    value: int


class LightStatus(TypedDict):
    """Status for lighting devices (Dimmer, CCT, RGB, RGBW, RGBWA)"""

    is_on: bool | None
    brightness: int | None  # 0-255
    color_temp_kelvin: int | None
    hs_color: Tuple[float, float] | None  # hue (0-360), saturation (0-100)
    rgbw_color: Tuple[int, int, int, int] | None  # r,g,b,w (0-255 each)
    white_level: int | None  # 0-255


class SceneDeviceType(TypedDict):
    dev_type: str
    channel: int
    address: int
    gw_sn_obj: str
    property: LightStatus


class VersionType(TypedDict):
    software: str
    firmware: str


class DeviceParamType(TypedDict):
    # address: int
    # fade_time: int
    # fade_rate: int
    # power_status: int
    # system_failure_status: int
    max_brightness: int
    # min_brightness: int
    # standby_power: int
    # max_power: int
    # cct_cool: int
    # cct_warm: int
    # phy_cct_cool: int
    # phy_cct_warm: int
    # step_cct: int
    # temp_thresholds: int
    # runtime_thresholds: int


class PanelConfig(TypedDict):
    """Panel configuration type definition."""

    button_count: int
    events: List[str]


class PanelStatus(TypedDict):
    """Status for control panels (2-Key, 4-Key, 6-Key, 8-Key)"""

    event_name: str  # button_{key_no}_{event_type}
    key_no: int  # Button number
    event_type: PanelEventType  # press, hold, double_press, rotate, release
    rotate_value: int | None  # For rotate events (only for rotate event type)


class MotionStatus(TypedDict):
    """Status for motion sensor devices"""

    motion_state: MotionState
    dpid: int  # The original dpid that triggered this state


class IlluminanceStatus(TypedDict):
    """Status for illuminance sensor devices"""

    illuminance_value: float  # Illuminance in lux
    is_valid: bool  # Whether the value is within valid range (0-1000)


LightStatusCallback = Callable[[LightStatus], None]
PanelStatusCallback = Callable[[PanelStatus], None]
MotionStatusCallback = Callable[[MotionStatus], None]
IlluminanceStatusCallback = Callable[[IlluminanceStatus], None]
