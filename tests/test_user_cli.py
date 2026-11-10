"""
Пользовательские тесты Darkmage CLI (без реального API сервера).
Проверяют:
1. Корректность работы всех команд CLI
2. Корректность аргументов и флагов
3. Конфигурационные операции (set/get/export/import)
4. История команд
5. SSE парсинг и форматирование
6. Цветной вывод
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from darkmage_cli.cli import _color_status, _format_event
from darkmage_cli.client import DarkmageClient

CLI = [sys.executable, "-m", "darkmage_cli.cli"]
FAILURES = 0
SUCCESSES = 0
# Isolate every subprocess from the real ~/.darkmage-cli.
TEST_HOME = tempfile.mkdtemp(prefix="darkmage-cli-test-home-")


def run_cmd(args, expected_code=0, env=None):
    """Run CLI command and return (returncode, stdout, stderr)."""
    run_env = dict(os.environ)
    run_env["HOME"] = TEST_HOME
    run_env.pop("DARKMAGE_TOKEN", None)
    run_env.pop("DARKMAGE_RUNNER_TOKEN", None)
    if env:
        run_env.update(env)
    result = subprocess.run(
        CLI + args,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env=run_env,
    )
    return result.returncode, result.stdout, result.stderr


def check(name, condition, detail=""):
    global SUCCESSES, FAILURES
    if condition:
        SUCCESSES += 1
        print(f"  ✅ {name}")
    else:
        FAILURES += 1
        raise AssertionError(f"{name}: {detail}")


def test_help():
    """Test that all subcommands show help."""
    print("\n📋 Тест 1: Help для всех команд")
    commands = [
        ["auth"], ["me"], ["usage"], ["memory"],
        ["workspace"], ["files"], ["session"],
        ["run"], ["process"], ["payment"],
        ["admin"], ["term"], ["tui"], ["config"],
        ["git"], ["mcp"], ["chat"], ["health"],
        ["ready"], ["doctor"], ["completion"], ["history"], ["parallel"],
    ]
    for cmd in commands:
        rc, _out, _err = run_cmd(cmd + ["--help"])
        check(f"{' '.join(cmd)} --help", rc == 0, f"rc={rc}")


def test_config():
    """Test config commands."""
    print("\n⚙️ Тест 2: Конфигурация (config)")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set config
        rc, _out, err = run_cmd(["config", "set", "--url", "http://test:8000", "--token", "test123"])
        check("config set", rc == 0, f"rc={rc}, err={err}")

        # Show config
        rc, out, err = run_cmd(["config", "show"])
        check("config show", rc == 0, f"rc={rc}")
        check("config show contains url", "http://test:8000" in out)
        check("config show masks token", "test123" not in out and "***" in out)

        # Show JSON
        rc, out, err = run_cmd(["config", "show", "--json"])
        check("config show --json", rc == 0, f"rc={rc}")
        shown = json.loads(out)
        check("config show --json redacts token", "test123" not in out)

        # Export
        export_file = os.path.join(tmpdir, "config.json")
        rc, out, err = run_cmd(["config", "export", export_file])
        check("config export", rc == 0, f"rc={rc}, err={err}")
        check("config export file exists", os.path.exists(export_file))
        exported_text = Path(export_file).read_text(encoding="utf-8")
        check("config export has no plaintext token", "test123" not in exported_text)
        check(
            "config export is 0600",
            (os.stat(export_file).st_mode & 0o777) == 0o600,
            oct(os.stat(export_file).st_mode),
        )

        # Modify config
        run_cmd(["config", "set", "--url", "http://changed:9000"])
        rc, out, err = run_cmd(["config", "import", export_file])
        check("config import", rc == 0, f"rc={rc}, err={err}")
        rc, out, err = run_cmd(["config", "show", "--json"])
        data = json.loads(out)
        check("config import restored url", data.get("base_url") == "http://test:8000")
        # A redacted import must not replace the live token with a placeholder.
        encrypted = json.loads(
            (Path(TEST_HOME) / ".darkmage-cli" / "config.json").read_text(encoding="utf-8")
        )
        check(
            "config import kept live token",
            shown.get("token") != "test123"
            and encrypted.get("token", "").startswith("gAAAA"),
            f"encrypted={encrypted.get('token', '')[:12]}",
        )


def test_doctor():
    """Test doctor command."""
    print("\n🩺 Тест 3: Doctor")
    rc, out, _err = run_cmd(["doctor", "--url", "http://localhost:1"])
    check("doctor fails non-zero on unreachable API", rc == 1, f"rc={rc}")
    check("doctor shows API URL", "API URL" in out)
    check("doctor shows health", "health" in out.lower())
    check("doctor shows ready", "ready" in out.lower())


def test_completion():
    """Test completion command."""
    print("\n🔧 Тест 4: Completion")
    for shell in ["bash", "zsh", "fish"]:
        rc, out, err = run_cmd(["completion", shell])
        check(f"completion {shell}", rc == 0, f"rc={rc}, err={err}")
        check(f"completion {shell} has content", len(out) > 0)


def test_run_events_parsing():
    """Test run events parsing logic."""
    print("\n📡 Тест 5: Парсинг SSE событий")
    from darkmage_cli.client import DarkmageClient

    DarkmageClient(base_url="http://localhost:8000", token="test")

    # Test _format_event
    event = {"id": "1", "event": "assistant.delta", "data": {"text": "Hello"}}
    line = _format_event(event)
    check("_format_event assistant.delta", "assistant.delta" in line)
    check("_format_event contains text", "Hello" in line)

    event = {"id": "2", "event": "run.completed", "data": {"finish_reason": "stop"}}
    line = _format_event(event)
    check("_format_event run.completed", "run.completed" in line)
    check("_format_event contains finish_reason", "stop" in line)

    # Test _color_status
    statuses = {
        "queued": "\033[1;33m",
        "running": "\033[1;36m",
        "completed": "\033[1;32m",
        "failed": "\033[1;31m",
        "cancelled": "\033[1;31m",
    }
    for status, color in statuses.items():
        with patch.object(sys.stdout, "isatty", return_value=True):
            colored = _color_status(status)
        check(f"_color_status {status}", color in colored)


def test_client_methods():
    """Test client method signatures."""
    print("\n🔧 Тест 6: Клиентские методы")

    client = DarkmageClient(base_url="http://localhost:8000", token="test")

    # Check all methods exist
    methods = [
        "register", "login", "logout",
        "me", "usage", "memory_get", "memory_put",
        "workspace_create", "workspace_list", "workspace_get",
        "workspace_update", "workspace_start", "workspace_stop", "workspace_delete",
        "workspace_blender", "workspace_export_godot", "workspace_godot_tests",
        "workspace_tiled_import", "workspace_ldtk_import",
        "workspace_files", "workspace_file_content", "workspace_file_edit",
        "workspace_file_download", "workspace_file_upload",
        "workspace_file_put", "workspace_file_delete",
        "workspace_search",
        "session_create", "session_list",
        "run_create", "run_get", "run_queue", "run_message", "run_answer", "run_context",
        "run_revert", "run_review", "run_stop", "run_events", "run_list",
        "tool_call_approve", "tool_call_reject",
        "process_start", "process_output", "process_stop",
        "payment_create", "payment_list",
        "admin_status",
        "pty_create", "pty_stop",
        "git_clone", "git_commit", "git_push", "git_pr_create",
        "mcp_list", "mpc_call",
        "chat_completion",
        "health", "ready",
    ]
    for method in methods:
        check(f"client.{method} exists", hasattr(client, method), f"Missing {method}")


def test_exit_codes():
    """Test exit codes for various scenarios."""
    print("\n🚪 Тест 7: Exit codes")
    # Use a fresh HOME: TEST_HOME already has a token from test_config, which
    # would send the no-args path into cmd_start instead of auth.
    with tempfile.TemporaryDirectory() as fresh_home:
        rc, _out, _err = run_cmd([], env={"HOME": fresh_home})
    check("no args exits non-zero in a fresh home", rc != 0, f"rc={rc}")

    rc, _out, _err = run_cmd(["auth"])
    check("auth without subcommand exits non-zero", rc != 0, f"rc={rc}")

    rc, _out, _err = run_cmd(["--help"])
    check("--help exits 0", rc == 0, f"rc={rc}")


def test_sync_module():
    """Test sync module functions."""
    print("\n🔄 Тест 8: Синхронизация файлов")

    from darkmage_cli.sync import (
        load_ignore_patterns,
        should_ignore,
        sha256_of_file,
        walk_local_files,
        DEFAULT_IGNORE_PATTERNS,
    )

    # Ignore patterns
    check("DEFAULT_IGNORE_PATTERNS non-empty", len(DEFAULT_IGNORE_PATTERNS) > 0)
    check(".git ignored", should_ignore(".git", DEFAULT_IGNORE_PATTERNS))
    check("__pycache__ ignored", should_ignore("__pycache__", DEFAULT_IGNORE_PATTERNS))
    check("node_modules ignored", should_ignore("node_modules", DEFAULT_IGNORE_PATTERNS))
    check("main.py not ignored", not should_ignore("main.py", DEFAULT_IGNORE_PATTERNS))
    check("src/main.gd not ignored", not should_ignore("src/main.gd", DEFAULT_IGNORE_PATTERNS))

    # SHA-256
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        tmp_path = f.name
    try:
        checksum = sha256_of_file(Path(tmp_path))
        check("SHA-256 is 64 hex chars", len(checksum) == 64 and all(c in "0123456789abcdef" for c in checksum))
    finally:
        os.unlink(tmp_path)

    # Walk local files
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        (td / "a.txt").write_text("aaa")
        (td / "b.py").write_text("bbb")
        (td / "sub").mkdir()
        (td / "sub" / "c.txt").write_text("ccc")
        (td / ".git").mkdir()
        (td / ".git" / "config").write_text("git config")
        (td / "__pycache__").mkdir()
        (td / "__pycache__" / "a.pyc").write_text("pyc")

        files = walk_local_files(td, DEFAULT_IGNORE_PATTERNS)
        rel_paths = {rel for _, rel in files}
        check("a.txt found", "a.txt" in rel_paths)
        check("b.py found", "b.py" in rel_paths)
        check("sub/c.txt found", "sub/c.txt" in rel_paths)
        check(".git/config ignored", ".git/config" not in rel_paths)
        check("__pycache__/a.pyc ignored", "__pycache__/a.pyc" not in rel_paths)

    # SyncState dataclass
    from darkmage_cli.sync import SyncState, FileEntry
    state = SyncState()
    check("SyncState empty", len(state.local_files) == 0 and len(state.workspace_files) == 0)
    fe = FileEntry(path="test.txt", size_bytes=10, checksum="abc123")
    check("FileEntry fields", fe.path == "test.txt" and fe.size_bytes == 10 and fe.checksum == "abc123")


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 Пользовательские тесты Darkmage CLI")
    print("=" * 60)

    test_help()
    test_config()
    test_doctor()
    test_completion()
    test_run_events_parsing()
    test_client_methods()
    test_sync_module()
    test_exit_codes()

    print("\n" + "=" * 60)
    print(f"Результаты: {SUCCESSES} прошло, {FAILURES} не прошло")
    print("=" * 60)
    sys.exit(0 if FAILURES == 0 else 1)