"""`run verification`: terminal-event evidence, diagnostics and errors."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import darkmage_cli.cli as cli
from darkmage_cli.cli import (
    _bash_completion_script,
    _fish_completion_script,
    _zsh_completion_script,
    build_parser,
    cmd_run_verification,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError

RUN_ID = "22222222-2222-4222-8222-222222222222"


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


class FakeVerificationClient:
    def __init__(self, events=None, error=None):
        self.events = events if events is not None else []
        self.error = error
        self.calls: list[str] = []
        self.token = "super-secret-token"

    def run_events_parsed(self, run_id, last_event_id=None, **kwargs):
        self.calls.append(run_id)
        if self.error:
            raise self.error
        for event in self.events:
            yield event


def _args(**overrides):
    values = {"run_id": RUN_ID, "json": False}
    values.update(overrides)
    return SimpleNamespace(**values)


def _quiet(text):
    return cli._ANSI_ESCAPE_RE.sub("", text)


def _event(event_type, **data):
    return {"id": "7", "event": event_type, "data": data}


def _completed(verification=None, finish_reason="completed", **data):
    payload = {"finish_reason": finish_reason, **data}
    if verification is not None:
        payload["verification"] = verification
    return _event("run.completed", **payload)


def _verified(**overrides):
    verification = {
        "status": "verified",
        "command": "pytest -q",
        "exit_code": 0,
    }
    verification.update(overrides)
    return verification


def _unverified(**overrides):
    verification = {
        "status": "unverified",
        "command": "npm test",
        "exit_code": 1,
        "failures": ["FAIL src/a.test.ts > adds", "AssertionError: expected 1"],
        "summary": "exit code 1",
    }
    verification.update(overrides)
    return verification


def _render(monkeypatch, events):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    assert cmd_run_verification(_args(), FakeVerificationClient(events)) == 0
    return _quiet(stream.getvalue())


# ---------------------------------------------------------------------------
# Human statuses
# ---------------------------------------------------------------------------


def test_verified_run_shows_checked_command_and_exit_code(monkeypatch):
    out = _render(monkeypatch, [_completed(_verified())])

    assert f"Run:         {RUN_ID}" in out
    assert "Проверка:    Проверено" in out
    assert "run.completed (finish_reason=completed)" in out
    assert "Команда:     pytest -q" in out
    assert "Код выхода:  0" in out
    assert "Ошибки:      —" in out
    assert "Диагностика: —" in out


def test_unverified_run_shows_failures_and_summary(monkeypatch):
    out = _render(monkeypatch, [_completed(_unverified())])

    assert "Проверка:    Не проверено" in out
    assert "Команда:     npm test" in out
    assert "Код выхода:  1" in out
    assert "Сводка:" in out and "exit code 1" in out
    assert "FAIL src/a.test.ts > adds" in out
    assert "AssertionError: expected 1" in out


def test_verification_required_explains_missing_check(monkeypatch):
    out = _render(
        monkeypatch,
        [_completed(_unverified(), finish_reason="verification_required")],
    )

    assert "Проверка:    Требуется проверка" in out
    assert "Пояснение:" in out
    assert "изменения не проверены" in out
    assert "verification_required" in out


def test_partial_run_shows_partial_report(monkeypatch):
    report = "Run stopped early (budget); this is a partial result."
    out = _render(
        monkeypatch,
        [
            _completed(
                _unverified(),
                finish_reason="partial",
                report=report,
            )
        ],
    )

    assert "Проверка:    Не проверено" in out
    assert "завершён частично" in out
    assert "partial" in out
    assert "Отчёт:" in out
    assert "partial result" in out


def test_not_run_status_when_terminal_event_has_no_check(monkeypatch):
    out = _render(
        monkeypatch,
        [_event("run.failed", reason="no_progress_timeout", report="Run failed early.")],
    )

    assert "Проверка:    Не запускалась" in out
    assert "run.failed (reason=no_progress_timeout)" in out
    assert "Run завершился ошибкой" in out
    assert "проверка не запускалась" in out
    assert "Отчёт:" in out and "Run failed early." in out


def test_explicit_verification_required_status_is_honored(capsys):
    events = [
        _completed(
            {"status": "verification_required", "command": None, "exit_code": None}
        )
    ]

    assert cmd_run_verification(_args(json=True), FakeVerificationClient(events)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "verification_required"


# ---------------------------------------------------------------------------
# Failures and diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_kind_and_counts_with_parsed_failures(monkeypatch):
    verification = _unverified(
        failures=[],
        diagnostics={
            "kind": "pytest",
            "status": "failed",
            "failures": [
                {
                    "path": "src/test_app.py",
                    "line": 12,
                    "message": "assert 1 == 2",
                }
            ],
            "counts": {"diagnostics": 12, "omitted": 10},
        },
    )
    out = _render(monkeypatch, [_completed(verification)])

    assert "Диагностика:" in out
    assert "pytest: failed" in out
    assert "counts: diagnostics=12, omitted=10" in out
    assert "src/test_app.py:12: assert 1 == 2" in out


def test_failures_are_limited_to_top_eight(monkeypatch):
    failures = [f"FAIL test_{index}.py" for index in range(10)]
    out = _render(
        monkeypatch,
        [_completed(_unverified(failures=failures))],
    )

    assert "Ошибки:      8 (первые 8)" in out
    assert "FAIL test_0.py" in out
    assert "FAIL test_7.py" in out
    assert "FAIL test_8.py" not in out
    assert "FAIL test_9.py" not in out


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def test_json_returns_required_envelope(capsys):
    verification = _verified()
    client = FakeVerificationClient([_completed(verification)])

    assert cmd_run_verification(_args(json=True), client) == 0

    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "run_id",
        "status",
        "finish_reason",
        "verification",
        "report",
    }
    assert payload["run_id"] == RUN_ID
    assert payload["status"] == "verified"
    assert payload["finish_reason"] == "completed"
    assert payload["verification"] == verification
    assert payload["report"] is None
    assert client.calls == [RUN_ID]


def test_json_uses_last_terminal_event(capsys):
    events = [
        _completed(_unverified(), finish_reason="verification_required"),
        _completed(_verified()),
    ]

    assert cmd_run_verification(_args(json=True), FakeVerificationClient(events)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "verified"
    assert payload["finish_reason"] == "completed"


def test_json_failed_run_falls_back_to_reason(capsys):
    events = [_event("run.failed", reason="output_truncated", report="Cut off.")]

    assert cmd_run_verification(_args(json=True), FakeVerificationClient(events)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_run"
    assert payload["finish_reason"] == "output_truncated"
    assert payload["verification"] == {}
    assert payload["report"] == "Cut off."


# ---------------------------------------------------------------------------
# Missing terminal event and HTTP errors
# ---------------------------------------------------------------------------


def test_no_terminal_event_is_clear_and_exits_two(capsys):
    client = FakeVerificationClient([_event("run.started")])

    assert cmd_run_verification(_args(), client) == 2

    captured = capsys.readouterr()
    assert "no terminal run.completed/run.failed event" in captured.err
    assert "darkmage run events" in captured.err
    assert "Traceback" not in captured.err


def test_cancelled_run_has_no_verification_terminal(capsys):
    client = FakeVerificationClient([_event("run.cancelled", reason="owner")])

    assert cmd_run_verification(_args(), client) == 2

    assert "no terminal run.completed/run.failed event" in capsys.readouterr().err


def test_no_terminal_event_json_is_structured(capsys):
    assert (
        cmd_run_verification(
            _args(json=True),
            FakeVerificationClient([_event("run.started")]),
        )
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "no_terminal_event"
    assert "run.completed/run.failed" in payload["error"]["message"]


def test_verification_404_is_clear_without_token(monkeypatch, capsys):
    def fail(self, run_id, *args, **kwargs):
        raise DarkmageError(
            "404 Not Found for GET /runs/x/events: Run not found",
            status_code=404,
        )

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_events_parsed", fail)

    assert main(["--url", "https://api.example.test", "run", "verification", RUN_ID]) == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()
    assert "404" in captured.err
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.err


def test_verification_403_is_clear_without_token(monkeypatch, capsys):
    def fail(self, run_id, *args, **kwargs):
        raise DarkmageError(
            "403 Forbidden for GET /runs/x/events: Not enough permissions",
            status_code=403,
        )

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_events_parsed", fail)

    assert main(["--url", "https://api.example.test", "run", "verification", RUN_ID]) == 1

    captured = capsys.readouterr()
    assert "access denied" in captured.err.lower()
    assert "403" in captured.err
    assert "super-secret-token" not in captured.out + captured.err


def test_verification_404_json_keeps_structured_error(monkeypatch, capsys):
    def fail(self, run_id, *args, **kwargs):
        raise DarkmageError(
            "404 Not Found for GET /runs/x/events: Run not found",
            status_code=404,
        )

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_events_parsed", fail)

    assert (
        main(
            [
                "--url",
                "https://api.example.test",
                "--json",
                "run",
                "verification",
                RUN_ID,
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 404
    assert "not found" in payload["error"]["message"].lower()
    assert "super-secret-token" not in captured.out + captured.err


# ---------------------------------------------------------------------------
# Parser, help and completion
# ---------------------------------------------------------------------------


def test_parser_registration_and_json_flag():
    args = build_parser().parse_args(["run", "verification", RUN_ID, "--json"])
    assert args.run_command == "verification"
    assert args.run_id == RUN_ID
    assert args.json is True

    args = build_parser().parse_args(["--json", "run", "verification", RUN_ID])
    assert args.json is True


def test_help_mentions_statuses_terminal_event_and_json():
    parser = build_parser()
    run_parser = parser._subparsers._group_actions[0].choices["run"]
    subparsers = run_parser._subparsers._group_actions[0].choices
    help_text = subparsers["verification"].format_help()

    assert "run_id" in help_text
    assert "--json" in help_text
    assert "run.completed/run.failed" in help_text
    assert "Проверено" in help_text
    assert "запускалась" in help_text


def test_completion_scripts_include_verification():
    assert "events verification" in _bash_completion_script()
    assert "events verification" in _zsh_completion_script()
    assert "events verification" in _fish_completion_script()
