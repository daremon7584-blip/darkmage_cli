"""Admin skill gate CLI and client contracts.

The backend answers non-admins with 404, so these tests also pin the friendly
"admin only or not found" rendering and the absence of token leaks.
"""

from __future__ import annotations

import hashlib
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
    cmd_admin_skills_approve,
    cmd_admin_skills_gate,
    cmd_admin_skills_list,
    cmd_admin_skills_reject,
    cmd_admin_skills_scan,
    cmd_admin_skills_show,
    main,
)
from darkmage_cli.client import DarkmageClient, DarkmageError

SCAN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DIGEST = "a" * 64
CREATED_AT = "2026-11-10T08:00:00+00:00"

ISSUES = [
    {
        "severity": "CRITICAL",
        "category": "Data Exfiltration",
        "confidence": 0.95,
        "finding": "Reads environment variables and uploads them to an external host.",
        "location": {"file": "scripts/install.sh", "start_line": 12},
    },
    {
        "severity": "HIGH",
        "category": "Supply Chain",
        "confidence": 0.85,
        "finding": "Downloads an executable from an untrusted host.",
        "location": {"file": "scripts/install.sh", "start_line": 20},
    },
    {
        "severity": "HIGH",
        "category": "Tool Misuse",
        "confidence": 0.70,
        "finding": "Can delete arbitrary workspace files.",
    },
    {
        "severity": "MEDIUM",
        "category": "Prompt Injection",
        "confidence": 0.65,
        "finding": "Instruction text targets the agent.",
    },
    {
        "severity": "LOW",
        "category": "Unknown",
        "confidence": 0.10,
        "finding": "Unclassified scanner note.",
    },
    {
        "severity": "HIGH",
        "category": "analysis-evasion",
        "confidence": 1.0,
        "finding": "Coverage-only finding that must be hidden beyond the top five.",
    },
]

SCAN = {
    "id": SCAN_ID,
    "name": "release-helper",
    "version": "0.1.0",
    "source": "https://example.test/skills/release-helper",
    "digest": DIGEST,
    "status": "blocked",
    "risk_score": 100,
    "severity": "CRITICAL",
    "recommendation": "DO_NOT_INSTALL",
    "review_note": None,
    "created_at": CREATED_AT,
    "reviewed_at": None,
    "report": {
        "risk_assessment": {
            "score": 100,
            "severity": "CRITICAL",
            "recommendation": "DO_NOT_INSTALL",
        },
        "issues": ISSUES,
    },
}

REVIEW_SCAN = dict(SCAN, status="review")
APPROVED_SCAN = dict(SCAN, status="approved", review_note="reviewed")
REJECTED_SCAN = dict(SCAN, status="rejected", review_note="untrusted publisher")


class _TTYStringIO(io.StringIO):
    def isatty(self):
        return True


class FakeSkillsClient:
    def __init__(
        self,
        scans=None,
        scan=None,
        decision=None,
        scanned=None,
        approved=None,
        rejected=None,
    ):
        self.scans = scans if scans is not None else []
        self.scan = scan if scan is not None else SCAN
        self.decision = decision if decision is not None else {
            "digest": DIGEST,
            "status": "approved",
            "allowed": True,
        }
        self.scanned = scanned if scanned is not None else SCAN
        self.approved = approved if approved is not None else APPROVED_SCAN
        self.rejected = rejected if rejected is not None else REJECTED_SCAN
        self.list_calls: list[str | None] = []
        self.get_calls: list[str] = []
        self.gate_calls: list[str] = []
        self.scan_calls: list[tuple] = []
        self.approve_calls: list[tuple] = []
        self.reject_calls: list[tuple] = []
        self.token = "super-secret-token"

    def admin_skill_list(self, status=None, limit=50):
        self.list_calls.append(status)
        return self.scans

    def admin_skill_get(self, scan_id):
        self.get_calls.append(scan_id)
        return self.scan

    def admin_skill_gate(self, digest):
        self.gate_calls.append(digest)
        return self.decision

    def admin_skill_scan(self, name, version, source, digest, report):
        self.scan_calls.append((name, version, source, digest, report))
        return self.scanned

    def admin_skill_approve(self, scan_id, note="", allow_high_risk=False):
        self.approve_calls.append((scan_id, note, allow_high_risk))
        return self.approved

    def admin_skill_reject(self, scan_id, note=""):
        self.reject_calls.append((scan_id, note))
        return self.rejected


def _response(status_code=200, data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason_phrase = "OK"
    resp.json.return_value = data if data is not None else {}
    resp.text = json.dumps(data if data is not None else {})
    resp.request = MagicMock()
    resp.request.method = "GET"
    resp.request.url.path = "/admin/skills"
    return resp


# ---------------------------------------------------------------------------
# Client API calls
# ---------------------------------------------------------------------------


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_skill_list_calls_filtered_endpoint(mock_request):
    mock_request.return_value = _response(200, [SCAN])
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_skill_list(status="blocked")

    assert result == [SCAN]
    args, kwargs = mock_request.call_args
    assert args == ("GET", "/admin/skills")
    assert kwargs["params"] == {"limit": 50, "status": "blocked"}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_skill_get_and_gate_use_safe_paths(mock_request):
    mock_request.return_value = _response(200, SCAN)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    client.admin_skill_get(SCAN_ID)
    assert mock_request.call_args.args == ("GET", f"/admin/skills/{SCAN_ID}")

    client.admin_skill_gate(DIGEST)
    args, kwargs = mock_request.call_args
    assert args == ("GET", "/admin/skills/gate")
    assert kwargs["params"] == {"digest": DIGEST}


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_skill_scan_posts_contract_body(mock_request):
    mock_request.return_value = _response(201, SCAN)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    result = client.admin_skill_scan("release-helper", "0.1.0", "url", DIGEST, {"issues": []})

    assert result == SCAN
    args, kwargs = mock_request.call_args
    assert args == ("POST", "/admin/skills/scan")
    assert kwargs["json"] == {
        "name": "release-helper",
        "version": "0.1.0",
        "source": "url",
        "digest": DIGEST,
        "report": {"issues": []},
    }


@patch("darkmage_cli.client.DarkmageClient._request")
def test_admin_skill_approve_and_reject_bodies(mock_request):
    mock_request.return_value = _response(200, APPROVED_SCAN)
    client = DarkmageClient(base_url="http://localhost:8000", token="t")

    client.admin_skill_approve(SCAN_ID, note="reviewed", allow_high_risk=True)
    args, kwargs = mock_request.call_args
    assert args == ("POST", f"/admin/skills/{SCAN_ID}/approve")
    assert kwargs["json"] == {"note": "reviewed", "allow_high_risk": True}

    mock_request.return_value = _response(200, REJECTED_SCAN)
    client.admin_skill_reject(SCAN_ID, note="untrusted")
    args, kwargs = mock_request.call_args
    assert args == ("POST", f"/admin/skills/{SCAN_ID}/reject")
    assert kwargs["json"] == {"note": "untrusted"}


# ---------------------------------------------------------------------------
# Parser and completion
# ---------------------------------------------------------------------------


def test_admin_skills_parser_registration():
    parser = build_parser()

    listed = parser.parse_args(["admin", "skills", "list", "--status", "blocked", "--json"])
    assert listed.skills_command == "list"
    assert listed.status == "blocked"
    assert listed.json is True

    shown = parser.parse_args(["admin", "skills", "show", SCAN_ID])
    assert shown.skills_command == "show"
    assert shown.scan_id == SCAN_ID

    gated = parser.parse_args(["admin", "skills", "gate", DIGEST])
    assert gated.skills_command == "gate"
    assert gated.digest == DIGEST

    scanned = parser.parse_args(
        [
            "admin",
            "skills",
            "scan",
            "--name",
            "release-helper",
            "--version",
            "0.1.0",
            "--source",
            "url",
            "--report",
            "report.json",
        ]
    )
    assert scanned.skills_command == "scan"
    assert scanned.name == "release-helper"
    assert scanned.report == "report.json"

    approved = parser.parse_args(
        ["admin", "skills", "approve", SCAN_ID, "--note", "ok", "--allow-high-risk"]
    )
    assert approved.allow_high_risk is True
    assert approved.note == "ok"

    rejected = parser.parse_args(["admin", "skills", "reject", SCAN_ID, "--note", "no"])
    assert rejected.skills_command == "reject"
    assert rejected.note == "no"


def test_completion_scripts_include_admin_skills():
    bash = _bash_completion_script()
    zsh = _zsh_completion_script()
    fish = _fish_completion_script()

    for script in (bash, zsh, fish):
        assert "list show gate scan approve reject" in script
        assert "allow-high-risk" in script
    assert "status skills" in bash and "status skills" in zsh and "status skills" in fish
    assert "--report" in bash and "--report" in zsh and "--report" in fish


# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------


def test_admin_skills_list_table_fits_80_columns(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakeSkillsClient([SCAN])

    assert cmd_admin_skills_list(SimpleNamespace(json=False, status=None), client) == 0

    out = stream.getvalue()
    lines = out.splitlines()
    assert lines
    assert all(len(line) <= 80 for line in lines)
    assert SCAN_ID in out
    assert "NAME: release-helper" in out
    assert "STATUS: blocked" in out
    assert "SEVERITY: CRITICAL" in out
    assert "RISK: 100" in out
    assert f"DIGEST: {DIGEST[:12]}" in out
    assert "CREATED: 2026-11-10 08:00" in out
    assert "super-secret-token" not in out
    assert client.list_calls == [None]


def test_admin_skills_list_empty_state(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_skills_list(SimpleNamespace(json=False, status=None), FakeSkillsClient([])) == 0

    out = stream.getvalue()
    assert "No skill scans." in out
    assert len(out.splitlines()) == 1


def test_admin_skills_show_prints_bounded_findings_and_hints(monkeypatch):
    monkeypatch.setattr(cli, "_terminal_width", lambda default=80: 80)
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    client = FakeSkillsClient()

    assert cmd_admin_skills_show(
        SimpleNamespace(json=False, scan_id=SCAN_ID), client
    ) == 0

    out = stream.getvalue()
    lines = out.splitlines()
    assert all(len(line) <= 80 for line in lines)
    assert f"Skill scan: {SCAN_ID}" in out
    assert "Name:       release-helper" in out
    assert "Digest:     " + DIGEST in out
    assert "Status:     blocked" in out
    assert "Risk:       100" in out
    assert "Severity:   CRITICAL" in out
    assert "Recommendation: DO_NOT_INSTALL" in out
    assert "Findings:   6 (top 5)" in out
    assert "Data Exfiltration" in out
    assert "scripts/install.sh:12" in out
    assert "Coverage-only finding" not in out
    assert "... 1 more; use --json for the full report" in out
    assert f"darkmage admin skills approve {SCAN_ID}" in out
    assert "--allow-high-risk" in out
    assert f"darkmage admin skills reject {SCAN_ID}" in out
    assert "super-secret-token" not in out
    assert client.get_calls == [SCAN_ID]


def test_admin_skills_show_review_scan_omits_override_hint(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_skills_show(
        SimpleNamespace(json=False, scan_id=SCAN_ID),
        FakeSkillsClient(scan=REVIEW_SCAN),
    ) == 0

    out = stream.getvalue()
    assert f"darkmage admin skills approve {SCAN_ID}" in out
    assert f"darkmage admin skills approve {SCAN_ID} --allow-high-risk" not in out


def test_admin_skills_gate_table(monkeypatch):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cmd_admin_skills_gate(
        SimpleNamespace(json=False, digest=DIGEST), FakeSkillsClient()
    ) == 0

    out = stream.getvalue()
    assert f"Digest: {DIGEST}" in out
    assert "Status: approved" in out
    assert "Allowed: yes" in out


def test_admin_skills_scan_table(monkeypatch, tmp_path):
    stream = _TTYStringIO()
    monkeypatch.setattr(cli.sys, "stdout", stream)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"digest": DIGEST, "issues": []}), encoding="utf-8")
    client = FakeSkillsClient()

    assert cmd_admin_skills_scan(
        SimpleNamespace(
            json=False,
            name="release-helper",
            version="0.1.0",
            source="url",
            report=str(report_path),
            digest=None,
        ),
        client,
    ) == 0

    out = stream.getvalue()
    assert f"Skill scan: {SCAN_ID}" in out
    assert "Status:     blocked" in out
    assert "Risk:       100" in out
    assert "Severity:   CRITICAL" in out
    assert f"darkmage admin skills show {SCAN_ID}" in out
    assert f"darkmage admin skills approve {SCAN_ID}" in out
    assert "--allow-high-risk" in out
    assert client.scan_calls[0][3] == DIGEST


# ---------------------------------------------------------------------------
# JSON output, scan input and validation
# ---------------------------------------------------------------------------


def test_admin_skills_list_json(capsys):
    assert cmd_admin_skills_list(
        SimpleNamespace(json=True, status="blocked"), FakeSkillsClient([SCAN])
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == [SCAN]


def test_admin_skills_show_json(capsys):
    assert cmd_admin_skills_show(
        SimpleNamespace(json=True, scan_id=SCAN_ID), FakeSkillsClient()
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == SCAN


def test_admin_skills_gate_json(capsys):
    assert cmd_admin_skills_gate(
        SimpleNamespace(json=True, digest=DIGEST), FakeSkillsClient()
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"digest": DIGEST, "status": "approved", "allowed": True}


def test_admin_skills_scan_json_uses_digest_from_report(capsys, tmp_path):
    report_path = tmp_path / "report.json"
    report = {"digest": DIGEST, "risk_assessment": {"severity": "LOW"}, "issues": []}
    report_path.write_text(json.dumps(report), encoding="utf-8")
    client = FakeSkillsClient()

    assert cmd_admin_skills_scan(
        SimpleNamespace(
            json=True,
            name="release-helper",
            version="0.1.0",
            source="url",
            report=str(report_path),
            digest=None,
        ),
        client,
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == SCAN
    assert client.scan_calls == [("release-helper", "0.1.0", "url", DIGEST, report)]


def test_admin_skills_scan_hashes_report_when_no_digest(capsys, tmp_path):
    report_path = tmp_path / "report.json"
    raw = b'{"risk_assessment": {"severity": "LOW"}, "issues": []}'
    report_path.write_bytes(raw)
    client = FakeSkillsClient()

    assert cmd_admin_skills_scan(
        SimpleNamespace(
            json=True,
            name="release-helper",
            version="",
            source="",
            report=str(report_path),
            digest=None,
        ),
        client,
    ) == 0

    assert client.scan_calls[0][3] == hashlib.sha256(raw).hexdigest()


def test_admin_skills_scan_nested_payload_uses_nested_report(capsys, tmp_path):
    report_path = tmp_path / "report.json"
    payload = {
        "name": "release-helper",
        "version": "0.1.0",
        "digest": DIGEST,
        "report": {"risk_assessment": {"severity": "LOW"}, "issues": []},
    }
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    client = FakeSkillsClient()

    assert cmd_admin_skills_scan(
        SimpleNamespace(
            json=True,
            name="release-helper",
            version="0.1.0",
            source="",
            report=str(report_path),
            digest=None,
        ),
        client,
    ) == 0

    assert client.scan_calls[0][4] == payload["report"]


def test_admin_skills_scan_invalid_json_exits_2_without_api_call(tmp_path, capsys):
    report_path = tmp_path / "broken.json"
    report_path.write_text("{not json", encoding="utf-8")
    client = FakeSkillsClient()

    code = cmd_admin_skills_scan(
        SimpleNamespace(
            json=False,
            name="release-helper",
            version="",
            source="",
            report=str(report_path),
            digest=None,
        ),
        client,
    )

    assert code == 2
    assert "not valid JSON" in capsys.readouterr().err
    assert client.scan_calls == []


def test_admin_skills_scan_invalid_report_digest_exits_2(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"digest": "sha256:abc"}), encoding="utf-8")
    client = FakeSkillsClient()

    code = cmd_admin_skills_scan(
        SimpleNamespace(
            json=False,
            name="release-helper",
            version="",
            source="",
            report=str(report_path),
            digest=None,
        ),
        client,
    )

    assert code == 2
    assert "64 lowercase hex" in capsys.readouterr().err
    assert client.scan_calls == []


@pytest.mark.parametrize(
    "digest",
    ["", " " + "a" * 64, "A" * 64, "a" * 63, "sha256:" + "a" * 64, "g" * 64],
)
def test_admin_skills_gate_rejects_invalid_digest_locally(digest, capsys):
    client = FakeSkillsClient()

    code = cmd_admin_skills_gate(
        SimpleNamespace(json=False, digest=digest), client
    )

    assert code == 2
    assert "64 lowercase hex" in capsys.readouterr().err
    assert client.gate_calls == []


def test_admin_skills_scan_rejects_invalid_explicit_digest(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"issues": []}), encoding="utf-8")
    client = FakeSkillsClient()

    code = cmd_admin_skills_scan(
        SimpleNamespace(
            json=False,
            name="release-helper",
            version="",
            source="",
            report=str(report_path),
            digest="not-a-digest",
        ),
        client,
    )

    assert code == 2
    assert "64 lowercase hex" in capsys.readouterr().err
    assert client.scan_calls == []


# ---------------------------------------------------------------------------
# High-risk approval guard and mutations
# ---------------------------------------------------------------------------


def test_admin_skills_approve_blocked_requires_override(capsys):
    client = FakeSkillsClient()

    code = cmd_admin_skills_approve(
        SimpleNamespace(json=False, scan_id=SCAN_ID, note="", allow_high_risk=False),
        client,
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "--allow-high-risk" in err
    assert "blocked" in err
    assert client.get_calls == [SCAN_ID]
    assert client.approve_calls == []


def test_admin_skills_approve_blocked_with_override(capsys):
    client = FakeSkillsClient()

    assert cmd_admin_skills_approve(
        SimpleNamespace(
            json=True,
            scan_id=SCAN_ID,
            note="reviewed",
            allow_high_risk=True,
        ),
        client,
    ) == 0

    assert client.approve_calls == [(SCAN_ID, "reviewed", True)]
    assert json.loads(capsys.readouterr().out) == APPROVED_SCAN


def test_admin_skills_approve_review_scan_without_override(capsys):
    client = FakeSkillsClient(scan=REVIEW_SCAN, approved=APPROVED_SCAN)

    assert cmd_admin_skills_approve(
        SimpleNamespace(json=True, scan_id=SCAN_ID, note="", allow_high_risk=False),
        client,
    ) == 0

    assert client.approve_calls == [(SCAN_ID, "", False)]


def test_admin_skills_reject(capsys):
    client = FakeSkillsClient()

    assert cmd_admin_skills_reject(
        SimpleNamespace(json=True, scan_id=SCAN_ID, note="untrusted publisher"),
        client,
    ) == 0

    assert client.reject_calls == [(SCAN_ID, "untrusted publisher")]
    assert json.loads(capsys.readouterr().out) == REJECTED_SCAN


# ---------------------------------------------------------------------------
# 404 / 409 / 422 rendering and token hygiene
# ---------------------------------------------------------------------------


def _raise(method_name, message, status_code):
    def fail(self, *args, **kwargs):
        raise DarkmageError(message, status_code=status_code)

    return patch.object(DarkmageClient, method_name, fail)


def test_admin_skills_show_404_is_admin_only_error(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise("admin_skill_get", "404 Not Found for GET /admin/skills/missing: Not found", 404):
        assert main(["--json", "admin", "skills", "show", "missing"]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 404
    assert payload["error"]["code"] == "admin_only_or_not_found"
    assert "admin only" in payload["error"]["message"].lower()
    assert "not found" in payload["error"]["message"].lower()
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_admin_skills_list_404_plain_error(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise("admin_skill_list", "404 Not Found for GET /admin/skills: Not found", 404):
        assert main(["admin", "skills", "list"]) == 2

    captured = capsys.readouterr()
    assert "admin only" in captured.err.lower()
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_admin_skills_gate_404_mentions_unscanned_digest(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    with _raise(
        "admin_skill_gate",
        "404 Not Found for GET /admin/skills/gate: Skill digest has not been scanned",
        404,
    ):
        assert main(["--json", "admin", "skills", "gate", DIGEST]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "has not been scanned" in payload["error"]["message"]
    assert "super-secret-token" not in captured.out + captured.err


def test_admin_skills_approve_409_is_clear_and_token_free(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "admin_skill_get", lambda self, scan_id: REVIEW_SCAN)
    with _raise(
        "admin_skill_approve",
        "409 Conflict for POST /admin/skills/x/approve: "
        "High-confidence findings block this skill; set allow_high_risk to override",
        409,
    ):
        assert main(["--json", "admin", "skills", "approve", SCAN_ID]) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 409
    assert "High-confidence findings" in payload["error"]["message"]
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_admin_skills_scan_422_is_clear_and_token_free(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"digest": DIGEST, "issues": []}), encoding="utf-8")
    with _raise(
        "admin_skill_scan",
        "422 Unprocessable Entity for POST /admin/skills/scan: name too long",
        422,
    ):
        assert main(
            [
                "--json",
                "admin",
                "skills",
                "scan",
                "--name",
                "release-helper",
                "--report",
                str(report_path),
            ]
        ) == 2

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["status_code"] == 422
    assert "name too long" in payload["error"]["message"]
    assert "super-secret-token" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_admin_skills_json_never_prints_the_client_token(monkeypatch, capsys):
    monkeypatch.setenv("DARKMAGE_TOKEN", "super-secret-token")
    monkeypatch.setattr(DarkmageClient, "admin_skill_list", lambda self, status=None: [SCAN])

    assert main(["--json", "admin", "skills", "list"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == [SCAN]
    assert "super-secret-token" not in captured.out + captured.err
