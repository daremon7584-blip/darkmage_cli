"""P1 UX contracts: --version, global --json, non-TTY no-args, DARKMAGE_TOKEN."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from darkmage_cli import __version__
from darkmage_cli.cli import (
    build_parser,
    cmd_auth_interactive,
    cmd_start,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError
from darkmage_cli.security import REDACTED


# ---------------------------------------------------------------------------
# P1-15: --version
# ---------------------------------------------------------------------------


def test_version_flag_prints_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"darkmage {__version__}"


def test_short_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["-V"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"darkmage {__version__}"


# ---------------------------------------------------------------------------
# P1-7: --json works before and after subcommands
# ---------------------------------------------------------------------------


def _save_config():
    from darkmage_cli.config import save_config

    save_config(
        {
            "base_url": "http://example.com:8000",
            "token": "secret-token-12345",
        }
    )


def test_json_after_subcommand(capsys):
    _save_config()
    assert main(["config", "show", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["base_url"] == "http://example.com:8000"
    assert payload["token"] == REDACTED
    assert "secret-token" not in json.dumps(payload)


def test_json_before_subcommand(capsys):
    _save_config()
    assert main(["--json", "config", "show"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["base_url"] == "http://example.com:8000"
    assert payload["token"] == REDACTED


def test_json_default_is_preserved(capsys):
    _save_config()
    assert main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert "Конфиг" in out
    assert "secret-token" not in out


@pytest.mark.parametrize(
    "argv",
    [
        ["workspace", "list", "--json"],
        ["workspace", "--json", "list"],
        ["run", "create", "ses-1", "--prompt", "hi", "--json"],
        ["exec", "hi", "--json"],
        ["health", "--json"],
    ],
)
def test_json_is_accepted_in_any_position(argv):
    assert build_parser().parse_args(argv).json is True


def test_json_is_false_by_default():
    assert build_parser().parse_args(["workspace", "list"]).json is False


def test_json_error_after_subcommand(monkeypatch, capsys):
    def fail(self):
        raise DarkmageError("bad token", status_code=401)

    monkeypatch.setattr(DarkmageClient, "health", fail)
    assert main(["health", "--json"]) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["message"] == "bad token"
    assert payload["error"]["status_code"] == 401


# ---------------------------------------------------------------------------
# P1-10: no args + non-TTY must not enter interactive login/TUI
# ---------------------------------------------------------------------------


def _non_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)


def test_main_no_args_non_tty_errors_instead_of_eoferror(monkeypatch, capsys):
    monkeypatch.delenv("DARKMAGE_TOKEN", raising=False)
    _non_tty(monkeypatch)

    assert main([]) == 2
    captured = capsys.readouterr()
    assert "TTY" in captured.err
    assert "Error:" in captured.err
    assert "EOFError" not in captured.err
    assert "Traceback" not in captured.err


def test_main_no_args_non_tty_does_not_start_tui_with_env_token(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "env-token")
    _non_tty(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        "darkmage_cli.cli.cmd_start", lambda args, client: calls.append("start") or 0
    )

    assert main([]) == 2
    assert calls == []
    assert "TTY" in capsys.readouterr().err


def test_main_no_args_non_tty_json_error(monkeypatch, capsys):
    monkeypatch.delenv("DARKMAGE_TOKEN", raising=False)
    _non_tty(monkeypatch)

    assert main(["--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["error"]["code"] == "interactive_required"
    assert payload["error"]["retryable"] is False


def test_auth_interactive_non_tty_errors(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cmd_auth_interactive(SimpleNamespace(), object()) == 2
    assert "TTY" in capsys.readouterr().err


def test_start_non_tty_errors(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "env-token")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cmd_start(SimpleNamespace(), object()) == 2
    assert "TTY" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# P1-11: cmd_start honors DARKMAGE_TOKEN
# ---------------------------------------------------------------------------


def test_cmd_start_uses_env_token(monkeypatch, capsys):
    from darkmage_cli.config import load_config

    monkeypatch.setenv("DARKMAGE_TOKEN", "env-token")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert load_config().get("token") is None  # nothing in the config file

    started: list[dict] = []
    monkeypatch.setattr(
        "darkmage_cli.tui.run_tui", lambda **kwargs: started.append(kwargs)
    )

    class Client:
        token = None
        base_url = "http://env.example:8000"

        def workspace_list(self):
            return [{"id": "ws-1", "name": "Workspace", "status": "running"}]

    client = Client()
    assert cmd_start(SimpleNamespace(), client) == 0
    assert client.token == "env-token"
    assert started == [
        {
            "base_url": "http://env.example:8000",
            "token": "env-token",
            "workspace_id": "ws-1",
        }
    ]
