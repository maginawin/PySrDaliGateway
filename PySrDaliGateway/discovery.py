"""Dali Gateway Discovery"""

import asyncio
import socket
import ipaddress
import psutil
import json
import uuid
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from typing import Any

from .types import DaliGatewayType


class NetworkManager:
    """Network interface manager"""

    def get_valid_interfaces(self) -> list[dict]:
        interfaces = []
        for interface_name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if self.is_valid_ip(ip):
                        interfaces.append(
                            self.create_interface_info(interface_name, ip)
                        )
        return interfaces

    def is_valid_ip(self, ip: str) -> bool:
        if not ip or ip.startswith("127."):
            return False
        ip_obj = ipaddress.IPv4Address(ip)
        return not ip_obj.is_loopback and not ip_obj.is_link_local

    def create_interface_info(self, name: str, ip: str) -> dict:
        return {
            "name": name,
            "address": ip,
            "network": f"{ip}/24"
        }


class MessageCryptor:
    """Message encryption and decryption handler"""

    SR_KEY = "SR-DALI-GW-HASYS"
    ENCRYPTION_IV = b"0000000000101111"

    def encrypt_data(self, data: str, key: str) -> str:
        key_bytes = key.encode("utf-8")
        cipher = Cipher(algorithms.AES(key_bytes),
                        modes.CTR(self.ENCRYPTION_IV))
        encryptor = cipher.encryptor()
        encrypted_data = encryptor.update(
            data.encode("utf-8")) + encryptor.finalize()
        return encrypted_data.hex()

    def decrypt_data(self, encrypted_hex: str, key: str) -> str:
        key_bytes = key.encode("utf-8")
        encrypted_bytes = bytes.fromhex(encrypted_hex)
        cipher = Cipher(algorithms.AES(key_bytes),
                        modes.CTR(self.ENCRYPTION_IV))
        decryptor = cipher.decryptor()
        decrypted_data = decryptor.update(
            encrypted_bytes) + decryptor.finalize()
        return decrypted_data.decode("utf-8")

    def random_key(self) -> str:
        return uuid.uuid4().hex[:16]

    def prepare_discovery_message(self) -> bytes:
        key = self.random_key()
        msg_enc = self.encrypt_data("discover", key)
        combined_data = key + msg_enc
        cmd = self.encrypt_data(combined_data, self.SR_KEY)
        message_dict = {"cmd": cmd, "type": "HA"}
        message_json = json.dumps(message_dict)
        return message_json.encode("utf-8")


class MulticastSender:
    """Multicast communication manager"""

    MULTICAST_ADDR = "239.255.255.250"
    SEND_PORT = 1900
    LISTEN_PORT = 50569

    def create_listener_socket(self, interfaces: list[dict]) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        self._bind_to_port(sock)
        self._join_multicast_groups(sock, interfaces)
        sock.setblocking(False)
        return sock

    def cleanup_socket(
        self, sock: socket.socket, interfaces: list[dict]
    ) -> None:
        for interface in interfaces:
            try:
                mreq = socket.inet_aton(
                    self.MULTICAST_ADDR
                ) + socket.inet_aton(interface["address"])
                sock.setsockopt(socket.IPPROTO_IP,
                                socket.IP_DROP_MEMBERSHIP, mreq)
            except socket.error:
                pass
        sock.close()

    async def send_multicast_message(
        self, interfaces: list[dict], message: bytes
    ) -> None:
        tasks = [asyncio.create_task(self._send_on_interface(
            interface, message)) for interface in interfaces]
        await asyncio.gather(*tasks, return_exceptions=True)

    def _bind_to_port(self, sock: socket.socket) -> None:
        for port in [self.LISTEN_PORT] + list(range(self.LISTEN_PORT + 1, self.LISTEN_PORT + 10)) + [0]:
            try:
                sock.bind(("0.0.0.0", port))
                return
            except OSError:
                if port == 0:
                    raise OSError("Unable to bind to any port")

    def _join_multicast_groups(self, sock: socket.socket, interfaces: list[dict]) -> None:
        for interface in interfaces:
            mreq = socket.inet_aton(self.MULTICAST_ADDR) + \
                socket.inet_aton(interface["address"])
            try:
                sock.setsockopt(socket.IPPROTO_IP,
                                socket.IP_DROP_MEMBERSHIP, mreq)
            except socket.error:
                pass
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    async def _send_on_interface(self, interface: dict, message: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind((interface["address"], 0))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                            socket.inet_aton(interface["address"]))
            sock.sendto(message, (self.MULTICAST_ADDR, self.SEND_PORT))


class DaliGatewayDiscovery:
    """Dali Gateway Discovery"""

    DISCOVERY_TIMEOUT = 180.0
    SEND_INTERVAL = 2.0

    def __init__(self):
        self.network_manager = NetworkManager()
        self.cryptor = MessageCryptor()
        self.sender = MulticastSender()

    async def discover_gateways(self) -> list[DaliGatewayType]:
        interfaces = self.network_manager.get_valid_interfaces()
        message = self.cryptor.prepare_discovery_message()
        listen_sock = self.sender.create_listener_socket(interfaces)
        try:
            return await self._run_discovery(listen_sock, interfaces, message)
        finally:
            self.sender.cleanup_socket(listen_sock, interfaces)

    async def _run_discovery(self, sock: socket.socket, interfaces: list[dict], message: bytes) -> list[DaliGatewayType]:
        start_time = asyncio.get_event_loop().time()
        first_gateway_found = asyncio.Event()
        unique_gateways: list[DaliGatewayType] = []
        seen_sns = set()

        # Sender task
        sender_task = asyncio.create_task(self._sender_loop(
            interfaces, message, first_gateway_found, start_time))

        # Receiver task
        receiver_task = asyncio.create_task(self._receiver_loop(
            sock, first_gateway_found, start_time, unique_gateways, seen_sns))

        _, pending = await asyncio.wait([sender_task, receiver_task], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return unique_gateways

    async def _sender_loop(self, interfaces: list[dict], message: bytes, first_gateway_found: asyncio.Event, start_time: float) -> None:
        while not first_gateway_found.is_set():
            if asyncio.get_event_loop().time() - start_time >= self.DISCOVERY_TIMEOUT:
                break
            await self.sender.send_multicast_message(interfaces, message)
            try:
                await asyncio.wait_for(first_gateway_found.wait(), timeout=self.SEND_INTERVAL)
                break
            except asyncio.TimeoutError:
                continue

    async def _receiver_loop(self, sock: socket.socket, first_gateway_found: asyncio.Event, start_time: float, unique_gateways: list[DaliGatewayType], seen_sns: set) -> None:
        while not first_gateway_found.is_set():
            if asyncio.get_event_loop().time() - start_time >= self.DISCOVERY_TIMEOUT:
                break
            try:
                await asyncio.sleep(0.1)
                data, addr = sock.recvfrom(1024)
                response_json = json.loads(data.decode("utf-8"))
                raw_data = response_json.get("data")
                if raw_data and raw_data.get("gwSn") not in seen_sns:
                    if gateway := self._process_gateway_data(raw_data):
                        unique_gateways.append(gateway)
                        seen_sns.add(gateway["gw_sn"])
                        first_gateway_found.set()
                        break
            except (BlockingIOError, asyncio.CancelledError, json.JSONDecodeError):
                continue

    def _process_gateway_data(self, raw_data: Any) -> DaliGatewayType | None:
        encrypted_user = raw_data.get("username", "")
        encrypted_pass = raw_data.get("passwd", "")
        decrypted_user = self.cryptor.decrypt_data(
            encrypted_user, self.cryptor.SR_KEY)
        decrypted_pass = self.cryptor.decrypt_data(
            encrypted_pass, self.cryptor.SR_KEY)
        gateway_name = raw_data.get(
            "name") or f"Dali Gateway {raw_data.get('gwSn')}"
        channel_total = [int(ch) for ch in raw_data.get(
            "channelTotal", []) if isinstance(ch, (int, str)) and str(ch).isdigit()]

        return DaliGatewayType(
            gw_sn=raw_data.get("gwSn"),
            gw_ip=raw_data.get("gwIp"),
            port=raw_data.get("port"),
            is_tls=raw_data.get("isMqttTls"),
            name=gateway_name,
            username=decrypted_user,
            passwd=decrypted_pass,
            channel_total=channel_total
        )
