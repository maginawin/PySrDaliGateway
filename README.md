# PySrDaliGateway

Python library for Sunricher DALI Gateway (EDA) integration with Home Assistant.

## Features

- Async/await support for non-blocking operations
- Device discovery and control (lights, sensors, panels)
- Group and scene management
- Real-time status updates via MQTT
- Energy monitoring support
- **Full Type Support**: Complete type hints for mypy, Pylance, and pyright
- IDE integration with auto-completion and error checking

## Installation

```bash
pip install PySrDaliGateway
```

## Device Types Supported

- **Lighting**: Dimmer, CCT, RGB, RGBW, RGBWA
- **Sensors**: Motion, Illuminance  
- **Panels**: 2-Key, 4-Key, 6-Key, 8-Key

## Requirements

- Python 3.8+
- paho-mqtt>=2.0.0

## CLI Testing Tool

Testing script located at `script/test_discovery_to_connect.py` for hardware validation:

```bash
# Run all tests
python script/test_discovery_to_connect.py

# Run specific tests
python script/test_discovery_to_connect.py --tests discovery connection devices

# List available tests
python script/test_discovery_to_connect.py --list-tests

# Test with specific gateway
python script/test_discovery_to_connect.py --gateway-sn "YOUR_GATEWAY_SN"

# Limit device operations for faster testing
python script/test_discovery_to_connect.py --device-limit 5
```

Available tests:

- `discovery` - Discover DALI gateways on network
- `connection` - Connect to discovered gateway
- `version` - Get gateway firmware version
- `devices` - Discover connected DALI devices
- `readdev` - Read device status via MQTT
- `devparam` - Get device parameters
- `groups` - Discover DALI groups
- `scenes` - Discover DALI scenes
- `reconnection` - Test disconnect/reconnect cycle
