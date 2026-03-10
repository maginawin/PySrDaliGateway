# PySrDaliGateway

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

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

## Testing

Hardware integration tests use pytest with real DALI gateway hardware.

### Setup

```bash
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run default tests (excludes destructive and slow tests)
pytest tests/

# Run all tests including slow (bus scan) tests
pytest tests/ -m ""

# Run only bus scan tests
pytest tests/ -m slow

# Run only destructive tests (e.g. gateway restart)
pytest tests/ -m destructive

# Run a specific test file
pytest tests/test_devices.py -v

# Limit device iterations for faster testing
pytest tests/ --device-limit 3
```

### Gateway Connection

Tests connect to a real gateway using one of three methods (in priority order):

1. **CLI parameters** — provide credentials directly:

   ```bash
   pytest tests/ --direct-sn GW123456 --direct-ip 192.168.1.100 \
     --direct-username admin --direct-passwd password123
   ```

2. **Credential cache** — reuses credentials from a previous session, stored in `tests/.gateway_cache.json`
3. **UDP discovery** — auto-discovers gateways on the local network

### Test Markers

| Marker        | Default | Description                                     |
| ------------- | ------- | ----------------------------------------------- |
| `destructive` | skip    | Tests that disrupt gateway state (e.g. restart) |
| `slow`        | skip    | Long-running tests (e.g. bus scan >30s)         |

### Test Files

| File                 | Coverage                                                  |
| -------------------- | --------------------------------------------------------- |
| `test_connection.py` | Discovery, connect, disconnect, reconnection              |
| `test_gateway.py`    | Version, status sync, restart (destructive)               |
| `test_devices.py`    | Device discovery, read, control, CCT range, sensor params |
| `test_groups.py`     | Group discovery, read, control, brightness                |
| `test_scenes.py`     | Scene discovery, read, scene devices                      |
| `test_callbacks.py`  | Real-time device status callbacks                         |
| `test_bus_scan.py`   | Bus scan, stop scan (slow)                                |
