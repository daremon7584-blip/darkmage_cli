"""Shared test isolation.

Every test gets its own CLI config directory.  `security` owns the path
constants and reads them at call time, so patching the re-exports in
`darkmage_cli.config` is not enough (P1-14 in docs/CLIENT_RESEARCH).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_cli_config(monkeypatch, tmp_path):
    from darkmage_cli import security

    config_dir = tmp_path / "home" / ".darkmage-cli"
    monkeypatch.setattr(security, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(security, "CONFIG_FILE", config_dir / "config.json")
    monkeypatch.setattr(security, "KEY_FILE", config_dir / ".key")
    monkeypatch.setattr(security, "HISTORY_FILE", config_dir / "history.json")
    return config_dir
