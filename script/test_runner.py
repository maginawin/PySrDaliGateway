#!/usr/bin/env python3
"""Test execution and dependency management for DALI Gateway tests."""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Set, Tuple

from test_cases import DaliGatewayTester

from PySrDaliGateway.exceptions import DaliGatewayError

_LOGGER = logging.getLogger(__name__)


async def run_selected_tests(tester: DaliGatewayTester, args: Any) -> bool:
    """Run selected tests with dependency management."""

    # Check if using testing mode (direct configuration)
    using_testing_mode = all(
        [
            args.direct_sn,
            args.direct_ip,
            args.direct_username,
            args.direct_passwd,
        ]
    )

    # Available tests with dependencies
    test_registry: Dict[str, Tuple[Callable[[], Any], List[str], str]] = {
        "discovery": (
            lambda: (
                tester.create_gateway_direct(
                    args.direct_sn,
                    args.direct_ip,
                    args.direct_port,
                    args.direct_username,
                    args.direct_passwd,
                    args.direct_tls,
                    args.direct_name,
                )
                if using_testing_mode
                else tester.test_discovery()
            ),
            [],
            "Gateway Discovery"
            if not using_testing_mode
            else "Gateway Direct Configuration",
        ),
        "connection": (
            lambda: tester.test_connection(args.gateway_index),
            ["discovery"],
            "Gateway Connection",
        ),
        "disconnect": (tester.test_disconnect, ["connection"], "Gateway Disconnect"),
        "reconnection": (
            tester.test_reconnection,
            ["connection"],
            "Reconnection Cycle",
        ),
        "statusync": (
            tester.test_gateway_status_sync,
            ["connection"],
            "Gateway Status Sync",
        ),
        "version": (tester.test_version, ["connection"], "Version Retrieval"),
        "devices": (tester.test_device_discovery, ["connection"], "Device Discovery"),
        "readdev": (
            lambda: tester.test_read_dev(args.device_limit),
            ["connection", "devices"],
            "ReadDev Commands",
        ),
        "setdevparam": (
            tester.test_set_dev_param,
            ["devices"],
            "SetDevParam Commands",
        ),
        "setsensorparam": (
            tester.test_set_sensor_param,
            ["connection"],
            "SetSensorParam Commands",
        ),
        "groups": (tester.test_group_discovery, ["connection"], "Group Discovery"),
        "readgroup": (
            tester.test_read_group,
            ["connection", "groups", "creategroup"],
            "Read Group Details",
        ),
        "scenes": (tester.test_scene_discovery, ["connection"], "Scene Discovery"),
        "readscene": (
            tester.test_scene_devices,
            ["connection", "scenes", "createscene"],
            "Read Scene Details",
        ),
        "scenedevices": (
            tester.test_scene_devices,
            ["connection", "scenes", "createscene"],
            "Scene Device Access",
        ),
        "callbacks": (
            tester.test_callback_setup,
            ["connection", "devices"],
            "Device Callbacks",
        ),
        # "identifygateway": (
        #     tester.test_identify_gateway,
        #     ["discovery"],
        #     "Identify Gateway",
        # ),
        "identifydevice": (
            lambda: tester.test_identify_device(args.device_limit),
            ["connection", "devices"],
            "Identify Devices",
        ),
        "creategroup": (
            tester.test_create_group,
            ["connection", "devices"],
            "Create Test Group",
        ),
        "createscene": (
            tester.test_create_scene,
            ["connection", "devices"],
            "Create Test Scene",
        ),
        "cleanup": (
            tester.test_cleanup_test_data,
            ["connection", "groups", "scenes"],
            "Cleanup Test Data",
        ),
        "busscan": (
            tester.test_bus_scan_basic,
            [
                "connection"
            ],  # Removed "devices" dependency to test without prior exited discovery
            "Bus Scan (Basic Flow)",
        ),
        "busscanbusy": (
            tester.test_bus_scan_after_control,
            ["connection", "devices"],
            "Bus Scan After Control",
        ),
        "stopscan": (
            tester.test_stop_scan,
            ["connection"],
            "Stop Bus Scan",
        ),
        "restart": (tester.test_restart_gateway, ["connection"], "Gateway Restart"),
    }

    # Determine which tests to run
    if "all" in args.tests:
        selected_tests = [
            "discovery",
            "connection",
            "statusync",
            "version",
            "devices",
            "callbacks",
            "readdev",
            "setdevparam",
            "groups",
            "readgroup",
            "scenes",
            "readscene",
            # "identifygateway",
            "identifydevice",
            "reconnection",
            "restart",
            "disconnect",
        ]
    else:
        selected_tests = args.tests

    # Build execution plan with dependencies
    execution_plan: List[Tuple[str, Callable[[], Any], str]] = []
    completed_tests: Set[str] = set()

    def add_test_with_deps(test_name: str):
        if test_name in completed_tests or test_name in [t[0] for t in execution_plan]:
            return

        if test_name not in test_registry:
            _LOGGER.error("Unknown test: %s", test_name)
            return

        test_func, dependencies, description = test_registry[test_name]

        # Add dependencies first
        for dep in dependencies:
            add_test_with_deps(dep)

        execution_plan.append((test_name, test_func, description))

    # Build execution plan
    for test_name in selected_tests:
        add_test_with_deps(test_name)

    # Execute tests
    _LOGGER.info("=== Test Execution Plan ===")
    for test_name, _, description in execution_plan:
        _LOGGER.info("- %s (%s)", description, test_name)

    results: Dict[str, bool] = {}
    for test_name, test_func, description in execution_plan:
        _LOGGER.info("\n🧪 Running: %s", description)
        try:
            # Special handling for discovery with gateway_sn parameter
            if test_name == "discovery" and args.gateway_sn:
                result = await tester.test_discovery(args.gateway_sn)
            else:
                result = await test_func()

            results[test_name] = result
            completed_tests.add(test_name)

            if result:
                _LOGGER.info("✅ %s completed successfully", description)
            else:
                _LOGGER.error("❌ %s failed", description)
                # Stop execution if critical test fails
                if test_name in ["discovery", "connection"]:
                    _LOGGER.error("Critical test failed, stopping execution")
                    break
        except KeyboardInterrupt:
            _LOGGER.error("❌ %s interrupted by user", description)
            results[test_name] = False
            # Always stop on user interrupt
            break
        except (DaliGatewayError, RuntimeError, asyncio.TimeoutError) as e:
            _LOGGER.error("❌ %s failed with exception: %s", description, e)
            results[test_name] = False
            # Stop on critical failures
            if test_name in ["discovery", "connection"]:
                break

    # Summary
    passed = sum(1 for r in results.values() if r)
    total = len(results)

    _LOGGER.info("\n=== Test Summary ===")
    _LOGGER.info("Executed: %d/%d planned tests", total, len(execution_plan))
    _LOGGER.info("Passed: %d/%d executed tests", passed, total)

    for test_name, result in results.items():
        status = "✅" if result else "❌"
        description = test_registry[test_name][2]
        _LOGGER.info("%s %s", status, description)

    success = passed == total == len(execution_plan)
    if success:
        _LOGGER.info("🎉 All requested tests completed successfully!")
    else:
        _LOGGER.error("❌ Some tests failed or were not executed!")

    return success
