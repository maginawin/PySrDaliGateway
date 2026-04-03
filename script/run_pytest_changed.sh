#!/bin/bash
# Pre-commit hook: run pytest only on changed files.
#
# - test file changed        → run that test file
# - source / infra changed   → run unit tests only (skip hardware tests)
#
# Hardware tests (test_devices, test_groups, test_scenes, test_bus_scan,
# test_connection) require a physical gateway and are skipped here.

REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTEST="${REPO_ROOT}/venv/bin/pytest"
if [ ! -x "$PYTEST" ]; then
    PYTEST="pytest"
fi

# Hardware test files that require a connected gateway.
HARDWARE_TESTS="tests/test_devices.py tests/test_groups.py tests/test_scenes.py tests/test_bus_scan.py tests/test_connection.py"

test_files=()
run_all=false

for f in "$@"; do
    case "$f" in
        tests/test_*.py)
            test_files+=("$f") ;;
        PySrDaliGateway/* | tests/conftest.py | tests/helpers.py | tests/cache.py)
            run_all=true ;;
    esac
done

ignore_args=()
for hw in $HARDWARE_TESTS; do
    ignore_args+=(--ignore="$hw")
done

if $run_all; then
    exec "$PYTEST" tests/ "${ignore_args[@]}"
elif (( ${#test_files[@]} )); then
    # Filter out hardware test files from explicit list.
    unit_files=()
    for f in "${test_files[@]}"; do
        is_hw=false
        for hw in $HARDWARE_TESTS; do
            if [ "$f" = "$hw" ]; then is_hw=true; break; fi
        done
        if ! $is_hw; then unit_files+=("$f"); fi
    done
    if (( ${#unit_files[@]} )); then
        exec "$PYTEST" "${unit_files[@]}"
    fi
fi
