"""Dali Gateway Discovery"""

import asyncio
import contextlib
import ipaddress
import json
import logging
import socket
from typing import Any, Dict, List, Set

import psutil

from .gateway import DaliGateway
from .udp_client import MessageCryptor, MulticastSender

_LOGGER = logging.getLogger(__name__)


class NetworkManager:
    """Network interface manager"""

    def get_valid_interfaces(self) -> List[Dict[str, Any]]:
        interfaces: List[Dict[str, Any]] = []
        for interface_name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if self.is_valid_ip(ip):
                        interface_info = self.create_interface_info(interface_name, ip)
                        interfaces.append(interface_info)
        return interfaces

    def is_valid_ip(self, ip: str) -> bool:
        if not ip or ip.startswith("127."):
            return False
        ip_obj = ipaddress.IPv4Address(ip)
        return not ip_obj.is_loopback and not ip_obj.is_link_local

    def create_interface_info(self, name: str, ip: str) -> Dict[str, Any]:
        return {"name": name, "address": ip, "network": f"{ip}/24"}


class DaliGatewayDiscovery:
    """Dali Gateway Discovery"""

    DISCOVERY_TIMEOUT: float = 180.0
    SEND_INTERVAL: float = 2.0

    def __init__(self) -> None:
        self.network_manager = NetworkManager()
        self.cryptor = MessageCryptor()
        self.sender = MulticastSender()

    async def discover_gateways(self, gw_sn: str | None = None) -> List[DaliGateway]:
        _LOGGER.info(
            "Starting DALI gateway discovery%s",
            f" for specific gateway: {gw_sn}" if gw_sn else "",
        )

        interfaces = self.network_manager.get_valid_interfaces()

        if not interfaces:
            _LOGGER.error(
                "No valid network interfaces found for discovery - check network connection"
            )
            return []

        message = self.cryptor.prepare_discovery_message(gw_sn)
        listen_sock = self.sender.create_listener_socket(interfaces)

        try:
            gateways = await self._run_discovery(
                listen_sock, interfaces, message, gw_sn
            )
            _LOGGER.info("Discovery completed. Found %d gateway(s)", len(gateways))
            return gateways
        finally:
            self.sender.cleanup_socket(listen_sock, interfaces)

    async def _run_discovery(
        self,
        sock: socket.socket,
        interfaces: List[Dict[str, Any]],
        message: bytes,
        gw_sn: str | None = None,
    ) -> List[DaliGateway]:
        start_time = asyncio.get_event_loop().time()
        first_gateway_found = asyncio.Event()
        unique_gateways: List[DaliGateway] = []
        seen_sns: Set[str] = set()

        # Sender task
        sender_task = asyncio.create_task(
            self._sender_loop(interfaces, message, first_gateway_found, start_time)
        )

        # Receiver task
        receiver_task = asyncio.create_task(
            self._receiver_loop(
                sock, first_gateway_found, start_time, unique_gateways, seen_sns, gw_sn
            )
        )

        _, pending = await asyncio.wait(
            [sender_task, receiver_task], return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return unique_gateways

    async def _sender_loop(
        self,
        interfaces: List[Dict[str, Any]],
        message: bytes,
        first_gateway_found: asyncio.Event,
        start_time: float,
    ) -> None:
        while not first_gateway_found.is_set():
            if asyncio.get_event_loop().time() - start_time >= self.DISCOVERY_TIMEOUT:
                _LOGGER.info(
                    "Discovery timeout reached after %.1f seconds",
                    self.DISCOVERY_TIMEOUT,
                )
                break

            await self.sender.send_multicast_message(interfaces, message)

            try:
                await asyncio.wait_for(
                    first_gateway_found.wait(), timeout=self.SEND_INTERVAL
                )
                break
            except asyncio.TimeoutError:
                continue

    async def _receiver_loop(
        self,
        sock: socket.socket,
        first_gateway_found: asyncio.Event,
        start_time: float,
        unique_gateways: List[DaliGateway],
        seen_sns: Set[str],
        gw_sn: str | None = None,
    ) -> None:
        while not first_gateway_found.is_set():
            if asyncio.get_event_loop().time() - start_time >= self.DISCOVERY_TIMEOUT:
                break

            addr = None
            try:
                await asyncio.sleep(0.1)
                data, addr = sock.recvfrom(1024)

                response_json = json.loads(data.decode("utf-8"))
                raw_data = response_json.get("data")

                if raw_data and raw_data.get("gwSn") not in seen_sns:
                    if gateway := self._process_gateway_data(raw_data, gw_sn):
                        _LOGGER.info(
                            "Discovered gateway: %s (%s) at %s:%s",
                            gateway.name,
                            gateway.gw_sn,
                            gateway.gw_ip,
                            gateway.port,
                        )
                        unique_gateways.append(gateway)
                        seen_sns.add(gateway.gw_sn)
                        first_gateway_found.set()
                        break

            except json.JSONDecodeError as exc:
                _LOGGER.warning(
                    "Invalid JSON response from %s: %s. Raw data: %s",
                    addr or "unknown",
                    exc,
                    data[:100] if data else "<empty>",
                )
                continue
            except (BlockingIOError, asyncio.CancelledError):
                continue
            except OSError as exc:
                _LOGGER.error(
                    "Socket error in receiver loop - this may prevent discovery: %s",
                    exc,
                )
                break

    def _process_gateway_data(
        self, raw_data: Any, requested_gw_sn: str | None = None
    ) -> DaliGateway | None:
        gw_sn = raw_data.get("gwSn")
        if not gw_sn:
            _LOGGER.warning("Gateway data missing required 'gwSn' field")
            return None

        encrypted_user = raw_data.get("username", "")
        encrypted_pass = raw_data.get("passwd", "")

        # Skip gateway with empty credentials if no specific gateway was requested
        if not encrypted_user and not encrypted_pass and requested_gw_sn is None:
            return None

        try:
            decrypted_user = self.cryptor.decrypt_data(
                encrypted_user, self.cryptor.SR_KEY
            )
            decrypted_pass = self.cryptor.decrypt_data(
                encrypted_pass, self.cryptor.SR_KEY
            )
        except UnicodeDecodeError as e:
            _LOGGER.error(
                "Failed to decrypt gateway credentials for %s: %s. "
                "This gateway will be skipped.",
                gw_sn,
                e,
            )
            return None

        gateway_name = raw_data.get("name") or f"Dali Gateway {gw_sn}"
        channel_total = [
            int(ch)
            for ch in raw_data.get("channelTotal", [])
            if isinstance(ch, (int, str)) and str(ch).isdigit()
        ]

        return DaliGateway(
            gw_sn=gw_sn,
            gw_ip=raw_data.get("gwIp"),
            port=int(raw_data.get("port", 0)),
            username=decrypted_user,
            passwd=decrypted_pass,
            name=gateway_name,
            channel_total=channel_total,
            is_tls=bool(raw_data.get("isMqttTls")),
        )
