"""Tests for darkmage-cli Phase 1 commands.

All HTTP calls are mocked via unittest.mock.patch on httpx.Client.request
and httpx.Client.get so no real network is used.
"""

from __future__ import annotations

import base64
import sys
from unittest.mock import MagicMock, patch

import pytest

from darkmage_cli.client import DarkmageClient, DarkmageError, _image_mime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, json_data: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.request = MagicMock()
    resp.request.method = "GET"
    resp.request.url.path = "/test"
    return resp


# ---------------------------------------------------------------------------
# _image_mime
# ---------------------------------------------------------------------------


def test_image_mime_png():
    assert _image_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"


def test_image_mime_jpeg():
    assert _image_mime(b"\xff\xd8\xffrest") == "image/jpeg"


def test_image_mime_webp():
    assert _image_mime(b"RIFF....WEBP....") == "image/webp"


def test_image_mime_unknown():
    with pytest.raises(DarkmageError):
        _image_mime(b"not an image")


# ---------------------------------------------------------------------------
# workspace_file_edit
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_workspace_file_edit(mock_request):
    mock_request.return_value = _make_response(201, {"id": "123", "status": "waiting_approval"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.workspace_file_edit("ws-1", "app/main.py", "print('hi')", base_content="print('old')")
    assert result["id"] == "123"
    mock_request.assert_called_once()
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/workspaces/ws-1/file-edits"
    assert kwargs["json"]["path"] == "app/main.py"
    assert kwargs["json"]["content"] == "print('hi')"
    assert kwargs["json"]["base_content"] == "print('old')"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_workspace_file_edit_fetch_base(mock_request):
    # First call: fetch current content (GET files/content)
    # Second call: POST file-edits
    mock_request.side_effect = [
        _make_response(200, {"content": "current content"}),
        _make_response(201, {"id": "456"}),
    ]
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.workspace_file_edit("ws-1", "app/main.py", "new content")
    assert result["id"] == "456"
    assert mock_request.call_count == 2


@patch("darkmage_cli.client.DarkmageClient._request")
def test_workspace_file_edit_error(mock_request):
    mock_request.return_value = _make_response(409, {"detail": "file changed"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    with pytest.raises(DarkmageError, match="409"):
        client.workspace_file_edit("ws-1", "app/main.py", "content")


# ---------------------------------------------------------------------------
# run_message
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_message(mock_request):
    mock_request.return_value = _make_response(202, {"id": "7"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_message("run-1", "additional context")
    assert result["id"] == "7"
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/runs/run-1/messages"
    assert kwargs["json"]["text"] == "additional context"


# ---------------------------------------------------------------------------
# run_revert
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_revert(mock_request):
    mock_request.return_value = _make_response(200, {"status": "reverted", "checkpoint_status": "reverted"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_revert("run-1")
    assert result["status"] == "reverted"
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/runs/run-1/revert"


# ---------------------------------------------------------------------------
# run_review
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_review(mock_request):
    mock_request.return_value = _make_response(200, {"model": "anthropic/claude-haiku-5.5", "findings": [], "cost_usd": "0.0004"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_review("run-1")
    assert result["findings"] == []
    assert result["cost_usd"] == "0.0004"
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/runs/run-1/review"


# ---------------------------------------------------------------------------
# run_create with images
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_create_with_images(mock_request, tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    mock_request.return_value = _make_response(202, {"id": "run-1", "image_count": 1})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_create("sess-1", "Make it blue", images=[str(img)])
    assert result["image_count"] == 1
    _args, kwargs = mock_request.call_args
    assert kwargs["json"]["prompt"] == "Make it blue"
    assert len(kwargs["json"]["images"]) == 1
    assert kwargs["json"]["images"][0]["media_type"] == "image/png"
    # Verify base64 round-trips
    decoded = base64.b64decode(kwargs["json"]["images"][0]["data_base64"])
    assert decoded == b"\x89PNG\r\n\x1a\nfake"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_create_image_not_found(mock_request):
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    with pytest.raises(DarkmageError, match="Image not found"):
        client.run_create("sess-1", "prompt", images=["/nonexistent.png"])


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_create_image_unsupported(mock_request, tmp_path):
    img = tmp_path / "test.bmp"
    img.write_bytes(b"BM fake bmp")
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    with pytest.raises(DarkmageError, match="Unsupported image format"):
        client.run_create("sess-1", "prompt", images=[str(img)])


# ---------------------------------------------------------------------------
# process_start / output / stop
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_process_start(mock_request):
    mock_request.return_value = _make_response(201, {"process_id": "proc-1", "status": "started"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.process_start("ws-1", ["python", "app.py"], cwd="/workspace", port=8080)
    assert result["process_id"] == "proc-1"
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/workspaces/ws-1/processes"
    assert kwargs["json"]["argv"] == ["python", "app.py"]
    assert kwargs["json"]["cwd"] == "/workspace"
    assert kwargs["json"]["port"] == 8080


@patch("darkmage_cli.client.DarkmageClient._request")
def test_process_output(mock_request):
    mock_request.return_value = _make_response(200, {"process_id": "proc-1", "output": "server running", "running": True})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.process_output("ws-1", "proc-1")
    assert result["output"] == "server running"
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/workspaces/ws-1/processes"
    assert kwargs["params"]["process_id"] == "proc-1"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_process_output_all(mock_request):
    mock_request.return_value = _make_response(200, {"processes": []})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.process_output("ws-1")
    assert result["processes"] == []
    _args, kwargs = mock_request.call_args
    assert kwargs["params"] == {}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_process_stop(mock_request):
    mock_request.return_value = _make_response(200, {"process_id": "proc-1", "status": "stopped"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.process_stop("ws-1", "proc-1")
    assert result["status"] == "stopped"
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/workspaces/ws-1/processes/proc-1/stop"


# ---------------------------------------------------------------------------
# run_answer
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_answer(mock_request):
    mock_request.return_value = _make_response(200, {"question_id": "q1", "answers": ["yes"]})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_answer("run-1", "q1", ["yes"])
    assert result["answers"] == ["yes"]
    call_args, kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/runs/run-1/questions/q1"
    assert kwargs["json"]["answers"] == ["yes"]


# ---------------------------------------------------------------------------
# run_context
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_context(mock_request):
    mock_request.return_value = _make_response(200, {
        "run_id": "run-1",
        "status": "running",
        "context_tokens": 5000,
        "context_limit": 96000,
        "prompt_tokens": 1000,
        "completion_tokens": 500,
    })
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_context("run-1")
    assert result["context_tokens"] == 5000
    assert result["context_limit"] == 96000
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "GET"
    assert call_args[1] == "/runs/run-1"


# ---------------------------------------------------------------------------
# run_events_parsed
# ---------------------------------------------------------------------------


def _stream_lines(lines):
    class FakeResponse:
        def __init__(self, lines):
            self._lines = lines
            self.status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def iter_lines(self):
            yield from self._lines

    return FakeResponse(lines)


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_events_parsed(mock_request):
    lines = [
        "id: 1",
        "event: run.started",
        "data: {\"status\":\"queued\"}",
        "",
        "id: 2",
        "event: assistant.delta",
        'data: {"text":"Hello"}',
        "",
        ": keep-alive",
        "",
        "id: 3",
        "event: run.completed",
        'data: {"finish_reason":"stop"}',
        "",
    ]
    fake_stream = _stream_lines(lines)
    mock_request.return_value = fake_stream
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    # Stream context manager is used; _request returns the fake response directly.
    client._client.stream = lambda method, url, headers=None: fake_stream
    events = list(client.run_events_parsed("run-1", last_event_id=0))
    assert len(events) == 3
    assert events[0] == {"id": "1", "event": "run.started", "data": {"status": "queued"}}
    assert events[1] == {"id": "2", "event": "assistant.delta", "data": {"text": "Hello"}}
    assert events[2] == {"id": "3", "event": "run.completed", "data": {"finish_reason": "stop"}}


# ---------------------------------------------------------------------------
# _format_event / _color
# ---------------------------------------------------------------------------


def test_format_event_assistant():
    from darkmage_cli.cli import _format_event
    ev = {"id": "5", "event": "assistant.delta", "data": {"text": "Hello world"}}
    line = _format_event(ev)
    assert "assistant.delta" in line
    assert "Hello world" in line


def test_format_event_tool_requested():
    from darkmage_cli.cli import _format_event
    ev = {"id": "6", "event": "tool.requested", "data": {"name": "write_file", "arguments": {"path": "a.py"}}}
    line = _format_event(ev)
    assert "write_file" in line


def test_color_non_tty(monkeypatch):
    from darkmage_cli.cli import _RESET, _color
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert _color("text", "run.completed") == "text"
    assert _RESET == "\033[0m"


# ---------------------------------------------------------------------------
# payment_create / payment_list
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_payment_create_standard(mock_request):
    mock_request.return_value = _make_response(201, {
        "id": "pay-1",
        "code": "ODY-ABCDE",
        "product": "standard_30d",
        "amount_rub": 990,
        "status": "pending",
        "payment_link": "https://example.com/pay",
        "created_at": "2026-10-31T10:00:00Z",
    })
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.payment_create("standard_30d")
    assert result["product"] == "standard_30d"
    assert result["amount_rub"] == 990
    assert result["payment_link"] == "https://example.com/pay"
    call_args, kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/billing/payments"
    assert kwargs["json"]["product"] == "standard_30d"
    assert kwargs["json"].get("amount_rub") is None


@patch("darkmage_cli.client.DarkmageClient._request")
def test_payment_create_credits(mock_request):
    mock_request.return_value = _make_response(201, {
        "id": "pay-2",
        "code": "ODY-FGHIJ",
        "product": "credits",
        "amount_rub": 1000,
        "status": "pending",
        "payment_link": "https://example.com/pay",
    })
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.payment_create("credits", amount_rub=1000)
    assert result["product"] == "credits"
    assert result["amount_rub"] == 1000
    _call_args, kwargs = mock_request.call_args
    assert kwargs["json"]["product"] == "credits"
    assert kwargs["json"]["amount_rub"] == 1000


@patch("darkmage_cli.client.DarkmageClient._request")
def test_payment_list(mock_request):
    mock_request.return_value = _make_response(200, [
        {"id": "pay-1", "product": "standard_30d", "amount_rub": 990, "status": "confirmed", "created_at": "2026-10-31T09:00:00Z"},
        {"id": "pay-2", "product": "credits", "amount_rub": 1000, "status": "pending", "created_at": "2026-10-31T10:00:00Z"},
    ])
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.payment_list()
    assert len(result) == 2
    assert result[0]["status"] == "confirmed"
    assert result[1]["status"] == "pending"
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "GET"
    assert call_args[1] == "/billing/payments"


# ---------------------------------------------------------------------------
# admin_status
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_status(mock_request):
    mock_request.return_value = _make_response(200, {
        "openrouter_balance_usd": "12.50",
        "openrouter_balance_low_usd": "5.00",
        "openrouter_balance_low": False,
    })
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.admin_status()
    assert result["openrouter_balance_usd"] == "12.50"
    assert result["openrouter_balance_low"] is False
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "GET"
    assert call_args[1] == "/admin/status"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_status_low(mock_request):
    mock_request.return_value = _make_response(200, {
        "openrouter_balance_usd": "1.25",
        "openrouter_balance_low_usd": "5.00",
        "openrouter_balance_low": True,
    })
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.admin_status()
    assert result["openrouter_balance_low"] is True


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_git_clone(mock_request):
    mock_request.return_value = _make_response(200, {
        "commit": "abc123",
        "url": "https://github.com/owner/repo.git",
    })
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.git_clone("ws-1", "https://github.com/owner/repo.git", ref="main", depth=1)
    assert result["commit"] == "abc123"
    call_args, kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/workspaces/ws-1/git/clone"
    assert kwargs["json"]["url"] == "https://github.com/owner/repo.git"
    assert kwargs["json"]["ref"] == "main"
    assert kwargs["json"]["depth"] == 1


@patch("darkmage_cli.client.DarkmageClient._request")
def test_git_commit(mock_request):
    mock_request.return_value = _make_response(200, {"commit": "def456", "branch": "main"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.git_commit("ws-1", "Add feature", branch="feature")
    assert result["commit"] == "def456"
    call_args, kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/workspaces/ws-1/git/commit"
    assert kwargs["json"]["message"] == "Add feature"
    assert kwargs["json"]["branch"] == "feature"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_git_push(mock_request):
    mock_request.return_value = _make_response(200, {"pushed": True, "branch": "main"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.git_push("ws-1", branch="main")
    assert result["pushed"] is True
    call_args, kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/workspaces/ws-1/git/push"
    assert kwargs["json"]["branch"] == "main"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_git_pr_create(mock_request):
    mock_request.return_value = _make_response(200, {"pr_number": 42, "url": "https://github.com/owner/repo/pull/42"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.git_pr_create("ws-1", "Add feature", body="Description", base="main", head="feature")
    assert result["pr_number"] == 42
    call_args, kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/workspaces/ws-1/git/pr"
    assert kwargs["json"]["title"] == "Add feature"
    assert kwargs["json"]["body"] == "Description"
    assert kwargs["json"]["base"] == "main"
    assert kwargs["json"]["head"] == "feature"


# ---------------------------------------------------------------------------
# mcp
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_mcp_list(mock_request):
    mock_request.return_value = _make_response(200, {"tools": ["files.read", "files.write", "run.create"]})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.mcp_list()
    assert "files.read" in result["tools"]
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "GET"
    assert call_args[1] == "/mcp/tools"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_mcp_call(mock_request):
    mock_request.return_value = _make_response(200, {"result": "ok", "tool": "files.read"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.mpc_call("files.read", {"path": "app/main.py"}, workspace_id="ws-1")
    assert result["result"] == "ok"
    call_args, kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/mcp/call"
    assert kwargs["json"]["tool"] == "files.read"
    assert kwargs["json"]["arguments"] == {"path": "app/main.py"}
    assert kwargs["json"]["workspace_id"] == "ws-1"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_mcp_call_no_workspace(mock_request):
    mock_request.return_value = _make_response(200, {"result": "ok", "tool": "files.read"})
    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    result = client.mpc_call("files.read", {"path": "app/main.py"})
    assert result["result"] == "ok"
    _call_args, kwargs = mock_request.call_args
    assert kwargs["json"].get("workspace_id") is None


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_config_show_json(capsys, monkeypatch, tmp_path):
    from darkmage_cli.config import save_config

    # Перенаправить конфиг во временную директорию
    monkeypatch.setattr("darkmage_cli.config.CONFIG_FILE", tmp_path / "config.json")
    save_config({"base_url": "http://example.com:8000", "token": "secret-token-12345"})

    from darkmage_cli.cli import cmd_config_show

    class Args:
        json = True

    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    cmd_config_show(Args(), client)
    captured = capsys.readouterr()
    assert "http://example.com:8000" in captured.out
    assert "secret-token" in captured.out


def test_config_show_empty(capsys, monkeypatch, tmp_path):
    from darkmage_cli.config import save_config

    monkeypatch.setattr("darkmage_cli.config.CONFIG_FILE", tmp_path / "config.json")
    save_config({})

    from darkmage_cli.cli import cmd_config_show

    class Args:
        json = False

    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    cmd_config_show(Args(), client)
    captured = capsys.readouterr()
    assert "Конфиг пуст" in captured.out


def test_config_set_url_and_token(monkeypatch, tmp_path):
    from darkmage_cli.config import load_config, save_config

    monkeypatch.setattr("darkmage_cli.config.CONFIG_FILE", tmp_path / "config.json")
    save_config({})

    from darkmage_cli.cli import cmd_config_set

    class Args:
        url = "http://new-server:9000"
        verbose = False

    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    cmd_config_set(Args(), client)
    cfg = load_config()
    assert cfg["base_url"] == "http://new-server:9000"
    # Token should not be set via CLI argument (security: use DARKMAGE_TOKEN env var instead)
    assert "token" not in cfg


def test_config_set_no_changes(capsys, monkeypatch, tmp_path):
    from darkmage_cli.config import save_config

    monkeypatch.setattr("darkmage_cli.config.CONFIG_FILE", tmp_path / "config.json")
    save_config({})

    from darkmage_cli.cli import cmd_config_set

    class Args:
        url = None
        token = None
        verbose = False

    client = DarkmageClient(base_url="http://localhost:8000", token="test-token")
    cmd_config_set(Args(), client)
    captured = capsys.readouterr()
    assert "Нечего менять" in captured.out

