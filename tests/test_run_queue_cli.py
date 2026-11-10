"""`run queue` and queue visibility in `run get`/`run list`."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

import darkmage_cli.cli as cli
from darkmage_cli.cli import (
    _bash_completion_script,
    _fish_completion_script,
    _humanize_seconds,
    _zsh_completion_script,
    build_parser,
    cmd_run_get,
    cmd_run_list,
    cmd_run_queue,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError

RUN_ID = "22222222-2222-4222-8222-222222222222"
WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"

QUEUE = {
    "position": 1,
    "ahead": 0,
    "estimated_wait_seconds": 120,
    "expires_at": "2026-11-10T12:05:00+00:00",
    "trial": True,
}


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


class FakeQueueClient:
    def __init__(self, data=None, error=None):
        self.data = data if data is not None else {}
        self.error = error
        self.calls: list[str] = []
        self.token = "super-secret-token"

    def run_queue(self, run_id):
        self.calls.append(run_id)
        if self.error:
            raise self.error
        return self.data


class FakeRunClient:
    def __init__(self, data=None, runs=None, error=None):
        self.data = data if data is not None else {}
        self.runs = runs or []
        self.error = error
        self.token = "super-secret-token"

    def run_get(self, run_id):
        if self.error:
            raise self.error
        return self.data

    def run_list(self, workspace_id):
        if self.error:
            raise self.error
        return self.runs


def _args(**overrides):
    values = {"run_id": RUN_ID, "json": False}
    values.update(overrides)
    return SimpleNamespace(**values)


def _quiet(text):
    return cli._ANSI_ESCAPE_RE.sub("", text)


def _run(status="queued", queue=None, **overrides):
    data = {
        "id": RUN_ID,
        "session_id": "33333333-3333-4333-8333-333333333333",
        "status": status,
        "prompt": "do work",
        "model": "gpt-5",
        "checkpoint_status": "none",
        "created_at": "2026-11-10T11:55:00+00:00",
        "queue": queue,
        "queue_position": None,
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# run queue text and JSON
# ---------------------------------------------------------------------------


def test_queue_text_shows_position_eta_expiry_and_trial(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakeQueueClient(_run(queue=QUEUE))

    assert cmd_run_queue(_args(), client) == 0

    out = _quiet(stream.getvalue())
    assert f"Run:        {RUN_ID}" in out
    assert "Status:" in out and "queued" in out
    assert "Position:   1" in out
    assert "Ahead:      0" in out
    assert "ETA:        ~2 min" in out
    assert "Expires:    2026-11-10 12:05 UTC" in out
    assert "Queue type: trial" in out
    assert client.calls == [RUN_ID]


def test_queue_text_paid_queue_wording(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    paid = dict(QUEUE, trial=False, estimated_wait_seconds=30)

    assert cmd_run_queue(_args(), FakeQueueClient(_run(queue=paid))) == 0

    out = _quiet(stream.getvalue())
    assert "Queue type: paid" in out
    assert "ETA:        ~30s" in out
    assert "trial" not in out.lower()


def test_queue_json_is_raw_api_object(capsys):
    data = _run(queue=QUEUE)

    assert cmd_run_queue(_args(json=True), FakeQueueClient(data)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == data
    assert payload["queue"] == QUEUE


def test_queue_json_without_metadata_keeps_raw_object(capsys):
    data = _run(status="queued", queue=None)

    assert cmd_run_queue(_args(json=True), FakeQueueClient(data)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == data
    assert payload["queue"] is None


def test_queue_not_queued_is_friendly(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert (
        cmd_run_queue(
            _args(),
            FakeQueueClient(
                _run(status="completed", queue=None, finished_at="2026-11-10T12:00:00+00:00")
            ),
        )
        == 0
    )

    out = _quiet(stream.getvalue())
    assert "Not queued" in out
    assert "completed" in out
    assert "Position:" not in out
    assert "ETA:" not in out


def test_queue_expired_or_missing_metadata_is_unavailable(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_run_queue(_args(), FakeQueueClient(_run(status="queued", queue=None))) == 0

    out = _quiet(stream.getvalue())
    assert "queue information is not available" in out
    assert "Position:" not in out


def test_queue_null_eta_is_unknown(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    queue = dict(QUEUE, estimated_wait_seconds=None, expires_at=None)

    assert cmd_run_queue(_args(), FakeQueueClient(_run(queue=queue))) == 0

    out = _quiet(stream.getvalue())
    assert "ETA:        unknown" in out
    assert "Expires:    -" in out


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "unknown"),
        (0, "0s"),
        (45, "45s"),
        (60, "1 min"),
        (120, "2 min"),
        (3660, "1 h 1 min"),
        (90000, "1 d 1 h"),
    ],
)
def test_humanize_seconds(seconds, expected):
    assert _humanize_seconds(seconds) == expected


# ---------------------------------------------------------------------------
# run get integration
# ---------------------------------------------------------------------------


def test_run_get_adds_queue_line_when_present(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_run_get(_args(), FakeRunClient(_run(queue=QUEUE))) is None

    out = _quiet(stream.getvalue())
    assert "Queue:" in out
    assert "position 1" in out
    assert "ahead 0" in out
    assert "ETA ~2 min" in out
    assert "trial" in out
    assert "queue" in out
    # Existing fields stay intact.
    assert f"ID:         {RUN_ID}" in out
    assert "Статус:" in out
    assert "Создан:" in out


def test_run_get_queued_without_metadata_reports_unavailable(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_run_get(_args(), FakeRunClient(_run(status="queued", queue=None))) is None

    assert "queue information is not available" in _quiet(stream.getvalue())


def test_run_get_json_is_unchanged(capsys):
    data = _run(queue=QUEUE)

    assert cmd_run_get(_args(json=True), FakeRunClient(data)) is None

    assert json.loads(capsys.readouterr().out) == data


# ---------------------------------------------------------------------------
# run list integration
# ---------------------------------------------------------------------------


def test_run_list_queue_column_only_when_queued(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    runs = [
        _run(status="queued", queue=QUEUE),
        _run(
            status="completed",
            queue=None,
            id="44444444-4444-4444-8444-444444444444",
        ),
    ]

    cmd_run_list(_args(workspace_id=WORKSPACE_ID), FakeRunClient(runs=runs))

    out = _quiet(stream.getvalue())
    assert "Очередь" in out
    assert "#1" in out
    assert all(len(line) <= 80 for line in out.splitlines())


def test_run_list_legacy_queue_position_column(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    runs = [_run(status="queued", queue=None, queue_position=2)]

    cmd_run_list(_args(workspace_id=WORKSPACE_ID), FakeRunClient(runs=runs))

    out = _quiet(stream.getvalue())
    assert "Очередь" in out
    assert "#3" in out


def test_run_list_without_queue_keeps_old_table(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    runs = [_run(status="completed", queue=None)]

    cmd_run_list(_args(workspace_id=WORKSPACE_ID), FakeRunClient(runs=runs))

    out = _quiet(stream.getvalue())
    assert "Очередь" not in out
    assert "Модель" in out


def test_run_list_narrow_terminal_uses_record_layout(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 40)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    runs = [_run(status="queued", queue=QUEUE)]

    cmd_run_list(_args(workspace_id=WORKSPACE_ID), FakeRunClient(runs=runs))

    out = _quiet(stream.getvalue())
    assert "Очередь:" in out
    assert all(len(line) <= 40 for line in out.splitlines())


def test_run_list_json_is_unchanged(capsys):
    runs = [_run(status="queued", queue=QUEUE)]

    cmd_run_list(_args(workspace_id=WORKSPACE_ID, json=True), FakeRunClient(runs=runs))

    assert json.loads(capsys.readouterr().out) == runs


# ---------------------------------------------------------------------------
# Errors and token safety
# ---------------------------------------------------------------------------


def test_queue_404_is_clear_without_token_or_traceback(monkeypatch, capsys):
    def fail(self, run_id):
        raise DarkmageError(
            "404 Not Found for GET /runs/x: Run not found",
            status_code=404,
        )

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_queue", fail)

    assert (
        main(["--url", "https://api.example.test", "run", "queue", RUN_ID]) == 1
    )

    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()
    assert "404" in captured.err
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.err


def test_queue_403_is_clear_without_token(monkeypatch, capsys):
    def fail(self, run_id):
        raise DarkmageError(
            "403 Forbidden for GET /runs/x: Not enough permissions",
            status_code=403,
        )

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_queue", fail)

    assert (
        main(["--url", "https://api.example.test", "run", "queue", RUN_ID]) == 1
    )

    captured = capsys.readouterr()
    assert "access denied" in captured.err.lower()
    assert "403" in captured.err
    assert "super-secret-token" not in captured.out + captured.err


def test_queue_404_json_keeps_structured_error(monkeypatch, capsys):
    def fail(self, run_id):
        raise DarkmageError(
            "404 Not Found for GET /runs/x: Run not found",
            status_code=404,
        )

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_queue", fail)

    assert (
        main(
            [
                "--url",
                "https://api.example.test",
                "--json",
                "run",
                "queue",
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
# Parser, help, completion and client
# ---------------------------------------------------------------------------


def test_queue_parser_registration_and_json_flag():
    args = build_parser().parse_args(["run", "queue", RUN_ID, "--json"])
    assert args.run_command == "queue"
    assert args.run_id == RUN_ID
    assert args.json is True

    args = build_parser().parse_args(["--json", "run", "queue", RUN_ID])
    assert args.json is True


def test_queue_help_mentions_run_id_and_json():
    parser = build_parser()
    run_parser = parser._subparsers._group_actions[0].choices["run"]
    subparsers = run_parser._subparsers._group_actions[0].choices
    assert "queue" in subparsers
    help_text = subparsers["queue"].format_help()
    assert "run_id" in help_text
    assert "--json" in help_text
    assert "ETA" in help_text


def test_completion_scripts_include_queue():
    assert "create get queue message" in _bash_completion_script()
    assert "create get queue message" in _zsh_completion_script()
    assert "create get queue message" in _fish_completion_script()


def test_client_run_queue_uses_run_get(monkeypatch):
    client = DarkmageClient(base_url="https://api.example.test", token="t")
    calls: list[str] = []
    payload = _run(queue=QUEUE)

    monkeypatch.setattr(client, "run_get", lambda run_id: calls.append(run_id) or payload)

    assert client.run_queue(RUN_ID) == payload
    assert calls == [RUN_ID]
