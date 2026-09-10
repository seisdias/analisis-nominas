"""Fail on new diagnostics or stale baseline entries; never rewrite the baseline."""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def diagnostics(tool: str) -> list[str]:
    commands = {
        "ruff": ["ruff", "check", ".", "--output-format", "concise"],
        "mypy": ["mypy", "--no-error-summary", "--no-incremental"],
    }
    result = subprocess.run(
        [sys.executable, "-m", *commands[tool]],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode not in (0, 1) or result.stderr:
        raise RuntimeError(result.stderr or result.stdout)
    lines = [
        line for line in result.stdout.splitlines()
        if ": error:" in line
        or (tool == "ruff" and ": " in line and not line.startswith("Found "))
    ]
    if result.returncode == 1 and not lines:
        raise RuntimeError(result.stdout)
    return sorted(lines)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"ruff", "mypy"}:
        raise SystemExit("Usage: check_static.py {ruff|mypy}")
    tool = sys.argv[1]
    baseline = json.loads((ROOT / "tooling-baseline.json").read_text())
    expected = Counter(baseline[tool])
    actual = Counter(diagnostics(tool))
    new, stale = actual - expected, expected - actual
    for label, entries in [("NEW", new), ("STALE (remove from baseline)", stale)]:
        for entry in entries.elements():
            print(f"{label}: {entry}")
    print(f"{tool}: {sum(actual.values())} legacy diagnostics; "
          f"{sum(new.values())} new; {sum(stale.values())} stale")
    return int(bool(new or stale))


if __name__ == "__main__":
    raise SystemExit(main())
