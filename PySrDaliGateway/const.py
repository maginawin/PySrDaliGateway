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

CA_CERT_PATH = resources.files("PySrDaliGateway") / "certs" / "ca.crt"
