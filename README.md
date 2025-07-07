# PySrDaliGateway

Python library for Sunricher DALI Gateway (EDA) integration with Home Assistant.

## Features

- Async/await support for non-blocking operations
- Device discovery and control (lights, sensors, panels)
- Group and scene management
- Real-time status updates via MQTT
- Energy monitoring support
- Type hints for better development experience

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
