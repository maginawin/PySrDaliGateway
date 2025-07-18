"""Constants for the Dali Center."""

from importlib import resources

DOMAIN = "dali_center"

DEVICE_TYPE_MAP = {
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

COLOR_MODE_MAP = {
    "0102": "color_temp",  # CCT
    "0103": "hs",          # RGB
    "0104": "hs",          # XY
    "0105": "rgbw",        # RGBW
    "0106": "rgbw",        # RGBWA
}

BUTTON_EVENTS = {
    1: "single_click",
    2: "long_press",
    3: "double_click",
    4: "rotate",
    5: "long_press_stop",
}

CA_CERT_PATH = resources.files("PySrDaliGateway") / "certs" / "ca.crt"
