#!/usr/bin/env python3
"""Lint: no numeric literals in backend/app/strategies/**.

Enforces Constraint #1 from the research doc — every parameter in a strategy
file must come from the profile registry, never from a hardcoded value.

Allowed literals: 0, 1, -1 (loop bounds, sentinels). Everything else fails CI.

Run: python scripts/lint_no_literals_in_strategies.py
Exit code: 0 if clean, 1 if violations found.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ALLOWED: set[int | float] = {0, 1, -1}
SCAN_DIR = pathlib.Path(__file__).parent.parent / "backend" / "app" / "strategies"


def main() -> int:
    if not SCAN_DIR.exists():
        print(f"lint: scan dir {SCAN_DIR} does not exist; nothing to check")
        return 0

    violations: list[tuple[pathlib.Path, int, float | int]] = []
    for py_file in SCAN_DIR.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if isinstance(node.value, bool):  # bools are ints in Python; allow
                    continue
                if node.value not in ALLOWED:
                    violations.append((py_file, node.lineno, node.value))

    if violations:
        for path, lineno, value in violations:
            print(
                f"{path}:{lineno}: numeric literal {value!r} - move to profile registry",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
