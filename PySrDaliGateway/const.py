"""Constants for the Dali Center."""

from importlib import resources

from .types import PanelConfig

DOMAIN = "dali_center"

# DALI Protocol Data Point IDs (DPID)
# These constants represent the standard DALI protocol property identifiers
DPID_POWER = 20  # Power state (on/off)
DPID_WHITE_LEVEL = 21  # White level for RGBW devices (0-255)
DPID_BRIGHTNESS = 22  # Brightness level (0-1000, maps to 0-100%)
DPID_COLOR_TEMP = 23  # Color temperature in Kelvin
DPID_HSV_COLOR = 24  # HSV color as hex string
DPID_ENERGY = 30  # Energy consumption value

# Base device model mappings
_BASE_DEVICE_MODEL_MAP: dict[str, str] = {
    "0101": "DALI DT6 Dimmable Driver",
    "0102": "DALI DT8 Tc Dimmable Driver",
    "0103": "DALI DT8 RGB Dimmable Driver",
    "0104": "DALI DT8 XY Dimmable Driver",
    "0105": "DALI DT8 RGBW Dimmable Driver",
    "0106": "DALI DT8 RGBWA Dimmable Driver",
    "0201": "DALI-2 Motion Sensor",
    "0202": "DALI-2 Illuminance Sensor",
    "0302": "DALI-2 2-Key Push Button Panel",
    "0304": "DALI-2 4-Key Push Button Panel",
    "0306": "DALI-2 6-Key Push Button Panel",
    "0308": "DALI-2 8-Key Push Button Panel",
}

# Generate motion sensor variants (020101-020120) dynamically
_MOTION_SENSOR_VARIANTS = {f"0201{i:02d}": "DALI-2 Motion Sensor" for i in range(1, 21)}

DEVICE_MODEL_MAP: dict[str, str] = {**_BASE_DEVICE_MODEL_MAP, **_MOTION_SENSOR_VARIANTS}

# Base device type mappings (human-readable names)
_BASE_DEVICE_TYPE_MAP: dict[str, str] = {
    "0101": "Dimmer",
    "0102": "CCT",
    "0103": "RGB",
    "0104": "XY",
    "0105": "RGBW",
    "0106": "RGBWA",
    "0201": "Motion",
    "0202": "Illuminance",
    "0302": "2-Key Panel",
    "0304": "4-Key Panel",
    "0306": "6-Key Panel",
    "0308": "8-Key Panel",
}

# Generate motion sensor type variants (020101-020120) dynamically
_MOTION_TYPE_VARIANTS = {f"0201{i:02d}": f"Motion ({i})" for i in range(1, 21)}

DEVICE_TYPE_MAP: dict[str, str] = {**_BASE_DEVICE_TYPE_MAP, **_MOTION_TYPE_VARIANTS}

COLOR_MODE_MAP = {
    "0102": "color_temp",  # CCT
    "0103": "hs",  # RGB
    "0104": "hs",  # XY
    "0105": "rgbw",  # RGBW
    "0106": "rgbw",  # RGBWA
}

BUTTON_EVENTS = {
    1: "press",
    2: "hold",
    3: "double_press",
    4: "rotate",
    5: "release",
}

PANEL_CONFIGS: dict[str, PanelConfig] = {
    "0302": {  # 2-button panel
        "button_count": 2,
        "events": ["press", "hold", "double_press", "release"],
    },
    "0304": {  # 4-button panel
        "button_count": 4,
        "events": ["press", "hold", "double_press", "release"],
    },
    "0306": {  # 6-button panel
        "button_count": 6,
        "events": ["press", "hold", "double_press", "release"],
    },
    "0308": {  # 8-button panel
        "button_count": 8,
        "events": ["press", "hold", "double_press", "release"],
    },
    "0300": {  # rotary knob panel
        "button_count": 1,
        "events": ["press", "double_press", "rotate"],
    },
}

INBOUND_CALLBACK_BATCH_WINDOW_MS = 100

# Concurrency limits for MQTT operations
MAX_CONCURRENT_READS = 3  # Limit parallel read operations to avoid MQTT message storms

CA_CERT_PATH = resources.files("PySrDaliGateway") / "certs" / "ca.crt"

# Protocol key mappings for device parameters
# Maps snake_case Python keys to camelCase protocol keys
DEVICE_PARAM_KEY_MAP: dict[str, str] = {
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

# Reverse mapping: protocol keys to Python keys
DEVICE_PARAM_PROTOCOL_KEY_MAP: dict[str, str] = {
    v: k for k, v in DEVICE_PARAM_KEY_MAP.items()
}

# Protocol key mappings for sensor parameters
SENSOR_PARAM_KEY_MAP: dict[str, str] = {
    "enable": "enable",
    "occpy_time": "occpyTime",
    "report_time": "reportTime",
    "down_time": "downTime",
    "coverage": "coverage",
    "sensitivity": "sensitivity",
}

# Reverse mapping: protocol keys to Python keys
SENSOR_PARAM_PROTOCOL_KEY_MAP: dict[str, str] = {
    v: k for k, v in SENSOR_PARAM_KEY_MAP.items()
}
