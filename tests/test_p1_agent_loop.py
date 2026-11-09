"""Tests for the P1 agent-client loop: approvals, questions, diffs.

These tests use fakes so they never touch a real backend or the real
``~/.darkmage-cli`` (see tests/conftest.py).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from darkmage_cli.cli import (
    _format_event,
    build_parser,
    cmd_doctor,
    cmd_exec,
    cmd_files_rm,
    cmd_run_create,
    cmd_ws_delete,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError
from darkmage_cli.events import format_diff, question_items, question_text


# ---------------------------------------------------------------------------
# Client approval endpoints (P1-1)
# ---------------------------------------------------------------------------


def _response(status_code: int = 200, data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = "OK"
    resp.json.return_value = data or {}
    resp.text = json.dumps(data or {})
    resp.request = MagicMock()
    resp.request.method = "POST"
    resp.request.url.path = "/tool-calls/x/approve"
    return resp


@patch("darkmage_cli.client.DarkmageClient._request")
def test_tool_call_approve_sends_scope(mock_request):
    mock_request.return_value = _response(200, {"id": "tc-1", "status": "approved"})
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.tool_call_approve("tc-1", scope="turn")

    assert result["status"] == "approved"
    args, kwargs = mock_request.call_args
    assert args == ("POST", "/tool-calls/tc-1/approve")
    assert kwargs["json"] == {"scope": "turn"}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_tool_call_reject(mock_request):
    mock_request.return_value = _response(200, {"id": "tc-1", "status": "rejected"})
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.tool_call_reject("tc-1")

    assert result["status"] == "rejected"
    args, _kwargs = mock_request.call_args
    assert args == ("POST", "/tool-calls/tc-1/reject")


def test_tool_call_approve_rejects_unknown_scope():
    client = DarkmageClient(base_url="http://localhost:8000", token="t")
    with pytest.raises(DarkmageError, match="scope"):
        client.tool_call_approve("tc-1", scope="always")


# ---------------------------------------------------------------------------
# Event rendering (P1-2, P1-3)
# ---------------------------------------------------------------------------


def test_format_event_approval_keeps_approval_id():
    event = {
        "id": "7",
        "event": "approval.required",
        "data": {
            "approval_id": "tc-123",
            "tool_call_id": "call-1",
            "name": "write_file",
            "arguments": {"path": "src/app.py"},
            "turn_remaining": 2,
        },
    }
    line = _format_event(event)
    assert "approval_id=tc-123" in line
    assert "src/app.py" in line
    assert "turn_remaining=2" in line


def test_question_payload_uses_questions_list():
    data = {
        "question_id": "q-1",
        "questions": [
            {
                "question": "Which database?",
                "options": [
                    {"label": "Postgres", "description": "production"},
                    {"label": "SQLite", "description": "local"},
                ],
            }
        ],
    }
    items = question_items(data)
    assert items[0]["question"] == "Which database?"
    assert [option["label"] for option in items[0]["options"]] == [
        "Postgres",
        "SQLite",
    ]
    text = question_text(data)
    assert "Which database?" in text
    assert "Postgres" in text and "SQLite" in text

    line = _format_event(
        {"id": "9", "event": "agent.question", "data": data}
    )
    assert "Which database?" in line
    assert "question_id=q-1" in line


def test_format_event_diff_ready_renders_unified_diff():
    event = {
        "id": "11",
        "event": "diff.ready",
        "data": {
            "path": "src/app.py",
            "before_content": "line one\nold line\n",
            "before_exists": True,
            "after_content": "line one\nnew line\n",
        },
    }
    rendered = _format_event(event)
    assert "--- a/src/app.py" in rendered
    assert "+++ b/src/app.py" in rendered
    assert "-old line" in rendered
    assert "+new line" in rendered


def test_format_diff_new_file():
    rendered = format_diff(
        {
            "path": "new.txt",
            "before_content": None,
            "before_exists": False,
            "after_content": "hello\n",
        }
    )
    assert "--- /dev/null" in rendered
    assert "+hello" in rendered


def test_format_diff_from_approval_arguments():
    rendered = format_diff(
        {
            "name": "write_file",
            "arguments": {"path": "app.py", "content": "new\n"},
            "before_content": "old\n",
            "before_exists": True,
        }
    )
    assert "--- a/app.py" in rendered
    assert "-old" in rendered
    assert "+new" in rendered


# ---------------------------------------------------------------------------
# Fake client for exec / run create
# ---------------------------------------------------------------------------


class FakeRunClient:
    def __init__(self, events: list[dict]):
        self.events = events
        self.session_id = "ses-1"
        self.run_id = "run-1"
        self.created: dict | None = None
        self.approvals: list[tuple[str, str]] = []
        self.rejections: list[str] = []
        self.answers: list[tuple[str, str, list[str]]] = []
        self.stopped: str | None = None

    def session_all(self, limit: int = 50):
        return [{"id": self.session_id}]

    def run_create(
        self, session_id, prompt, model=None, plan_only=False, thorough=False, image=None, **kwargs
    ):
        self.created = {"session_id": session_id, "prompt": prompt}
        return {"id": self.run_id, "session_id": session_id, "status": "queued"}

    def run_events_parsed(self, run_id, last_event_id=None):
        assert run_id == self.run_id
        yield from self.events

    def run_get(self, run_id):
        return {
            "id": run_id,
            "status": "completed",
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "last_event_sequence": 6,
        }

    def tool_call_approve(self, approval_id, scope="call"):
        self.approvals.append((approval_id, scope))
        return {"id": approval_id, "name": "write_file", "status": "approved"}

    def tool_call_reject(self, approval_id):
        self.rejections.append(approval_id)
        return {"id": approval_id, "name": "write_file", "status": "rejected"}

    def run_answer(self, run_id, question_id, answers):
        self.answers.append((run_id, question_id, answers))
        return {"question_id": question_id, "answers": answers}

    def run_stop(self, run_id):
        self.stopped = run_id
        return {"id": run_id, "status": "cancelled"}


def _args(**overrides):
    values = {
        "prompt": ["do", "the", "thing"],
        "session_id": None,
        "output_format": "text",
        "output_last_message": None,
        "model": None,
        "plan_only": False,
        "json": False,
        "follow": False,
        "no_follow": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _approval_event() -> dict:
    return {
        "id": "2",
        "event": "approval.required",
        "data": {
            "approval_id": "tc-9",
            "tool_call_id": "call-1",
            "name": "write_file",
            "arguments": {"path": "app.py", "content": "print('new')\n"},
            "before_content": "print('old')\n",
            "before_exists": True,
            "turn_remaining": 2,
        },
    }


def _completed(answer: str) -> list[dict]:
    return [
        {"id": "1", "event": "assistant.delta", "data": {"text": "working"}},
        _approval_event(),
        {
            "id": "3",
            "event": "approval.resolved",
            "data": {"approval_id": "tc-9", "decision": "approved"},
        },
        {"id": "4", "event": "assistant.delta", "data": {"text": answer}},
        {"id": "5", "event": "run.completed", "data": {"finish_reason": "stop"}},
    ]


def test_exec_interactive_approve_continues(monkeypatch, capsys):
    client = FakeRunClient(_completed("done"))
    monkeypatch.setattr("darkmage_cli.cli._is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "A")

    assert cmd_exec(_args(), client) == 0

    assert client.approvals == [("tc-9", "turn")]
    captured = capsys.readouterr()
    assert captured.out == "done\n"
    assert "Approved write_file" in captured.err


def test_exec_interactive_reject_continues(monkeypatch, capsys):
    client = FakeRunClient(
        [
            _approval_event(),
            {
                "id": "3",
                "event": "approval.resolved",
                "data": {"approval_id": "tc-9", "decision": "rejected"},
            },
            {"id": "4", "event": "run.completed", "data": {"finish_reason": "approval_rejected"}},
        ]
    )
    monkeypatch.setattr("darkmage_cli.cli._is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "r")

    assert cmd_exec(_args(), client) == 0

    assert client.rejections == ["tc-9"]
    assert client.approvals == []
    assert "Rejected write_file" in capsys.readouterr().err


def test_exec_non_interactive_returns_exit_4_with_approval_id(monkeypatch, capsys):
    client = FakeRunClient([_approval_event()])
    monkeypatch.setattr("darkmage_cli.cli._is_interactive", lambda: False)

    assert cmd_exec(_args(output_format="json"), client) == 4

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "approval_required"
    assert payload["approval"]["approval_id"] == "tc-9"
    assert "darkmage approvals approve tc-9" in captured.err
    assert client.approvals == []


def test_exec_interactive_answers_questions(monkeypatch, capsys):
    question_event = {
        "id": "2",
        "event": "agent.question",
        "data": {
            "question_id": "q-1",
            "questions": [
                {
                    "question": "Which database?",
                    "options": [
                        {"label": "Postgres", "description": ""},
                        {"label": "SQLite", "description": ""},
                    ],
                },
                {"question": "Anything else?", "options": []},
            ],
        },
    }
    client = FakeRunClient(
        [
            question_event,
            {
                "id": "3",
                "event": "agent.answer",
                "data": {"question_id": "q-1", "answers": ["SQLite", "no"], "by": "owner"},
            },
            {"id": "4", "event": "assistant.delta", "data": {"text": "ok"}},
            {"id": "5", "event": "run.completed", "data": {"finish_reason": "stop"}},
        ]
    )
    answers = iter(["2", "no"])
    monkeypatch.setattr("darkmage_cli.cli._is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cmd_exec(_args(), client) == 0

    assert client.answers == [("run-1", "q-1", ["SQLite", "no"])]
    assert capsys.readouterr().out == "ok\n"


def test_exec_non_interactive_question_exit_4(monkeypatch, capsys):
    event = {
        "id": "1",
        "event": "agent.question",
        "data": {
            "question_id": "q-1",
            "questions": [{"question": "Pick one", "options": [{"label": "A"}]}],
        },
    }
    client = FakeRunClient([event])
    monkeypatch.setattr("darkmage_cli.cli._is_interactive", lambda: False)

    assert cmd_exec(_args(output_format="json"), client) == 4

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "question"
    assert payload["question"]["question_id"] == "q-1"
    assert client.answers == []


def test_run_create_follow_stops_at_pending_approval(monkeypatch, capsys):
    client = FakeRunClient([_approval_event()])
    monkeypatch.setattr("darkmage_cli.cli._is_interactive", lambda: False)

    args = SimpleNamespace(
        session_id="ses-1",
        prompt="fix it",
        model=None,
        plan_only=False,
        thorough=False,
        image=[],
        follow=True,
        no_follow=False,
        json=False,
    )
    assert cmd_run_create(args, client) == 4

    captured = capsys.readouterr()
    assert "approval_id=tc-9" in captured.err
    assert client.created == {"session_id": "ses-1", "prompt": "fix it"}


# ---------------------------------------------------------------------------
# SSE reconnect / Last-Event-ID dedupe (P1-16)
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    def __init__(self, lines, error=None, status_code=200):
        self._lines = lines
        self._error = error
        self.status_code = status_code
        self.reason_phrase = "OK"
        self.text = ""
        self.request = MagicMock()
        self.request.method = "GET"
        self.request.url.path = "/runs/run-1/events"
        self.url = self.request.url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def json(self):
        return {}

    def iter_lines(self):
        yield from self._lines
        if self._error is not None:
            raise self._error


def _sse(*events: tuple[str, str, dict]) -> list[str]:
    lines: list[str] = []
    for event_id, event_type, data in events:
        lines.extend(
            [
                f"id: {event_id}",
                f"event: {event_type}",
                f"data: {json.dumps(data)}",
                "",
            ]
        )
    return lines


def test_sse_reconnects_with_last_event_id_and_dedupes(monkeypatch):
    first = _FakeStreamResponse(
        _sse(("1", "assistant.delta", {"text": "A"})),
        error=httpx.ReadError("connection dropped"),
    )
    second = _FakeStreamResponse(
        _sse(
            ("1", "assistant.delta", {"text": "A"}),
            ("2", "assistant.delta", {"text": "B"}),
            ("3", "run.completed", {"finish_reason": "stop"}),
        )
    )
    responses = iter([first, second])
    calls: list[dict] = []

    def fake_stream(method, url, headers=None):
        calls.append({"method": method, "url": url, "headers": dict(headers or {})})
        return next(responses)

    sleeps: list[float] = []
    monkeypatch.setattr("darkmage_cli.client.time.sleep", sleeps.append)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")
    client._client.stream = fake_stream

    events = list(client.run_events_parsed("run-1", max_retries=2))

    assert [event["id"] for event in events] == ["1", "2", "3"]
    assert len(calls) == 2
    assert "Last-Event-ID" not in calls[0]["headers"]
    assert calls[1]["headers"]["Last-Event-ID"] == "1"
    assert sleeps == [0.5]


def test_sse_stops_when_run_finished_without_terminal_event(monkeypatch):
    response = _FakeStreamResponse(
        _sse(("1", "assistant.delta", {"text": "A"}))
    )
    calls: list[dict] = []

    def fake_stream(method, url, headers=None):
        calls.append({"headers": dict(headers or {})})
        return response

    client = DarkmageClient(base_url="http://localhost:8000", token="t")
    client._client.stream = fake_stream
    client.run_get = lambda run_id: {"id": run_id, "status": "completed"}

    events = list(client.run_events_parsed("run-1", max_retries=3))

    assert [event["id"] for event in events] == ["1"]
    assert len(calls) == 1


def test_sse_reconnect_is_bounded(monkeypatch):
    def fake_stream(method, url, headers=None):
        return _FakeStreamResponse([])

    monkeypatch.setattr("darkmage_cli.client.time.sleep", lambda _delay: None)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")
    client._client.stream = fake_stream
    client.run_get = lambda run_id: {"id": run_id, "status": "running"}

    with pytest.raises(DarkmageError, match="closed after 2 reconnect attempts"):
        list(
            client.run_events_parsed(
                "run-1", max_retries=2, initial_backoff=0
            )
        )


def test_sse_does_not_retry_client_errors():
    def fake_stream(method, url, headers=None):
        return _FakeStreamResponse([], status_code=404)

    client = DarkmageClient(base_url="http://localhost:8000", token="t")
    client._client.stream = fake_stream

    with pytest.raises(DarkmageError) as excinfo:
        list(client.run_events_parsed("run-1", max_retries=2))
    assert excinfo.value.status_code == 404
    assert excinfo.value.retryable is False


# ---------------------------------------------------------------------------
# Destructive confirmations (P1-17)
# ---------------------------------------------------------------------------


class RecordingClient:
    def __init__(self):
        self.deleted_workspaces: list[str] = []
        self.deleted_files: list[tuple[str, str]] = []

    def workspace_delete(self, workspace_id):
        self.deleted_workspaces.append(workspace_id)

    def workspace_file_delete(self, workspace_id, path):
        self.deleted_files.append((workspace_id, path))
        return {"status": "deleted"}


def test_workspace_delete_requires_confirmation(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    client = RecordingClient()

    assert cmd_ws_delete(SimpleNamespace(workspace_id="ws-1", yes=False), client) == 1

    assert client.deleted_workspaces == []
    assert "--yes" in capsys.readouterr().err


def test_workspace_delete_with_yes(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    client = RecordingClient()

    assert cmd_ws_delete(SimpleNamespace(workspace_id="ws-1", yes=True), client) == 0
    assert client.deleted_workspaces == ["ws-1"]


def test_files_rm_local_requires_confirmation(monkeypatch, tmp_path):
    target = tmp_path / "keep.txt"
    target.write_text("data", encoding="utf-8")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    client = RecordingClient()

    assert (
        cmd_files_rm(
            SimpleNamespace(workspace_id="ws-1", path=str(target), yes=False), client
        )
        == 1
    )
    assert target.exists()

    assert (
        cmd_files_rm(
            SimpleNamespace(workspace_id="ws-1", path=str(target), yes=True), client
        )
        == 0
    )
    assert not target.exists()


def test_files_rm_remote_requires_confirmation(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    client = RecordingClient()

    assert (
        cmd_files_rm(
            SimpleNamespace(workspace_id="ws-1", path="ws:/app.py", yes=False), client
        )
        == 1
    )
    assert client.deleted_files == []


def test_destructive_flags_are_registered():
    parser = build_parser()
    ws = parser.parse_args(["workspace", "delete", "ws-1", "--yes"])
    assert ws.yes is True
    files = parser.parse_args(["files", "rm", "ws-1", "ws:/a.py", "-y"])
    assert files.yes is True


def test_approvals_commands_are_registered():
    parser = build_parser()
    approve = parser.parse_args(
        ["approvals", "approve", "tc-1", "--scope", "turn"]
    )
    assert approve.tool_call_id == "tc-1"
    assert approve.scope == "turn"
    reject = parser.parse_args(["approvals", "reject", "tc-1"])
    assert reject.tool_call_id == "tc-1"


# ---------------------------------------------------------------------------
# doctor exit code (P1-9)
# ---------------------------------------------------------------------------


class DoctorClient:
    def __init__(self, healthy: bool):
        self.healthy = healthy

    def health(self):
        if not self.healthy:
            raise DarkmageError("connection refused", retryable=True)
        return {"status": "alive"}

    def ready(self):
        if not self.healthy:
            raise DarkmageError("connection refused", retryable=True)
        return {"status": "ready"}


def test_doctor_returns_nonzero_on_failure(monkeypatch, capsys):
    monkeypatch.delenv("DARKMAGE_TOKEN", raising=False)
    assert cmd_doctor(SimpleNamespace(url="http://localhost:1", json=False), DoctorClient(False)) == 1
    out = capsys.readouterr().out
    assert "Есть проблемы" in out
    assert "Готово к работе" not in out


def test_doctor_returns_zero_when_healthy(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "token-value")
    assert cmd_doctor(SimpleNamespace(url="http://localhost:1", json=False), DoctorClient(True)) == 0
    assert "Готово к работе" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# JSON errors (P1-8)
# ---------------------------------------------------------------------------


def test_main_json_error_envelope(monkeypatch, capsys):
    def fail(self):
        raise DarkmageError("bad token", status_code=401)

    monkeypatch.setattr(DarkmageClient, "health", fail)
    assert main(["--json", "health"]) == 3

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["message"] == "bad token"
    assert payload["error"]["status_code"] == 401
    assert payload["error"]["retryable"] is False


def test_main_json_error_runtime_exit_code(monkeypatch, capsys):
    def fail(self):
        raise DarkmageError("connection refused", retryable=True)

    monkeypatch.setattr(DarkmageClient, "health", fail)
    assert main(["--json", "health"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["retryable"] is True


# ---------------------------------------------------------------------------
# Test isolation (P1-14)
# ---------------------------------------------------------------------------


def test_config_io_uses_security_module_paths(isolate_cli_config):
    from darkmage_cli.config import load_config, save_config

    save_config({"base_url": "http://isolated:8000", "token": "secret"})

    assert (isolate_cli_config / "config.json").exists()
    assert load_config()["base_url"] == "http://isolated:8000"


# ---------------------------------------------------------------------------
# TUI controllers (P1-1/P1-2/P1-6)
# ---------------------------------------------------------------------------


class _Log:
    def __init__(self):
        self.lines: list[str] = []

    def write(self, value):
        self.lines.append(str(value))


def _tui_with_pending():
    from darkmage_cli.tui import DarkmageTUI

    app = object.__new__(DarkmageTUI)
    app.client = FakeRunClient([])
    app.run_id = "run-1"
    app.pending_approval = _approval_event()["data"]
    app.pending_question = None
    app._events_log = []
    log = _Log()
    app.query_one = lambda _selector, *args: log
    return app, log


def test_tui_approve_turn_calls_backend():
    app, log = _tui_with_pending()

    asyncio.run(app._cmd_approve(["turn"]))

    assert app.client.approvals == [("tc-9", "turn")]
    assert app.pending_approval is None
    assert any("Одобрено" in line for line in log.lines)


def test_tui_reject_calls_backend():
    app, _log = _tui_with_pending()

    asyncio.run(app._cmd_reject([]))

    assert app.client.rejections == ["tc-9"]
    assert app.pending_approval is None


def test_tui_run_stop_calls_backend():
    app, _log = _tui_with_pending()

    asyncio.run(app._cmd_run(["stop"]))

    assert app.client.stopped == "run-1"


def test_tui_answer_splits_multiple_answers():
    from darkmage_cli.tui import DarkmageTUI

    app = object.__new__(DarkmageTUI)
    app.client = FakeRunClient([])
    app.run_id = "run-1"
    app.pending_approval = None
    app.pending_question = {
        "question_id": "q-1",
        "questions": [
            {"question": "One?", "options": [{"label": "A"}]},
            {"question": "Two?", "options": [{"label": "B"}]},
        ],
    }
    app._events_log = []
    app.query_one = lambda _selector, *args: _Log()

    asyncio.run(app._cmd_answer(["yes", "|", "no"]))

    assert app.client.answers == [("run-1", "q-1", ["yes", "no"])]
    assert app.pending_question is None
