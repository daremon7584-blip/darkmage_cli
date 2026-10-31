"""Tests for odyssey-cli Phase 1 commands.

All HTTP calls are mocked via unittest.mock.patch on httpx.Client.request
and httpx.Client.get so no real network is used.
"""

from __future__ import annotations

import base64
import sys
from unittest.mock import MagicMock, patch

import pytest

from odyssey_cli.client import OdysseyClient, OdysseyError, _image_mime

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
    with pytest.raises(OdysseyError):
        _image_mime(b"not an image")


# ---------------------------------------------------------------------------
# workspace_file_edit
# ---------------------------------------------------------------------------


@patch("odyssey_cli.client.OdysseyClient._request")
def test_workspace_file_edit(mock_request):
    mock_request.return_value = _make_response(201, {"id": "123", "status": "waiting_approval"})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.workspace_file_edit("ws-1", "app/main.py", "print('hi')", base_content="print('old')")
    assert result["id"] == "123"
    mock_request.assert_called_once()
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/workspaces/ws-1/file-edits"
    assert kwargs["json"]["path"] == "app/main.py"
    assert kwargs["json"]["content"] == "print('hi')"
    assert kwargs["json"]["base_content"] == "print('old')"


@patch("odyssey_cli.client.OdysseyClient._request")
def test_workspace_file_edit_fetch_base(mock_request):
    # First call: fetch current content (GET files/content)
    # Second call: POST file-edits
    mock_request.side_effect = [
        _make_response(200, {"content": "current content"}),
        _make_response(201, {"id": "456"}),
    ]
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.workspace_file_edit("ws-1", "app/main.py", "new content")
    assert result["id"] == "456"
    assert mock_request.call_count == 2


@patch("odyssey_cli.client.OdysseyClient._request")
def test_workspace_file_edit_error(mock_request):
    mock_request.return_value = _make_response(409, {"detail": "file changed"})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    with pytest.raises(OdysseyError, match="409"):
        client.workspace_file_edit("ws-1", "app/main.py", "content")


# ---------------------------------------------------------------------------
# run_message
# ---------------------------------------------------------------------------


@patch("odyssey_cli.client.OdysseyClient._request")
def test_run_message(mock_request):
    mock_request.return_value = _make_response(202, {"id": "7"})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_message("run-1", "additional context")
    assert result["id"] == "7"
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/runs/run-1/messages"
    assert kwargs["json"]["text"] == "additional context"


# ---------------------------------------------------------------------------
# run_revert
# ---------------------------------------------------------------------------


@patch("odyssey_cli.client.OdysseyClient._request")
def test_run_revert(mock_request):
    mock_request.return_value = _make_response(200, {"status": "reverted", "checkpoint_status": "reverted"})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_revert("run-1")
    assert result["status"] == "reverted"
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/runs/run-1/revert"


# ---------------------------------------------------------------------------
# run_review
# ---------------------------------------------------------------------------


@patch("odyssey_cli.client.OdysseyClient._request")
def test_run_review(mock_request):
    mock_request.return_value = _make_response(200, {"model": "anthropic/claude-haiku-5.5", "findings": [], "cost_usd": "0.0004"})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_review("run-1")
    assert result["findings"] == []
    assert result["cost_usd"] == "0.0004"
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/runs/run-1/review"


# ---------------------------------------------------------------------------
# run_create with images
# ---------------------------------------------------------------------------


@patch("odyssey_cli.client.OdysseyClient._request")
def test_run_create_with_images(mock_request, tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    mock_request.return_value = _make_response(202, {"id": "run-1", "image_count": 1})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_create("sess-1", "Make it blue", images=[str(img)])
    assert result["image_count"] == 1
    _args, kwargs = mock_request.call_args
    assert kwargs["json"]["prompt"] == "Make it blue"
    assert len(kwargs["json"]["images"]) == 1
    assert kwargs["json"]["images"][0]["media_type"] == "image/png"
    # Verify base64 round-trips
    decoded = base64.b64decode(kwargs["json"]["images"][0]["data_base64"])
    assert decoded == b"\x89PNG\r\n\x1a\nfake"


@patch("odyssey_cli.client.OdysseyClient._request")
def test_run_create_image_not_found(mock_request):
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    with pytest.raises(OdysseyError, match="Image not found"):
        client.run_create("sess-1", "prompt", images=["/nonexistent.png"])


@patch("odyssey_cli.client.OdysseyClient._request")
def test_run_create_image_unsupported(mock_request, tmp_path):
    img = tmp_path / "test.bmp"
    img.write_bytes(b"BM fake bmp")
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    with pytest.raises(OdysseyError, match="Unsupported image format"):
        client.run_create("sess-1", "prompt", images=[str(img)])


# ---------------------------------------------------------------------------
# process_start / output / stop
# ---------------------------------------------------------------------------


@patch("odyssey_cli.client.OdysseyClient._request")
def test_process_start(mock_request):
    mock_request.return_value = _make_response(201, {"process_id": "proc-1", "status": "started"})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.process_start("ws-1", ["python", "app.py"], cwd="/workspace", port=8080)
    assert result["process_id"] == "proc-1"
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/workspaces/ws-1/processes"
    assert kwargs["json"]["argv"] == ["python", "app.py"]
    assert kwargs["json"]["cwd"] == "/workspace"
    assert kwargs["json"]["port"] == 8080


@patch("odyssey_cli.client.OdysseyClient._request")
def test_process_output(mock_request):
    mock_request.return_value = _make_response(200, {"process_id": "proc-1", "output": "server running", "running": True})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.process_output("ws-1", "proc-1")
    assert result["output"] == "server running"
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/workspaces/ws-1/processes"
    assert kwargs["params"]["process_id"] == "proc-1"


@patch("odyssey_cli.client.OdysseyClient._request")
def test_process_output_all(mock_request):
    mock_request.return_value = _make_response(200, {"processes": []})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.process_output("ws-1")
    assert result["processes"] == []
    _args, kwargs = mock_request.call_args
    assert kwargs["params"] == {}


@patch("odyssey_cli.client.OdysseyClient._request")
def test_process_stop(mock_request):
    mock_request.return_value = _make_response(200, {"process_id": "proc-1", "status": "stopped"})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.process_stop("ws-1", "proc-1")
    assert result["status"] == "stopped"
    call_args, _kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/workspaces/ws-1/processes/proc-1/stop"


# ---------------------------------------------------------------------------
# run_answer
# ---------------------------------------------------------------------------


@patch("odyssey_cli.client.OdysseyClient._request")
def test_run_answer(mock_request):
    mock_request.return_value = _make_response(200, {"question_id": "q1", "answers": ["yes"]})
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
    result = client.run_answer("run-1", "q1", ["yes"])
    assert result["answers"] == ["yes"]
    call_args, kwargs = mock_request.call_args
    assert call_args[0] == "POST"
    assert call_args[1] == "/runs/run-1/questions/q1"
    assert kwargs["json"]["answers"] == ["yes"]


# ---------------------------------------------------------------------------
# run_context
# ---------------------------------------------------------------------------


@patch("odyssey_cli.client.OdysseyClient._request")
def test_run_context(mock_request):
    mock_request.return_value = _make_response(200, {
        "run_id": "run-1",
        "status": "running",
        "context_tokens": 5000,
        "context_limit": 96000,
        "prompt_tokens": 1000,
        "completion_tokens": 500,
    })
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
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


@patch("odyssey_cli.client.OdysseyClient._request")
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
    client = OdysseyClient(base_url="http://localhost:8000", token="test-token")
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
    from odyssey_cli.cli import _format_event
    ev = {"id": "5", "event": "assistant.delta", "data": {"text": "Hello world"}}
    line = _format_event(ev)
    assert "assistant.delta" in line
    assert "Hello world" in line


def test_format_event_tool_requested():
    from odyssey_cli.cli import _format_event
    ev = {"id": "6", "event": "tool.requested", "data": {"name": "write_file", "arguments": {"path": "a.py"}}}
    line = _format_event(ev)
    assert "write_file" in line


def test_color_non_tty(monkeypatch):
    from odyssey_cli.cli import _RESET, _color
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert _color("text", "run.completed") == "text"
    assert _RESET == "\033[0m"

