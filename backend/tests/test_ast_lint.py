"""Tests for the AST lint script."""

from __future__ import annotations

import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
LINT_SCRIPT = REPO_ROOT / "scripts" / "lint_no_literals_in_strategies.py"
STRATEGIES_DIR = REPO_ROOT / "backend" / "app" / "strategies"


def test_lint_passes_on_clean_strategies_dir() -> None:
    result = subprocess.run(
        [sys.executable, str(LINT_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"unexpected lint failure on clean tree:\n{result.stderr}"
    )


def test_lint_catches_injected_literal() -> None:
    """Drop a file with a numeric literal into strategies/ and expect failure."""
    offending = STRATEGIES_DIR / "_lint_probe.py"
    offending.write_text(
        '"""Test probe for AST lint."""\n'
        "def evaluate() -> float:\n"
        "    return 8.0\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, str(LINT_SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "_lint_probe.py" in result.stderr
        assert "8.0" in result.stderr
    finally:
        offending.unlink(missing_ok=True)
