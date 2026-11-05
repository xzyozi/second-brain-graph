#!/bin/sh
set -eu

if command -v python >/dev/null 2>&1; then
    python_command=python
elif command -v python3 >/dev/null 2>&1; then
    python_command=python3
else
    echo "FAKE_AGY_PYTHON_NOT_FOUND" >&2
    exit 127
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$python_command" "$script_dir/fake_agy.py" "$@"
