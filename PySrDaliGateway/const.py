"""Constants for the Dali Center."""

from importlib import resources

from .types import PanelConfig

DOMAIN = "dali_center"

DEVICE_MODEL_MAP = {
    "0101": "DALI DT6 Dimmable Driver",
    "0102": "DALI DT8 Tc Dimmable Driver",
    "0103": "DALI DT8 RGB Dimmable Driver",
    "0104": "DALI DT8 XY Dimmable Driver",
    "0105": "DALI DT8 RGBW Dimmable Driver",
    "0106": "DALI DT8 RGBWA Dimmable Driver",
    "0201": "DALI-2 Motion Sensor",
    "020101": "DALI-2 Motion Sensor",
    "020102": "DALI-2 Motion Sensor",
    "020103": "DALI-2 Motion Sensor",
    "020104": "DALI-2 Motion Sensor",
    "020105": "DALI-2 Motion Sensor",
    "020106": "DALI-2 Motion Sensor",
    "020107": "DALI-2 Motion Sensor",
    "020108": "DALI-2 Motion Sensor",
    "020109": "DALI-2 Motion Sensor",
    "020110": "DALI-2 Motion Sensor",
    "020111": "DALI-2 Motion Sensor",
    "020112": "DALI-2 Motion Sensor",
    "020113": "DALI-2 Motion Sensor",
    "020114": "DALI-2 Motion Sensor",
    "020115": "DALI-2 Motion Sensor",
    "020116": "DALI-2 Motion Sensor",
    "020117": "DALI-2 Motion Sensor",
    "020118": "DALI-2 Motion Sensor",
    "020119": "DALI-2 Motion Sensor",
    "020120": "DALI-2 Motion Sensor",
    "0202": "DALI-2 Illuminance Sensor",
    "0302": "DALI-2 2-Key Push Button Panel",
    "0304": "DALI-2 4-Key Push Button Panel",
    "0306": "DALI-2 6-Key Push Button Panel",
    "0308": "DALI-2 8-Key Push Button Panel",
}

DEVICE_TYPE_MAP = {
    "0101": "Dimmer",
    "0102": "CCT",
    "0103": "RGB",
    "0104": "XY",
    "0105": "RGBW",
    "0106": "RGBWA",
    "0201": "Motion",
    "020101": "Motion (1)",
    "020102": "Motion (2)",
    "020103": "Motion (3)",
    "020104": "Motion (4)",
    "020105": "Motion (5)",
    "020106": "Motion (6)",
    "020107": "Motion (7)",
    "020108": "Motion (8)",
    "020109": "Motion (9)",
    "020110": "Motion (10)",
    "020111": "Motion (11)",
    "020112": "Motion (12)",
    "020113": "Motion (13)",
    "020114": "Motion (14)",
    "020115": "Motion (15)",
    "020116": "Motion (16)",
    "020117": "Motion (17)",
    "020118": "Motion (18)",
    "020119": "Motion (19)",
    "020120": "Motion (20)",
    "0202": "Illuminance",
    "0302": "2-Key Panel",
    "0304": "4-Key Panel",
    "0306": "6-Key Panel",
    "0308": "8-Key Panel",
}

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

CA_CERT_PATH = resources.files("PySrDaliGateway") / "certs" / "ca.crt"
