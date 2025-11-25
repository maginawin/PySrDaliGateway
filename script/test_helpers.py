#!/usr/bin/env python3
"""Helper classes for DALI Gateway testing."""

import asyncio
import json
import logging
import socket
from typing import Any, Dict, List

import psutil

from PySrDaliGateway.gateway import DaliGateway

_LOGGER = logging.getLogger(__name__)


class IdentifyResponseListener:
    """Listener for UDP identify gateway responses."""

    def __init__(self, gw_sn: str):
        self.gw_sn = gw_sn
        self._response_received = asyncio.Event()
        self._ack: bool = False
        self._listen_sock: socket.socket | None = None

    async def wait_for_response(self, timeout: float = 5.0) -> bool:
        """Wait for identify response via UDP.

        Args:
            timeout: Maximum time to wait for response in seconds

        Returns:
            True if ack was received, False otherwise
        """
        from PySrDaliGateway.udp_client import MessageCryptor, MulticastSender

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
                            {
                                "name": interface_name,
                                "address": ip,
                                "network": f"{ip}/24",
                            }
                        )

        if not interfaces:
            _LOGGER.warning("No network interfaces for listening")
            return False

        # Create listener socket
        self._listen_sock = sender.create_listener_socket(interfaces)

        try:
            # Wait for response with timeout
            await asyncio.wait_for(self._listen_for_response(cryptor), timeout=timeout)
            return self._ack
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for UDP identify response")
            return False
        finally:
            if self._listen_sock:
                sender.cleanup_socket(self._listen_sock, interfaces)

    async def _listen_for_response(self, cryptor: Any) -> None:
        """Listen for UDP response."""
        if self._listen_sock is None:
            return

        loop = asyncio.get_event_loop()

        while not self._response_received.is_set():
            try:
                data = await loop.sock_recv(self._listen_sock, 4096)
                response_json = json.loads(data.decode("utf-8"))

                # Decrypt cmd field
                encrypted_cmd = response_json.get("cmd", "")
                try:
                    decrypted_cmd = cryptor.decrypt_data(encrypted_cmd, cryptor.SR_KEY)
                except Exception:
                    continue

                # Check if this is identifyDevRes for our gateway
                if decrypted_cmd == "identifyDevRes":
                    gw_sn = response_json.get("gwSn")
                    if gw_sn == self.gw_sn:
                        self._ack = response_json.get("ack", False)
                        self._response_received.set()
                        _LOGGER.debug(
                            "Received UDP identify response for %s: ack=%s",
                            gw_sn,
                            self._ack,
                        )
                        break
            except Exception as e:
                _LOGGER.debug("Error reading UDP response: %s", e)
                continue


class TestDaliGateway(DaliGateway):
    """Extended DaliGateway with response tracking for testing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track identify responses
        self._identify_received = asyncio.Event()
        self._identify_ack: bool = False

    def _process_identify_dev_response(self, payload: Dict[str, Any]) -> None:
        """Override to track identify responses for testing."""
        # Call parent implementation
        super()._process_identify_dev_response(payload)

        # Track response for testing
        self._identify_ack = payload.get("ack", False)
        self._identify_received.set()

    async def wait_for_identify_response(self, timeout: float = 5.0) -> bool:
        """Wait for identify response and return ack status.

        Args:
            timeout: Maximum time to wait for response in seconds

        Returns:
            True if ack was received, False otherwise
        """
        self._identify_received.clear()
        self._identify_ack = False

        try:
            await asyncio.wait_for(self._identify_received.wait(), timeout=timeout)
            return self._identify_ack
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for identify response")
            return False
