"""Error codes for DALI Gateway operations"""


class ErrorCodes:
    """Centralized error codes for DALI Gateway operations"""

    # Connection related errors
    NETWORK_ERROR = "NETWORK_ERROR"
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    DISCONNECT_ERROR = "DISCONNECT_ERROR"
    SSL_CONFIG_ERROR = "SSL_CONFIG_ERROR"

    # Authentication related errors
    AUTH_REQUIRED = "AUTH_REQUIRED"          # Need to press gateway button
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"

    # MQTT specific errors
    MQTT_CONNECTION_REFUSED = "MQTT_CONNECTION_REFUSED"
    MQTT_PROTOCOL_ERROR = "MQTT_PROTOCOL_ERROR"
    MQTT_BROKER_UNAVAILABLE = "MQTT_BROKER_UNAVAILABLE"

    # Discovery related errors
    DISCOVERY_NO_INTERFACES = "DISCOVERY_NO_INTERFACES"
    DISCOVERY_TIMEOUT = "DISCOVERY_TIMEOUT"
    DISCOVERY_MESSAGE_ERROR = "DISCOVERY_MESSAGE_ERROR"
    DISCOVERY_FAILED = "DISCOVERY_FAILED"

    @classmethod
    def get_mqtt_error_code(cls, mqtt_result_code: int) -> str:
        """Convert MQTT result code to error code"""
        mqtt_error_map = {
            1: cls.MQTT_PROTOCOL_ERROR,
            2: cls.MQTT_BROKER_UNAVAILABLE,
            3: cls.MQTT_BROKER_UNAVAILABLE,
            4: cls.AUTH_REQUIRED,
            5: cls.AUTH_INVALID_CREDENTIALS,
        }
        return mqtt_error_map.get(
            mqtt_result_code, f"MQTT_ERROR_{mqtt_result_code}"
        )
