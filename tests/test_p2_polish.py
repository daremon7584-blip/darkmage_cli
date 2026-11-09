"""Focused tests for the CLI P2 polish pass.

Covers responsive tables, REPL help/history/parser reuse, concurrent
``parallel`` with bounded output, streaming/JSON ``chat``, TUI escaping and
bounded event memory, and the ``term``/URL-warning/config guards.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import threading
from types import SimpleNamespace

import pytest

import darkmage_cli.cli as cli
from darkmage_cli.cli import (
    _bash_completion_script,
    _fish_completion_script,
    _format_table,
    _load_repl_history,
    _run_parallel_commands,
    _zsh_completion_script,
    build_parser,
    cmd_chat,
    cmd_parallel,
    cmd_repl,
    cmd_term,
    cmd_ws_list,
    print_help_repl,
)
from darkmage_cli.client import _chat_events_from_payload


# ---------------------------------------------------------------------------
# Responsive tables
# ---------------------------------------------------------------------------


def test_format_table_never_exceeds_80_columns():
    rows = [
        [
            "ws_" + "a" * 33,
            "Очень длинное имя рабочей зоны " * 3,
            "running",
            "auto",
        ]
    ]
    lines = _format_table(
        ["ID", "Имя", "Статус", "Режим"],
        rows,
        width=80,
        min_widths=[36, 12, 9, 6],
        drop_order=[3, 2],
    )
    assert lines
    assert all(len(line) <= 80 for line in lines)
    assert rows[0][0] in "\n".join(lines)


def test_format_table_falls_back_to_compact_before_overflowing():
    rows = [["run_" + "a" * 36, "waiting_approval", "model", "prompt " * 20, "2026-01-01"]]
    lines = _format_table(
        ["ID", "Статус", "Модель", "Промпт", "Создан"],
        rows,
        width=60,
        min_widths=[40, 16, 6, 8, 10],
        drop_order=[2],
    )
    assert all(len(line) <= 60 for line in lines)
    assert any("Статус: waiting_approval" in line for line in lines)


def test_format_table_compact_layout_keeps_fields_at_40_columns():
    rows = [["ws_" + "a" * 33, "Очень длинное имя", "running", "ask"]]
    lines = _format_table(
        ["ID", "Имя", "Статус", "Режим"],
        rows,
        width=40,
        min_widths=[36, 12, 9, 6],
        drop_order=[3, 2],
    )
    rendered = "\n".join(lines)
    assert all(len(line) <= 40 for line in lines)
    assert "Статус: running" in rendered
    assert "Режим: ask" in rendered


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


def test_workspace_list_renders_at_80_columns(monkeypatch):
    class FakeClient:
        def workspace_list(self, limit=50):
            return [
                {
                    "id": "ws_" + "a" * 33,
                    "name": "Очень длинное имя рабочей зоны",
                    "status": "running",
                    "approval_mode": "auto",
                }
            ]

    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    cmd_ws_list(SimpleNamespace(json=False, limit=50), FakeClient())
    out = stream.getvalue()
    assert out.strip()
    assert all(len(line) <= 80 for line in out.splitlines())


# ---------------------------------------------------------------------------
# REPL: current help, parser reuse, shlex errors, persistent history
# ---------------------------------------------------------------------------


def test_repl_help_is_generated_from_current_parser(capsys):
    print_help_repl()
    out = capsys.readouterr().out
    for command in ("approvals", "exec", "history", "parallel", "completion"):
        assert command in out
    assert all(len(line) <= 96 for line in out.splitlines())


def test_repl_builds_parser_once_and_survives_bad_quote(monkeypatch, capsys):
    inputs = iter(["help", "workspace create 'unterminated", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(cli, "_readline_module", lambda: None)
    monkeypatch.setattr(cli, "_load_repl_history", lambda module: 0)

    calls = {"count": 0}
    real_build = cli.build_parser

    def counting_build():
        calls["count"] += 1
        return real_build()

    monkeypatch.setattr(cli, "build_parser", counting_build)

    cmd_repl(SimpleNamespace(), object())

    captured = capsys.readouterr()
    assert calls["count"] == 1
    assert "Ошибка разбора команды" in captured.err


def test_repl_history_is_loaded_from_persisted_commands(isolate_cli_config):
    from darkmage_cli.cli import _record_history

    _record_history(["workspace", "list"])
    _record_history(["auth", "login", "user@example.com", "hunter2"])

    class FakeReadline:
        def __init__(self):
            self.lines = []
            self.length = None

        def add_history(self, line):
            self.lines.append(line)

        def set_history_length(self, length):
            self.length = length

    fake = FakeReadline()
    assert _load_repl_history(fake) == 2
    assert fake.lines[0] == "workspace list"
    assert "hunter2" not in fake.lines[1]
    assert fake.length == 100


# ---------------------------------------------------------------------------
# parallel: genuinely concurrent + bounded output
# ---------------------------------------------------------------------------


def test_parallel_runs_commands_concurrently(monkeypatch, capsys):
    barrier = threading.Barrier(2, timeout=2)

    def rendezvous(args, client):
        # Only a genuinely concurrent implementation lets both workers reach
        # the barrier. Sequential execution raises BrokenBarrierError.
        barrier.wait()
        print(f"done {args.command}")

    monkeypatch.setattr(
        cli, "cmd_health", lambda args, client: rendezvous(
            SimpleNamespace(command="health"), client
        )
    )
    monkeypatch.setattr(
        cli, "cmd_ready", lambda args, client: rendezvous(
            SimpleNamespace(command="ready"), client
        )
    )

    args = SimpleNamespace(
        commands=["health", "ready"],
        url=None,
        runner_url=None,
        runner_token=None,
        json=False,
        verbose=False,
    )
    cmd_parallel(args, object())

    out = capsys.readouterr().out
    assert "OK: health" in out
    assert "OK: ready" in out
    assert "BrokenBarrier" not in out


def test_parallel_output_is_bounded(monkeypatch):
    monkeypatch.setattr(
        cli, "cmd_health", lambda args, client: print("x" * 5000)
    )
    results = asyncio.run(
        _run_parallel_commands(["health"], defaults={}, limit=200)
    )
    code, output, errors, truncated = results[0]
    assert code == 0
    assert len(output) <= 200
    assert truncated is True


def test_bounded_buffer_caps_and_marks_truncation():
    buffer = cli._BoundedBuffer(10)
    buffer.write("abcdefghijklmnop")
    assert buffer.value() == "abcdefghij"
    assert buffer.truncated is True


# ---------------------------------------------------------------------------
# chat: streaming, JSON, stdin, usage not on stdout in normal mode
# ---------------------------------------------------------------------------


class FakeChatClient:
    def __init__(self, chunks: list[str] | None = None):
        self.chunks = chunks or ["Hel", "lo"]
        self.messages: list[dict[str, str]] = []
        self.usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}

    def chat_completion_stream(self, messages, model, temperature, max_tokens):
        self.messages = messages
        for chunk in self.chunks:
            yield {"type": "delta", "text": chunk}
        yield {"type": "usage", "usage": self.usage}
        yield {"type": "done"}


def _chat_args(**overrides):
    values = {
        "message": "hi",
        "system": None,
        "model": None,
        "temperature": 0.7,
        "max_tokens": None,
        "json": False,
        "no_stream": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_chat_streams_text_and_sends_usage_to_stderr(capsys):
    client = FakeChatClient()
    assert cmd_chat(_chat_args(), client) == 0
    captured = capsys.readouterr()
    assert captured.out == "Hello\n"
    assert "usage: prompt=1 completion=2 total=3" in captured.err
    # Usage must never be a JSON blob on stdout in normal mode.
    assert "prompt_tokens" not in captured.out


def test_chat_json_envelope(capsys):
    client = FakeChatClient()
    assert cmd_chat(_chat_args(json=True), client) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["content"] == "Hello"
    assert payload["usage"]["total_tokens"] == 3
    assert captured.err == ""


def test_chat_reads_stdin_when_message_omitted(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("from stdin"))
    client = FakeChatClient()
    assert cmd_chat(_chat_args(message=None), client) == 0
    assert client.messages[-1] == {"role": "user", "content": "from stdin"}
    assert capsys.readouterr().out == "Hello\n"


def test_chat_json_flag_is_accepted_after_message():
    args = build_parser().parse_args(["chat", "hi", "--json", "--no-stream"])
    assert args.json is True
    assert args.no_stream is True


def test_chat_payload_normalization_handles_delta_and_usage():
    events = list(
        _chat_events_from_payload(
            {
                "choices": [{"delta": {"content": "Hi"}}],
                "usage": {"total_tokens": 4},
            }
        )
    )
    assert events == [
        {"type": "delta", "text": "Hi"},
        {"type": "usage", "usage": {"total_tokens": 4}},
    ]


# ---------------------------------------------------------------------------
# TUI escaping and bounded event log
# ---------------------------------------------------------------------------


def test_tui_sanitizer_strips_ansi_and_escapes_markup():
    from darkmage_cli.tui import safe_markup, strip_control

    raw = "hello\x1b[31m[bold red]pwn[/]\x07\r"
    cleaned = strip_control(raw)
    assert "\x1b" not in cleaned
    assert "\x07" not in cleaned
    assert "\r" not in cleaned
    escaped = safe_markup(raw)
    assert "\\[bold red]" in escaped


def test_tui_event_log_is_bounded():
    from darkmage_cli.tui import MAX_EVENTS_LOG, DarkmageTUI

    tui = object.__new__(DarkmageTUI)
    tui._events_log = []
    for index in range(MAX_EVENTS_LOG + 50):
        tui._remember_event({"id": index})
    assert len(tui._events_log) == MAX_EVENTS_LOG
    assert tui._events_log[0]["id"] == 50


# ---------------------------------------------------------------------------
# term guard, config dedup, insecure URL warning
# ---------------------------------------------------------------------------


def test_term_rejects_windows_and_non_tty(monkeypatch, capsys):
    monkeypatch.setattr("darkmage_cli.cli.os.name", "nt")
    assert cmd_term(SimpleNamespace(workspace_id="ws-1"), object()) == 1
    assert "Windows" in capsys.readouterr().err

    monkeypatch.setattr("darkmage_cli.cli.os.name", "posix")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert cmd_term(SimpleNamespace(workspace_id="ws-1"), object()) == 1
    assert "TTY" in capsys.readouterr().err


def test_is_configured_has_one_semantics(monkeypatch, isolate_cli_config):
    from darkmage_cli.config import is_configured as config_is_configured
    from darkmage_cli.security import is_configured as security_is_configured

    monkeypatch.setenv("DARKMAGE_TOKEN", "env-token")
    monkeypatch.delenv("DARKMAGE_API_URL", raising=False)
    assert config_is_configured() is True
    assert security_is_configured() is True

    monkeypatch.delenv("DARKMAGE_TOKEN")
    assert config_is_configured() is False
    assert security_is_configured() is False


def test_warn_insecure_url_goes_to_stderr_and_rejects_lookalike(monkeypatch, capsys):
    from darkmage_cli.security import is_secure_connection, warn_insecure_url

    assert is_secure_connection("http://localhost:8000") is True
    assert is_secure_connection("http://localhost.evil.example") is False
    warn_insecure_url("http://example.com")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ПРЕДУПРЕЖДЕНИЕ" in captured.err

    warn_insecure_url("http://127.0.0.1:8000")
    assert capsys.readouterr().err == ""


def test_main_warns_about_insecure_base_url(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cli, "warn_insecure_url", lambda url, **kwargs: calls.append(url))
    assert cli.main(["--url", "http://example.com", "completion", "bash"]) == 0
    assert calls == ["http://example.com"]


# ---------------------------------------------------------------------------
# Completion/help includes new commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    [_bash_completion_script, _zsh_completion_script, _fish_completion_script],
)
def test_completion_scripts_include_new_commands(script):
    text = script()
    for command in ("approvals", "exec", "history", "parallel", "repl"):
        assert command in text


@pytest.mark.parametrize(
    ("script", "flags"),
    [
        (_bash_completion_script, ("--json", "--version", "--output-format", "--scope")),
        (_zsh_completion_script, ("--json", "--version", "--output-format", "--scope")),
        (_fish_completion_script, ("-l json", "-l version", "-l output-format", "-l scope")),
    ],
)
def test_completion_scripts_include_new_global_and_subcommand_flags(script, flags):
    text = script()
    for flag in flags:
        assert flag in text


def test_zsh_completion_invokes_the_defined_function():
    script = _zsh_completion_script()
    assert "_darkmage()" in script
    assert '_darkmage "$@"' in script


def test_parser_registers_p2_commands():
    parser = build_parser()
    for command in ("approvals", "exec", "history", "parallel", "repl", "chat"):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args([command, "--help"])
        assert exc.value.code == 0
