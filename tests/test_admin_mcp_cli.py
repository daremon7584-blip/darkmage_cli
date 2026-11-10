"""Admin MCP gateway CLI and client contracts.

These tests pin the exact backend shapes from ``app/endpoints/mcp_gateway.py``
and ``app/schemas.py``, the local hash guard, JSON envelopes and the absence of
token leaks.
"""

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
    cmd_admin_mcp_approve,
    cmd_admin_mcp_call,
    cmd_admin_mcp_list,
    cmd_admin_mcp_show,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError

HASH_A = "a" * 64
HASH_B = "b" * 64
TOOL_NAME = "github.search"
LAST_SEEN = "2026-11-10T09:30:00+00:00"

APPROVED_TOOL = {
    "name": TOOL_NAME,
    "description": "Search GitHub repositories and issues.",
    "read_only": True,
    "destructive": False,
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
    "schema_hash": HASH_A,
    "approval_status": "approved",
    "approved_schema_hash": HASH_A,
    "last_seen": LAST_SEEN,
}

CHANGED_TOOL = {
    **APPROVED_TOOL,
    "name": "github.issue",
    "schema_hash": HASH_B,
    "approval_status": "changed",
    "approved_schema_hash": HASH_A,
}

NEW_TOOL = {
    **APPROVED_TOOL,
    "name": "github.repo",
    "schema_hash": HASH_B,
    "approval_status": "new",
    "approved_schema_hash": None,
    "last_seen": None,
}

TOOLS_PAYLOAD = {
    "server": "github-mcp",
    "tools": [APPROVED_TOOL, CHANGED_TOOL, NEW_TOOL],
    "truncated": False,
}


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


class FakeMCPClient:
    def __init__(
        self,
        payload=None,
        approved=None,
        called=None,
    ):
        self.payload = payload if payload is not None else TOOLS_PAYLOAD
        self.approved = approved if approved is not None else APPROVED_TOOL
        self.called = called if called is not None else {
            "ok": True,
            "server": "github-mcp",
            "tool": TOOL_NAME,
            "result": '{"items":[{"title":"bug"}]}',
            "error": None,
            "truncated": False,
        }
        self.list_calls = 0
        self.approve_calls: list[tuple[str, str]] = []
        self.call_calls: list[tuple[str, dict]] = []
        self.token = "super-secret-token"

    def admin_mcp_tools(self):
        self.list_calls += 1
        return self.payload

    def admin_mcp_approve(self, tool, schema_hash):
        self.approve_calls.append((tool, schema_hash))
        return self.approved

    def admin_mcp_call(self, tool, arguments):
        self.call_calls.append((tool, arguments))
        return self.called


def _response(status_code=200, data=None, path="/admin/mcp/tools"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = "OK"
    resp.json.return_value = data if data is not None else {}
    resp.text = json.dumps(data if data is not None else {})
    resp.request = MagicMock()
    resp.request.method = "GET"
    resp.request.url.path = path
    return resp


# ---------------------------------------------------------------------------
# Client API calls
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_mcp_tools_calls_list_endpoint(mock_request):
    mock_request.return_value = _response(200, TOOLS_PAYLOAD)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_mcp_tools()

    assert result == TOOLS_PAYLOAD
    assert mock_request.call_args.args == ("GET", "/admin/mcp/tools")


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_mcp_approve_encodes_tool_and_posts_hash(mock_request):
    mock_request.return_value = _response(200, APPROVED_TOOL)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_mcp_approve("github/search", HASH_A)

    assert result == APPROVED_TOOL
    args, kwargs = mock_request.call_args
    assert args == ("POST", "/admin/mcp/tools/github%2Fsearch/approve")
    assert kwargs["json"] == {"schema_hash": HASH_A}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_mcp_call_posts_tool_and_arguments(mock_request):
    response = {
        "ok": True,
        "server": "github-mcp",
        "tool": TOOL_NAME,
        "result": "[]",
        "error": None,
        "truncated": False,
    }
    mock_request.return_value = _response(200, response, path="/admin/mcp/call")
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_mcp_call(TOOL_NAME, {"query": "bug"})

    assert result == response
    args, kwargs = mock_request.call_args
    assert args == ("POST", "/admin/mcp/call")
    assert kwargs["json"] == {"tool": TOOL_NAME, "arguments": {"query": "bug"}}


# ---------------------------------------------------------------------------
# Parser and completions
# ---------------------------------------------------------------------------


def test_admin_mcp_parser_registration():
    parser = build_parser()

    listed = parser.parse_args(["admin", "mcp", "list", "--json"])
    assert listed.mcp_admin_command == "list"
    assert listed.json is True

    shown = parser.parse_args(["admin", "mcp", "show", TOOL_NAME])
    assert shown.mcp_admin_command == "show"
    assert shown.tool == TOOL_NAME

    approved = parser.parse_args(
        ["admin", "mcp", "approve", TOOL_NAME, "--hash", HASH_A, "--yes"]
    )
    assert approved.mcp_admin_command == "approve"
    assert approved.hash == HASH_A
    assert approved.yes is True

    called = parser.parse_args(
        ["admin", "mcp", "call", TOOL_NAME, "--args", '{"query":"bug"}']
    )
    assert called.mcp_admin_command == "call"
    assert called.arguments_json == '{"query":"bug"}'


def test_completion_scripts_include_admin_mcp():
    bash = _bash_completion_script()
    zsh = _zsh_completion_script()
    fish = _fish_completion_script()

    for script in (bash, zsh, fish):
        assert "status skills mcp" in script
        assert "list show approve call" in script
        assert "--hash" in script
        assert "--yes" in script
        assert "--args" in script


def test_help_lists_admin_mcp_commands(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["admin", "mcp", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "list" in out
    assert "show" in out
    assert "approve" in out
    assert "call" in out


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_admin_mcp_list_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakeMCPClient()

    assert cmd_admin_mcp_list(SimpleNamespace(json=False), client) == 0

    out = stream.getvalue()
    lines = out.splitlines()
    assert lines
    assert all(len(line) <= 80 for line in lines)
    assert "MCP tools on github-mcp:" in out
    assert TOOL_NAME in out
    assert HASH_A[:12] in out
    assert "approved" in out
    assert "changed" in out
    assert "new" in out
    assert "2026-11-10 09:30" in out
    assert "LAST SEEN" in out
    assert "super-secret-token" not in out
    assert client.list_calls == 1


def test_admin_mcp_list_empty_state(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    payload = {"server": "github-mcp", "tools": [], "truncated": False}

    assert cmd_admin_mcp_list(
        SimpleNamespace(json=False), FakeMCPClient(payload=payload)
    ) == 0

    assert stream.getvalue().strip() == "No MCP tools."


def test_admin_mcp_list_json_envelope(capsys):
    assert cmd_admin_mcp_list(
        SimpleNamespace(json=True), FakeMCPClient()
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["server"] == "github-mcp"
    assert payload["count"] == 3
    assert payload["truncated"] is False
    assert payload["tools"] == [APPROVED_TOOL, CHANGED_TOOL, NEW_TOOL]


def test_admin_mcp_list_malformed_response_exits_2(capsys):
    client = FakeMCPClient(payload={"server": "x", "tools": "not-a-list"})

    assert cmd_admin_mcp_list(SimpleNamespace(json=False), client) == 2

    assert "Unexpected response" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_admin_mcp_show_prints_hashes_schema_and_hint(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_mcp_show(
        SimpleNamespace(json=False, tool="github.issue"), FakeMCPClient()
    ) == 0

    out = stream.getvalue()
    lines = out.splitlines()
    assert all(len(line) <= 80 for line in lines)
    assert "MCP tool: github.issue" in out
    assert "Approval:   changed" in out
    assert f"Schema hash: {HASH_B}" in out
    assert f"Approved hash: {HASH_A}" in out
    assert "both hashes are shown above" in out
    assert "Schema:" in out
    assert '"query"' in out
    assert "darkmage admin mcp approve github.issue --hash \\" in out
    assert HASH_B in out
    assert "super-secret-token" not in out


def test_admin_mcp_show_bounds_large_schema(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    huge = {
        "type": "object",
        "properties": {
            f"field_{index}": {"type": "string", "description": "x" * 80}
            for index in range(120)
        },
    }
    tool = {**APPROVED_TOOL, "parameters": huge}
    payload = {"server": "github-mcp", "tools": [tool], "truncated": False}

    assert cmd_admin_mcp_show(
        SimpleNamespace(json=False, tool=TOOL_NAME),
        FakeMCPClient(payload=payload),
    ) == 0

    out = stream.getvalue()
    assert len(out.splitlines()) < 90
    assert "schema truncated; use --json for the full parameters" in out


def test_admin_mcp_show_json_envelope(capsys):
    assert cmd_admin_mcp_show(
        SimpleNamespace(json=True, tool=TOOL_NAME), FakeMCPClient()
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["server"] == "github-mcp"
    assert payload["tool"] == APPROVED_TOOL


def test_admin_mcp_show_unknown_tool_exits_2(capsys):
    client = FakeMCPClient()

    assert cmd_admin_mcp_show(
        SimpleNamespace(json=False, tool="missing.tool"), client
    ) == 2

    err = capsys.readouterr().err
    assert "Tool not found: missing.tool" in err
    assert "darkmage admin mcp list" in err
    assert client.list_calls == 1


@pytest.mark.parametrize("tool", ["", " bad", "bad/name", "bad\\name", "x" * 129])
def test_admin_mcp_show_rejects_bad_tool_locally(tool, capsys):
    client = FakeMCPClient()

    assert cmd_admin_mcp_show(SimpleNamespace(json=False, tool=tool), client) == 2

    assert "Invalid tool name" in capsys.readouterr().err
    assert client.list_calls == 0


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------


def test_admin_mcp_approve_current_hash_posts_exactly(capsys):
    client = FakeMCPClient(
        approved={**APPROVED_TOOL, "approval_status": "approved"}
    )

    assert cmd_admin_mcp_approve(
        SimpleNamespace(json=True, tool=TOOL_NAME, hash=HASH_A, yes=False),
        client,
    ) == 0

    assert client.approve_calls == [(TOOL_NAME, HASH_A)]
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["server"] == "github-mcp"
    assert payload["approved"] is True
    assert payload["tool"]["schema_hash"] == HASH_A
    assert "super-secret-token" not in json.dumps(payload)


def test_admin_mcp_approve_changed_hash_with_explicit_current(capsys):
    client = FakeMCPClient(
        payload={**TOOLS_PAYLOAD, "tools": [CHANGED_TOOL]},
        approved={**CHANGED_TOOL, "approval_status": "approved", "approved_schema_hash": HASH_B},
    )

    assert cmd_admin_mcp_approve(
        SimpleNamespace(json=True, tool="github.issue", hash=HASH_B, yes=False),
        client,
    ) == 0

    assert client.approve_calls == [("github.issue", HASH_B)]


def test_admin_mcp_approve_hash_mismatch_refuses_locally(capsys):
    client = FakeMCPClient()

    code = cmd_admin_mcp_approve(
        SimpleNamespace(json=True, tool="github.issue", hash=HASH_A, yes=True),
        client,
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "schema_hash_mismatch"
    assert payload["error"]["status_code"] is None
    message = payload["error"]["message"]
    assert f"provided={HASH_A}" in message
    assert f"current={HASH_B}" in message
    assert f"approved={HASH_A}" in message
    assert "Refusing to approve" in message
    assert client.approve_calls == []


@pytest.mark.parametrize(
    "bad_hash",
    ["", " " + HASH_A, HASH_A.upper(), HASH_A[:-1], "sha256:" + HASH_A, "g" * 64],
)
def test_admin_mcp_approve_rejects_malformed_hash_locally(bad_hash, capsys):
    client = FakeMCPClient()

    code = cmd_admin_mcp_approve(
        SimpleNamespace(json=False, tool=TOOL_NAME, hash=bad_hash, yes=True),
        client,
    )

    assert code == 2
    assert "64 lowercase hex" in capsys.readouterr().err
    assert client.list_calls == 0
    assert client.approve_calls == []


def test_admin_mcp_approve_without_hash_requires_yes(capsys):
    client = FakeMCPClient()

    code = cmd_admin_mcp_approve(
        SimpleNamespace(json=True, tool=TOOL_NAME, hash=None, yes=False),
        client,
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"
    assert HASH_A in payload["error"]["message"]
    assert "--yes" in payload["error"]["message"]
    assert client.list_calls == 1
    assert client.approve_calls == []


def test_admin_mcp_approve_without_hash_reports_changed_hashes(capsys):
    client = FakeMCPClient(payload={**TOOLS_PAYLOAD, "tools": [CHANGED_TOOL]})

    assert cmd_admin_mcp_approve(
        SimpleNamespace(json=True, tool="github.issue", hash=None, yes=False),
        client,
    ) == 2

    message = json.loads(capsys.readouterr().out)["error"]["message"]
    assert f"Current schema hash: {HASH_B}" in message
    assert f"Approved schema hash: {HASH_A}" in message
    assert client.approve_calls == []


def test_admin_mcp_approve_without_hash_with_yes_uses_fetched_hash(capsys):
    client = FakeMCPClient()

    assert cmd_admin_mcp_approve(
        SimpleNamespace(json=True, tool=TOOL_NAME, hash=None, yes=True),
        client,
    ) == 0

    assert client.list_calls == 1
    assert client.approve_calls == [(TOOL_NAME, HASH_A)]


def test_admin_mcp_approve_unknown_tool_does_not_post(capsys):
    client = FakeMCPClient()

    assert cmd_admin_mcp_approve(
        SimpleNamespace(json=False, tool="missing.tool", hash=None, yes=True),
        client,
    ) == 2

    assert "Tool not found: missing.tool" in capsys.readouterr().err
    assert client.approve_calls == []


def test_admin_mcp_approve_malformed_current_hash_does_not_post(capsys):
    broken = {**APPROVED_TOOL, "schema_hash": "short"}
    client = FakeMCPClient(
        payload={"server": "github-mcp", "tools": [broken], "truncated": False}
    )

    assert cmd_admin_mcp_approve(
        SimpleNamespace(json=False, tool=TOOL_NAME, hash=None, yes=True),
        client,
    ) == 2

    assert "missing or malformed" in capsys.readouterr().err
    assert client.approve_calls == []


# ---------------------------------------------------------------------------
# call
# ---------------------------------------------------------------------------


def test_admin_mcp_call_json_envelope(capsys):
    client = FakeMCPClient()

    assert cmd_admin_mcp_call(
        SimpleNamespace(
            json=True, tool=TOOL_NAME, arguments_json='{"query":"bug"}'
        ),
        client,
    ) == 0

    assert client.call_calls == [(TOOL_NAME, {"query": "bug"})]
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["server"] == "github-mcp"
    assert payload["tool"] == TOOL_NAME
    assert payload["ok"] is True
    assert payload["result"] == '{"items":[{"title":"bug"}]}'
    assert payload["error"] is None
    assert payload["truncated"] is False
    assert "super-secret-token" not in json.dumps(payload)


def test_admin_mcp_call_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_mcp_call(
        SimpleNamespace(
            json=False, tool=TOOL_NAME, arguments_json='{"query":"bug"}'
        ),
        FakeMCPClient(),
    ) == 0

    out = stream.getvalue()
    assert all(len(line) <= 80 for line in out.splitlines())
    assert f"MCP tool: {TOOL_NAME}" in out
    assert "Server:     github-mcp" in out
    assert "OK:         yes" in out
    assert "Result:" in out
    assert "bug" in out
    assert "super-secret-token" not in out


def test_admin_mcp_call_tool_error_exits_1(capsys):
    called = {
        "ok": False,
        "server": "github-mcp",
        "tool": TOOL_NAME,
        "result": None,
        "error": "upstream failed",
        "truncated": False,
    }

    assert cmd_admin_mcp_call(
        SimpleNamespace(json=True, tool=TOOL_NAME, arguments_json="{}"),
        FakeMCPClient(called=called),
    ) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == "upstream failed"


@pytest.mark.parametrize(
    "raw",
    [None, "", "{not json", "[]", '"text"', "null", "42"],
)
def test_admin_mcp_call_rejects_bad_args_locally(raw, capsys):
    client = FakeMCPClient()

    assert cmd_admin_mcp_call(
        SimpleNamespace(json=False, tool=TOOL_NAME, arguments_json=raw),
        client,
    ) == 2

    err = capsys.readouterr().err
    assert "Invalid --args" in err or "Missing --args" in err
    assert client.call_calls == []


def test_admin_mcp_call_bounds_long_result(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    called = {
        "ok": True,
        "server": "github-mcp",
        "tool": TOOL_NAME,
        "result": "x" * 10000,
        "error": None,
        "truncated": False,
    }

    assert cmd_admin_mcp_call(
        SimpleNamespace(json=False, tool=TOOL_NAME, arguments_json="{}"),
        FakeMCPClient(called=called),
    ) == 0

    out = stream.getvalue()
    assert all(len(line) <= 80 for line in out.splitlines())
    assert "result truncated by the CLI; use --json" in out


# ---------------------------------------------------------------------------
# 404 / 409 / 422 rendering and token hygiene
# ---------------------------------------------------------------------------


def _raise(method_name, message, status_code):
    def fail(self, *args, **kwargs):
        raise DarkmageError(message, status_code=status_code)

    return patch.object(DarkmageClient, method_name, fail)


def test_admin_mcp_list_404_json_is_admin_only(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_mcp_tools",
        "404 Not Found for GET /admin/mcp/tools: Not found",
        404,
    ):
        assert main(["--json", "admin", "mcp", "list"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 404
    assert payload["error"]["code"] == "admin_only_or_not_found"
    assert "admin only" in payload["error"]["message"].lower()
    assert "not found" in payload["error"]["message"].lower()
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_admin_mcp_list_404_plain_error(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_mcp_tools",
        "404 Not Found for GET /admin/mcp/tools: Not found",
        404,
    ):
        assert main(["admin", "mcp", "list"]) == 2

    captured = capsys.readouterr()
    assert "admin only" in captured.err.lower()
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_admin_mcp_show_404_is_admin_only(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise("admin_mcp_tools", "404 Not Found", 404):
        assert main(["--json", "admin", "mcp", "show", TOOL_NAME]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "admin_only_or_not_found"
    assert payload["error"]["status_code"] == 404


def test_admin_mcp_approve_409_is_clear(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(
        DarkmageClient, "admin_mcp_tools", lambda self: TOOLS_PAYLOAD
    )
    with _raise(
        "admin_mcp_approve",
        "409 Conflict for POST /admin/mcp/tools/github.search/approve: "
        "The tool schema changed while you were reviewing it; reload tools and approve again",
        409,
    ):
        assert main(
            [
                "--json",
                "admin",
                "mcp",
                "approve",
                TOOL_NAME,
                "--hash",
                HASH_A,
            ]
        ) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 409
    assert payload["error"]["code"] == "conflict"
    assert "schema changed" in payload["error"]["message"]
    assert "darkmage admin mcp list" in payload["error"]["message"]
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_admin_mcp_call_409_is_clear(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_mcp_call",
        "409 Conflict for POST /admin/mcp/call: MCP tool is not approved",
        409,
    ):
        assert main(
            ["--json", "admin", "mcp", "call", TOOL_NAME, "--args", "{}"]
        ) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "conflict"
    assert payload["error"]["message"] == (
        "409 Conflict for POST /admin/mcp/call: MCP tool is not approved"
    )
    assert "Traceback" not in payload["error"]["message"]


def test_admin_mcp_call_422_is_clear(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_mcp_call",
        "422 Unprocessable Entity for POST /admin/mcp/call: arguments must be an object",
        422,
    ):
        assert main(
            ["--json", "admin", "mcp", "call", TOOL_NAME, "--args", "{}"]
        ) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 422
    assert payload["error"]["code"] == "invalid_request"
    assert "arguments must be an object" in payload["error"]["message"]
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_admin_mcp_call_404_is_admin_only(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise("admin_mcp_call", "404 Not Found", 404):
        assert main(
            ["--json", "admin", "mcp", "call", TOOL_NAME, "--args", "{}"]
        ) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "admin_only_or_not_found"
    assert payload["error"]["status_code"] == 404


def test_admin_mcp_show_json_never_prints_client_token(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(
        DarkmageClient, "admin_mcp_tools", lambda self: TOOLS_PAYLOAD
    )

    assert main(["--json", "admin", "mcp", "show", TOOL_NAME]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["tool"] == APPROVED_TOOL
    assert "super-secret-token" not in captured.out + captured.err
