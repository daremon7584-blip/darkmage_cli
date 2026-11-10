"""Approval listing/show CLI and client contracts."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import darkmage_cli.cli as cli
from darkmage_cli.cli import (
    _bash_completion_script,
    _fish_completion_script,
    _zsh_completion_script,
    build_parser,
    cmd_approval_list,
    cmd_approval_show,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError

APPROVAL_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
SESSION_ID = "33333333-3333-4333-8333-333333333333"

APPROVAL = {
    "id": APPROVAL_ID,
    "approval_id": APPROVAL_ID,
    "run_id": RUN_ID,
    "session_id": SESSION_ID,
    "name": "write_file",
    "status": "pending",
    "run_status": "waiting_approval",
    "requested_at": "2026-02-02T10:00:00+00:00",
    "resolved_at": None,
    "target": "src/app.py",
    "summary": "path=src/app.py content=<1200 chars> token=<redacted>",
}


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


class FakeApprovalClient:
    def __init__(self, approvals=None, approval=None, error=None):
        self.approvals = approvals if approvals is not None else []
        self.approval = approval if approval is not None else APPROVAL
        self.error = error
        self.list_calls: list[int] = []
        self.get_calls: list[str] = []
        self.token = "super-secret-token"

    def approval_list(self, limit=50):
        self.list_calls.append(limit)
        if self.error:
            raise self.error
        return self.approvals

    def approval_get(self, approval_id):
        self.get_calls.append(approval_id)
        if self.error:
            raise self.error
        return self.approval


# ---------------------------------------------------------------------------
# Client API calls
# ---------------------------------------------------------------------------


def _response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = "OK"
    resp.json.return_value = data if data is not None else {}
    resp.text = json.dumps(data if data is not None else {})
    resp.request = MagicMock()
    resp.request.method = "GET"
    resp.request.url.path = "/approvals"
    return resp


@patch("darkmage_cli.client.DarkmageClient._request")
def test_approval_list_calls_approvals_endpoint(mock_request):
    mock_request.return_value = _response(200, [APPROVAL])
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.approval_list(limit=25)

    assert result == [APPROVAL]
    args, kwargs = mock_request.call_args
    assert args == ("GET", "/approvals")
    assert kwargs["params"] == {"limit": 25}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_approval_get_calls_safe_approval_id(mock_request):
    mock_request.return_value = _response(200, APPROVAL)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.approval_get(APPROVAL_ID)

    assert result["id"] == APPROVAL_ID
    args, _kwargs = mock_request.call_args
    assert args == ("GET", f"/approvals/{APPROVAL_ID}")


# ---------------------------------------------------------------------------
# Parser and completion
# ---------------------------------------------------------------------------


def test_approvals_list_show_parser_registration():
    parser = build_parser()
    listed = parser.parse_args(["approvals", "list", "--limit", "5", "--json"])
    assert listed.approvals_command == "list"
    assert listed.limit == 5
    assert listed.json is True

    shown = parser.parse_args(["approvals", "show", APPROVAL_ID, "--json"])
    assert shown.approvals_command == "show"
    assert shown.approval_id == APPROVAL_ID
    assert shown.json is True


def test_completion_scripts_include_approval_list_and_show():
    bash = _bash_completion_script()
    zsh = _zsh_completion_script()
    fish = _fish_completion_script()
    assert "list show approve reject" in bash
    assert "1:subcommand:(list show approve reject)" in zsh
    assert "list show approve reject" in fish


# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------


def test_approval_list_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakeApprovalClient([APPROVAL])

    assert cmd_approval_list(SimpleNamespace(json=False, limit=50), client) == 0

    out = stream.getvalue()
    lines = out.splitlines()
    assert lines
    assert all(len(line) <= 80 for line in lines)
    assert APPROVAL_ID in out
    assert "TOOL: write_file" in out
    assert f"RUN: {RUN_ID}" in out
    assert "REQUESTED: 2026-02-02 10:00" in out
    assert "SUMMARY: path=src/app.py content=<1200 chars> token=<redacted>" in out
    assert "super-secret-token" not in out
    assert client.list_calls == [50]


def test_approval_list_empty_state(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_approval_list(SimpleNamespace(json=False, limit=50), FakeApprovalClient([])) == 0

    out = stream.getvalue()
    assert "No pending approvals." in out
    assert len(out.splitlines()) == 1


def test_approval_show_prints_details_and_command_hints(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakeApprovalClient()

    assert cmd_approval_show(
        SimpleNamespace(json=False, approval_id=APPROVAL_ID), client
    ) == 0

    out = stream.getvalue()
    lines = out.splitlines()
    assert all(len(line) <= 80 for line in lines)
    assert f"Approval: {APPROVAL_ID}" in out
    assert "Tool:       write_file" in out
    assert "Status:     pending" in out
    assert "Run status: waiting_approval" in out
    assert f"Run:        {RUN_ID}" in out
    assert f"Session:    {SESSION_ID}" in out
    assert "Requested:  2026-02-02T10:00:00+00:00" in out
    assert "Summary:    path=src/app.py content=<1200 chars> token=<redacted>" in out
    assert f"darkmage approvals approve {APPROVAL_ID}" in out
    assert f"darkmage approvals reject {APPROVAL_ID}" in out
    assert f"darkmage approvals approve {APPROVAL_ID} --scope turn" in out
    assert "super-secret-token" not in out
    assert client.get_calls == [APPROVAL_ID]


# ---------------------------------------------------------------------------
# JSON output, errors and token redaction
# ---------------------------------------------------------------------------


def test_approval_list_json(capsys):
    client = FakeApprovalClient([APPROVAL])

    assert cmd_approval_list(SimpleNamespace(json=True, limit=50), client) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == [APPROVAL]


def test_approval_show_json(capsys):
    client = FakeApprovalClient()

    assert cmd_approval_show(
        SimpleNamespace(json=True, approval_id=APPROVAL_ID), client
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == APPROVAL


def test_approval_show_404_is_an_error_without_token_leak(monkeypatch, capsys):
    def fail(self, approval_id):
        raise DarkmageError(
            "404 Not Found for GET /approvals/missing: Approval not found",
            status_code=404,
        )

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "approval_get", fail)

    assert main(["--json", "approvals", "show", "missing"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 404
    assert "Approval not found" in payload["error"]["message"]
    assert "super-secret-token" not in captured.out + captured.err


def test_approval_list_does_not_print_the_client_token(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(
        DarkmageClient, "approval_list", lambda self, limit=50: [APPROVAL]
    )

    assert main(["--json", "approvals", "list"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == [APPROVAL]
    assert "super-secret-token" not in captured.out + captured.err
