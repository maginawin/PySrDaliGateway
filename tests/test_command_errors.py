"""Unit tests for command error handling without gateway hardware."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import paho.mqtt.client as paho_mqtt
import pytest

from PySrDaliGateway import DaliGateway, Device, Group, Scene
from PySrDaliGateway.exceptions import DaliGatewayError
from PySrDaliGateway.gateway import ConnectionState

GATEWAY_SERIAL = "6A242121110E"


def _create_gateway(
    *,
    connected: bool = True,
    publish_rc: int = paho_mqtt.MQTT_ERR_SUCCESS,
    loop: asyncio.AbstractEventLoop | None = None,
) -> tuple[DaliGateway, MagicMock]:
    """Create a gateway with a mocked MQTT client."""
    mock_client = MagicMock()
    mock_client.publish.return_value = SimpleNamespace(rc=publish_rc)
    with patch("PySrDaliGateway.gateway.paho_mqtt.Client", return_value=mock_client):
        gateway = DaliGateway(
            GATEWAY_SERIAL,
            "192.0.2.1",
            1883,
            "test_user",
            "test_password",
            loop=loop,
        )
    if connected:
        gateway._connection_state = ConnectionState.CONNECTED
    return gateway, mock_client


def _create_device(gateway: DaliGateway, address: int = 1) -> Device:
    """Create a dimmable light device bound to *gateway*."""
    return Device(
        command_client=gateway,
        unique_id=f"{GATEWAY_SERIAL}_0101_0_{address}",
        dev_id=f"0101_0_{address}",
        name=f"Light {address}",
        dev_type="0101",
        channel=0,
        address=address,
        status="online",
        dev_sn=f"sn_{address}",
        area_name="Room",
        area_id="1",
        model="Dimmer",
    )


def _create_scene(gateway: DaliGateway) -> Scene:
    """Create a scene bound to *gateway*."""
    return Scene(
        command_client=gateway,
        scene_id=1,
        name="Evening",
        channel=0,
        area_id="1",
        devices=[],
    )


def _create_group(gateway: DaliGateway) -> Group:
    """Create a group bound to *gateway*."""
    return Group(
        command_client=gateway,
        group_id=1,
        name="Living Room",
        channel=0,
        area_id="1",
        devices=[],
    )


def test_direct_commands_raise_when_disconnected() -> None:
    """Direct publish commands must raise DaliGatewayError when disconnected."""
    gateway, mock_client = _create_gateway(connected=False)
    device = _create_device(gateway)
    scene = _create_scene(gateway)
    group = _create_group(gateway)

    with pytest.raises(DaliGatewayError, match="not connected"):
        device.identify()
    with pytest.raises(DaliGatewayError, match="not connected"):
        scene.activate()
    with pytest.raises(DaliGatewayError, match="not connected"):
        group.turn_on(brightness=128)
    with pytest.raises(DaliGatewayError, match="not connected"):
        group.turn_off()
    with pytest.raises(DaliGatewayError, match="not connected"):
        device.set_sensor_enabled(True)
    with pytest.raises(DaliGatewayError, match="not connected"):
        device.set_sensor_parameters({"enable": True})
    with pytest.raises(DaliGatewayError, match="not connected"):
        device.set_device_parameters({"fade_time": 1})
    with pytest.raises(DaliGatewayError, match="not connected"):
        gateway.command_set_dev_params(
            [
                {
                    "dev_type": "0101",
                    "channel": 0,
                    "address": 1,
                    "param": {"fade_time": 1},
                }
            ]
        )
    with pytest.raises(DaliGatewayError, match="not connected"):
        gateway.restart_gateway()

    mock_client.publish.assert_not_called()


def test_direct_commands_raise_on_nonzero_publish_rc() -> None:
    """Direct publish commands must raise DaliGatewayError when paho returns an error rc."""
    gateway, mock_client = _create_gateway(
        connected=True, publish_rc=paho_mqtt.MQTT_ERR_NO_CONN
    )
    device = _create_device(gateway)
    scene = _create_scene(gateway)
    group = _create_group(gateway)

    with pytest.raises(DaliGatewayError, match="Failed to publish 'identifyDev'"):
        device.identify()
    with pytest.raises(DaliGatewayError, match="Failed to publish 'writeScene'"):
        scene.activate()
    with pytest.raises(DaliGatewayError, match="Failed to publish 'writeGroup'"):
        group.turn_on()
    with pytest.raises(DaliGatewayError, match="Failed to publish 'setDevParam'"):
        device.set_device_parameters({"fade_time": 1})

    assert mock_client.publish.call_count == 4


def test_direct_commands_succeed_when_connected() -> None:
    """Direct publish commands succeed when connected and publish returns MQTT_ERR_SUCCESS."""
    gateway, mock_client = _create_gateway(connected=True)
    device = _create_device(gateway)
    scene = _create_scene(gateway)

    device.identify()
    scene.activate()

    assert mock_client.publish.call_count == 2
    identify_payload = json.loads(mock_client.publish.call_args_list[0].args[1])
    scene_payload = json.loads(mock_client.publish.call_args_list[1].args[1])
    assert identify_payload["cmd"] == "identifyDev"
    assert scene_payload["cmd"] == "writeScene"


async def test_async_turn_on_batches_concurrent_devices() -> None:
    """Concurrent async_turn_on calls merge into one MQTT writeDev message."""
    loop = asyncio.get_running_loop()
    gateway, mock_client = _create_gateway(connected=True, loop=loop)
    light_1 = _create_device(gateway, address=1)
    light_2 = _create_device(gateway, address=2)

    await asyncio.gather(
        light_1.async_turn_on(brightness=255),
        light_2.async_turn_off(),
    )

    mock_client.publish.assert_called_once()
    payload = json.loads(mock_client.publish.call_args.args[1])
    assert payload["cmd"] == "writeDev"
    assert len(payload["data"]) == 2
    by_addr = {item["address"]: item["property"] for item in payload["data"]}
    assert {prop["dpid"] for prop in by_addr[1]} == {20, 22}
    assert by_addr[2] == [{"dpid": 20, "dataType": "bool", "value": False}]


async def test_async_turn_on_raises_immediately_when_disconnected() -> None:
    """async_turn_on/off raises immediately without scheduling a batch when disconnected."""
    loop = asyncio.get_running_loop()
    gateway, mock_client = _create_gateway(connected=False, loop=loop)
    light = _create_device(gateway)

    with pytest.raises(DaliGatewayError, match="not connected"):
        await light.async_turn_on(brightness=128)
    with pytest.raises(DaliGatewayError, match="not connected"):
        await light.async_turn_off()

    mock_client.publish.assert_not_called()
    assert not gateway._batch_timer
    assert not gateway._batch_futures


async def test_async_turn_on_propagates_batch_publish_failure() -> None:
    """Non-zero publish rc during _flush_batch fails every awaiting caller."""
    loop = asyncio.get_running_loop()
    gateway, mock_client = _create_gateway(
        connected=True,
        publish_rc=paho_mqtt.MQTT_ERR_QUEUE_SIZE,
        loop=loop,
    )
    light_1 = _create_device(gateway, address=1)
    light_2 = _create_device(gateway, address=2)

    results = await asyncio.gather(
        light_1.async_turn_on(),
        light_2.async_turn_off(),
        return_exceptions=True,
    )

    mock_client.publish.assert_called_once()
    assert len(results) == 2
    for result in results:
        assert isinstance(result, DaliGatewayError)
        assert "Failed to publish 'writeDev'" in str(result)


async def test_async_turn_on_fails_when_disconnected_during_batch_window() -> None:
    """Disconnecting while a batch is queued fails pending callers immediately."""
    loop = asyncio.get_running_loop()
    gateway, mock_client = _create_gateway(connected=True, loop=loop)
    light = _create_device(gateway)

    task = asyncio.create_task(light.async_turn_on(brightness=100))
    await asyncio.sleep(0)

    await gateway.disconnect()

    with pytest.raises(
        DaliGatewayError, match="disconnected before sending 'writeDev'"
    ):
        await task

    mock_client.publish.assert_not_called()
    assert not gateway._batch_timer
    assert not gateway._batch_futures


async def test_async_turn_on_fails_on_unexpected_mqtt_disconnect_thread() -> None:
    """Unexpected _on_disconnect from paho thread fails pending batch futures."""
    loop = asyncio.get_running_loop()
    gateway, mock_client = _create_gateway(connected=True, loop=loop)
    gateway._shutdown_requested = True
    light = _create_device(gateway)

    task = asyncio.create_task(light.async_turn_on())
    await asyncio.sleep(0)

    await asyncio.to_thread(gateway._on_disconnect, mock_client, None, 1)

    with pytest.raises(
        DaliGatewayError, match="disconnected before sending 'writeDev'"
    ):
        await task

    mock_client.publish.assert_not_called()


async def test_cancelled_caller_does_not_break_sibling_batch_caller() -> None:
    """Cancelling one caller in a batch still resolves remaining callers cleanly."""
    loop = asyncio.get_running_loop()
    gateway, mock_client = _create_gateway(connected=True, loop=loop)
    light_1 = _create_device(gateway, address=1)
    light_2 = _create_device(gateway, address=2)

    task_1 = asyncio.create_task(light_1.async_turn_on())
    task_2 = asyncio.create_task(light_2.async_turn_off())
    await asyncio.sleep(0)

    task_1.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_1

    await task_2
    mock_client.publish.assert_called_once()


def test_sync_turn_on_raises_when_disconnected_and_on_sync_flush_error() -> None:
    """Legacy sync turn_on raises when disconnected or when no-loop flush fails."""
    disconnected_gw, mock_disc = _create_gateway(connected=False)
    disconnected_light = _create_device(disconnected_gw)
    with pytest.raises(DaliGatewayError, match="not connected"):
        disconnected_light.turn_on()
    mock_disc.publish.assert_not_called()

    failing_gw, _ = _create_gateway(
        connected=True, publish_rc=paho_mqtt.MQTT_ERR_NO_CONN
    )
    failing_light = _create_device(failing_gw)
    with pytest.raises(DaliGatewayError, match="Failed to publish 'writeDev'"):
        failing_light.turn_on()


async def test_read_status_does_not_raise_when_disconnected() -> None:
    """Background read_status remains non-raising when gateway is disconnected."""
    loop = asyncio.get_running_loop()
    gateway, mock_client = _create_gateway(connected=False, loop=loop)
    light = _create_device(gateway)

    light.read_status()
    gateway._flush_batch("readDev")

    mock_client.publish.assert_not_called()
