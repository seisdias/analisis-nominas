#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "${PYTHON:-}" ]]; then
    python_bin="$PYTHON"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
    python_bin="$VIRTUAL_ENV/bin/python"
elif [[ -x venv/bin/python ]]; then
    python_bin=venv/bin/python
else
    python_bin=python3
fi
export PYTHONDONTWRITEBYTECODE=1
"$python_bin" -c 'import pathlib, platform; expected = pathlib.Path(".python-version").read_text().strip(); assert platform.python_version() == expected, f"Python {expected} required"'
"$python_bin" scripts/check_static.py ruff
"$python_bin" scripts/check_static.py mypy
"$python_bin" -m pytest -q -m 'not private'
