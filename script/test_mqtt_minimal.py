#!/usr/bin/env python3
"""Minimal MQTT test case for Sunricher DALI Gateway troubleshooting."""

import logging
import ssl
import time

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

_LOGGER = logging.getLogger(__name__)


def on_connect(client, userdata, flags, rc, properties):  # pylint: disable=unused-argument
    """Handle MQTT connection callback."""
    if rc == 0:
        _LOGGER.info("✓ Connected successfully")
    else:
        _LOGGER.error("✗ Connection failed: %s", rc)


def on_disconnect(client, userdata, disconnect_flags, rc, properties):  # pylint: disable=unused-argument
    """Handle MQTT disconnection callback."""
    _LOGGER.info("Disconnected: %s", rc)


def on_log(client, userdata, level, buf):  # pylint: disable=unused-argument
    """Handle MQTT log callback."""
    _LOGGER.info("[MQTT] %s", buf)


def main():
    """Main test function."""
    _LOGGER.info("=== Sunricher DALI Gateway MQTT Test ===")

    # Create MQTT client
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="test_client",
        protocol=mqtt.MQTTv311
    )

    # Set up SSL context
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.load_verify_locations("PySrDaliGateway/certs/ca.crt")
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED

    # Set callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_log = on_log

    # Configure TLS
    client.tls_set_context(context)

    # Optional: Try with authentication
    # client.username_pw_set("admin", "admin")

    try:
        _LOGGER.info("Connecting to 192.168.xxx.xxx:8883...")
        client.connect("192.168.xxx.xx", 8883, 60)
        client.loop_start()

        time.sleep(10)

        client.loop_stop()
        client.disconnect()

    except (ConnectionError, ssl.SSLError, OSError) as e:
        _LOGGER.error("Error: %s", e)

if __name__ == "__main__":
    main()
