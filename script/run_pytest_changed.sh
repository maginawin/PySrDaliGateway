#!/bin/bash
# Pre-commit hook: run pytest only on changed files.
#
# - test file changed        → run that test file
# - source / infra changed   → run all tests

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

if $run_all; then
    exec pytest tests/
elif (( ${#test_files[@]} )); then
    exec pytest "${test_files[@]}"
fi
