"""Packaging metadata checks for a clean `pip install .`."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project_dependencies() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib

        return list(tomllib.loads(text)["project"]["dependencies"])
    except (ImportError, KeyError):
        # Python 3.10 has no tomllib; the dependencies block is simple TOML.
        match = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.MULTILINE | re.DOTALL)
        assert match, "dependencies block not found"
        return re.findall(r'"([^"]+)"', match.group(1))


def _dependency_name(requirement: str) -> str:
    return re.split(r"[<>=!~\[ ;]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def test_cryptography_is_declared():
    names = {_dependency_name(item) for item in _project_dependencies()}
    assert "cryptography" in names, f"missing cryptography in {sorted(names)}"


def test_security_module_imports_standalone():
    result = subprocess.run(
        [sys.executable, "-c", "import darkmage_cli.security"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_console_script_is_declared():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'darkmage = "darkmage_cli.cli:main"' in text
