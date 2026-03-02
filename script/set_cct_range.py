#!/usr/bin/env python3
"""One-shot script to set CCT range parameters on real devices.

Sets different cct_warm/cct_cool values on 3 devices, then reads back
to verify. After running, HA should show different color temp slider
ranges for these devices.

Usage:
    cd repos/PySrDaliGateway/script
    source ../venv/bin/activate
    python set_cct_range.py
"""

import asyncio
import contextlib
import logging
import sys
from typing import Any, Dict, List, Tuple

from test_cache import GatewayCredentialCache
from test_helpers import TestDaliGateway

from PySrDaliGateway.device import Device
from PySrDaliGateway.exceptions import DaliGatewayError
from PySrDaliGateway.types import CallbackEventType, DeviceParamType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
_LOGGER = logging.getLogger(__name__)

# Devices to configure: (address, cct_warm, cct_cool, description)
CCT_CONFIGS: List[Tuple[int, int, int, str]] = [
    (0, 2700, 6500, "standard white range"),
    (1, 3000, 5000, "narrow range"),
    (2, 2000, 7000, "wide range"),
]


async def main() -> bool:
    """Connect to gateway, set CCT ranges, read back and verify."""
    # 1. Load cached credentials
    cache = GatewayCredentialCache()
    if not cache.has_cache():
        _LOGGER.error("No cached gateway credentials found.")
        _LOGGER.error("Run test_all.py first to discover and cache a gateway.")
        return False

    cached = cache.get_last_gateway()
    if not cached:
        _LOGGER.error("Failed to load cached gateway info.")
        return False

    _LOGGER.info(
        "Using cached gateway: %s at %s:%s",
        cached["gw_sn"],
        cached["gw_ip"],
        cached["port"],
    )

    # 2. Create gateway and connect
    loop = asyncio.get_running_loop()
    gateway = TestDaliGateway(
        gw_sn=cached["gw_sn"],
        gw_ip=cached["gw_ip"],
        port=cached["port"],
        username=cached["username"],
        passwd=cached["passwd"],
        name=cached.get("name"),
        channel_total=cached.get("channel_total"),
        is_tls=cached.get("is_tls", False),
        loop=loop,
    )

    try:
        await gateway.connect()
    except DaliGatewayError as e:
        _LOGGER.error("Connection failed: %s", e)
        return False

    _LOGGER.info("Connected to gateway")

    # 3. Discover devices
    try:
        devices = await gateway.discover_devices()
    except DaliGatewayError as e:
        _LOGGER.error("Device discovery failed: %s", e)
        await gateway.disconnect()
        return False

    _LOGGER.info("Discovered %d devices", len(devices))

    # Build address -> device lookup (channel 0 only)
    dev_by_addr: Dict[int, Device] = {d.address: d for d in devices if d.channel == 0}

    # Collect param callback results
    param_events: List[Tuple[str, DeviceParamType]] = []

    def make_param_callback(dev_id: str):
        def callback(params: DeviceParamType) -> None:
            param_events.append((dev_id, params))

        return callback

    # 4. Set CCT range for each target device
    all_ok = True
    interval = 3  # seconds between operations

    for address, cct_warm, cct_cool, desc in CCT_CONFIGS:
        device = dev_by_addr.get(address)
        if device is None:
            _LOGGER.warning(
                "Address %d not found on channel 0 - skipping (%s)", address, desc
            )
            all_ok = False
            continue

        if device.dev_type != "0102":
            _LOGGER.warning(
                "Address %d is type %s, not CCT (0102) - setting anyway (%s)",
                address,
                device.dev_type,
                desc,
            )

        _LOGGER.info(
            "Setting address %d (%s): cct_warm=%d, cct_cool=%d [%s]",
            address,
            device.name,
            cct_warm,
            cct_cool,
            desc,
        )

        params: DeviceParamType = {"cct_warm": cct_warm, "cct_cool": cct_cool}
        device.set_device_parameters(params)
        await asyncio.sleep(interval)

    _LOGGER.info("--- All set commands sent. Reading back to verify... ---")
    await asyncio.sleep(2)

    # 5. Read back and verify
    results: List[Dict[str, Any]] = []

    for address, expected_warm, expected_cool, _desc in CCT_CONFIGS:
        device = dev_by_addr.get(address)
        if device is None:
            results.append(
                {"address": address, "status": "SKIP", "reason": "not found"}
            )
            continue

        param_events.clear()
        device.register_listener(
            CallbackEventType.DEV_PARAM,
            make_param_callback(device.dev_id),
        )
        device.get_device_parameters()

        # Wait for callback
        for _ in range(24):  # up to 12 seconds
            await asyncio.sleep(0.5)
            if param_events:
                break

        if not param_events:
            _LOGGER.error("No parameter response for address %d", address)
            results.append(
                {"address": address, "status": "FAIL", "reason": "no response"}
            )
            all_ok = False
            continue

        got = param_events[-1][1]
        got_warm = got.get("cct_warm", -1)
        got_cool = got.get("cct_cool", -1)

        if got_warm == expected_warm and got_cool == expected_cool:
            status = "OK"
            _LOGGER.info(
                "Address %d: cct_warm=%d, cct_cool=%d - VERIFIED",
                address,
                got_warm,
                got_cool,
            )
        else:
            status = "MISMATCH"
            all_ok = False
            _LOGGER.warning(
                "Address %d: expected warm=%d/cool=%d, got warm=%d/cool=%d",
                address,
                expected_warm,
                expected_cool,
                got_warm,
                got_cool,
            )

        results.append(
            {
                "address": address,
                "status": status,
                "expected": {"cct_warm": expected_warm, "cct_cool": expected_cool},
                "actual": {"cct_warm": got_warm, "cct_cool": got_cool},
            }
        )

    # 6. Print summary
    _LOGGER.info("\n=== CCT Range Configuration Summary ===")
    for r in results:
        addr = r["address"]
        if r["status"] == "SKIP":
            _LOGGER.info("  Address %d: SKIPPED (%s)", addr, r["reason"])
        elif r["status"] == "FAIL":
            _LOGGER.info("  Address %d: FAILED (%s)", addr, r["reason"])
        elif r["status"] == "OK":
            _LOGGER.info(
                "  Address %d: OK (warm=%d, cool=%d)",
                addr,
                r["actual"]["cct_warm"],
                r["actual"]["cct_cool"],
            )
        else:
            _LOGGER.info(
                "  Address %d: MISMATCH (expected warm=%d/cool=%d, got warm=%d/cool=%d)",
                addr,
                r["expected"]["cct_warm"],
                r["expected"]["cct_cool"],
                r["actual"]["cct_warm"],
                r["actual"]["cct_cool"],
            )

    # Disconnect
    with contextlib.suppress(DaliGatewayError):
        await gateway.disconnect()

    if all_ok:
        _LOGGER.info("All CCT ranges set and verified successfully!")
        _LOGGER.info("Reload the HA integration to see updated color temp sliders.")
    else:
        _LOGGER.warning("Some devices had issues - check output above.")

    return all_ok


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
