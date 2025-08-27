"""Dali Gateway Discovery"""

import asyncio
import contextlib
import ipaddress
import json
import logging
import socket
from typing import Any, Dict, List, Optional, Set
import uuid

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import psutil

from .types import DaliGatewayType

_LOGGER = logging.getLogger(__name__)


class NetworkManager:
    """Network interface manager"""

    def get_valid_interfaces(self) -> List[Dict[str, Any]]:
        interfaces: List[Dict[str, Any]] = []
        _LOGGER.debug("Scanning network interfaces for discovery")
        for interface_name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if self.is_valid_ip(ip):
                        interface_info = self.create_interface_info(interface_name, ip)
                        interfaces.append(interface_info)
                        _LOGGER.debug(
                            "Found valid interface: %s (%s)", interface_name, ip
                        )
                    else:
                        _LOGGER.debug(
                            "Skipping invalid IP: %s on %s", ip, interface_name
                        )

        _LOGGER.debug(
            "Network scan complete. %d valid interfaces found", len(interfaces)
        )
        return interfaces

    def is_valid_ip(self, ip: str) -> bool:
        if not ip or ip.startswith("127."):
            return False
        ip_obj = ipaddress.IPv4Address(ip)
        return not ip_obj.is_loopback and not ip_obj.is_link_local

    def create_interface_info(self, name: str, ip: str) -> Dict[str, Any]:
        return {"name": name, "address": ip, "network": f"{ip}/24"}


class MessageCryptor:
    """Message encryption and decryption handler"""

    SR_KEY = "SR-DALI-GW-HASYS"
    ENCRYPTION_IV = b"0000000000101111"

    def encrypt_data(self, data: str, key: str) -> str:
        key_bytes = key.encode("utf-8")
        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(self.ENCRYPTION_IV))
        encryptor = cipher.encryptor()
        encrypted_data = encryptor.update(data.encode("utf-8")) + encryptor.finalize()
        return encrypted_data.hex()

    def decrypt_data(self, encrypted_hex: str, key: str) -> str:
        key_bytes = key.encode("utf-8")
        encrypted_bytes = bytes.fromhex(encrypted_hex)
        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(self.ENCRYPTION_IV))
        decryptor = cipher.decryptor()
        decrypted_data = decryptor.update(encrypted_bytes) + decryptor.finalize()
        return decrypted_data.decode("utf-8")

    def random_key(self) -> str:
        return uuid.uuid4().hex[:16]

    def prepare_discovery_message(self, gw_sn: Optional[str] = None) -> bytes:
        key = self.random_key()
        msg_enc = self.encrypt_data("discover", key)
        combined_data = key + msg_enc
        cmd = self.encrypt_data(combined_data, self.SR_KEY)
        message_dict = {"cmd": cmd, "type": "HA", "snList": []}
        if gw_sn:
            message_dict["snList"] = [gw_sn]

        _LOGGER.debug("Prepared discovery message: %s", message_dict)
        message_json = json.dumps(message_dict)
        return message_json.encode("utf-8")


class MulticastSender:
    """Multicast communication manager"""

    MULTICAST_ADDR = "239.255.255.250"
    SEND_PORT = 1900
    LISTEN_PORT = 50569

    def create_listener_socket(self, interfaces: List[Dict[str, Any]]) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with contextlib.suppress(AttributeError, OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._bind_to_port(sock)
        self._join_multicast_groups(sock, interfaces)
        sock.setblocking(False)
        return sock

    def cleanup_socket(
        self, sock: socket.socket, interfaces: List[Dict[str, Any]]
    ) -> None:
        mreq_list = []
        for interface in interfaces:
            mreq = socket.inet_aton(self.MULTICAST_ADDR) + socket.inet_aton(
                interface["address"]
            )
            mreq_list.append(mreq)
        for mreq in mreq_list:
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
        sock.close()

    async def send_multicast_message(
        self, interfaces: List[Dict[str, Any]], message: bytes
    ) -> None:
        tasks = [
            asyncio.create_task(self._send_on_interface(interface, message))
            for interface in interfaces
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    def _bind_to_port(self, sock: socket.socket) -> None:
        ports_to_try = [
            self.LISTEN_PORT,
            *range(self.LISTEN_PORT + 1, self.LISTEN_PORT + 10),
            0,
        ]

        def try_bind_port(port: int) -> bool:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                _LOGGER.debug("Port %d unavailable, trying next port", port)
                return False
            else:
                _LOGGER.debug("Successfully bound listener socket to port %d", port)
                return True

        for port in ports_to_try:
            if try_bind_port(port):
                return

        _LOGGER.error("Unable to bind to any port after trying all options")
        raise OSError("Unable to bind to any port")

    def _join_multicast_groups(
        self, sock: socket.socket, interfaces: List[Dict[str, Any]]
    ) -> None:
        _LOGGER.debug("Joining multicast groups on %d interfaces", len(interfaces))

        for interface in interfaces:
            mreq = socket.inet_aton(self.MULTICAST_ADDR) + socket.inet_aton(
                interface["address"]
            )
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)

            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            _LOGGER.debug(
                "Joined multicast group on interface %s (%s)",
                interface["name"],
                interface["address"],
            )

    async def _send_on_interface(
        self, interface: Dict[str, Any], message: bytes
    ) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((interface["address"], 0))
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(interface["address"]),
            )
            sock.sendto(message, (self.MULTICAST_ADDR, self.SEND_PORT))


class DaliGatewayDiscovery:
    """Dali Gateway Discovery"""

    DISCOVERY_TIMEOUT = 180.0
    SEND_INTERVAL = 2.0

    def __init__(self):
        self.network_manager = NetworkManager()
        self.cryptor = MessageCryptor()
        self.sender = MulticastSender()

    async def discover_gateways(
        self, gw_sn: Optional[str] = None
    ) -> List[DaliGatewayType]:
        _LOGGER.info(
            "Starting DALI gateway discovery%s",
            f" for specific gateway: {gw_sn}" if gw_sn else "",
        )

        interfaces = self.network_manager.get_valid_interfaces()
        _LOGGER.debug(
            "Found %d valid network interfaces: %s",
            len(interfaces),
            [iface["name"] for iface in interfaces],
        )

        if not interfaces:
            _LOGGER.error(
                "No valid network interfaces found for discovery - check network connection"
            )
            return []

        message = self.cryptor.prepare_discovery_message(gw_sn)
        listen_sock = self.sender.create_listener_socket(interfaces)

        try:
            gateways = await self._run_discovery(listen_sock, interfaces, message)
            _LOGGER.info("Discovery completed. Found %d gateway(s)", len(gateways))
            return gateways
        finally:
            self.sender.cleanup_socket(listen_sock, interfaces)

    async def _run_discovery(
        self, sock: socket.socket, interfaces: List[Dict[str, Any]], message: bytes
    ) -> List[DaliGatewayType]:
        start_time = asyncio.get_event_loop().time()
        first_gateway_found = asyncio.Event()
        unique_gateways: List[DaliGatewayType] = []
        seen_sns: Set[str] = set()

        # Sender task
        sender_task = asyncio.create_task(
            self._sender_loop(interfaces, message, first_gateway_found, start_time)
        )

        # Receiver task
        receiver_task = asyncio.create_task(
            self._receiver_loop(
                sock, first_gateway_found, start_time, unique_gateways, seen_sns
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
        send_count = 0
        while not first_gateway_found.is_set():
            if asyncio.get_event_loop().time() - start_time >= self.DISCOVERY_TIMEOUT:
                _LOGGER.info(
                    "Discovery timeout reached after %.1f seconds",
                    self.DISCOVERY_TIMEOUT,
                )
                break

            send_count += 1
            _LOGGER.debug(
                "Sending discovery message #%d to %d interfaces",
                send_count,
                len(interfaces),
            )
            await self.sender.send_multicast_message(interfaces, message)

            try:
                await asyncio.wait_for(
                    first_gateway_found.wait(), timeout=self.SEND_INTERVAL
                )
                _LOGGER.debug(
                    "Gateway found, stopping sender loop after %d sends", send_count
                )
                break
            except asyncio.TimeoutError:
                continue

    async def _receiver_loop(
        self,
        sock: socket.socket,
        first_gateway_found: asyncio.Event,
        start_time: float,
        unique_gateways: List[DaliGatewayType],
        seen_sns: Set[str],
    ) -> None:
        _LOGGER.debug("Starting receiver loop, listening on socket")

        while not first_gateway_found.is_set():
            if asyncio.get_event_loop().time() - start_time >= self.DISCOVERY_TIMEOUT:
                _LOGGER.debug("Receiver loop timeout reached")
                break

            addr = None
            try:
                await asyncio.sleep(0.1)
                data, addr = sock.recvfrom(1024)
                _LOGGER.debug("Received response from %s, processing data", addr)

                response_json = json.loads(data.decode("utf-8"))
                raw_data = response_json.get("data")

                if raw_data and raw_data.get("gwSn") not in seen_sns:
                    if gateway := self._process_gateway_data(raw_data):
                        _LOGGER.info(
                            "Discovered gateway: %s (%s) at %s:%s",
                            gateway["name"],
                            gateway["gw_sn"],
                            gateway["gw_ip"],
                            gateway["port"],
                        )
                        unique_gateways.append(gateway)
                        seen_sns.add(gateway["gw_sn"])
                        first_gateway_found.set()
                        break
                    _LOGGER.warning("Failed to process gateway data from %s", addr)
                elif raw_data and raw_data.get("gwSn") in seen_sns:
                    _LOGGER.debug(
                        "Ignoring duplicate gateway response: %s", raw_data.get("gwSn")
                    )

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

    def _process_gateway_data(self, raw_data: Any) -> Optional[DaliGatewayType]:
        gw_sn = raw_data.get("gwSn")
        if not gw_sn:
            _LOGGER.warning("Gateway data missing required 'gwSn' field")
            return None

        _LOGGER.debug("Processing gateway data for: %s", gw_sn)

        encrypted_user = raw_data.get("username", "")
        encrypted_pass = raw_data.get("passwd", "")

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

        gateway = DaliGatewayType(
            gw_sn=gw_sn,
            gw_ip=raw_data.get("gwIp"),
            port=raw_data.get("port"),
            is_tls=raw_data.get("isMqttTls"),
            name=gateway_name,
            username=decrypted_user,
            passwd=decrypted_pass,
            channel_total=channel_total,
        )

        _LOGGER.debug("Successfully processed gateway: %s", gateway_name)
        return gateway
