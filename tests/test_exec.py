"""Tests for the minimal one-shot `exec` / `-p` flow."""

from __future__ import annotations

import json
from types import SimpleNamespace

from darkmage_cli.cli import _normalize_exec_alias, build_parser, cmd_exec


class _FakeClient:
    def __init__(self, events: list[dict]):
        self.events = events
        self.created: dict | None = None
        self.run_id = "run-1"
        self.session_id = "ses-1"

    def session_all(self, limit: int = 50):
        return [{"id": self.session_id}]

    def run_create(self, session_id, prompt, model=None, plan_only=False, **kwargs):
        self.created = {
            "session_id": session_id,
            "prompt": prompt,
            "model": model,
            "plan_only": plan_only,
        }
        return {"id": self.run_id, "status": "queued"}

    def run_events_parsed(self, run_id, last_event_id=None):
        assert run_id == self.run_id
        yield from self.events

    def run_get(self, run_id):
        return {
            "id": run_id,
            "status": "completed",
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "last_event_sequence": 9,
        }


def _args(**overrides):
    values = {
        "prompt": ["do", "the", "thing"],
        "session_id": None,
        "output_format": "text",
        "output_last_message": None,
        "model": None,
        "plan_only": False,
        "json": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _events() -> list[dict]:
    return [
        {"id": "1", "event": "assistant.delta", "data": {"text": "I will check."}},
        {"id": "2", "event": "tool.requested", "data": {"name": "read_file"}},
        {"id": "3", "event": "assistant.delta", "data": {"text": "Final "}},
        {"id": "4", "event": "assistant.delta", "data": {"text": "answer."}},
        {"id": "5", "event": "run.completed", "data": {"finish_reason": "stop"}},
    ]


def test_exec_prints_final_answer_and_progress_separately(capsys):
    client = _FakeClient(_events())

    assert cmd_exec(_args(), client) == 0

    captured = capsys.readouterr()
    assert captured.out == "Final answer.\n"
    assert "tool.requested" in captured.err
    assert "I will check." not in captured.out


def test_exec_json_envelope(capsys):
    client = _FakeClient(_events())

    assert cmd_exec(_args(output_format="json"), client) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["run_id"] == "run-1"
    assert payload["session_id"] == "ses-1"
    assert payload["status"] == "completed"
    assert payload["result"] == "Final answer."
    assert payload["usage"]["prompt_tokens"] == 12


def test_exec_writes_private_output_file(tmp_path, capsys):
    client = _FakeClient(_events())
    target = tmp_path / "answer.txt"

    assert cmd_exec(_args(output_last_message=str(target)), client) == 0

    assert target.read_text(encoding="utf-8") == "Final answer.\n"
    assert (target.stat().st_mode & 0o777) == 0o600


def test_exec_stops_on_approval_required(capsys):
    client = _FakeClient(
        [
            {"id": "1", "event": "assistant.delta", "data": {"text": "creating"}},
            {
                "id": "2",
                "event": "approval.required",
                "data": {"name": "write_file", "approval_id": "a1"},
            },
        ]
    )

    assert cmd_exec(_args(), client) == 4
    captured = capsys.readouterr()
    assert "Approval required" in captured.err
    assert captured.out == ""


def test_print_alias_normalizes_to_exec():
    from darkmage_cli.cli import _normalize_exec_alias

    assert _normalize_exec_alias(["-p", "hello"]) == ["exec", "hello"]
    assert _normalize_exec_alias(["--print", "hello"]) == ["exec", "hello"]
    assert _normalize_exec_alias(["--print=hello", "--output-format", "json"]) == [
        "exec",
        "hello",
        "--output-format",
        "json",
    ]

    parser = build_parser()
    args = parser.parse_args(
        _normalize_exec_alias(["-p", "hello", "--output-format", "json"])
    )
    assert args.command == "exec"
    assert args.prompt == ["hello"]
    assert args.output_format == "json"
