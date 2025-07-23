"""Dali Gateway Discovery"""

import asyncio
import socket
import logging
import ipaddress
import psutil
import json
import uuid
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from typing import Any

from .types import DaliGatewayType
from .exceptions import DaliGatewayError

_LOGGER = logging.getLogger(__name__)


class DaliGatewayDiscovery:
    """Dali Gateway Discovery"""

    MULTICAST_ADDR = "239.255.255.250"
    SEND_PORT = 1900
    LISTEN_PORT = 50569
    SR_KEY = "SR-DALI-GW-HASYS"
    ENCRYPTION_IV = b"0000000000101111"
    ENCRYPTION_METHOD = "aes-128-ctr"

    def _get_valid_interfaces(self) -> list[dict]:
        try:
            interfaces = self._detect_interfaces()
            if not interfaces:
                _LOGGER.warning(
                    "No network interfaces detected, using default")
                return [self._create_default_interface()]
            return interfaces
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error detecting network interfaces: %s", e)
            raise DaliGatewayError(
                f"Failed to detect network interfaces: {e}"
            ) from e

    def _detect_interfaces(self) -> list[dict]:
        interfaces = []
        for interface_name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    if self._is_valid_ip(ip):
                        interfaces.append(
                            self._create_interface_info(interface_name, ip))
        return interfaces or [self._create_default_interface()]

    def _is_valid_ip(self, ip: str) -> bool:
        if not ip or ip.startswith("127."):
            return False
        try:
            ip_obj = ipaddress.IPv4Address(ip)
            return not ip_obj.is_loopback and not ip_obj.is_link_local
        except ValueError:
            return False

    def _create_interface_info(self, name: str, ip: str) -> dict:
        return {
            "name": name,
            "address": ip,
            "network": f"{ip}/24"
        }

    def _create_default_interface(self) -> dict:
        return {
            "name": "default",
            "address": "0.0.0.0",
            "network": "0.0.0.0/0"
        }

    async def _send_multicast_on_interface(
        self, interface: dict, message: bytes
    ) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as send_sock:
            try:
                send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

                if interface["address"] != "0.0.0.0":
                    self._configure_multicast_interface(send_sock, interface)

                _LOGGER.debug(
                    "Sending discovery on interface %s (%s)",
                    interface["name"], interface["address"]
                )

                send_sock.sendto(
                    message, (self.MULTICAST_ADDR, self.SEND_PORT))

            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.error(
                    "Failed to send on interface %s: %s",
                    interface["name"], e
                )

    def _configure_multicast_interface(
        self, sock: socket.socket, interface: dict
    ) -> None:
        try:
            sock.bind((interface["address"], 0))
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(interface["address"])
            )
        except socket.error:
            _LOGGER.warning(
                "Failed to configure multicast on interface %s",
                interface["name"]
            )

    async def discover_gateways(self) -> list[DaliGatewayType]:
        try:
            return await self._do_discovery()
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Unexpected error during discovery: %s", e)
            raise DaliGatewayError(
                f"Gateway discovery failed: {e}"
            ) from e

    async def _do_discovery(self) -> list[DaliGatewayType]:
        valid_interfaces = self._get_valid_interfaces()
        if not valid_interfaces:
            _LOGGER.error("No valid network interfaces found")
            raise DaliGatewayError(
                "No valid network interfaces found for gateway discovery"
            )

        _LOGGER.info(
            "Starting gateway discovery on %d interfaces",
            len(valid_interfaces)
        )

        # Prepare discovery message
        try:
            message = self._prepare_discovery_message()
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Failed to prepare discovery message: %s", e)
            raise DaliGatewayError(
                f"Failed to prepare discovery message: {e}"
            ) from e

        # Create and configure listener socket
        listen_sock = None
        try:
            listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._configure_listener_socket(listen_sock, valid_interfaces)
            return await self._discovery_with_periodic_sending(
                listen_sock, valid_interfaces, message
            )

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error during gateway discovery: %s", e)
            raise DaliGatewayError(
                f"Error during gateway discovery: {e}"
            ) from e

        finally:
            if listen_sock:
                try:
                    # Leave multicast groups before closing
                    self._cleanup_multicast_groups(
                        listen_sock, valid_interfaces
                    )
                    listen_sock.close()
                except Exception as e:  # pylint: disable=broad-exception-caught
                    _LOGGER.warning(
                        "Error closing discovery socket: %s", e)

    def _prepare_discovery_message(self) -> bytes:
        key = self._random_key()
        msg_enc = self._encrypt_data("discover", key)
        combined_data = key + msg_enc
        cmd = self._encrypt_data(combined_data, self.SR_KEY)

        message_dict = {"cmd": cmd, "type": "HA"}
        message_json = json.dumps(message_dict)
        return message_json.encode("utf-8")

    def _configure_listener_socket(
        self, sock: socket.socket, interfaces: list[dict]
    ) -> None:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass

        port_to_bind = self._bind_to_available_port(sock)
        if port_to_bind != self.LISTEN_PORT:
            _LOGGER.warning(
                "Default port %d was occupied, using port %d instead",
                self.LISTEN_PORT, port_to_bind
            )

        for interface in interfaces:
            if interface["address"] != "0.0.0.0":
                self._join_multicast_group(sock, interface)

        # Join on default interface
        self._join_multicast_group(sock, self._create_default_interface())
        sock.setblocking(False)

    def _bind_to_available_port(self, sock: socket.socket) -> int:
        ports_to_try = [self.LISTEN_PORT]

        for i in range(1, 10):
            alternative_port = self.LISTEN_PORT + i
            if alternative_port not in ports_to_try:
                ports_to_try.append(alternative_port)

        ports_to_try.extend([0])

        last_exception = None
        for port in ports_to_try:
            try:
                sock.bind(("0.0.0.0", port))
                actual_port = sock.getsockname()[1] if port == 0 else port
                return actual_port
            except OSError as e:
                last_exception = e
                if port == 0:
                    break
                continue

        raise OSError(
            f"Unable to bind to any port. Last error: {last_exception}")

    def _join_multicast_group(
        self, sock: socket.socket, interface: dict
    ) -> None:
        try:
            mreq = socket.inet_aton(self.MULTICAST_ADDR) + \
                socket.inet_aton(interface["address"])

            # Try to leave the group first (in case it's already joined)
            try:
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_DROP_MEMBERSHIP, mreq
                )
            except socket.error:
                # It's okay if we can't leave (probably wasn't joined)
                pass

            # Now join the multicast group
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            _LOGGER.debug(
                "Successfully joined multicast on interface %s",
                interface["name"]
            )
        except socket.error as e:
            # Only log as debug for "Address already in use" errors
            if e.errno == 48:  # EADDRINUSE
                _LOGGER.debug(
                    "Multicast already in use on interface %s, continuing",
                    interface["name"]
                )
            else:
                _LOGGER.warning(
                    "Failed to join multicast on interface %s: %s",
                    interface["name"], e
                )

    def _cleanup_multicast_groups(
        self, sock: socket.socket, interfaces: list[dict]
    ) -> None:
        for interface in interfaces:
            if interface["address"] != "0.0.0.0":
                self._leave_multicast_group(sock, interface)
        # Leave default interface
        self._leave_multicast_group(sock, self._create_default_interface())

    def _leave_multicast_group(
        self, sock: socket.socket, interface: dict
    ) -> None:
        try:
            mreq = socket.inet_aton(self.MULTICAST_ADDR) + \
                socket.inet_aton(interface["address"])
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            _LOGGER.debug(
                "Successfully left multicast on interface %s",
                interface["name"]
            )
        except socket.error as e:
            # It's okay if we can't leave (probably wasn't joined)
            _LOGGER.debug(
                "Could not leave multicast on interface %s: %s",
                interface["name"], e
            )

    async def _send_discovery_messages(
        self, interfaces: list[dict], message: bytes
    ) -> None:
        send_tasks = [
            asyncio.create_task(
                self._send_multicast_on_interface(interface, message))
            for interface in interfaces
        ]

        await asyncio.gather(*send_tasks, return_exceptions=True)

    async def _discovery_with_periodic_sending(
        self, sock: socket.socket, interfaces: list[dict], message: bytes
    ) -> list[DaliGatewayType]:
        _LOGGER.debug(
            "Starting discovery with periodic sending (every 2s, max 180s)")

        start_time = asyncio.get_event_loop().time()
        timeout = 180.0  # 3 minutes
        send_interval = 2.0  # 2 seconds

        # Event to signal when first gateway is found
        first_gateway_found = asyncio.Event()
        unique_gateways: list[DaliGatewayType] = []

        async def periodic_sender():
            send_count = 0
            while not first_gateway_found.is_set():
                current_time = asyncio.get_event_loop().time()
                if current_time - start_time >= timeout:
                    _LOGGER.warning(
                        "Discovery sender timeout after %.1f seconds", timeout)
                    break

                send_count += 1
                _LOGGER.debug("Sending discovery attempt #%d", send_count)
                try:
                    await self._send_discovery_messages(interfaces, message)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    _LOGGER.error(
                        "Error sending discovery attempt #%d: %s",
                        send_count, e
                    )

                # Wait for send_interval or until first gateway found
                try:
                    await asyncio.wait_for(
                        first_gateway_found.wait(),
                        timeout=send_interval
                    )
                    break  # First gateway found, stop sending
                except asyncio.TimeoutError:
                    continue  # Continue sending

            _LOGGER.debug(
                "Periodic sender stopped after %d attempts", send_count)

        async def response_receiver():
            seen_sns = set()
            receive_count = 0

            while not first_gateway_found.is_set():
                current_time = asyncio.get_event_loop().time()
                if current_time - start_time >= timeout:
                    _LOGGER.warning(
                        "Discovery receiver timeout after %.1f seconds",
                        timeout
                    )
                    break

                try:
                    await asyncio.sleep(0.1)
                    data, addr = sock.recvfrom(1024)
                    receive_count += 1

                    _LOGGER.debug(
                        "Received discovery response #%d from %s:%d",
                        receive_count, addr[0], addr[1])

                    decoded_data = data.decode("utf-8")
                    response_json = json.loads(decoded_data)

                    raw_data = response_json.get("data")
                    if not raw_data:
                        _LOGGER.warning(
                            "No 'data' field in response from %s", addr[0])
                        continue

                    if raw_data.get("gwSn") in seen_sns:
                        continue

                    if gateway := self._process_discovery_gateway_data(
                        raw_data
                    ):
                        unique_gateways.append(gateway)
                        seen_sns.add(gateway["gw_sn"])
                        _LOGGER.info(
                            "Discovered DALI gateway: %s (SN: %s) at %s:%s",
                            gateway["name"], gateway["gw_sn"],
                            gateway["gw_ip"], gateway["port"]
                        )

                        # Signal that first gateway is found
                        first_gateway_found.set()
                        _LOGGER.debug(
                            "First gateway found! Stopping discovery process.")
                        break
                    else:
                        _LOGGER.warning(
                            "Failed to process gateway data from %s", addr[0])

                except BlockingIOError:
                    continue
                except asyncio.CancelledError:
                    break
                except json.JSONDecodeError as e:
                    _LOGGER.error(
                        "Invalid JSON in response from %s: %s",
                        addr[0] if "addr" in locals() else "unknown", e
                    )
                    continue
                except Exception as e:  # pylint: disable=broad-exception-caught
                    _LOGGER.error("Error receiving discovery response: %s", e)
                    continue

            _LOGGER.debug(
                "Response receiver stopped after processing %d responses",
                receive_count
            )

        # Run both tasks concurrently
        try:
            sender_task = asyncio.create_task(periodic_sender())
            receiver_task = asyncio.create_task(response_receiver())

            # Wait for either task to complete
            _, pending = await asyncio.wait(
                [sender_task, receiver_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel any remaining tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error during concurrent discovery: %s", e)

        elapsed_time = asyncio.get_event_loop().time() - start_time
        _LOGGER.info(
            "Gateway discovery completed: Found %d gateway(s) in %.2f seconds",
            len(unique_gateways), elapsed_time
        )

        if not unique_gateways:
            _LOGGER.warning("No gateways were discovered during this scan")

        return unique_gateways

    def _encrypt_data(self, data: str, key: str) -> str:
        key_bytes = key.encode("utf-8")
        cipher = Cipher(algorithms.AES(key_bytes),
                        modes.CTR(self.ENCRYPTION_IV))
        encryptor = cipher.encryptor()
        encrypted_data = encryptor.update(
            data.encode("utf-8")) + encryptor.finalize()
        return encrypted_data.hex()

    def _decrypt_data(self, encrypted_hex: str, key: str) -> str:
        if not encrypted_hex:
            raise ValueError("Encrypted hex is required")

        key_bytes = key.encode("utf-8")
        encrypted_bytes = bytes.fromhex(encrypted_hex)
        cipher = Cipher(algorithms.AES(key_bytes),
                        modes.CTR(self.ENCRYPTION_IV))
        decryptor = cipher.decryptor()
        decrypted_data = decryptor.update(
            encrypted_bytes) + decryptor.finalize()
        return decrypted_data.decode("utf-8")

    def _random_key(self) -> str:
        return uuid.uuid4().hex[:16]

    def _process_discovery_gateway_data(
        self, raw_data: Any
    ) -> DaliGatewayType | None:
        try:
            _LOGGER.debug(
                "Processing discovery gateway data: %s",
                raw_data
            )
            encrypted_user = raw_data.get("username", "")
            encrypted_pass = raw_data.get("passwd", "")

            decrypted_user = self._decrypt_data(encrypted_user, self.SR_KEY)
            decrypted_pass = self._decrypt_data(encrypted_pass, self.SR_KEY)

            gateway_name = raw_data.get(
                "name"
            ) or f"Dali Gateway {raw_data.get("gwSn")}"
            channel_total = []
            for channel in raw_data.get("channelTotal", []):
                if isinstance(channel, int):
                    channel_total.append(channel)
                elif isinstance(channel, str) and channel.isdigit():
                    channel_total.append(int(channel))
                else:
                    _LOGGER.warning(
                        "Invalid channel value in channelTotal: %s (type: %s)",
                        channel, type(channel)
                    )

            gateway = DaliGatewayType(
                gw_sn=raw_data.get("gwSn"),
                gw_ip=raw_data.get("gwIp"),
                port=raw_data.get("port"),
                is_tls=raw_data.get("isMqttTls"),
                name=gateway_name,
                username=decrypted_user,
                passwd=decrypted_pass,
                channel_total=channel_total
            )

            return gateway

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _LOGGER.error("Failed to process discovery response: %s", e)
            return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Unexpected error processing gateway data: %s", e)
            return None
