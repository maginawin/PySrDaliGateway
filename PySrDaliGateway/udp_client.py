"""UDP client utilities for DALI Gateway communication"""

import asyncio
import contextlib
import json
import logging
import socket
import time
from typing import Any, Dict, List
import uuid

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import psutil

_LOGGER = logging.getLogger(__name__)


class MessageCryptor:
    """Message encryption and decryption handler"""

    SR_KEY: str = "SR-DALI-GW-HASYS"
    ENCRYPTION_IV: bytes = b"0000000000101111"

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

    def prepare_discovery_message(self, gw_sn: str | None = None) -> bytes:
        key = self.random_key()
        msg_enc = self.encrypt_data("discover", key)
        combined_data = key + msg_enc
        cmd = self.encrypt_data(combined_data, self.SR_KEY)

        message_dict: Dict[str, Any] = {"cmd": cmd, "type": "HA"}
        if gw_sn is not None:
            message_dict = {**message_dict, "snList": [gw_sn]}

        _LOGGER.debug("Prepared discovery message: %s", message_dict)
        message_json = json.dumps(message_dict)
        return message_json.encode("utf-8")

    def prepare_identify_message(self, gw_sn: str, msg_id: str) -> bytes:
        """Prepare identify gateway message for UDP multicast.

        Args:
            gw_sn: Gateway serial number
            msg_id: Message ID (typically timestamp)

        Returns:
            Encrypted message bytes ready to send via UDP
        """
        key = self.random_key()
        msg_enc = self.encrypt_data("identifyDev", key)
        combined_data = key + msg_enc
        cmd = self.encrypt_data(combined_data, self.SR_KEY)

        message_dict: Dict[str, Any] = {
            "cmd": cmd,
            "msgId": msg_id,
            "gwSn": gw_sn,
        }

        _LOGGER.debug("Prepared identify gateway message for %s", gw_sn)
        message_json = json.dumps(message_dict)
        return message_json.encode("utf-8")


class MulticastSender:
    """Multicast communication manager"""

    MULTICAST_ADDR: str = "239.255.255.250"
    SEND_PORT: int = 1900
    LISTEN_PORT: int = 50569

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


async def send_identify_gateway(gw_sn: str) -> None:
    """Send identify command to gateway via UDP multicast.

    Args:
        gw_sn: Gateway serial number to identify

    This sends the identifyDev command via UDP multicast which will make
    the gateway's LED blink for physical identification.
    """
    cryptor = MessageCryptor()
    sender = MulticastSender()

    # Get network interfaces
    interfaces: List[Dict[str, Any]] = []
    for interface_name, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET:
                ip = addr.address
                if ip and not ip.startswith("127."):
                    interfaces.append(
                        {"name": interface_name, "address": ip, "network": f"{ip}/24"}
                    )

    if not interfaces:
        _LOGGER.warning("No valid network interfaces found for identify command")
        return

    # Prepare and send identify message
    msg_id = str(int(time.time()))
    message = cryptor.prepare_identify_message(gw_sn, msg_id)

    _LOGGER.debug(
        "Sending identify command to gateway %s on %d interface(s)",
        gw_sn,
        len(interfaces),
    )

    await sender.send_multicast_message(interfaces, message)
