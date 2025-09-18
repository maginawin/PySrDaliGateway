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
- paho-mqtt>=1.6.0

## CLI Testing Tool

Testing script located at `script/test_discovery_to_connect.py` for hardware validation:

```bash
# Run all tests
python script/test_discovery_to_connect.py

# Run specific tests
python script/test_discovery_to_connect.py --tests discovery connection devices

# List available tests
python script/test_discovery_to_connect.py --list-tests

# Test device callbacks specifically
python script/test_discovery_to_connect.py --tests callbacks

# Test with specific gateway
python script/test_discovery_to_connect.py --gateway-sn "YOUR_GATEWAY_SN"

# Limit device operations for faster testing
python script/test_discovery_to_connect.py --device-limit 5

# Testing mode (skip discovery) - when you know gateway parameters
python script/test_discovery_to_connect.py \
  --direct-sn GW123456 \
  --direct-ip 192.168.1.100 \
  --direct-username admin \
  --direct-passwd password123
```

Available tests:

- `discovery` - Discover DALI gateways on network
- `connection` - Connect to discovered gateway
- `version` - Get gateway firmware version
- `devices` - Discover connected DALI devices
- `readdev` - Read device status via MQTT
- `callbacks` - Test device status callbacks (light, motion, illuminance, panel)
- `devparam` - Get device parameters
- `groups` - Discover DALI groups
- `readgroup` - Read group details with device list
- `scenes` - Discover DALI scenes
- `readscene` - Read scene details with device list and property values
- `restart` - Restart gateway (WARNING: gateway will disconnect)
- `reconnection` - Test disconnect/reconnect cycle
