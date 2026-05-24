#!/usr/bin/env python3
"""Lint: no numeric literals in strategy + backtest engine files.

Enforces Constraint #1 from the research doc — every tunable parameter must
come from the profile registry, never from a hardcoded value.

Allowed literals (universal): 0, 1, -1 (loop bounds, sentinels).
Also allowed:
  - Module-level ``_NAME = literal`` assignments — these are unit-of-measure
    constants (e.g. ``_BPS_DIVISOR = 10_000.0``, ``_SECONDS_PER_MINUTE = 60.0``)
    that are not "parameters" in the tunable-knob sense and must not live in
    the registry.
  - Integer subscript indices (``tup[2]``) — structural indexing into a
    fixed-shape tuple, not a tunable knob.
  - Integer exponents in ``x ** N`` — mathematical operators (e.g. squaring
    for variance), not a tunable knob.

Run: python scripts/lint_no_literals_in_strategies.py
Exit code: 0 if clean, 1 if violations found.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ALLOWED: set[int | float] = {0, 1, -1, 0.0, 1.0, -1.0}

REPO_ROOT = pathlib.Path(__file__).parent.parent
SCAN_TARGETS: list[pathlib.Path] = [
    REPO_ROOT / "backend" / "app" / "strategies",
    REPO_ROOT / "backend" / "app" / "backtest" / "engine.py",
    REPO_ROOT / "backend" / "app" / "backtest" / "fills.py",
    REPO_ROOT / "backend" / "app" / "backtest" / "funding.py",
    REPO_ROOT / "backend" / "app" / "backtest" / "metrics.py",
    REPO_ROOT / "backend" / "app" / "backtest" / "strategies",
]


def _is_module_level_const_assign(node: ast.AST) -> bool:
    """A module-level ``_NAME = literal`` (or annotated) is allowed."""
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        return False
    return all(isinstance(t, ast.Name) and t.id.startswith("_") for t in targets)


def _violations_in_file(
    path: pathlib.Path,
) -> list[tuple[pathlib.Path, int, float | int]]:
    tree = ast.parse(path.read_text())
    # Collect nodes to skip:
    #   - module-level _NAME = ... assignments (unit-of-measure constants)
    #   - subscript indices and Pow exponents (structural / mathematical, not tunable)
    skip_nodes: set[int] = set()
    for node in tree.body:
        if _is_module_level_const_assign(node):
            value_node = node.value
            if value_node is not None:
                for child in ast.walk(value_node):
                    skip_nodes.add(id(child))
    for node in ast.walk(tree):
        # ``tup[N]`` — integer indices into fixed-shape tuples
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            skip_nodes.add(id(node.slice))
        # ``x ** N`` — integer/float exponent is a mathematical operator
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Pow)
            and isinstance(node.right, ast.Constant)
        ):
            skip_nodes.add(id(node.right))

    violations: list[tuple[pathlib.Path, int, float | int]] = []
    for node in ast.walk(tree):
        if id(node) in skip_nodes:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):  # bools are ints in Python; allow
                continue
            if node.value not in ALLOWED:
                violations.append((path, node.lineno, node.value))
    return violations


def _iter_target_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for target in SCAN_TARGETS:
        if not target.exists():
            continue
        if target.is_file() and target.suffix == ".py":
            files.append(target)
        elif target.is_dir():
            files.extend(target.rglob("*.py"))
    return files


def main() -> int:
    violations: list[tuple[pathlib.Path, int, float | int]] = []
    for py_file in _iter_target_files():
        violations.extend(_violations_in_file(py_file))

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
