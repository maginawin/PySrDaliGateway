#!/usr/bin/env python3
"""Gateway credential caching for test scripts."""

import base64
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from PySrDaliGateway.gateway import DaliGateway

_LOGGER = logging.getLogger(__name__)


class GatewayCredentialCache:
    """Manages persistent storage of gateway credentials for testing."""

    CACHE_VERSION = 1
    CACHE_FILE = Path(__file__).parent / ".gateway_cache.json"

    def __init__(self) -> None:
        """Initialize cache and load existing data."""
        self._cache_data: Dict[str, Any] = self._get_empty_cache()
        self._load_cache()

    def has_cache(self) -> bool:
        """Check if cache exists and has at least one gateway.

        Returns:
            True if cache has gateways, False otherwise
        """
        return len(self._cache_data["gateways"]) > 0

    def save_gateway(self, gateway: DaliGateway) -> None:
        """Save gateway credentials to cache.

        Args:
            gateway: DaliGateway instance with connection info
        """
        gw_data: dict[str, Any] = {
            "gw_sn": gateway.gw_sn,
            "gw_ip": gateway.gw_ip,
            "port": gateway.port,
            "username": self._encode_credential(gateway.username),
            "passwd": self._encode_credential(gateway.passwd),
            "name": gateway.name,
            "is_tls": gateway.is_tls,
            "channel_total": list(gateway.channel_total),
            "last_connection": datetime.now(timezone.utc).isoformat(),
        }

        self._cache_data["gateways"][gateway.gw_sn] = gw_data
        self._save_cache()
        _LOGGER.debug("Saved gateway %s to cache", gateway.gw_sn)

    def get_last_gateway(self) -> Optional[Dict[str, Any]]:
        """Retrieve most recently connected gateway from cache.

        Returns:
            Dictionary with gateway info and decoded credentials, or None if cache is empty
        """
        if not self.has_cache():
            return None

        # Find gateway with most recent last_connection timestamp
        gateways = self._cache_data["gateways"]
        last_gw_sn = max(
            gateways.keys(),
            key=lambda sn: gateways[sn].get("last_connection", ""),
        )

        gw_data = gateways[last_gw_sn]

        # Decode credentials and return
        return {
            "gw_sn": gw_data["gw_sn"],
            "gw_ip": gw_data["gw_ip"],
            "port": gw_data["port"],
            "username": self._decode_credential(gw_data["username"]),
            "passwd": self._decode_credential(gw_data["passwd"]),
            "name": gw_data.get("name"),
            "is_tls": gw_data.get("is_tls", False),
            "channel_total": gw_data.get("channel_total", [0]),
        }

    def _get_empty_cache(self) -> Dict[str, Any]:
        """Get empty cache structure.

        Returns:
            Empty cache dictionary
        """
        return {
            "version": self.CACHE_VERSION,
            "last_updated": None,
            "gateways": {},
        }

    def _load_cache(self) -> None:
        """Load cache from disk with error handling."""
        try:
            if self.CACHE_FILE.exists():
                with self.CACHE_FILE.open() as f:
                    data = json.load(f)

                # Validate version
                if data.get("version") != self.CACHE_VERSION:
                    _LOGGER.warning("Cache version mismatch, resetting cache")
                    self._cache_data = self._get_empty_cache()
                else:
                    self._cache_data = data
                    _LOGGER.debug(
                        "Loaded cache with %d gateway(s)",
                        len(self._cache_data["gateways"]),
                    )
        except (OSError, json.JSONDecodeError, KeyError) as e:
            _LOGGER.warning("Failed to load cache, starting fresh: %s", e)
            self._cache_data = self._get_empty_cache()

    def _save_cache(self) -> None:
        """Save cache to disk atomically with restrictive permissions."""
        try:
            # Update timestamp
            self._cache_data["last_updated"] = datetime.now(timezone.utc).isoformat()

            # Atomic write pattern: write to temp file, then rename
            temp_file = self.CACHE_FILE.with_suffix(".json.tmp")
            with temp_file.open("w") as f:
                json.dump(self._cache_data, f, indent=2)

            # Replace original file atomically
            temp_file.replace(self.CACHE_FILE)

            # Set restrictive permissions (Unix only)
            if hasattr(os, "chmod"):
                self.CACHE_FILE.chmod(0o600)

            _LOGGER.debug("Cache saved successfully")

        except OSError as e:
            _LOGGER.error("Failed to save cache: %s", e)

    def _encode_credential(self, value: str) -> str:
        """Encode credential using base64.

        Args:
            value: Credential string to encode

        Returns:
            Base64 encoded string
        """
        return base64.b64encode(value.encode("utf-8")).decode("utf-8")

    def _decode_credential(self, value: str) -> str:
        """Decode credential from base64.

        Args:
            value: Base64 encoded string

        Returns:
            Decoded credential string
        """
        return base64.b64decode(value.encode("utf-8")).decode("utf-8")
