"""Pytest configuration and fixtures for DALI Gateway hardware testing."""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List

import pytest

from PySrDaliGateway.device import Device
from PySrDaliGateway.discovery import DaliGatewayDiscovery
from PySrDaliGateway.group import Group
from PySrDaliGateway.helper import is_light_device
from PySrDaliGateway.scene import Scene

from .cache import GatewayCredentialCache
from .helpers import TestDaliGateway

_LOGGER = logging.getLogger(__name__)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom CLI options for gateway testing."""
    group = parser.getgroup("dali", "DALI Gateway testing options")

    # Direct connection mode
    group.addoption("--direct-sn", type=str, help="Gateway serial number (direct mode)")
    group.addoption("--direct-ip", type=str, help="Gateway IP address (direct mode)")
    group.addoption(
        "--direct-port",
        type=int,
        default=1883,
        help="Gateway MQTT port (default: 1883)",
    )
    group.addoption(
        "--direct-username", type=str, help="Gateway username (direct mode)"
    )
    group.addoption("--direct-passwd", type=str, help="Gateway password (direct mode)")
    group.addoption("--direct-tls", action="store_true", help="Use TLS connection")
    group.addoption("--direct-name", type=str, help="Gateway name (optional)")

    # Discovery mode
    group.addoption("--gateway-sn", type=str, help="Specific gateway SN to discover")
    group.addoption(
        "--gateway-index",
        type=int,
        default=0,
        help="Gateway index to connect to (default: 0)",
    )

    # Test options
    group.addoption(
        "--device-limit", type=int, help="Limit number of devices for testing"
    )


@pytest.fixture(scope="session")
def gateway_config(request: pytest.FixtureRequest) -> Dict[str, Any]:
    """Resolve gateway configuration from CLI args, cache, or discovery.

    Priority: direct CLI args > credential cache > UDP discovery.
    """
    direct_sn = request.config.getoption("--direct-sn")
    direct_ip = request.config.getoption("--direct-ip")
    direct_username = request.config.getoption("--direct-username")
    direct_passwd = request.config.getoption("--direct-passwd")

    # Direct mode: all required params provided
    if all([direct_sn, direct_ip, direct_username, direct_passwd]):
        _LOGGER.info("Using direct connection mode: %s at %s", direct_sn, direct_ip)
        return {
            "gw_sn": direct_sn,
            "gw_ip": direct_ip,
            "port": request.config.getoption("--direct-port"),
            "username": direct_username,
            "passwd": direct_passwd,
            "is_tls": request.config.getoption("--direct-tls"),
            "name": request.config.getoption("--direct-name"),
            "channel_total": None,
            "mode": "direct",
        }

    # Partial direct args is an error
    partial = [direct_sn, direct_ip, direct_username, direct_passwd]
    if any(partial):
        pytest.fail(
            "Direct mode requires all of: --direct-sn, --direct-ip, "
            "--direct-username, --direct-passwd"
        )

    # Cache mode
    cache = GatewayCredentialCache()
    if cache.has_cache():
        cached = cache.get_last_gateway()
        if cached:
            _LOGGER.info(
                "Using cached credentials for gateway %s (delete tests/.gateway_cache.json to force rediscovery)",
                cached["gw_sn"],
            )
            return {**cached, "mode": "cache"}

    # Discovery mode - will be handled async in connected_gateway fixture
    _LOGGER.info("No cached credentials, will use UDP discovery")
    return {
        "gateway_sn": request.config.getoption("--gateway-sn"),
        "gateway_index": request.config.getoption("--gateway-index"),
        "mode": "discovery",
    }


@pytest.fixture(scope="session")
async def connected_gateway(
    gateway_config: Dict[str, Any],
) -> TestDaliGateway:
    """Connect to a DALI gateway for the entire test session.

    Yields a connected TestDaliGateway instance. Disconnects on teardown.
    """
    mode = gateway_config["mode"]

    if mode == "discovery":
        # Run UDP discovery
        discovery = DaliGatewayDiscovery()
        gateway_sn = gateway_config.get("gateway_sn")
        gateway_index = gateway_config.get("gateway_index", 0)

        discovered = await discovery.discover_gateways(gateway_sn)
        if not discovered:
            pytest.fail(
                "No gateways discovered! Check network connectivity and gateway power."
            )

        if gateway_index >= len(discovered):
            pytest.fail(
                f"Gateway index {gateway_index} out of range (0-{len(discovered) - 1})"
            )

        gw = discovered[gateway_index]
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        gateway = TestDaliGateway(
            gw_sn=gw.gw_sn,
            gw_ip=gw.gw_ip,
            port=gw.port,
            username=gw.username,
            passwd=gw.passwd,
            name=gw.name,
            channel_total=gw.channel_total,
            is_tls=gw.is_tls,
            loop=loop,
        )
    else:
        # Direct or cache mode
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        gateway = TestDaliGateway(
            gw_sn=gateway_config["gw_sn"],
            gw_ip=gateway_config["gw_ip"],
            port=gateway_config.get("port", 1883),
            username=gateway_config["username"],
            passwd=gateway_config["passwd"],
            name=gateway_config.get("name"),
            channel_total=gateway_config.get("channel_total"),
            is_tls=gateway_config.get("is_tls", False),
            loop=loop,
        )

    _LOGGER.info(
        "Connecting to gateway '%s' (%s) at %s:%s (TLS: %s)...",
        gateway.name,
        gateway.gw_sn,
        gateway.gw_ip,
        gateway.port,
        gateway.is_tls,
    )

    await gateway.connect()

    _LOGGER.info("Connected to gateway successfully")

    # Save credentials to cache after successful connection
    if gateway.username and gateway.passwd:
        cache = GatewayCredentialCache()
        cache.save_gateway(gateway)

    yield gateway

    # Teardown: disconnect
    try:
        await gateway.disconnect()
        _LOGGER.info("Disconnected from gateway")
    except Exception:
        _LOGGER.warning("Error during gateway disconnect", exc_info=True)


@pytest.fixture(scope="session")
async def discovered_devices(connected_gateway: TestDaliGateway) -> List[Device]:
    """Discover devices on the connected gateway."""
    devices = await connected_gateway.discover_devices()
    _LOGGER.info("Discovered %d device(s)", len(devices))
    return devices


@pytest.fixture(scope="session")
async def discovered_groups(connected_gateway: TestDaliGateway) -> List[Group]:
    """Discover groups on the connected gateway."""
    groups = await connected_gateway.discover_groups()
    _LOGGER.info("Discovered %d group(s)", len(groups))
    return groups


@pytest.fixture(scope="session")
async def discovered_scenes(connected_gateway: TestDaliGateway) -> List[Scene]:
    """Discover scenes on the connected gateway."""
    scenes = await connected_gateway.discover_scenes()
    _LOGGER.info("Discovered %d scene(s)", len(scenes))
    return scenes


@pytest.fixture(scope="session")
async def ensured_groups(
    connected_gateway: TestDaliGateway,
    discovered_groups: List[Group],
    discovered_devices: List[Device],
) -> List[Group]:
    """Ensure at least one group exists. Creates a test group if none found."""
    if discovered_groups:
        return discovered_groups

    assert discovered_devices, "No devices available to create a test group"

    _LOGGER.info("No groups found, creating a test group...")
    await asyncio.sleep(3.0)

    group_id = 0
    group_name = f"test_group_{int(time.time())}"
    device_data = [
        {"devType": d.dev_type, "channel": d.channel, "address": d.address}
        for d in discovered_devices[:3]
    ]

    payload = {
        "cmd": "addGroup",
        "msgId": str(int(time.time() * 1000)),
        "gwSn": connected_gateway.gw_sn,
        "channel": 0,
        "groupId": group_id,
        "crossGateway": "yes",
        "name": group_name,
        "areaId": "0001",
        "data": device_data,
    }
    connected_gateway._mqtt_client.publish(
        connected_gateway._pub_topic, json.dumps(payload)
    )

    _LOGGER.info("Waiting for addGroupRes...")
    await asyncio.sleep(7.0)

    groups = await connected_gateway.discover_groups()
    assert groups, "Failed to create test group"
    _LOGGER.info("Ensured %d group(s) available", len(groups))
    return groups


@pytest.fixture(scope="session")
async def ensured_scenes(
    connected_gateway: TestDaliGateway,
    discovered_scenes: List[Scene],
    discovered_devices: List[Device],
) -> List[Scene]:
    """Ensure at least one scene exists. Creates a test scene if none found."""
    if discovered_scenes:
        return discovered_scenes

    light_devices = [d for d in discovered_devices if is_light_device(d.dev_type)]
    assert light_devices, "No light devices available to create a test scene"

    _LOGGER.info("No scenes found, creating a test scene...")

    scene_id = 0
    scene_name = f"test_scene_{int(time.time())}"
    scene_device_data = [
        {
            "gwSnObj": connected_gateway.gw_sn,
            "devType": d.dev_type,
            "channel": d.channel,
            "address": d.address,
            "property": [
                {"dpid": 22, "dataType": "uint16", "value": 128},
                {"dpid": 23, "dataType": "uint16", "value": 4000},
            ],
        }
        for d in light_devices[:2]
    ]

    payload = {
        "cmd": "addScene",
        "msgId": str(int(time.time() * 1000)),
        "gwSn": connected_gateway.gw_sn,
        "channel": 0,
        "sceneId": scene_id,
        "crossGateway": "yes",
        "name": scene_name,
        "areaId": "0001",
        "data": {"objType": "device", "device": scene_device_data},
    }
    connected_gateway._mqtt_client.publish(
        connected_gateway._pub_topic, json.dumps(payload)
    )

    _LOGGER.info("Waiting for addSceneRes...")
    await asyncio.sleep(7.0)

    scenes = await connected_gateway.discover_scenes()
    assert scenes, "Failed to create test scene"
    _LOGGER.info("Ensured %d scene(s) available", len(scenes))
    return scenes
