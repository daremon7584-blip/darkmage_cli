"""Admin publish moderation CLI and client contracts.

The moderation API hides non-admins behind a 404. These tests pin the exact
request shapes, the 80-column tables, destructive-action guards, JSON output
and the absence of token leaks.
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
    cmd_admin_publish_apps,
    cmd_admin_publish_block,
    cmd_admin_publish_reports,
    cmd_admin_publish_resolve,
    cmd_admin_publish_unblock,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError

REPORT_ID = "11111111-1111-4111-8111-111111111111"
REPORT_ID_2 = "22222222-2222-4222-8222-222222222222"
APP_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
WORKSPACE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SESSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
CREATED_AT = "2026-11-10T08:15:00+00:00"
UPDATED_AT = "2026-11-10T09:30:00+00:00"

REPORT = {
    "id": REPORT_ID,
    "app_id": APP_ID,
    "slug": "demo-shop-abc12345",
    "app_status": "published",
    "moderation_status": "approved",
    "owner_id": 7,
    "title": "Demo shop",
    "reason": "phishing",
    "details": "Login page imitates the platform.",
    "status": "open",
    "resolution": None,
    "created_at": CREATED_AT,
    "resolved_at": None,
    "resolved_by": None,
}

DISMISSED_REPORT = {
    **REPORT,
    "status": "dismissed",
    "resolution": "not actionable",
    "resolved_at": UPDATED_AT,
    "resolved_by": 1,
}

REMOVED_REPORT = {
    **REPORT,
    "status": "resolved",
    "resolution": "malware",
    "app_status": "disabled",
    "moderation_status": "blocked",
    "resolved_at": UPDATED_AT,
    "resolved_by": 1,
}

APP = {
    "id": APP_ID,
    "owner_id": 7,
    "owner_email": "owner@example.test",
    "owner_publish_banned": False,
    "workspace_id": WORKSPACE_ID,
    "session_id": SESSION_ID,
    "slug": "demo-shop-abc12345",
    "title": "Demo shop",
    "status": "published",
    "moderation_status": "approved",
    "visibility": "public",
    "file_count": 3,
    "total_bytes": 2048,
    "open_reports": 2,
    "created_at": CREATED_AT,
    "updated_at": UPDATED_AT,
    "expires_at": None,
    "last_published_at": UPDATED_AT,
}

BANNED_APP = {
    **APP,
    "owner_publish_banned": True,
    "status": "blocked",
    "moderation_status": "blocked",
    "open_reports": 0,
}

UNBLOCKED_APP = {
    **APP,
    "owner_publish_banned": True,
    "status": "published",
    "moderation_status": "approved",
    "open_reports": 0,
}


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


class FakePublishClient:
    def __init__(
        self,
        reports=None,
        report=None,
        apps=None,
        blocked=None,
        unblocked=None,
    ):
        self.reports = reports if reports is not None else [REPORT]
        self.report = report if report is not None else DISMISSED_REPORT
        self.apps = apps if apps is not None else [APP]
        self.blocked = blocked if blocked is not None else BANNED_APP
        self.unblocked = unblocked if unblocked is not None else UNBLOCKED_APP
        self.report_calls: list[tuple[str | None, int]] = []
        self.resolve_calls: list[tuple[str, str, str | None]] = []
        self.app_calls: list[tuple[str | None, int]] = []
        self.block_calls: list[tuple[str, bool]] = []
        self.unblock_calls: list[str] = []
        self.token = "super-secret-token"

    def admin_publish_reports(self, status=None, limit=50):
        self.report_calls.append((status, limit))
        return self.reports

    def admin_publish_resolve(self, report_id, decision, note=None):
        self.resolve_calls.append((report_id, decision, note))
        return self.report

    def admin_publish_apps(self, status=None, limit=50):
        self.app_calls.append((status, limit))
        return self.apps

    def admin_publish_block(self, app_id, ban_owner=False):
        self.block_calls.append((app_id, ban_owner))
        return self.blocked

    def admin_publish_unblock(self, app_id):
        self.unblock_calls.append(app_id)
        return self.unblocked


def _args(**overrides):
    values = {
        "json": False,
        "status": None,
        "limit": 50,
        "decision": None,
        "note": None,
        "yes": False,
        "ban_owner": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _response(status_code=200, data=None, path="/admin/publish/reports"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = "OK" if status_code < 400 else "Error"
    resp.json.return_value = data if data is not None else {}
    resp.text = json.dumps(data if data is not None else {})
    resp.request = MagicMock()
    resp.request.method = "POST" if status_code != 200 else "GET"
    resp.request.url.path = path
    return resp


def _raise(method_name, message, status_code):
    def fail(self, *args, **kwargs):
        raise DarkmageError(message, status_code=status_code)

    return patch.object(DarkmageClient, method_name, fail)


# ---------------------------------------------------------------------------
# Client API calls
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_publish_reports_calls_list_endpoint(mock_request):
    mock_request.return_value = _response(200, [REPORT])
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_publish_reports("open", 25)

    assert result == [REPORT]
    args, kwargs = mock_request.call_args
    assert args == ("GET", "/admin/publish/reports")
    assert kwargs["params"] == {"limit": 25, "status": "open"}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_publish_resolve_posts_decision_and_note(mock_request):
    mock_request.return_value = _response(200, DISMISSED_REPORT)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_publish_resolve(REPORT_ID, "dismiss", "not actionable")

    assert result == DISMISSED_REPORT
    args, kwargs = mock_request.call_args
    assert args == (
        "POST",
        f"/admin/publish/reports/{REPORT_ID}/resolve",
    )
    assert kwargs["json"]["decision"] == "dismiss"
    assert kwargs["json"]["action"] == "dismissed"
    assert kwargs["json"]["note"] == "not actionable"


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_publish_resolve_remove_maps_to_resolved_action(mock_request):
    mock_request.return_value = _response(200, REMOVED_REPORT)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    client.admin_publish_resolve(REPORT_ID, "remove")

    _, kwargs = mock_request.call_args
    assert kwargs["json"]["decision"] == "remove"
    assert kwargs["json"]["action"] == "resolved"
    assert "note" not in kwargs["json"]


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_publish_apps_calls_list_endpoint(mock_request):
    mock_request.return_value = _response(200, [APP], path="/admin/publish/apps")
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_publish_apps("published", 10)

    assert result == [APP]
    args, kwargs = mock_request.call_args
    assert args == ("GET", "/admin/publish/apps")
    assert kwargs["params"] == {"limit": 10, "status": "published"}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_publish_block_posts_ban_owner(mock_request):
    mock_request.return_value = _response(200, BANNED_APP)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_publish_block(APP_ID, True)

    assert result == BANNED_APP
    args, kwargs = mock_request.call_args
    assert args == ("POST", f"/admin/publish/{APP_ID}/block")
    assert kwargs["json"] == {"ban_owner": True}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_publish_block_falls_back_to_old_path_and_bans_owner(mock_request):
    old_app = {k: v for k, v in BANNED_APP.items() if k != "owner_publish_banned"}
    mock_request.side_effect = [
        _response(404, {"detail": "Not Found"}),
        _response(200, old_app),
        _response(200, {"user_id": 7, "publish_banned_at": UPDATED_AT}),
    ]
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_publish_block(APP_ID, True)

    assert result == old_app
    paths = [call.args[1] for call in mock_request.call_args_list]
    assert paths == [
        f"/admin/publish/{APP_ID}/block",
        f"/admin/publish/apps/{APP_ID}/block",
        "/admin/publish/users/7/ban",
    ]


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_publish_unblock_calls_endpoint(mock_request):
    mock_request.return_value = _response(200, UNBLOCKED_APP)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_publish_unblock(APP_ID)

    assert result == UNBLOCKED_APP
    args, _kwargs = mock_request.call_args
    assert args == ("POST", f"/admin/publish/{APP_ID}/unblock")


# ---------------------------------------------------------------------------
# Parser, help and completions
# ---------------------------------------------------------------------------


def test_admin_publish_parser_registration():
    parser = build_parser()

    reports = parser.parse_args(
        ["admin", "publish", "reports", "--status", "open", "--limit", "10"]
    )
    assert reports.publish_command == "reports"
    assert reports.status == "open"
    assert reports.limit == 10
    assert reports.func is cmd_admin_publish_reports

    resolve = parser.parse_args(
        ["admin", "publish", "resolve", REPORT_ID, "--decision", "dismiss"]
    )
    assert resolve.publish_command == "resolve"
    assert resolve.report_id == REPORT_ID
    assert resolve.decision == "dismiss"
    assert resolve.func is cmd_admin_publish_resolve

    missing = parser.parse_args(["admin", "publish", "resolve", REPORT_ID])
    assert missing.decision is None

    apps = parser.parse_args(
        ["admin", "publish", "apps", "--status", "published"]
    )
    assert apps.publish_command == "apps"
    assert apps.status == "published"
    assert apps.func is cmd_admin_publish_apps

    block = parser.parse_args(
        ["admin", "publish", "block", APP_ID, "--ban-owner", "--yes"]
    )
    assert block.publish_command == "block"
    assert block.ban_owner is True
    assert block.yes is True
    assert block.func is cmd_admin_publish_block

    unblock = parser.parse_args(["admin", "publish", "unblock", APP_ID])
    assert unblock.publish_command == "unblock"
    assert unblock.func is cmd_admin_publish_unblock


def test_help_lists_admin_publish_commands(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["admin", "publish", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in ("reports", "resolve", "apps", "block", "unblock"):
        assert command in out

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["admin", "publish", "resolve", "--help"])
    assert exc.value.code == 0
    resolve_help = capsys.readouterr().out
    assert "--decision" in resolve_help
    assert "--note" in resolve_help
    assert "--yes" in resolve_help

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["admin", "publish", "block", "--help"])
    assert exc.value.code == 0
    block_help = capsys.readouterr().out
    assert "--ban-owner" in block_help
    assert "--yes" in block_help


def test_completion_scripts_include_admin_publish():
    bash = _bash_completion_script()
    zsh = _zsh_completion_script()
    fish = _fish_completion_script()

    for script in (bash, zsh, fish):
        assert "publish" in script
        assert "reports resolve apps block unblock" in script
        assert "--decision" in script
        assert "--ban-owner" in script
        assert "dismiss remove" in script
    assert "open resolved dismissed published draft disabled expired" in bash
    assert "open resolved dismissed published draft disabled expired" in zsh
    assert "open resolved dismissed published draft disabled expired" in fish


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def test_reports_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakePublishClient(reports=[REPORT, {**REPORT, "id": REPORT_ID_2}])

    assert cmd_admin_publish_reports(_args(), client) == 0

    out = stream.getvalue()
    lines = out.splitlines()
    assert lines
    assert all(len(line) <= 80 for line in lines)
    assert "Abuse reports:" in out
    assert REPORT_ID[:12] in out
    assert "Demo shop" in out
    assert "demo-shop" in out
    assert "phishing" in out
    assert "open" in out
    assert "2026-11-10" in out
    assert "IDs are shortened; use --json for full values." in out
    assert "super-secret-token" not in out
    assert client.report_calls == [(None, 50)]


def test_reports_empty_state(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_publish_reports(
        _args(), FakePublishClient(reports=[])
    ) == 0

    assert stream.getvalue().strip() == "No abuse reports."


def test_reports_json_is_raw_list(capsys):
    assert cmd_admin_publish_reports(
        _args(json=True), FakePublishClient(reports=[REPORT])
    ) == 0

    assert json.loads(capsys.readouterr().out) == [REPORT]


def test_reports_invalid_limit_does_not_call_api(capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_reports(_args(limit=201), client) == 2

    assert "Invalid --limit" in capsys.readouterr().err
    assert client.report_calls == []


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------


def test_resolve_dismiss_is_safe_and_posts_note(capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_resolve(
        _args(
            json=True,
            report_id=REPORT_ID,
            decision="dismiss",
            note="not actionable",
        ),
        client,
    ) == 0

    assert client.resolve_calls == [(REPORT_ID, "dismiss", "not actionable")]
    assert json.loads(capsys.readouterr().out) == DISMISSED_REPORT


def test_resolve_missing_decision_exits_2_without_call(capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_resolve(
        _args(json=True, report_id=REPORT_ID), client
    ) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "missing_decision"
    assert "--decision" in payload["error"]["message"]
    assert payload["error"]["status_code"] is None
    assert client.resolve_calls == []


def test_resolve_remove_non_tty_requires_yes(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_interactive_session", lambda: False)
    client = FakePublishClient()

    assert cmd_admin_publish_resolve(
        _args(json=True, report_id=REPORT_ID, decision="remove"), client
    ) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"
    assert "--yes" in payload["error"]["message"]
    assert "snapshot is deleted later" in payload["error"]["message"]
    assert client.resolve_calls == []


def test_resolve_remove_with_yes_posts(capsys):
    client = FakePublishClient(report=REMOVED_REPORT)

    assert cmd_admin_publish_resolve(
        _args(
            json=True,
            report_id=REPORT_ID,
            decision="remove",
            yes=True,
        ),
        client,
    ) == 0

    assert client.resolve_calls == [(REPORT_ID, "remove", None)]
    assert json.loads(capsys.readouterr().out) == REMOVED_REPORT


def test_resolve_remove_old_api_also_blocks_app(capsys):
    old_report = {**DISMISSED_REPORT, "app_status": "published"}
    client = FakePublishClient(report=old_report)

    assert cmd_admin_publish_resolve(
        _args(
            json=True,
            report_id=REPORT_ID,
            decision="remove",
            yes=True,
        ),
        client,
    ) == 0

    assert client.resolve_calls == [(REPORT_ID, "remove", None)]
    assert client.block_calls == [(APP_ID, False)]
    assert json.loads(capsys.readouterr().out) == old_report


def test_resolve_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_publish_resolve(
        _args(report_id=REPORT_ID, decision="dismiss", note="not actionable"),
        FakePublishClient(),
    ) == 0

    out = stream.getvalue()
    assert all(len(line) <= 80 for line in out.splitlines())
    assert f"Report: {REPORT_ID}" in out
    assert "Status:" in out
    assert "dismissed" in out
    assert "not actionable" in out


@pytest.mark.parametrize(
    "report_id",
    ["", "not-a-uuid", "1111", "11111111-1111-4111-8111"],
)
def test_resolve_rejects_invalid_report_id(report_id, capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_resolve(
        _args(report_id=report_id, decision="dismiss"), client
    ) == 2

    assert "Invalid report id" in capsys.readouterr().err
    assert client.resolve_calls == []


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------


def test_apps_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakePublishClient(
        apps=[APP, {**BANNED_APP, "open_reports": 5}]
    )

    assert cmd_admin_publish_apps(_args(), client) == 0

    out = stream.getvalue()
    lines = out.splitlines()
    assert lines
    assert all(len(line) <= 80 for line in lines)
    assert "Published apps:" in out
    assert "ID" in out
    assert "SLUG" in out
    assert "STATUS" in out
    assert "OWNER BAN" in out
    assert "REPORTS" in out
    assert APP_ID in out
    assert "demo-shop" in out
    assert "published" in out
    assert "no" in out
    assert "yes" in out
    assert "super-secret-token" not in out
    assert client.app_calls == [(None, 50)]


def test_apps_empty_state(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_publish_apps(_args(), FakePublishClient(apps=[])) == 0

    assert stream.getvalue().strip() == "No published apps."


def test_apps_json_is_raw_list(capsys):
    assert cmd_admin_publish_apps(
        _args(json=True, status="published"), FakePublishClient(apps=[APP])
    ) == 0

    assert json.loads(capsys.readouterr().out) == [APP]


# ---------------------------------------------------------------------------
# Block / unblock
# ---------------------------------------------------------------------------


def test_block_json_posts_ban_owner(capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_block(
        _args(json=True, app_id=APP_ID, ban_owner=True, yes=True), client
    ) == 0

    assert client.block_calls == [(APP_ID, True)]
    assert json.loads(capsys.readouterr().out) == BANNED_APP


def test_block_plain_does_not_require_confirmation(capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_block(
        _args(json=True, app_id=APP_ID), client
    ) == 0

    assert client.block_calls == [(APP_ID, False)]
    assert "super-secret-token" not in capsys.readouterr().out


def test_block_ban_owner_non_tty_requires_yes(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_interactive_session", lambda: False)
    client = FakePublishClient()

    assert cmd_admin_publish_block(
        _args(json=True, app_id=APP_ID, ban_owner=True), client
    ) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "confirmation_required"
    assert "--yes" in payload["error"]["message"]
    assert client.block_calls == []


def test_block_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_publish_block(
        _args(app_id=APP_ID, ban_owner=True, yes=True), FakePublishClient()
    ) == 0

    out = stream.getvalue()
    assert all(len(line) <= 80 for line in out.splitlines())
    assert f"Blocked app: {APP_ID}" in out
    assert "Owner banned:" in out
    assert "yes" in out


def test_unblock_json(capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_unblock(
        _args(json=True, app_id=APP_ID), client
    ) == 0

    assert client.unblock_calls == [APP_ID]
    assert json.loads(capsys.readouterr().out) == UNBLOCKED_APP


def test_unblock_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_publish_unblock(
        _args(app_id=APP_ID), FakePublishClient()
    ) == 0

    out = stream.getvalue()
    assert all(len(line) <= 80 for line in out.splitlines())
    assert f"Unblocked app: {APP_ID}" in out
    assert "Owner banned:" in out


@pytest.mark.parametrize("app_id", ["", "not-a-uuid", "aaaa"])
def test_block_rejects_invalid_app_id(app_id, capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_block(_args(app_id=app_id), client) == 2

    assert "Invalid app id" in capsys.readouterr().err
    assert client.block_calls == []


def test_unblock_rejects_invalid_app_id(capsys):
    client = FakePublishClient()

    assert cmd_admin_publish_unblock(_args(app_id="bad"), client) == 2

    assert "Invalid app id" in capsys.readouterr().err
    assert client.unblock_calls == []


# ---------------------------------------------------------------------------
# 404 / 409 / 422 rendering and token hygiene
# ---------------------------------------------------------------------------


def test_reports_404_json_is_admin_only(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_publish_reports",
        "404 Not Found for GET /admin/publish/reports: Not found",
        404,
    ):
        assert main(["--json", "admin", "publish", "reports"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 404
    assert payload["error"]["code"] == "admin_only_or_not_found"
    assert "admin only" in payload["error"]["message"].lower()
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_apps_404_plain_error(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_publish_apps",
        "404 Not Found for GET /admin/publish/apps: Not found",
        404,
    ):
        assert main(["admin", "publish", "apps"]) == 2

    captured = capsys.readouterr()
    assert "admin only" in captured.err.lower()
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_resolve_409_is_clear(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_publish_resolve",
        "409 Conflict for POST /admin/publish/reports/x/resolve: Report is already resolved",
        409,
    ):
        assert main(
            [
                "--json",
                "admin",
                "publish",
                "resolve",
                REPORT_ID,
                "--decision",
                "dismiss",
            ]
        ) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 409
    assert payload["error"]["code"] == "conflict"
    assert "already resolved" in payload["error"]["message"]
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_block_422_is_clear(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_publish_block",
        "422 Unprocessable Entity for POST /admin/publish/x/block: invalid app id",
        422,
    ):
        assert main(
            ["--json", "admin", "publish", "block", APP_ID]
        ) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 422
    assert payload["error"]["code"] == "invalid_request"
    assert "invalid app id" in payload["error"]["message"]
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_unblock_409_is_clear(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_publish_unblock",
        "409 Conflict for POST /admin/publish/x/unblock: Published app is not blocked",
        409,
    ):
        assert main(
            ["--json", "admin", "publish", "unblock", APP_ID]
        ) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "conflict"
    assert "not blocked" in payload["error"]["message"]


def test_admin_publish_success_json_never_prints_token(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(
        DarkmageClient,
        "admin_publish_reports",
        lambda self, status=None, limit=50: [REPORT],
    )

    assert main(["--json", "admin", "publish", "reports"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == [REPORT]
    assert "super-secret-token" not in captured.out + captured.err
