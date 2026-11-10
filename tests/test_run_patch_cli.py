"""`run patch` CLI/client contracts: diff output, stat, files, JSON and errors."""

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
    _parse_patch_stats,
    _zsh_completion_script,
    build_parser,
    cmd_run_patch,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError

RUN_ID = "22222222-2222-4222-8222-222222222222"

PATCH = """diff --git a/src/app.py b/src/app.py
index 1234567..89abcde 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 import os
-old line
+new line
+extra line
 print("hi")
diff --git a/docs/readme.md b/docs/readme.md
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1 @@
-Old title
+New title
"""


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


class _RawPatch(str):
    """Minimal stand-in for the client's str subclass with raw bytes."""

    raw: bytes

    def __new__(cls, raw: bytes):
        obj = super().__new__(cls, raw.decode("utf-8", errors="replace"))
        obj.raw = raw
        return obj


class FakePatchClient:
    def __init__(self, patch_text=PATCH, error=None):
        self.patch_text = patch_text
        self.error = error
        self.calls: list[str] = []
        self.token = "super-secret-token"

    def run_patch(self, run_id):
        self.calls.append(run_id)
        if self.error:
            raise self.error
        return self.patch_text


def _args(**overrides):
    values = {
        "run_id": RUN_ID,
        "stat": False,
        "output": None,
        "no_color": False,
        "force": False,
        "json": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _response(status_code=200, data=None, text="", content=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = "OK"
    resp.json.return_value = data if data is not None else {}
    resp.text = text
    if content is not None:
        resp.content = content
    else:
        resp.content = text.encode("utf-8")
    resp.request = MagicMock()
    resp.request.method = "GET"
    resp.request.url.path = "/runs/run-1/patch"
    return resp


# ---------------------------------------------------------------------------
# Client API
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_patch_calls_endpoint_and_returns_text(mock_request):
    mock_request.return_value = _response(200, text=PATCH)
    client = DarkmageClient(
        base_url="https://api.example.test", token="super-secret-token"
    )

    result = client.run_patch(RUN_ID)

    assert result == PATCH
    assert isinstance(result, str)
    args, kwargs = mock_request.call_args
    assert args == ("GET", f"/runs/{RUN_ID}/patch")
    assert kwargs["headers"] == {"Accept": "text/x-patch"}
    assert "super-secret-token" not in str(result)


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_patch_keeps_exact_bytes_for_output(mock_request):
    body = b"diff --git a/x b/x\n+hello \xff\n"
    mock_request.return_value = _response(200, content=body)
    client = DarkmageClient(base_url="https://api.example.test", token="t")

    result = client.run_patch(RUN_ID)

    assert result.raw == body
    assert isinstance(result, str)


@patch("darkmage_cli.client.DarkmageClient._request")
def test_run_patch_surfaces_413_without_token(mock_request):
    mock_request.return_value = _response(
        413, {"detail": "Run changes are too large for a patch"}
    )
    client = DarkmageClient(
        base_url="https://api.example.test", token="super-secret-token"
    )

    with pytest.raises(DarkmageError) as exc_info:
        client.run_patch(RUN_ID)

    message = str(exc_info.value)
    assert exc_info.value.status_code == 413
    assert "Run changes are too large for a patch" in message
    assert "super-secret-token" not in message


# ---------------------------------------------------------------------------
# Parser, help and completion
# ---------------------------------------------------------------------------


def test_patch_parser_registration_and_flags():
    args = build_parser().parse_args(
        [
            "run",
            "patch",
            RUN_ID,
            "--stat",
            "--output",
            "out.patch",
            "--no-color",
            "--force",
            "--json",
        ]
    )
    assert args.run_command == "patch"
    assert args.run_id == RUN_ID
    assert args.stat is True
    assert args.output == "out.patch"
    assert args.no_color is True
    assert args.force is True
    assert args.json is True


def test_patch_help_mentions_flags():
    parser = build_parser()
    run_parser = parser._subparsers._group_actions[0].choices["run"]
    subparsers = run_parser._subparsers._group_actions[0].choices
    assert "patch" in subparsers
    help_text = subparsers["patch"].format_help()
    for flag in ("--stat", "--output", "--no-color", "--force", "--json"):
        assert flag in help_text


def test_completion_scripts_include_patch_and_flags():
    bash = _bash_completion_script()
    zsh = _zsh_completion_script()
    fish = _fish_completion_script()
    assert "review patch stop" in bash
    assert "--stat --output --no-color --force" in bash
    assert "review patch stop" in zsh
    assert "--output[Write exact patch bytes]" in zsh
    assert "review patch stop" in fish
    assert "-l stat" in fish
    assert "-l output" in fish
    assert "-l no-color" in fish


# ---------------------------------------------------------------------------
# Text/stat/JSON output
# ---------------------------------------------------------------------------


def test_patch_text_is_raw_and_uncolored_without_tty(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakePatchClient()

    assert cmd_run_patch(_args(), client) == 0

    assert stream.getvalue() == PATCH
    assert "\x1b[" not in stream.getvalue()
    assert client.calls == [RUN_ID]


def test_patch_accepts_bytes_from_client(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_run_patch(_args(), FakePatchClient(PATCH.encode("utf-8"))) == 0

    assert stream.getvalue() == PATCH


def test_patch_text_uses_color_on_tty(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakePatchClient()

    assert cmd_run_patch(_args(), client) == 0

    out = stream.getvalue()
    assert "\x1b[36m@@" in out
    assert "\x1b[32m+new line" in out
    assert "\x1b[31m-old line" in out
    assert "\x1b[1mdiff --git" in out


def test_patch_no_color_disables_ansi_on_tty(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_run_patch(_args(no_color=True), FakePatchClient()) == 0

    assert "\x1b[" not in stream.getvalue()
    assert stream.getvalue() == PATCH


def test_patch_stat_prints_file_and_line_counts(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_run_patch(_args(stat=True), FakePatchClient()) == 0

    out = stream.getvalue()
    assert "src/app.py  +2 -1" in out
    assert "docs/readme.md  +1 -1" in out
    assert "2 files changed, 3 insertions(+), 2 deletions(-)" in out
    assert all(len(line) <= 80 for line in out.splitlines())


def test_patch_stat_parses_new_deleted_binary_and_rename_files():
    patch_text = """diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+one
+two
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-one
-two
diff --git a/logo.png b/logo.png
Binary files a/logo.png and b/logo.png differ
diff --git a/old name.py b/new name.py
similarity index 100%
rename from old name.py
rename to new name.py
"""
    stats = _parse_patch_stats(patch_text)
    assert stats["files"] == 4
    assert stats["additions"] == 2
    assert stats["deletions"] == 2
    assert stats["stat"] == [
        {"path": "new.txt", "additions": 2, "deletions": 0},
        {"path": "old.txt", "additions": 0, "deletions": 2},
        {"path": "logo.png", "additions": 0, "deletions": 0},
        {"path": "new name.py", "additions": 0, "deletions": 0},
    ]


def test_patch_json_is_structured(capsys):
    client = FakePatchClient()

    assert cmd_run_patch(_args(json=True), client) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "run_id": RUN_ID,
        "files": 2,
        "additions": 3,
        "deletions": 2,
        "stat": [
            {"path": "src/app.py", "additions": 2, "deletions": 1},
            {"path": "docs/readme.md", "additions": 1, "deletions": 1},
        ],
        "patch": PATCH,
    }


# ---------------------------------------------------------------------------
# --output and empty patches
# ---------------------------------------------------------------------------


def test_patch_output_writes_exact_bytes_and_prints_path(monkeypatch, tmp_path):
    body = b"diff --git a/x b/x\n+hello \xff\n"
    target = tmp_path / "changes.patch"
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert (
        cmd_run_patch(
            _args(output=str(target)), FakePatchClient(_RawPatch(body))
        )
        == 0
    )

    assert target.read_bytes() == body
    out = stream.getvalue()
    assert f"Saved patch to {target}" in out
    assert f"({len(body)} bytes)" in out
    assert "+hello" not in out


def test_patch_output_refuses_overwrite_without_force(monkeypatch, tmp_path):
    target = tmp_path / "changes.patch"
    target.write_text("keep me", encoding="utf-8")
    client = FakePatchClient()
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    errors = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", errors)

    assert cmd_run_patch(_args(output=str(target)), client) == 1

    assert target.read_text(encoding="utf-8") == "keep me"
    assert client.calls == []
    assert "Refusing to overwrite" in errors.getvalue()
    assert "--force" in errors.getvalue()


def test_patch_output_force_overwrites(monkeypatch, tmp_path):
    target = tmp_path / "changes.patch"
    target.write_text("old", encoding="utf-8")
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert (
        cmd_run_patch(
            _args(output=str(target), force=True), FakePatchClient()
        )
        == 0
    )

    assert target.read_text(encoding="utf-8") == PATCH


def test_patch_output_with_json_writes_file_and_prints_json(
    capsys, tmp_path
):
    target = tmp_path / "changes.patch"

    assert (
        cmd_run_patch(_args(output=str(target), json=True), FakePatchClient())
        == 0
    )

    assert target.read_text(encoding="utf-8") == PATCH
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == 2
    assert payload["patch"] == PATCH


def test_patch_empty_is_friendly(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_run_patch(_args(), FakePatchClient("")) == 0

    out = stream.getvalue()
    assert "No changes" in out
    assert "empty patch" in out
    assert "\x1b[" not in out


def test_patch_empty_json_has_empty_arrays(capsys):
    assert cmd_run_patch(_args(json=True), FakePatchClient("")) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "run_id": RUN_ID,
        "files": 0,
        "additions": 0,
        "deletions": 0,
        "stat": [],
        "patch": "",
    }


def test_patch_empty_output_writes_zero_bytes(monkeypatch, tmp_path):
    target = tmp_path / "empty.patch"
    stream = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_run_patch(_args(output=str(target)), FakePatchClient("")) == 0

    assert target.read_bytes() == b""
    assert f"Saved patch to {target} (0 bytes)" in stream.getvalue()


# ---------------------------------------------------------------------------
# Errors and token safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "raw", "needle"),
    [
        (
            402,
            "402 Payment Required for GET /runs/x/patch: "
            "Downloads are part of the subscription",
            "subscription",
        ),
        (
            404,
            "404 Not Found for GET /runs/x/patch: Run not found",
            "not found",
        ),
        (
            409,
            "409 Conflict for GET /runs/x/patch: "
            "Wait for the run to finish before downloading its changes",
            "not finished",
        ),
    ],
)
def test_patch_http_errors_are_clear_and_do_not_leak_token(
    monkeypatch, capsys, status, raw, needle
):
    def fail(self, run_id):
        raise DarkmageError(raw, status_code=status)

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_patch", fail)

    assert (
        main(
            [
                "--url",
                "https://api.example.test",
                "run",
                "patch",
                RUN_ID,
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    assert needle in captured.err.lower()
    assert "super-secret-token" not in captured.out + captured.err


def test_patch_409_no_checkpoint_is_clear(monkeypatch, capsys):
    def fail(self, run_id):
        raise DarkmageError(
            "409 Conflict for GET /runs/x/patch: This run has no available "
            "checkpoint: it changed no files",
            status_code=409,
        )

    monkeypatch.setattr(DarkmageClient, "run_patch", fail)

    assert (
        main(
            [
                "--url",
                "https://api.example.test",
                "run",
                "patch",
                RUN_ID,
            ]
        )
        == 1
    )
    err = capsys.readouterr().err.lower()
    assert "no patch is available" in err
    assert "checkpoint" in err


def test_patch_413_suggests_review_and_output_limits(monkeypatch, capsys):
    def fail(self, run_id):
        raise DarkmageError(
            "413 Request Entity Too Large for GET /runs/x/patch: "
            "Run changes are too large for a patch",
            status_code=413,
        )

    monkeypatch.setattr(DarkmageClient, "run_patch", fail)

    assert (
        main(
            [
                "--url",
                "https://api.example.test",
                "run",
                "patch",
                RUN_ID,
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "too large" in err.lower()
    assert "413" in err
    assert "16 MiB" in err
    assert "darkmage run review" in err
    assert "--stat" in err
    assert "--output" in err


def test_patch_json_error_keeps_status_and_message(monkeypatch, capsys):
    def fail(self, run_id):
        raise DarkmageError(
            "404 Not Found for GET /runs/x/patch: Run not found",
            status_code=404,
        )

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_patch", fail)

    assert (
        main(
            [
                "--url",
                "https://api.example.test",
                "--json",
                "run",
                "patch",
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


def test_patch_main_passes_run_id_and_json_is_valid(monkeypatch, capsys):
    calls: list[str] = []

    def fake_run_patch(self, run_id):
        calls.append(run_id)
        return PATCH

    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "run_patch", fake_run_patch)

    assert (
        main(
            [
                "--url",
                "https://api.example.test",
                "--json",
                "run",
                "patch",
                RUN_ID,
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert calls == [RUN_ID]
    assert payload["run_id"] == RUN_ID
    assert payload["patch"] == PATCH


def test_large_patch_is_not_truncated(monkeypatch, capsys):
    chunks = ["diff --git a/f{i}.txt b/f{i}.txt\n".format(i=i) for i in range(300)]
    body_lines = []
    for i in range(300):
        body_lines.append(
            f"--- a/f{i}.txt\n+++ b/f{i}.txt\n@@ -0,0 +1,10 @@\n"
            + "".join(f"+line {i}-{n}\n" for n in range(10))
        )
    large = "".join(chunks) + "".join(body_lines)

    assert cmd_run_patch(_args(json=True), FakePatchClient(large)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["files"] == 300
    assert payload["additions"] == 3000
    assert payload["deletions"] == 0
    assert payload["patch"] == large
    assert len(payload["stat"]) == 300
