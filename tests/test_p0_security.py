"""Focused regression tests for the CLI P0 security fixes."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _client() -> Any:
    from darkmage_cli.client import DarkmageClient

    return DarkmageClient(base_url="http://localhost:8000", token="test-token")


@pytest.fixture
def isolated_security(monkeypatch, tmp_path):
    """Redirect config/key/history paths away from the real home directory."""
    from darkmage_cli import security

    config_dir = tmp_path / "home" / ".darkmage-cli"
    monkeypatch.setattr(security, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(security, "CONFIG_FILE", config_dir / "config.json")
    monkeypatch.setattr(security, "KEY_FILE", config_dir / ".key")
    monkeypatch.setattr(security, "HISTORY_FILE", config_dir / "history.json")
    return config_dir


# ---------------------------------------------------------------------------
# config redaction / permissions
# ---------------------------------------------------------------------------


def test_config_show_json_redacts_token(isolated_security, capsys):
    from darkmage_cli.cli import cmd_config_show
    from darkmage_cli.config import save_config
    from darkmage_cli.security import REDACTED

    save_config(
        {
            "base_url": "http://example.com:8000",
            "token": "super-secret-token",
            "runner_token": "runner-secret-token",
        }
    )

    cmd_config_show(SimpleNamespace(json=True), _client())
    out = capsys.readouterr().out

    assert "super-secret-token" not in out
    assert "runner-secret-token" not in out
    payload = json.loads(out)
    assert payload["base_url"] == "http://example.com:8000"
    assert payload["token"] == REDACTED
    assert payload["runner_token"] == REDACTED


def test_config_set_verbose_redacts_token(isolated_security, capsys):
    from darkmage_cli.cli import cmd_config_set
    from darkmage_cli.config import save_config

    save_config({"token": "super-secret-token"})
    cmd_config_set(
        SimpleNamespace(
            url="http://new:8000",
            token=None,
            runner_url=None,
            runner_token=None,
            verbose=True,
        ),
        _client(),
    )
    out = capsys.readouterr().out
    assert "super-secret-token" not in out
    assert "***REDACTED***" in out


def test_config_export_is_redacted_and_0600(isolated_security, tmp_path):
    from darkmage_cli.cli import cmd_config_export
    from darkmage_cli.config import save_config
    from darkmage_cli.security import REDACTED

    save_config({"base_url": "http://example.com:8000", "token": "super-secret-token"})
    target = tmp_path / "export.json"
    target.write_text("old", encoding="utf-8")
    os.chmod(target, 0o644)

    cmd_config_export(SimpleNamespace(output=str(target)), _client())

    assert (target.stat().st_mode & 0o777) == 0o600
    text = target.read_text(encoding="utf-8")
    assert "super-secret-token" not in text
    payload = json.loads(text)
    assert payload["base_url"] == "http://example.com:8000"
    assert payload["token"] == REDACTED


def test_config_import_does_not_overwrite_live_token(isolated_security, tmp_path):
    from darkmage_cli.cli import cmd_config_export, cmd_config_import
    from darkmage_cli.config import load_config, save_config, set_base_url

    save_config({"base_url": "http://old:8000", "token": "live-secret"})
    target = tmp_path / "export.json"
    cmd_config_export(SimpleNamespace(output=str(target)), _client())

    set_base_url("http://changed:9000")
    cmd_config_import(SimpleNamespace(input=str(target)), _client())

    config = load_config()
    assert config["base_url"] == "http://old:8000"
    assert config["token"] == "live-secret"


# ---------------------------------------------------------------------------
# history masking / permissions / first-run directory
# ---------------------------------------------------------------------------


def test_history_masks_secret_flags_and_creates_dir(isolated_security):
    from darkmage_cli.cli import _record_history

    assert not isolated_security.exists()
    _record_history(
        [
            "config",
            "set",
            "--token",
            "token-value",
            "--runner-token=runner-value",
            "--password",
            "password-value",
            "--api-key",
            "api-key-value",
        ]
    )

    history_file = isolated_security / "history.json"
    assert history_file.exists()
    assert (history_file.stat().st_mode & 0o777) == 0o600
    saved = json.loads(history_file.read_text(encoding="utf-8"))
    command = saved[-1]["command"]
    for secret in (
        "token-value",
        "runner-value",
        "password-value",
        "api-key-value",
    ):
        assert secret not in command
    assert "--token ***" in command
    assert "--runner-token=***" in command


@pytest.mark.parametrize(
    ("command", "secret"),
    [
        ("auth login user@example.com hunter2", "hunter2"),
        ("login user@example.com hunter2", "hunter2"),
        ("auth register --password=hunter2", "hunter2"),
        ("config set --token=hunter2", "hunter2"),
        ("config set --runner-token hunter2", "hunter2"),
        ("admin --api-key hunter2", "hunter2"),
    ],
)
def test_mask_secrets_forms(command, secret):
    from darkmage_cli.cli import _mask_secrets

    masked = _mask_secrets(command)
    assert secret not in masked
    assert "***" in masked


# ---------------------------------------------------------------------------
# term: no local shell, output is only written to stdout
# ---------------------------------------------------------------------------


def test_cmd_term_has_no_local_shell():
    from darkmage_cli.cli import cmd_term

    source = inspect.getsource(cmd_term)
    for forbidden in ("subprocess", "Popen", "openpty", "pty.", '"sh"', "'sh'"):
        assert forbidden not in source


def test_cmd_term_rejects_windows(monkeypatch, capsys):
    from darkmage_cli.cli import cmd_term

    monkeypatch.setattr("darkmage_cli.cli.os.name", "nt")
    cmd_term(SimpleNamespace(workspace_id="ws-1"), object())
    err = capsys.readouterr().err
    assert "Windows" in err


class _FakeWebSocket:
    def __init__(self, incoming: list[bytes | str]) -> None:
        self.incoming = list(incoming)
        self.sent: list[bytes] = []
        self.closed = False

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming:
            raise StopAsyncIteration
        return self.incoming.pop(0)


def test_term_relay_never_executes_remote_output():
    from darkmage_cli.cli import _relay_terminal

    marker = Path("/tmp/darkmage-term-pwned")
    marker.unlink(missing_ok=True)
    remote_output = b"echo PWNED > /tmp/darkmage-term-pwned\n$ "
    ws = _FakeWebSocket([remote_output])
    chunks = iter([b"id\n", b""])

    async def read_stdin() -> bytes:
        return next(chunks)

    local_output = bytearray()
    asyncio.run(_relay_terminal(ws, read_stdin, local_output.extend))

    assert ws.sent == [b"id\n"]
    assert bytes(local_output) == remote_output
    assert not marker.exists()


# ---------------------------------------------------------------------------
# installers: no shell interpolation, fail closed on bad server values
# ---------------------------------------------------------------------------


def _load_install_module():
    path = ROOT / "install.py"
    spec = importlib.util.spec_from_file_location("darkmage_install", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_py_has_no_shell_true():
    tree = ast.parse((ROOT / "install.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    assert not (
                        isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ), f"shell=True at line {node.lineno}"


@pytest.mark.parametrize(
    "server",
    [
        "evil; touch /tmp/pwned",
        "$(touch /tmp/pwned)",
        "`touch /tmp/pwned`",
        "example.com/path",
        "http://example.com",
        "example..com",
        "-rf",
        ".hidden",
        "",
    ],
)
def test_install_py_rejects_injection(server):
    module = _load_install_module()
    with pytest.raises(ValueError):
        module.validate_server(server)


@pytest.mark.parametrize("server", ["127.0.0.1", "example.com", "my-server.local"])
def test_install_py_accepts_hosts(server):
    module = _load_install_module()
    assert module.validate_server(server) == server


def test_install_py_run_uses_argv(monkeypatch):
    module = _load_install_module()
    calls: list[dict[str, Any]] = []

    def fake_run(argv, cwd=None, check=False):
        calls.append({"argv": argv, "cwd": cwd, "check": check})
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.run(["echo", "hello world"])

    assert calls == [{"argv": ["echo", "hello world"], "cwd": None, "check": False}]


def test_install_sh_has_no_rm_rf_and_validates_before_install(tmp_path):
    script = ROOT / "install.sh"
    text = script.read_text(encoding="utf-8")
    assert "rm -rf" not in text

    import subprocess

    syntax = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr

    marker = tmp_path / "pwned"
    env = dict(os.environ, DARKMAGE_INSTALL_DRY_RUN="1")
    injected = subprocess.run(
        ["bash", str(script), f"evil;touch {marker}"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert injected.returncode == 2
    assert not marker.exists()

    valid = subprocess.run(
        ["bash", str(script), "127.0.0.1"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr
    assert "validation passed" in valid.stdout
