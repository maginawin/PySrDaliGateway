#!/bin/bash
# Pre-commit hook: run pytest for changed files.
#
# Strategy:
# - test file changed         → run that test file directly
# - source file changed       → run the matching test file (by name convention)
# - infra file changed        → run all tests
#
# When no gateway is connected, hardware tests auto-skip (pytest.skip in conftest).

REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTEST="${REPO_ROOT}/venv/bin/pytest"
if [ ! -x "$PYTEST" ]; then
    PYTEST="pytest"
fi

# Infra files: changes here affect everything → run all tests.
# Source files with no single matching test also fall into this category.
INFRA_PATTERNS="tests/conftest.py|tests/helpers.py|tests/cache.py|PySrDaliGateway/types.py|PySrDaliGateway/helper.py|PySrDaliGateway/const.py|PySrDaliGateway/__init__.py"

# Source → test mapping (by naming convention).
# PySrDaliGateway/foo.py → tests/test_foo.py (if it exists)
# Special cases mapped explicitly.
source_to_test() {
    local src="$1"
    local base
    base="$(basename "$src" .py)"

    case "$base" in
        discovery) echo "tests/test_connection.py" ;;
        *)         echo "tests/test_${base}.py" ;;
    esac
}

test_files=()
run_all=false

for f in "$@"; do
    # Infra file → run all
    if echo "$f" | grep -qE "^($INFRA_PATTERNS)$"; then
        run_all=true
        continue
    fi

    case "$f" in
        tests/test_*.py)
            test_files+=("$f") ;;
        PySrDaliGateway/*.py)
            mapped="$(source_to_test "$f")"
            if [ -f "$REPO_ROOT/$mapped" ]; then
                test_files+=("$mapped")
            else
                run_all=true
            fi
            ;;
    esac
done

# Deduplicate test files (compatible with macOS bash 3.2).
if (( ${#test_files[@]} )); then
    deduped=()
    while IFS= read -r f; do
        deduped+=("$f")
    done <<< "$(printf '%s\n' "${test_files[@]}" | sort -u)"
    test_files=("${deduped[@]}")
fi

if $run_all; then
    exec "$PYTEST" tests/
elif (( ${#test_files[@]} )); then
    exec "$PYTEST" "${test_files[@]}"
fi
