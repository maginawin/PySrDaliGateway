# PySrDaliGateway

Python SDK that discovers, connects to, and controls Sunricher DALI gateways and their attached DALI devices, groups, and scenes over LAN UDP multicast and MQTT.

## Language

**Gateway**:
A Sunricher DALI EDA bridge on the local network that exposes DALI bus devices, groups, and scenes over MQTT.
_Avoid_: Hub, bridge, controller

**Control Command**:
An outbound action sent to a **Gateway** to change device, group, scene, or gateway state (such as turning lights on/off, identifying a device, activating a scene, updating parameters, or restarting). A **Control Command** succeeds once published to a connected MQTT session and raises on disconnect or publish failure.
_Avoid_: Action, mutation, write request

**Status Query**:
A best-effort outbound read sent to a **Gateway** to refresh device or energy state (such as `readDev` or `getEnergy`). A **Status Query** is dropped silently when the **Gateway** is disconnected rather than failing caller initialization.
_Avoid_: Poll, read command

**Command Batch**:
A short aggregation window in which concurrent outbound device messages for the same command type are merged into a single MQTT payload to avoid overloading a **Gateway**.
_Avoid_: Queue, buffer
