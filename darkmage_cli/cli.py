from __future__ import annotations

import argparse
import getpass
import io
import json
import os
import re
import shlex
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from .client import DarkmageClient, DarkmageError, print_error, print_json
from .config import get_token, load_config, save_config
from .events import (
    approval_card,
    approval_summary,
    format_diff,
    question_card,
    question_items,
    question_text,
)
from .security import (
    is_redacted_value,
    is_secret_key,
    mask_token,
    redact_config,
    strip_redacted,
    warn_insecure_url,
    write_private_json,
    write_private_text,
)
from . import sync as sync_mod


def cmd_register(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.register(args.email, args.password, args.full_name)
    print_json(data)


def cmd_login(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Войти в систему. Можно передать email и пароль аргументами,
    или ввести интерактивно (как в Claude Code)."""
    from .config import set_token

    email = args.email
    password = args.password

    if not email:
        email = input("Email: ").strip()
    if not email:
        print("Ошибка: email не может быть пустым.")
        return

    if not password:
        password = getpass.getpass("Пароль: ")
    if not password:
        print("Ошибка: пароль не может быть пустым.")
        return

    data = client.login(email, password)
    token = data.get("access_token")
    if token:
        set_token(token)
        client.token = token
        print(f"✅ Вход выполнен как {email}")
    else:
        print_json(data)


def cmd_logout(args: argparse.Namespace, client: DarkmageClient) -> None:
    client.logout()
    print("Logged out.")


def cmd_auth_interactive(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Интерактивный вход/регистрация как в Claude Code."""

    print("👋 Добро пожаловать в Darkmage AI")
    print()

    # Проверяем, уже есть ли токен
    config = load_config()
    if config.get("token") and config.get("base_url"):
        print(f"Вы уже вошли как токен: {mask_token(config['token'])}")
        print("Используйте 'darkmage auth logout' для выхода.")
        return

    email = input("Email: ").strip()
    if not email:
        print("Ошибка: email не может быть пустым.")
        return

    password = getpass.getpass("Пароль: ")
    if not password:
        print("Ошибка: пароль не может быть пустым.")
        return

    full_name = input("Полное имя (опционально): ").strip() or None

    try:
        # Пробуем войти
        data = client.login(email, password)
        token = data.get("access_token")
        if token:
            from .config import set_token
            set_token(token)
            client.token = token
            print(f"\n✅ Вход выполнен как {email}")
            return
    except DarkmageError as exc:
        if "already exists" in str(exc).lower() or "not found" in str(exc).lower():
            pass  # Регистрируемся ниже
        else:
            print(f"Ошибка входа: {exc}")
            return

    # Регистрируемся
    print("Аккаунт не найден. Регистрация нового аккаунта...")
    try:
        data = client.register(email, password, full_name)
        token = data.get("access_token")
        if token:
            from .config import set_token
            set_token(token)
            client.token = token
            print(f"\n✅ Аккаунт создан и вход выполнен как {email}")
        else:
            print(f"Не удалось зарегистрироваться: {data}")
    except DarkmageError as exc:
        print(f"Ошибка регистрации: {exc}")
        return

    # Предлагаем открыть рабочую зону
    print()
    print("🎉 Готово! Теперь вы можете:")
    print("  darkmage workspace list   — посмотреть рабочие зоны")
    print("  darkmage tui <workspace_id> — открыть интерактивный терминал")


def cmd_login_alias(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Alias для auth interactive."""
    cmd_auth_interactive(args, client)


def cmd_start(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Запуск интерактивного сеанса как в Claude Code."""
    from .config import load_config

    config = load_config()
    token = config.get("token")
    base_url = config.get("base_url")

    if not token:
        print("🔐 Токен не найден. Нужно войти в систему.")
        cmd_auth_interactive(args, client)
        config = load_config()
        token = config.get("token")
        if not token:
            print("Не удалось войти. Попробуйте позже.")
            return

    # Обновляем клиент с токеном
    client.token = token
    client.base_url = base_url or client.base_url

    # Показываем рабочие зоны (на каждого пользователя одна)
    print("\n📋 Ваша рабочая зона:")
    try:
        workspaces = client.workspace_list()
        if not workspaces:
            print("   Рабочих зон нет. Создайте сессию: darkmage session new")
            return
        for i, ws in enumerate(workspaces, 1):
            status = _color_status(ws.get("status", ""))
            print(f"  {i}. {ws.get('name')} ({ws.get('id')}) [{status}]")
    except DarkmageError as exc:
        print(f"Ошибка получения рабочих зон: {exc}")
        return

    if len(workspaces) == 1:
        # Одна зона на пользователя: выбирать нечего.
        idx = 0
    else:
        choice = input("\nВыберите рабочую зону (номер) или нажмите Enter для отмены: ").strip()
        if not choice:
            print("Отменено.")
            return
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(workspaces):
                print("Неверный номер.")
                return
        except ValueError:
            print("Неверный номер.")
            return
    workspace_id = workspaces[idx]["id"]

    # Запуск TUI
    print(f"\n🚀 Запуск рабочей зоны {workspaces[idx]['name']}...")
    from .tui import run_tui

    run_tui(
        base_url=client.base_url,
        token=client.token,
        workspace_id=workspace_id,
    )


def cmd_me(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.me())


def cmd_usage(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.usage())


def cmd_memory_get(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.memory_get())


def cmd_memory_put(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.memory_put(args.content))


# ---------------------------------------------------------------------------
# Responsive table rendering
# ---------------------------------------------------------------------------

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
TABLE_GAP = 2


def _terminal_width(default: int = 80) -> int:
    """Return the usable terminal width, capped to a readable range."""
    columns = os.environ.get("COLUMNS")
    if columns:
        try:
            return max(20, min(160, int(columns)))
        except ValueError:
            pass
    try:
        size = shutil.get_terminal_size((default, 24))
    except OSError:  # pragma: no cover - unusual terminals
        return default
    return max(20, min(160, size.columns))


def _visible_len(text: str) -> int:
    return len(_ANSI_ESCAPE_RE.sub("", text))


def _truncate_cell(text: str, width: int) -> str:
    """Truncate a cell to *width* visible characters (ellipsis-free below 2)."""
    text = str(text)
    if _visible_len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def _format_table(
    headers: list[str],
    rows: list[list[Any]],
    *,
    width: int | None = None,
    min_widths: list[int] | None = None,
    drop_order: list[int] | None = None,
    compact_below: int = 44,
) -> list[str]:
    """Render a table that never exceeds *width* columns.

    Low-priority columns (``drop_order``) are removed first, then the remaining
    columns shrink down to ``min_widths``. Very narrow terminals switch to a
    per-record two-line layout instead of unreadable one-character columns.
    """
    available = max(20, width if width is not None else _terminal_width())
    columns_count = len(headers)
    string_rows = [
        [str(value) for value in row[:columns_count]]
        + [""] * max(0, columns_count - len(row))
        for row in rows
    ]
    default_mins = [max(2, len(header)) for header in headers]
    mins = list(min_widths or default_mins)
    mins = (mins + default_mins[len(mins):])[:columns_count]
    mins = [max(1, value) for value in mins]
    natural = [
        max(len(headers[index]), *(len(row[index]) for row in string_rows))
        if string_rows
        else len(headers[index])
        for index in range(columns_count)
    ]
    floors = [min(mins[index], natural[index]) for index in range(columns_count)]
    if floors:
        # The first column is an identifier (workspace/session/run). Never
        # truncate it while it still fits on its own line.
        floors[0] = min(natural[0], available)

    def compact_lines() -> list[str]:
        # Record-oriented layout keeps every field readable instead of
        # collapsing columns to one character each.
        lines: list[str] = []
        for row in string_rows:
            lines.append(_truncate_cell(row[0], available))
            for index in range(1, columns_count):
                prefix = f"  {_truncate_cell(headers[index], max(1, available // 3))}: "
                lines.append(
                    prefix
                    + _truncate_cell(row[index], max(1, available - len(prefix)))
                )
        return lines

    if available < compact_below and columns_count > 1 and string_rows:
        return compact_lines()

    kept = list(range(columns_count))
    droppable = list(drop_order or [])

    def minimum_total() -> int:
        return sum(floors[index] for index in kept) + TABLE_GAP * (len(kept) - 1)

    while len(kept) > 1 and minimum_total() > available and droppable:
        candidate = droppable.pop(0)
        if candidate in kept:
            kept.remove(candidate)

    if minimum_total() > available and string_rows:
        return compact_lines()

    widths = {index: min(natural[index], available) for index in kept}
    while sum(widths.values()) + TABLE_GAP * (len(kept) - 1) > available:
        shrinkable = [index for index in kept if widths[index] > floors[index]]
        if not shrinkable:
            break
        widest = max(shrinkable, key=lambda index: widths[index] - floors[index])
        widths[widest] -= 1

    if sum(widths.values()) + TABLE_GAP * (len(kept) - 1) > available:
        return compact_lines()

    def render(row: list[str]) -> str:
        return "  ".join(
            _truncate_cell(row[index], widths[index]).ljust(widths[index])
            for index in kept
        ).rstrip()

    header_line = render([str(header) for header in headers])
    separator = "-" * min(available, _visible_len(header_line))
    lines = [header_line, separator]
    lines.extend(render(row) for row in string_rows)
    return lines


def _print_table(
    headers: list[str],
    rows: list[list[Any]],
    *,
    width: int | None = None,
    min_widths: list[int] | None = None,
    drop_order: list[int] | None = None,
) -> None:
    for line in _format_table(
        headers,
        rows,
        width=width,
        min_widths=min_widths,
        drop_order=drop_order,
    ):
        print(line)


def cmd_ws_create(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.workspace_create(args.name))


def cmd_ws_list(args: argparse.Namespace, client: DarkmageClient) -> None:
    workspaces = client.workspace_list(args.limit)
    if args.json or not sys.stdout.isatty():
        print_json(workspaces)
        return
    _print_table(
        ["ID", "Имя", "Статус", "Режим"],
        [
            [
                w.get("id", ""),
                w.get("name", ""),
                w.get("status", ""),
                w.get("approval_mode", ""),
            ]
            for w in workspaces
        ],
        min_widths=[36, 12, 9, 6],
        drop_order=[3, 2],
    )
    if not workspaces:
        print("Нет рабочих зон.")


def cmd_ws_get(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.workspace_get(args.workspace_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
        return
    print(f"ID:        {data.get('id')}")
    print(f"Имя:       {data.get('name')}")
    print(f"Статус:    {_color_status(data.get('status', ''))}")
    print(f"Режим:     {data.get('approval_mode', '')}")
    print(f"Создан:    {data.get('created_at', '')}")
    print(f"Обновлён:  {data.get('updated_at', '')}")


def cmd_ws_update(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(
        client.workspace_update(args.workspace_id, args.name, args.approval_mode)
    )


def cmd_ws_start(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.workspace_start(args.workspace_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
        return
    print(f"Рабочая зона запущена: {data.get('id')}")
    print(f"Статус: {_color_status(data.get('status', ''))}")


def cmd_ws_stop(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.workspace_stop(args.workspace_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
        return
    print(f"Рабочая зона остановлена: {data.get('id')}")
    print(f"Статус: {_color_status(data.get('status', ''))}")


def _confirm_destructive(
    action: str, assume_yes: bool, *, input_fn: Callable[[str], str] | None = None
) -> bool:
    """Ask before a destructive operation, or require an explicit --yes.

    In a non-interactive session (CI, piped stdin) the safe default is to
    refuse and tell the caller to pass --yes.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            f"{action}: confirmation required in non-interactive mode; re-run with --yes",
            file=sys.stderr,
        )
        return False
    reader = input_fn or input
    try:
        answer = reader(f"{action}? [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def cmd_ws_delete(args: argparse.Namespace, client: DarkmageClient) -> int:
    action = f"Delete workspace {args.workspace_id} (this cannot be undone)"
    if not _confirm_destructive(action, getattr(args, "yes", False)):
        print("Cancelled.")
        return 1
    client.workspace_delete(args.workspace_id)
    print(f"Workspace {args.workspace_id} deleted.")
    return 0


def cmd_ws_files(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.workspace_files(args.workspace_id, args.path))


def cmd_ws_read(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.workspace_file_content(
        args.workspace_id, args.path, args.offset, args.limit
    )
    print(data.get("content", ""))


def cmd_ws_edit(args: argparse.Namespace, client: DarkmageClient) -> None:
    content = args.content
    if content == "-":
        content = sys.stdin.read()
    print_json(
        client.workspace_file_edit(
            args.workspace_id,
            args.path,
            content,
            args.base_content,
            args.session_id,
        )
    )


def cmd_ws_search(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.workspace_search(args.workspace_id, args.query, args.path))


def cmd_ws_download(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Download file from workspace to local filesystem."""
    result = client.workspace_file_download(
        args.workspace_id, args.remote_path, args.local_path
    )
    if args.json:
        print_json(result)
        return
    print(
        f"Downloaded: {result['remote_path']} → {result['local_path']} "
        f"({result.get('size_bytes', 0)} bytes)"
    )


def cmd_ws_upload(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Upload local file to workspace."""
    result = client.workspace_file_upload(
        args.local_path, args.workspace_id, args.remote_path
    )
    if args.json:
        print_json(result)
        return
    print(
        f"Uploaded: {args.local_path} → {result.get('remote_path', args.remote_path)} "
        f"({result.get('size_bytes', 0)} bytes)"
    )


def cmd_ws_tree(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Show directory tree for workspace."""
    if args.json:
        result = _tree_to_dict(client, args.workspace_id, args.path, 0, args.depth)
        print_json(result)
        return
    print(f"{args.workspace_id}/{args.path}")
    _print_tree(client, args.workspace_id, args.path, "", 0, args.depth)


# ---------------------------------------------------------------------------
# Simplified bidirectional file operations (cp / mv / rm / export / status)
# ---------------------------------------------------------------------------

def cmd_files_cp(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Copy a file between local filesystem and workspace.

    darkmage files cp local.txt ws:/remote/path.txt   (local -> workspace)
    darkmage files cp ws:/remote/path.txt local.txt   (workspace -> local)
    """
    src = args.source
    dst = args.destination

    if src.startswith("ws:") and not dst.startswith("ws:"):
        # workspace -> local
        remote_path = src[3:]
        local_path = dst
        result = client.workspace_file_download(args.workspace_id, remote_path, local_path)
        print(
            f"✅ Copied ws://{remote_path} → {local_path} "
            f"({result.get('size_bytes', 0)} bytes)"
        )
    elif not src.startswith("ws:") and dst.startswith("ws:"):
        # local -> workspace
        local_path = src
        remote_path = dst[3:]
        try:
            content = Path(local_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print_error(f"Cannot read {local_path}: {exc}")
        result = client.workspace_file_put(args.workspace_id, remote_path, content)
        print(
            f"✅ Copied {local_path} → ws://{remote_path} "
            f"({result.get('size_bytes', 0)} bytes)"
        )
    else:
        print_error("Specify exactly one side as ws:/path (e.g. ws:/src/main.gd)")


def cmd_files_mv(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Move a file between local filesystem and workspace (copy + delete source)."""
    src = args.source
    dst = args.destination

    if src.startswith("ws:") and not dst.startswith("ws:"):
        remote_path = src[3:]
        local_path = dst
        result = client.workspace_file_download(args.workspace_id, remote_path, local_path)
        client.workspace_file_delete(args.workspace_id, remote_path)
        print(
            f"✅ Moved ws://{remote_path} → {local_path} "
            f"({result.get('size_bytes', 0)} bytes)"
        )
    elif not src.startswith("ws:") and dst.startswith("ws:"):
        local_path = src
        remote_path = dst[3:]
        try:
            content = Path(local_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print_error(f"Cannot read {local_path}: {exc}")
        client.workspace_file_put(args.workspace_id, remote_path, content)
        Path(local_path).unlink()
        print(f"✅ Moved {local_path} → ws://{remote_path}")
    else:
        print_error("Specify exactly one side as ws:/path")


def cmd_files_rm(args: argparse.Namespace, client: DarkmageClient) -> int:
    """Remove a file from workspace or local filesystem."""
    target = args.path
    if not _confirm_destructive(
        f"Delete {target}", getattr(args, "yes", False)
    ):
        print("Cancelled.")
        return 1
    if target.startswith("ws:"):
        remote_path = target[3:]
        client.workspace_file_delete(args.workspace_id, remote_path)
        print(f"✅ Deleted ws://{remote_path}")
    else:
        p = Path(target)
        if p.exists():
            p.unlink()
            print(f"✅ Deleted {target}")
        else:
            print_error(f"File not found: {target}")
    return 0


def cmd_files_export(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Download the entire workspace as a ZIP archive."""
    out = args.output or f"darkmage-{args.workspace_id[:8]}.zip"
    # The endpoint streams the ZIP; save it locally.
    resp = client._request("GET", f"/workspaces/{args.workspace_id}/export.zip")
    client._raise_for_status(resp)
    try:
        with open(out, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=65536):
                f.write(chunk)
        size = os.path.getsize(out)
        print(f"✅ Exported workspace to {out} ({size} bytes)")
    except OSError as exc:
        print_error(f"Cannot write {out}: {exc}")


def cmd_files_status(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Show sync status between local directory and workspace."""
    local_dir = Path(args.path or ".").resolve()
    patterns = sync_mod.load_ignore_patterns(local_dir)
    state = sync_mod.compute_sync_state(local_dir, client, args.workspace_id, patterns)

    print(f"📁 Local:  {local_dir}")
    print(f"📦 Workspace: {args.workspace_id}")
    print(f"   Identical:  {len(state.identical)}")
    print(f"   Only local: {len(state.only_local)} (to upload)")
    print(f"   Only ws:    {len(state.only_workspace)} (to download)")
    print(f"   Conflicts:  {len(state.conflicts)}")
    print()

    if state.only_local:
        print("📤 To upload (local only):")
        for rel in state.only_local[:20]:
            print(f"   + {rel}")
        if len(state.only_local) > 20:
            print(f"   ... and {len(state.only_local) - 20} more")
        print()

    if state.only_workspace:
        print("📥 To download (workspace only):")
        for rel in state.only_workspace[:20]:
            print(f"   - {rel}")
        if len(state.only_workspace) > 20:
            print(f"   ... and {len(state.only_workspace) - 20} more")
        print()

    if state.conflicts:
        print("⚠️  Conflicts (different on both sides):")
        for rel in state.conflicts[:20]:
            print(f"   ? {rel}")
        if len(state.conflicts) > 20:
            print(f"   ... and {len(state.conflicts) - 20} more")
        print()


def cmd_files_sync_pull(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Pull files from workspace to local directory."""
    local_dir = Path(args.path or ".").resolve()
    patterns = sync_mod.load_ignore_patterns(local_dir)
    result = sync_mod.sync_pull(
        client, args.workspace_id, local_dir, patterns,
        auto_resolve=args.auto_resolve,
    )
    print()
    print(f"✅ Pull complete: {result['downloaded']} downloaded, "
          f"{result['skipped']} skipped, {len(result['errors'])} errors")
    if result["conflicts"]:
        print(f"   ⚠️  {len(result['conflicts'])} conflicts unresolved")
    if result["errors"]:
        print("   Errors:")
        for e in result["errors"][:10]:
            print(f"     - {e}")


def cmd_files_sync_push(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Push files from local directory to workspace."""
    local_dir = Path(args.path or ".").resolve()
    patterns = sync_mod.load_ignore_patterns(local_dir)
    result = sync_mod.sync_push(
        client, args.workspace_id, local_dir, patterns,
        auto_resolve=args.auto_resolve,
    )
    print()
    print(f"✅ Push complete: {result['uploaded']} uploaded, "
          f"{result['skipped']} skipped, {len(result['errors'])} errors")
    if result["conflicts"]:
        print(f"   ⚠️  {len(result['conflicts'])} conflicts unresolved")
    if result["errors"]:
        print("   Errors:")
        for e in result["errors"][:10]:
            print(f"     - {e}")


def cmd_files_sync_diff(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Show differences between local directory and workspace."""
    local_dir = Path(args.path or ".").resolve()
    patterns = sync_mod.load_ignore_patterns(local_dir)
    diff = sync_mod.sync_diff(client, args.workspace_id, local_dir, patterns)

    print(f"📁 Local:  {local_dir}")
    print(f"📦 Workspace: {args.workspace_id}")
    print()

    if diff["identical"]:
        print(f"✅ Identical: {len(diff['identical'])} files")
    if diff["only_local"]:
        print(f"📤 Only local ({len(diff['only_local'])}):")
        for rel in diff["only_local"][:30]:
            print(f"   + {rel}")
    if diff["only_workspace"]:
        print(f"📥 Only workspace ({len(diff['only_workspace'])}):")
        for rel in diff["only_workspace"][:30]:
            print(f"   - {rel}")
    if diff["conflicts"]:
        print(f"⚠️  Conflicts ({len(diff['conflicts'])}):")
        for rel in diff["conflicts"][:30]:
            print(f"   ? {rel}")


def cmd_files_sync_watch(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Watch local directory and push changes to workspace automatically."""
    local_dir = Path(args.path or ".").resolve()
    patterns = sync_mod.load_ignore_patterns(local_dir)
    sync_mod.sync_watch(
        client, args.workspace_id, local_dir, patterns,
        interval=args.interval,
    )


def cmd_files_sync_resolve(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Resolve a conflict by choosing local or workspace version."""
    rel_path = args.path
    if args.wins == "local":
        local_dir = Path(args.local_path or ".").resolve()
        try:
            content = (local_dir / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print_error(f"Cannot read local {rel_path}: {exc}")
        client.workspace_file_put(args.workspace_id, rel_path, content)
        print(f"✅ Resolved {rel_path}: local → workspace")
    elif args.wins == "workspace":
        local_dir = Path(args.local_path or ".").resolve()
        local_dir.mkdir(parents=True, exist_ok=True)
        data = client.workspace_file_content(args.workspace_id, rel_path)
        content = data.get("content", "")
        local_path = local_dir / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")
        print(f"✅ Resolved {rel_path}: workspace → local")



def _tree_to_dict(
    client: DarkmageClient,
    workspace_id: str,
    path: str,
    depth: int,
    max_depth: int,
) -> dict:
    """Build a nested dict representation of the workspace tree."""
    try:
        data = client.workspace_files(workspace_id, path)
    except DarkmageError:
        return {"path": path, "error": "Cannot list directory"}
    entries = cast(list, data.get("entries", []))
    entries_list: list = []
    result = {"path": path, "entries": entries_list}
    if depth < max_depth:
        for entry in entries:
            entry_path = f"{path}/{entry['name']}" if path != "." else entry["name"]
            if entry["kind"] == "directory":
                entries_list.append(
                    _tree_to_dict(client, workspace_id, entry_path, depth + 1, max_depth)
                )
            else:
                entries_list.append(
                    {
                        "name": entry["name"],
                        "kind": entry["kind"],
                        "size_bytes": entry.get("size_bytes"),
                    }
                )
    return result


def _print_tree(
    client: DarkmageClient,
    workspace_id: str,
    path: str,
    prefix: str,
    depth: int,
    max_depth: int,
) -> None:
    """Recursively print directory tree."""
    try:
        data = client.workspace_files(workspace_id, path)
    except DarkmageError as exc:
        print(f"{prefix}❌ {path} (error: {exc})")
        return
    entries = data.get("entries", [])
    # Sort directories first, then files
    entries.sort(key=lambda e: (e["kind"] != "directory", e["name"]))
    for i, entry in enumerate(entries):
        entry_path = f"{path}/{entry['name']}" if path != "." else entry["name"]
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        if entry["kind"] == "directory":
            print(f"{prefix}{connector}📁 {entry['name']}/")
            if depth < max_depth:
                extension = "    " if is_last else "│   "
                _print_tree(client, workspace_id, entry_path, prefix + extension, depth + 1, max_depth)
        else:
            size = entry.get("size_bytes", 0)
            size_str = f" ({size} B)" if size else ""
            print(f"{prefix}{connector}📄 {entry['name']}{size_str}")


def cmd_ws_build_apk(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Build a debug Android APK from the workspace's web files."""
    print_json(
        client.workspace_build_apk(
            args.workspace_id,
            web_dir=args.web_dir,
            output=args.output,
            app_name=args.app_name,
            app_id=args.app_id,
            version_code=args.version_code,
        )
    )


def cmd_ws_export_godot(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Export a Godot 4 project to a Web build."""
    print_json(
        client.workspace_export_godot(
            args.workspace_id,
            project_dir=args.project_dir,
            output_dir=args.output_dir,
        )
    )


def cmd_ws_blender(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Convert a .blend file to .glb for Godot via runner-manager."""
    print_json(
        client.workspace_blender(
            args.workspace_id,
            blend_path=args.blend_path,
            output=args.output,
            preview=args.preview,
            metadata=not args.no_metadata,
        )
    )


def cmd_ws_godot_tests(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Run Godot Unit Test (GUT) tests headless via runner-manager."""
    print_json(
        client.workspace_godot_tests(
            args.workspace_id,
            test_dir=args.test_dir,
            test_suffix=args.test_suffix,
        )
    )


def cmd_ws_tiled_import(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Import a Tiled .tmx map into a Godot .tscn scene via runner-manager."""
    print_json(
        client.workspace_tiled_import(
            args.workspace_id,
            tmx_path=args.tmx_path,
            output=args.output,
        )
    )


def cmd_ws_ldtk_import(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Import an LDtk .ldtk project into a Godot .tscn scene via runner-manager."""
    print_json(
        client.workspace_ldtk_import(
            args.workspace_id,
            ldtk_path=args.ldtk_path,
            output=args.output,
        )
    )


def cmd_session_create(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.session_create(args.workspace_id, args.title))


def cmd_session_list(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.session_list(args.workspace_id, args.limit))


def cmd_session_new(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.session_new(args.title))


def cmd_session_all(args: argparse.Namespace, client: DarkmageClient) -> None:
    sessions = client.session_all(args.limit, args.archived)
    if args.json or not sys.stdout.isatty():
        print_json(sessions)
        return
    _print_table(
        ["ID", "Название", "Создана"],
        [
            [
                s.get("id", ""),
                s.get("title") or "Сессия",
                s.get("created_at", "")[:10],
            ]
            for s in sessions
        ],
        min_widths=[36, 12, 10],
        drop_order=[2],
    )
    if not sessions:
        print("Сессий нет. Создайте: darkmage session new --title \"Моя сессия\"")


def cmd_session_runs(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.session_runs(args.session_id))


def cmd_session_files(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.session_files(args.session_id, args.path))


def cmd_session_read(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.session_read_file(args.session_id, args.path)
    if args.json:
        print_json(data)
    else:
        print(data.get("content", ""))


# ANSI colors for pretty SSE output (only used when stdout is a TTY).
_COLORS = {
    "run.started": "\033[1;34m",      # bold blue
    "assistant.delta": "\033[1;32m",  # bold green
    "tool.requested": "\033[1;36m",   # bold cyan
    "tool.started": "\033[1;36m",
    "tool.output": "\033[0;36m",
    "approval.required": "\033[1;33m",  # bold yellow
    "approval.resolved": "\033[0;33m",
    "checkpoint.ready": "\033[1;35m",   # bold magenta
    "checkpoint.resolved": "\033[0;35m",
    "diff.ready": "\033[1;35m",
    "run.completed": "\033[1;32m",      # bold green
    "run.failed": "\033[1;31m",         # bold red
    "run.cancelled": "\033[1;31m",
    "user.message": "\033[1;37m",       # bold white
    "agent.question": "\033[1;33m",
    "agent.answer": "\033[0;33m",
    "context.compacted": "\033[1;34m",
}
_RESET = "\033[0m"


def _color(text: str, event_type: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{_COLORS.get(event_type, '')}{text}{_RESET}"


def _color_status(status: str) -> str:
    """Цветной вывод статуса задачи/воркспейса (только для TTY)."""
    if not sys.stdout.isatty():
        return status
    colors = {
        "queued": "\033[1;33m",      # bold yellow
        "running": "\033[1;36m",     # bold cyan
        "waiting_approval": "\033[1;35m",  # bold magenta
        "completed": "\033[1;32m",   # bold green
        "failed": "\033[1;31m",      # bold red
        "cancelled": "\033[1;31m",   # bold red
        "creating": "\033[1;34m",    # bold blue
        "starting": "\033[1;34m",
        "stopped": "\033[0;37m",     # gray
        "error": "\033[1;31m",
        "ready": "\033[1;32m",
    }
    return f"{colors.get(status, '')}{status}{_RESET}"


def _format_event(ev: dict) -> str:
    eid = ev.get("id", "")
    etype = ev.get("event", "")
    data = ev.get("data", {})
    if isinstance(data, dict):
        detail = ""
        if etype == "assistant.delta":
            detail = data.get("text", "")
        elif etype == "tool.requested":
            detail = f"{data.get('name', '')} {json.dumps(data.get('arguments', {}))[:80]}"
        elif etype == "tool.output":
            detail = str(data.get("output", ""))[:120]
        elif etype == "approval.required":
            detail = approval_summary(data)
        elif etype == "approval.resolved":
            detail = (
                f"{data.get('decision', '')} "
                f"scope={data.get('scope', 'call')} "
                f"by={data.get('by', 'owner')}"
            )
        elif etype == "run.completed":
            detail = f"finish_reason={data.get('finish_reason', '')}"
        elif etype == "run.failed":
            detail = f"error={data.get('error', '')}"
        elif etype == "context.compacted":
            detail = f"dropped={data.get('dropped_messages', '')} before={data.get('tokens_before', '')} after={data.get('tokens_after', '')}"
        elif etype == "agent.question":
            detail = question_text(data)
            if data.get("question_id"):
                detail += f" (question_id={data['question_id']})"
        elif etype == "agent.answer":
            detail = f"answers={data.get('answers', [])}"
        elif etype == "diff.ready":
            detail = "\n" + format_diff(data)
            return f"[{eid}] {etype}: {detail}"
        return f"[{eid}] {etype}: {detail}"
    return f"[{eid}] {etype}: {data}"


def cmd_run_create(args: argparse.Namespace, client: DarkmageClient) -> int:
    run = client.run_create(
        args.session_id,
        args.prompt,
        args.model,
        args.plan_only,
        args.thorough,
        args.image if args.image else None,
    )
    run_id = str(run.get("id") or run.get("run_id") or "")
    # On a terminal, follow the run like an agent CLI; --no-follow keeps the
    # old "create and exit" behaviour for scripts that parse the JSON.
    follow = getattr(args, "follow", False) or (
        sys.stdout.isatty()
        and not getattr(args, "no_follow", False)
        and not getattr(args, "json", False)
    )
    if follow and run_id:
        print(f"▶ run {run_id}", file=sys.stderr, flush=True)
        return _follow_run(
            client,
            run_id,
            str(run.get("session_id") or args.session_id),
            output_format="json" if getattr(args, "json", False) else "text",
        )
    print_json(run)
    return 0


def cmd_run_get(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.run_get(args.run_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
        return
    print(f"ID:         {data.get('id')}")
    print(f"Сессия:     {data.get('session_id')}")
    print(f"Статус:     {_color_status(data.get('status', ''))}")
    print(f"Модель:     {data.get('model', '')}")
    print(f"Промпт:     {data.get('prompt', '')[:100]}")
    print(f"Чекпоинт:   {data.get('checkpoint_status', '')}")
    print(f"Создан:     {data.get('created_at', '')}")
    if data.get("started_at"):
        print(f"Начат:      {data.get('started_at')}")
    if data.get("finished_at"):
        print(f"Завершён:   {data.get('finished_at')}")


def cmd_run_message(args: argparse.Namespace, client: DarkmageClient) -> None:
    text = args.text
    if text == "-":
        text = sys.stdin.read().strip()
    print_json(client.run_message(args.run_id, text))


def cmd_run_answer(args: argparse.Namespace, client: DarkmageClient) -> None:
    answers = args.answer if isinstance(args.answer, list) else [args.answer]
    print_json(client.run_answer(args.run_id, args.question_id, answers))


def cmd_run_context(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.run_context(args.run_id))


def cmd_run_revert(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.run_revert(args.run_id))


def cmd_run_review(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.run_review(args.run_id))


def cmd_run_list(args: argparse.Namespace, client: DarkmageClient) -> None:
    runs = client.run_list(args.workspace_id)
    if args.json or not sys.stdout.isatty():
        print_json(runs)
        return
    _print_table(
        ["ID", "Статус", "Модель", "Промпт", "Создан"],
        [
            [
                r.get("id", ""),
                r.get("status", ""),
                r.get("model") or "-",
                r.get("prompt", ""),
                r.get("created_at", "")[:10],
            ]
            for r in runs
        ],
        min_widths=[40, 16, 6, 8, 10],
        drop_order=[2],
    )
    if not runs:
        print("Нет ran.")


def cmd_run_stop(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.run_stop(args.run_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
        return
    print(f"Run остановлен: {data.get('id')}")
    print(f"Статус: {_color_status(data.get('status', ''))}")


def cmd_run_events(args: argparse.Namespace, client: DarkmageClient) -> int:
    last_id = args.last_event_id
    pretty = args.pretty
    try:
        for ev in client.run_events_parsed(args.run_id, last_id):
            line = _format_event(ev)
            if pretty:
                print(_color(line, ev.get("event", "")))
            else:
                print(json.dumps(ev, ensure_ascii=False))
            if ev.get("event") in {"run.completed", "run.failed", "run.cancelled"}:
                break
    except KeyboardInterrupt:
        print(
            f"\nDetached. Run {args.run_id} continues; "
            f"stop it with 'darkmage run stop {args.run_id}'.",
            file=sys.stderr,
        )
        return 130
    return 0


def cmd_approval_approve(args: argparse.Namespace, client: DarkmageClient) -> int:
    data = client.tool_call_approve(args.tool_call_id, args.scope)
    if args.json or not sys.stdout.isatty():
        print_json(data)
    else:
        print(
            f"Approved {data.get('name', 'tool call')} "
            f"({data.get('id', args.tool_call_id)}), status={data.get('status', 'approved')}"
        )
    return 0


def cmd_approval_reject(args: argparse.Namespace, client: DarkmageClient) -> int:
    data = client.tool_call_reject(args.tool_call_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
    else:
        print(
            f"Rejected {data.get('name', 'tool call')} "
            f"({data.get('id', args.tool_call_id)}), status={data.get('status', 'rejected')}"
        )
    return 0


_EXEC_TERMINAL_EVENTS = {
    "run.completed": "completed",
    "run.failed": "failed",
    "run.cancelled": "cancelled",
}
_EXIT_APPROVAL_DENIED = 4
_EXIT_INTERRUPTED = 130


def _resolve_exec_session(client: DarkmageClient, session_id: str | None) -> str:
    """Use the requested session, or the newest one (creating one if needed)."""
    if session_id:
        return session_id
    try:
        sessions = client.session_all(limit=1)
        if sessions:
            return str(sessions[0]["id"])
        return str(client.session_new(title="CLI exec")["id"])
    except DarkmageError:
        workspaces = client.workspace_list(limit=1)
        if not workspaces:
            raise DarkmageError(
                "Нет доступных сессий. Создайте: darkmage session new"
            ) from None
        return str(
            client.session_create(str(workspaces[0]["id"]), title="CLI exec")["id"]
        )


def _question_text(data: dict[str, Any]) -> str:
    """Backwards-compatible wrapper around the shared question renderer."""
    return question_text(data)


def _is_interactive() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False


def _prompt_approval(
    client: DarkmageClient,
    data: dict[str, Any],
    *,
    input_fn: Callable[[str], str] | None = None,
    output: Any = None,
) -> bool:
    """Resolve an ``approval.required`` event interactively.

    Returns True when the decision was sent (or the approval was already
    resolved by someone else), False when the caller must stop and expose the
    approval id (non-interactive mode).
    """
    stream = output or sys.stderr
    approval_id = str(data.get("approval_id") or "")
    if data.get("auto"):
        # Policy-approved call: approval.resolved follows immediately.
        return False
    if not approval_id:
        print(
            "Approval required but the event has no approval_id; "
            "open the run in the web UI.",
            file=stream,
        )
        return False
    if not _is_interactive():
        print(approval_card(data), file=stream)
        print(
            "Non-interactive: decide with "
            f"'darkmage approvals approve {approval_id}' or "
            f"'darkmage approvals reject {approval_id}'.",
            file=stream,
        )
        return False

    reader = input_fn or input
    while True:
        print(approval_card(data), file=stream)
        try:
            choice = reader(
                "Approve? [a] once / [A] rest of turn / [r] reject / [d] diff: "
            )
        except EOFError:
            return False
        choice = choice.strip()
        scope = "call"
        if choice in ("", "a", "y", "yes"):
            scope = "call"
        elif choice in ("A", "t", "turn", "all"):
            scope = "turn"
        elif choice.lower() in ("r", "n", "no", "reject"):
            try:
                result = client.tool_call_reject(approval_id)
            except DarkmageError as exc:
                if exc.status_code == 409:
                    print(
                        f"Approval {approval_id} is no longer pending; "
                        "continuing the stream.",
                        file=stream,
                    )
                    return True
                print(f"Could not reject approval {approval_id}: {exc}", file=stream)
                return False
            print(
                f"Rejected {result.get('name', 'tool call')} ({approval_id}).",
                file=stream,
            )
            return True
        elif choice.lower() in ("d", "diff"):
            print(format_diff(data, max_lines=1000), file=stream)
            continue
        else:
            print("Unknown choice. Use a, A, r or d.", file=stream)
            continue

        try:
            result = client.tool_call_approve(approval_id, scope)
        except DarkmageError as exc:
            if exc.status_code == 409:
                print(
                    f"Approval {approval_id} is no longer pending; "
                    "continuing the stream.",
                    file=stream,
                )
                return True
            print(f"Could not approve {approval_id}: {exc}", file=stream)
            return False
        print(
            f"Approved {result.get('name', 'tool call')} ({approval_id}) "
            f"for {'the rest of the turn' if scope == 'turn' else 'this call'}.",
            file=stream,
        )
        return True


def _prompt_question(
    client: DarkmageClient,
    run_id: str,
    data: dict[str, Any],
    *,
    input_fn: Callable[[str], str] | None = None,
    output: Any = None,
) -> bool:
    """Answer an ``agent.question`` event interactively.

    Returns True when answers were submitted; False in non-interactive mode
    (caller exits 4 and prints the question_id).
    """
    stream = output or sys.stderr
    question_id = str(data.get("question_id") or "")
    items = question_items(data)
    if not question_id or not items:
        print(
            "Agent asked a question but the event is incomplete; "
            f"open the run in the web UI. {question_card(data)}",
            file=stream,
        )
        return False
    if not _is_interactive():
        print(question_card(data), file=stream)
        print(
            "Non-interactive: answer with "
            f"'darkmage run answer {run_id} {question_id} \"answer\" ...'.",
            file=stream,
        )
        return False

    print(question_card(data), file=stream)
    reader = input_fn or input
    answers: list[str] = []
    for index, item in enumerate(items, 1):
        options = item.get("options") or []
        while True:
            try:
                value = reader(
                    f"Answer {index}/{len(items)}"
                    + (" (number or text): " if options else ": ")
                ).strip()
            except EOFError:
                return False
            if not value:
                if options:
                    value = options[0]["label"]
                else:
                    print("Answer cannot be empty.", file=stream)
                    continue
            if options and value.isdigit():
                option_index = int(value)
                if 1 <= option_index <= len(options):
                    value = options[option_index - 1]["label"]
                else:
                    print(f"Choose 1..{len(options)}.", file=stream)
                    continue
            answers.append(value)
            break

    try:
        result = client.run_answer(run_id, question_id, answers)
    except DarkmageError as exc:
        if exc.status_code == 409:
            print(
                f"Question {question_id} was already answered; "
                "continuing the stream.",
                file=stream,
            )
            return True
        print(f"Could not answer question {question_id}: {exc}", file=stream)
        return False
    print(
        f"Answer sent: {result.get('answers', answers)}",
        file=stream,
    )
    return True


def _follow_run(
    client: DarkmageClient,
    run_id: str,
    session_id: str,
    *,
    output_format: str = "text",
    output_last_message: str | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> int:
    """Stream a run, resolving approvals/questions, and return an exit code."""
    if output_format != "stream-json":
        print(f"▶ run {run_id}", file=sys.stderr, flush=True)

    answer_parts: list[str] = []
    status = "unknown"
    pending_approval: dict[str, Any] | None = None
    pending_question: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None

    try:
        for event in client.run_events_parsed(run_id):
            event_type = str(event.get("event", ""))
            data = event.get("data") or {}
            if not isinstance(data, dict):
                data = {"value": data}

            if event_type == "assistant.delta":
                answer_parts.append(str(data.get("text") or ""))
            elif event_type == "tool.requested":
                # Text before a tool call is progress, not the final answer.
                answer_parts.clear()

            if output_format == "stream-json":
                print(
                    json.dumps(event, ensure_ascii=False, default=str),
                    flush=True,
                )
            elif event_type != "assistant.delta":
                print(_format_event(event), file=sys.stderr, flush=True)

            if event_type == "approval.required":
                if data.get("auto"):
                    answer_parts.clear()
                    continue
                answer_parts.clear()
                if _prompt_approval(
                    client, data, input_fn=input_fn, output=sys.stderr
                ):
                    continue
                status = "approval_required"
                pending_approval = data
                break
            if event_type == "agent.question":
                answer_parts.clear()
                if _prompt_question(
                    client, run_id, data, input_fn=input_fn, output=sys.stderr
                ):
                    continue
                status = "question"
                pending_question = data
                break
            if event_type in _EXEC_TERMINAL_EVENTS:
                status = _EXEC_TERMINAL_EVENTS[event_type]
                break
    except KeyboardInterrupt:
        print(
            f"\nDetached. Run {run_id} continues; "
            f"stop it with 'darkmage run stop {run_id}'.",
            file=sys.stderr,
        )
        return _EXIT_INTERRUPTED
    except DarkmageError as exc:
        if output_format != "json":
            print(f"Error: {exc}", file=sys.stderr)
        status = "failed"
        error_payload = {
            "message": str(exc),
            "status_code": exc.status_code,
            "retryable": exc.retryable,
        }

    run_data: dict[str, Any] = {}
    try:
        fetched = client.run_get(run_id)
        if isinstance(fetched, dict):
            run_data = fetched
    except DarkmageError:
        pass
    if status in ("unknown", "running") and run_data.get("status"):
        status = str(run_data["status"])

    final_answer = "".join(answer_parts).strip()
    if output_last_message and final_answer:
        try:
            write_private_text(output_last_message, final_answer + "\n")
        except OSError as exc:
            print(
                f"Warning: не удалось записать {output_last_message}: {exc}",
                file=sys.stderr,
            )

    envelope = {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": session_id,
        "status": status,
        "result": final_answer,
        "usage": {
            "prompt_tokens": run_data.get("prompt_tokens"),
            "completion_tokens": run_data.get("completion_tokens"),
        },
        "last_event_sequence": run_data.get("last_event_sequence"),
    }
    if pending_approval is not None:
        envelope["approval"] = {
            "approval_id": pending_approval.get("approval_id"),
            "tool_call_id": pending_approval.get("tool_call_id"),
            "name": pending_approval.get("name"),
            "summary": approval_summary(pending_approval),
        }
    if pending_question is not None:
        envelope["question"] = {
            "question_id": pending_question.get("question_id"),
            "questions": pending_question.get("questions") or [],
        }
    if error_payload is not None:
        envelope["error"] = error_payload

    if output_format == "json":
        print_json(envelope)
    elif output_format == "text" and final_answer and status == "completed":
        print(final_answer)

    if status == "completed":
        return 0
    if status in ("approval_required", "question"):
        return _EXIT_APPROVAL_DENIED
    return 1


def cmd_exec(args: argparse.Namespace, client: DarkmageClient) -> int:
    """One-shot run: create -> follow SSE -> final answer on stdout."""
    prompt = " ".join(getattr(args, "prompt", None) or []).strip()
    if not prompt or prompt == "-":
        prompt = sys.stdin.read().strip()
    if not prompt:
        print("Error: пустой prompt (передайте текст или stdin)", file=sys.stderr)
        return 2

    output_format = getattr(args, "output_format", None) or (
        "json" if getattr(args, "json", False) else "text"
    )
    if output_format not in ("text", "json", "stream-json"):
        print(f"Error: неизвестный output format: {output_format}", file=sys.stderr)
        return 2

    try:
        session_id = _resolve_exec_session(client, getattr(args, "session_id", None))
        run = client.run_create(
            session_id,
            prompt,
            model=getattr(args, "model", None),
            plan_only=getattr(args, "plan_only", False),
        )
    except DarkmageError as exc:
        if output_format == "json":
            print_json(
                {
                    "schema_version": 1,
                    "status": "error",
                    "error": {
                        "message": str(exc),
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                    },
                }
            )
            return 1
        print_error(str(exc))

    run_id = str(run.get("id") or run.get("run_id") or "")
    if not run_id:
        print("Error: сервер не вернул run id", file=sys.stderr)
        return 1

    return _follow_run(
        client,
        run_id,
        session_id,
        output_format=output_format,
        output_last_message=getattr(args, "output_last_message", None),
    )



def cmd_process_start(args: argparse.Namespace, client: DarkmageClient) -> None:
    argv = args.argv
    print_json(
        client.process_start(
            args.workspace_id, argv, args.cwd, args.port
        )
    )


def cmd_process_output(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(
        client.process_output(args.workspace_id, args.process_id)
    )


def cmd_process_stop(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.process_stop(args.workspace_id, args.process_id))


def cmd_payment_create(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.payment_create(args.product, args.amount_rub)
    link = data.get("payment_link")
    code = data.get("code")
    status = data.get("status")
    amount = data.get("amount_rub")
    product = data.get("product")
    print(f"Платеж создан: {product} на {amount} ₽")
    print(f"Статус: {status}")
    if code:
        print(f"Код для перевода: {code}")
    if link:
        print(f"Ссылка для оплаты: {link}")
        print("Перейдите по ссылке, оплатите и пришлите чек владельцу.")
    print_json(data)


def cmd_payment_list(args: argparse.Namespace, client: DarkmageClient) -> None:
    payments = client.payment_list()
    for p in payments:
        print(
            f"{p.get('id')}  {p.get('product')}  {p.get('amount_rub')} ₽  "
            f"{p.get('status')}  {p.get('created_at', '')[:16]}"
        )
    if not payments:
        print("Платежей нет.")


def cmd_admin_status(args: argparse.Namespace, client: DarkmageClient) -> None:
    data = client.admin_status()
    balance = data.get("openrouter_balance_usd")
    low = data.get("openrouter_balance_low")
    low_threshold = data.get("openrouter_low_balance_usd")
    print("Статус сервера (админ):")
    if balance is None:
        print("  Баланс OpenRouter: недоступен")
    else:
        print(f"  Баланс OpenRouter: ${balance} USD")
        if low:
            print(f"  ВНИМАНИЕ: баланс ниже порога ${low_threshold} USD")
        else:
            print(f"  Порог низкого баланса: ${low_threshold} USD")


async def _relay_terminal(
    ws: Any,
    read_stdin: Callable[[], Awaitable[bytes]],
    write_stdout: Callable[[bytes], Any],
) -> None:
    """Relay bytes between a remote PTY WebSocket and local stdio.

    Remote output is written verbatim to stdout. It is never interpreted by a
    local shell, so a compromised workspace cannot execute code on the client.
    Ctrl-] (0x1d) detaches locally, telnet-style.
    """
    import asyncio

    async def stdin_to_ws() -> None:
        while True:
            try:
                data = await read_stdin()
            except (EOFError, OSError):
                break
            if not data:
                break
            marker = data.find(b"\x1d")
            if marker >= 0:
                if marker:
                    await ws.send(data[:marker])
                break
            await ws.send(data)
        await ws.close()

    async def ws_to_stdout() -> None:
        async for message in ws:
            if isinstance(message, str):
                message = message.encode("utf-8", errors="replace")
            write_stdout(message)

    stdin_task = asyncio.create_task(stdin_to_ws())
    ws_task = asyncio.create_task(ws_to_stdout())
    await asyncio.wait({stdin_task, ws_task}, return_when=asyncio.FIRST_COMPLETED)

    if stdin_task.done():
        # The user detached (Ctrl-] or EOF): flush pending remote output, then stop.
        try:
            await asyncio.wait_for(asyncio.shield(ws_task), timeout=0.2)
        except asyncio.TimeoutError:
            ws_task.cancel()
    else:
        stdin_task.cancel()

    await asyncio.gather(stdin_task, ws_task, return_exceptions=True)

    for task in (stdin_task, ws_task):
        if not task.cancelled():
            task.result()


def _make_stdin_reader(fd: int) -> tuple[Callable[[], Awaitable[bytes]], Callable[[], None]]:
    """Create a non-blocking stdin reader backed by the asyncio event loop."""
    import asyncio

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def on_readable() -> None:
        try:
            data = os.read(fd, 4096)
        except OSError:
            data = b""
        if not data:
            loop.remove_reader(fd)
        queue.put_nowait(data)

    loop.add_reader(fd, on_readable)

    async def read() -> bytes:
        return await queue.get()

    def close() -> None:
        try:
            loop.remove_reader(fd)
        except Exception:  # noqa: S110, BLE001
            pass

    return read, close


def _term_guard_reason() -> str | None:
    """Return why the local PTY relay cannot run, or ``None`` if it can."""
    if os.name != "posix":
        return (
            "Команда term доступна только на Unix (Linux/macOS/WSL). "
            "На Windows используйте TUI: darkmage tui <workspace_id>"
        )
    try:
        import termios
        import tty

        if not hasattr(termios, "tcgetattr") or not hasattr(tty, "setraw"):
            return (
                "term требует полный Unix PTY API (termios/tty). "
                "Используйте TUI: darkmage tui <workspace_id>"
            )
    except ImportError:
        return (
            "term требует модули termios/tty (Unix). "
            "Используйте TUI: darkmage tui <workspace_id>"
        )
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return (
                "term требует интерактивный TTY. Для скриптов используйте "
                "darkmage run create/run events."
            )
        sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        return (
            "term требует интерактивный TTY с доступным stdin. "
            "Для скриптов используйте darkmage run create/run events."
        )
    return None


def cmd_term(args: argparse.Namespace, client: DarkmageClient) -> int:
    """Интерактивный терминал workspace (PTY через runner-manager).

    Безопасный relay: ввод уходит в удалённый PTY, вывод пишется в stdout.
    Локальный shell не создаётся и удалённый вывод не исполняется.
    """
    reason = _term_guard_reason()
    if reason is not None:
        print(reason, file=sys.stderr)
        return 1

    import asyncio
    import termios
    import tty

    try:
        import websockets  # type: ignore[import-not-found]
    except ImportError:
        print(
            "term требует пакет websockets. Установите: pip install websockets",
            file=sys.stderr,
        )
        return 1

    result = client.pty_create(args.workspace_id)
    session_id = result["session_id"]
    print(f"PTY session {session_id}. Выход: 'exit' или Ctrl-].\n", end="")

    ws_url = (
        client.base_url.replace("http://", "ws://")
        .replace("https://", "wss://")
        + f"/workspaces/{args.workspace_id}/pty/{session_id}"
    )
    extra_headers = (
        {"Authorization": f"Bearer {client.token}"} if client.token else None
    )
    stdin_fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(stdin_fd)

    async def run() -> None:
        async with websockets.connect(ws_url, additional_headers=extra_headers) as ws:
            read_stdin, close_reader = _make_stdin_reader(stdin_fd)

            def write_stdout(data: bytes) -> None:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()

            try:
                await _relay_terminal(ws, read_stdin, write_stdout)
            finally:
                close_reader()

    try:
        tty.setraw(stdin_fd)
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"term: {exc}", file=sys.stderr)
    finally:
        try:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_settings)
        except Exception:  # noqa: S110, BLE001
            pass
        try:
            client.pty_stop(args.workspace_id, session_id)
        except Exception:  # noqa: S110, BLE001
            pass
    return 0


def cmd_tui(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Запустить полноценный TUI клиент (Textual)."""
    from .tui import run_tui

    run_tui(
        base_url=client.base_url,
        token=client.token,
        workspace_id=args.workspace_id,
        run_id=args.run_id,
    )




def _subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _iter_cli_commands(
    parser: argparse.ArgumentParser, prefix: str = ""
) -> list[tuple[str, str]]:
    """Flatten the argparse tree into ``(command, help)`` rows for the REPL."""
    action = _subparser_action(parser)
    if action is None:
        return []
    helps = {
        getattr(choice, "dest", ""): getattr(choice, "help", "") or ""
        for choice in getattr(action, "_choices_actions", [])
    }
    rows: list[tuple[str, str]] = []
    for name, child in action.choices.items():
        command = f"{prefix} {name}".strip()
        child_action = _subparser_action(child)
        if child_action is None:
            rows.append((command, helps.get(name, "")))
        else:
            rows.extend(_iter_cli_commands(child, command))
    return rows


def print_help_repl(parser: argparse.ArgumentParser | None = None) -> None:
    """Показать актуальную справку, собранную из parser'а."""
    parser = parser or build_parser()
    width = min(96, max(60, _terminal_width()))
    print("Интерактивный режим. Команды вводятся без префикса 'darkmage'.")
    print("Пример: run create <session_id> --prompt \"исправь тесты\"\n")
    print("Доступные команды:")
    rows = _iter_cli_commands(parser)
    for line in _format_table(
        ["Команда", "Описание"],
        [[command, help_text] for command, help_text in rows],
        width=width,
        min_widths=[22, 20],
        drop_order=[1],
        compact_below=30,
    ):
        print(line)
    print("\n  help <команда>   Подробная справка по команде")
    print("  exit | quit | q  Выйти из интерактивного режима")


def _readline_module() -> Any:
    """Return the stdlib readline module, or ``None`` where unavailable."""
    try:
        import readline  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - Windows without pyreadline
        return None
    return readline


def _load_repl_history(readline_module: Any) -> int:
    """Seed readline with the persisted (masked) command history."""
    if readline_module is None:
        return 0
    from .security import HISTORY_FILE

    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(data, list):
        return 0
    loaded = 0
    for entry in data:
        command = entry.get("command") if isinstance(entry, dict) else None
        if not command:
            continue
        try:
            readline_module.add_history(str(command))
            loaded += 1
        except Exception:  # noqa: BLE001, S110
            break
    try:
        readline_module.set_history_length(100)
    except Exception:  # noqa: BLE001, S110
        pass
    return loaded


def cmd_repl(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Интерактивный режим REPL для работы с Darkmage AI."""
    import shlex

    readline = _readline_module()
    _load_repl_history(readline)
    parser = build_parser()

    print("🚀 Darkmage CLI — Интерактивный режим (REPL)")
    print("Введите команду или 'help' для справки, 'exit' или 'quit' для выхода.\n")

    while True:
        try:
            user_input = input("darkmage> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 До свидания!")
            return

        if not user_input.strip():
            continue

        lowered = user_input.lower()
        if lowered in ("exit", "quit", "q"):
            print("👋 До свидания!")
            return

        try:
            parts = shlex.split(user_input)
        except ValueError as exc:
            print(f"Ошибка разбора команды: {exc}", file=sys.stderr)
            continue
        if not parts:
            continue

        if readline is not None:
            try:
                readline.add_history(_mask_secrets(user_input))
            except Exception:  # noqa: BLE001, S110
                pass

        if parts[0].lower() in ("help", "h", "?"):
            if len(parts) > 1:
                try:
                    parser.parse_args([*parts[1:], "--help"])
                except SystemExit:
                    pass
            else:
                print_help_repl(parser)
            continue

        try:
            sub_args = parser.parse_args(parts)
            func = getattr(sub_args, "func", None)
            if func is None:
                print_help_repl(parser)
                continue
            func(sub_args, client)
            try:
                _record_history(parts)
            except OSError as exc:
                print(f"history: {exc}", file=sys.stderr)
        except SystemExit:
            pass
        except DarkmageError as exc:
            print(f"Error: {exc}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nПрервано.", file=sys.stderr)


def cmd_config_show(args: argparse.Namespace, client: DarkmageClient) -> None:
    from .config import load_config
    from .security import CONFIG_FILE

    config = load_config()
    if args.json:
        # Never print the decrypted token, even when CI captures stdout.
        print_json(redact_config(config))
        return
    if not config:
        print("Конфиг пуст. Файл: " + str(CONFIG_FILE))
        return
    print(f"Конфиг ({CONFIG_FILE}):")
    for key, value in config.items():
        if value and is_secret_key(key):
            value = mask_token(str(value))
        print(f"  {key}: {value}")


def cmd_config_set(args: argparse.Namespace, client: DarkmageClient) -> None:
    from .config import load_config, set_base_url, set_runner_token, set_runner_url, set_token

    changed = False
    if getattr(args, "url", None) is not None:
        set_base_url(args.url)
        warn_insecure_url(args.url)
        changed = True
    if getattr(args, "token", None) is not None:
        set_token(args.token)
        changed = True
    if getattr(args, "runner_url", None) is not None:
        set_runner_url(args.runner_url)
        changed = True
    if getattr(args, "runner_token", None) is not None:
        set_runner_token(args.runner_token)
        changed = True
    if not changed:
        print("Нечего менять: укажите --url, --token, --runner-url или --runner-token")
        return
    print("Конфиг обновлён.")
    if getattr(args, "verbose", False):
        print_json(redact_config(load_config()))


def cmd_config_export(args: argparse.Namespace, client: DarkmageClient) -> None:
    from .config import load_config

    config = load_config()
    if not config:
        print("Конфиг пуст, нечего экспортировать.")
        return
    try:
        # Exports are always redacted and owner-read/write only.
        write_private_json(args.output, redact_config(config))
        print(
            f"Конфиг экспортирован в {args.output} "
            "(секреты замаскированы, права 0600)"
        )
    except OSError as exc:
        print(f"Ошибка записи файла: {exc}")


def cmd_config_import(args: argparse.Namespace, client: DarkmageClient) -> None:
    import json

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Ошибка чтения файла: {exc}")
        return
    if not isinstance(config, dict):
        print("Ошибка: ожидается JSON-объект.")
        return
    # A redacted export must not overwrite a live token with a placeholder.
    redacted_keys = [
        key
        for key, value in config.items()
        if is_secret_key(str(key)) and is_redacted_value(value)
    ]
    config = strip_redacted(config)
    if not config:
        print("В файле нет данных для импорта (все секреты замаскированы).")
        return
    if redacted_keys:
        current = load_config()
        for key in redacted_keys:
            if current.get(key):
                config[key] = current[key]
    save_config(config)
    print(f"Конфиг импортирован из {args.input}")


def cmd_history(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Показать или повторить предыдущие команды CLI."""
    import json

    from .security import HISTORY_FILE

    history_file = HISTORY_FILE
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        history = []

    if args.number is not None:
        idx = args.number - 1
        if idx < 0 or idx >= len(history):
            print(f"Команда #{args.number} не найдена в истории")
            return
        cmd = history[idx]["command"]
        print(f"Повтор #{args.number}: {cmd}")
        import shlex

        sys.exit(main(shlex.split(cmd)))
    else:
        if not history:
            print("История команд пуста")
            return
        print("Последние команды:")
        start = max(0, len(history) - 10)
        for i in range(start, len(history)):
            entry = history[i]
            print(f"  {i + 1:>3}. {entry['command']}")


PARALLEL_OUTPUT_LIMIT = 64_000


class _BoundedBuffer(io.TextIOBase):
    """Per-thread output buffer with a hard character cap."""

    def __init__(self, limit: int) -> None:
        self.limit = max(0, limit)
        self._parts: list[str] = []
        self._size = 0
        self.truncated = False

    def write(self, text: str) -> int:  # type: ignore[override]
        if not isinstance(text, str):
            text = str(text)
        remaining = self.limit - self._size
        if remaining > 0:
            kept = text[:remaining]
            if kept:
                self._parts.append(kept)
                self._size += len(kept)
        if len(text) > max(remaining, 0):
            self.truncated = True
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"

    def value(self) -> str:
        return "".join(self._parts)


class _ThreadStreamRouter:
    """Route writes to a per-thread bounded buffer, else the real stream.

    Commands print directly to ``sys.stdout``/``sys.stderr``. A thread-local
    router lets ``parallel`` capture each command independently without the
    process-global races of ``contextlib.redirect_stdout``.
    """

    def __init__(self, default: Any, limit: int) -> None:
        self._default = default
        self._limit = limit
        self._local = threading.local()

    def bind(self) -> _BoundedBuffer:
        buffer = _BoundedBuffer(self._limit)
        self._local.buffer = buffer
        return buffer

    def unbind(self) -> None:
        self._local.buffer = None

    def _buffer(self) -> _BoundedBuffer | None:
        return getattr(self._local, "buffer", None)

    def write(self, text: str) -> int:
        buffer = self._buffer()
        if buffer is not None:
            return buffer.write(text)
        return self._default.write(text)

    def flush(self) -> None:
        buffer = self._buffer()
        if buffer is None:
            self._default.flush()

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._default, name)


def _parallel_defaults(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "url": getattr(args, "url", None),
        "runner_url": getattr(args, "runner_url", None),
        "runner_token": getattr(args, "runner_token", None),
        "json": getattr(args, "json", False),
        "verbose": getattr(args, "verbose", False),
    }


def _run_one_parallel(
    cmd_str: str,
    parser: argparse.ArgumentParser,
    defaults: dict[str, Any],
    stdout_router: _ThreadStreamRouter,
    stderr_router: _ThreadStreamRouter,
) -> tuple[int, str, str, bool]:
    """Run one command synchronously inside its own worker thread."""
    out = stdout_router.bind()
    err = stderr_router.bind()
    code = 1
    client_obj: DarkmageClient | None = None
    try:
        parts = shlex.split(cmd_str)
        sub_args = parser.parse_args(parts)
        for key, value in defaults.items():
            current = getattr(sub_args, key, None)
            if value and current in (None, False):
                setattr(sub_args, key, value)
        func = getattr(sub_args, "func", None)
        if func is None:
            err.write("no command function\n")
        else:
            client_obj = DarkmageClient(base_url=getattr(sub_args, "url", None))
            if getattr(sub_args, "runner_url", None):
                client_obj.runner_url = sub_args.runner_url.rstrip("/")
            if getattr(sub_args, "runner_token", None):
                client_obj.runner_token = sub_args.runner_token
            result = func(sub_args, client_obj)
            code = result if isinstance(result, int) else 0
    except SystemExit as exc:
        if exc.code is None:
            code = 0
        elif isinstance(exc.code, int):
            code = exc.code
        else:
            code = 1
            err.write(f"{exc.code}\n")
    except BaseException as exc:  # noqa: BLE001 - reported per command
        code = 1
        err.write(f"{type(exc).__name__}: {exc}\n")
    finally:
        if client_obj is not None:
            try:
                client_obj.close()
            except Exception:  # noqa: BLE001, S110
                pass
        stdout_router.unbind()
        stderr_router.unbind()
    return code, out.value(), err.value(), out.truncated or err.truncated


async def _run_parallel_commands(
    commands: list[str],
    *,
    parser_arg: argparse.ArgumentParser | None = None,
    defaults: dict[str, Any] | None = None,
    limit: int = PARALLEL_OUTPUT_LIMIT,
) -> list[tuple[int, str, str, bool]]:
    """Execute command strings concurrently with bounded per-command output."""
    import asyncio

    parser_obj = parser_arg or build_parser()
    stdout_router = _ThreadStreamRouter(sys.stdout, limit)
    stderr_router = _ThreadStreamRouter(sys.stderr, limit)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout_router, stderr_router
    try:
        tasks = [
            asyncio.to_thread(
                _run_one_parallel,
                command,
                parser_obj,
                defaults or {},
                stdout_router,
                stderr_router,
            )
            for command in commands
        ]
        return list(await asyncio.gather(*tasks))
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr


def _print_parallel_results(
    commands: list[str], results: list[tuple[int, str, str, bool]]
) -> None:
    for index, (code, output, errors, truncated) in enumerate(results, 1):
        status = "OK" if code == 0 else f"Ошибка ({code})"
        print(f"[{index}] {status}: {commands[index - 1]}")
        for label, text in (("", output), ("stderr: ", errors)):
            if not text:
                continue
            indented = "\n".join(
                f"    {label}{line}" if line else f"    {label}".rstrip()
                for line in text.rstrip("\n").splitlines()
            )
            print(indented)
        if truncated:
            print("    … вывод обрезан (лимит 64 КиБ на команду)")


def cmd_parallel(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Выполнить несколько команд параллельно (bounded output)."""
    import asyncio

    results = asyncio.run(
        _run_parallel_commands(
            list(args.commands),
            defaults=_parallel_defaults(args),
        )
    )
    _print_parallel_results(list(args.commands), results)


def cmd_git_clone(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.git_clone(args.workspace_id, args.url, args.ref, args.depth))


def cmd_git_commit(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.git_commit(args.workspace_id, args.message, args.branch))


def cmd_git_push(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.git_push(args.workspace_id, args.branch))


def cmd_git_pr_create(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(
        client.git_pr_create(
            args.workspace_id, args.title, args.body, args.base, args.head
        )
    )


def cmd_mcp_list(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.mcp_list())


def cmd_mcp_call(args: argparse.Namespace, client: DarkmageClient) -> None:
    arguments: dict[str, Any] = {}
    if args.arguments:
        for item in args.arguments:
            if "=" not in item:
                print_error(f"Неверный формат аргумента: {item} (ожидается ключ=значение)")
            key, value = item.split("=", 1)
            arguments[key] = value
    print_json(client.mpc_call(args.tool, arguments, args.workspace_id))


def _chat_events_from_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Fallback adapter for clients/servers without streaming support."""
    events: list[dict[str, Any]] = []
    for choice in data.get("choices", []):
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if content:
            events.append({"type": "delta", "text": str(content)})
    usage = data.get("usage")
    if isinstance(usage, dict):
        events.append({"type": "usage", "usage": usage})
    events.append({"type": "done"})
    return events


def cmd_chat(args: argparse.Namespace, client: DarkmageClient) -> int:
    """Chat completion with optional streaming, JSON output and stdin input."""
    message = getattr(args, "message", None)
    if message is None or message == "-":
        if message is None and sys.stdin.isatty():
            print(
                "Error: укажите сообщение или передайте его через stdin.",
                file=sys.stderr,
            )
            return 2
        message = sys.stdin.read().strip()
    if not message:
        print("Error: пустое сообщение.", file=sys.stderr)
        return 2

    messages = [{"role": "user", "content": message}]
    if getattr(args, "system", None):
        messages.insert(0, {"role": "system", "content": args.system})

    json_mode = bool(getattr(args, "json", False))
    streaming = not bool(getattr(args, "no_stream", False))
    model = getattr(args, "model", None)
    content_parts: list[str] = []
    usage: dict[str, Any] | None = None

    try:
        if streaming and hasattr(client, "chat_completion_stream"):
            events = client.chat_completion_stream(
                messages,
                model,
                getattr(args, "temperature", 0.7),
                getattr(args, "max_tokens", None),
            )
        else:
            events = _chat_events_from_response(
                client.chat_completion(
                    messages,
                    model,
                    getattr(args, "temperature", 0.7),
                    getattr(args, "max_tokens", None),
                )
            )
        for event in events:
            event_type = event.get("type")
            if event_type == "delta":
                text = str(event.get("text") or "")
                content_parts.append(text)
                if not json_mode and text:
                    sys.stdout.write(text)
                    sys.stdout.flush()
            elif event_type == "usage" and isinstance(event.get("usage"), dict):
                usage = event["usage"]
    except DarkmageError as exc:
        if json_mode:
            print_json(
                {
                    "schema_version": 1,
                    "status": "error",
                    "error": {
                        "message": str(exc),
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                    },
                }
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    content = "".join(content_parts)
    if json_mode:
        print_json(
            {
                "schema_version": 1,
                "model": model,
                "content": content,
                "usage": usage,
            }
        )
        return 0

    if content and not content.endswith("\n"):
        print()
    if usage:
        parts = [
            f"prompt={usage.get('prompt_tokens')}"
            if usage.get("prompt_tokens") is not None
            else None,
            f"completion={usage.get('completion_tokens')}"
            if usage.get("completion_tokens") is not None
            else None,
            f"total={usage.get('total_tokens')}"
            if usage.get("total_tokens") is not None
            else None,
        ]
        summary = " ".join(part for part in parts if part)
        if summary:
            print(f"usage: {summary}", file=sys.stderr)
    return 0


def cmd_health(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.health())


def cmd_ready(args: argparse.Namespace, client: DarkmageClient) -> None:
    print_json(client.ready())


def cmd_doctor(args: argparse.Namespace, client: DarkmageClient) -> int:
    """Проверка окружения и подключения к серверу Darkmage."""
    from .config import get_base_url

    api_url = getattr(args, "url", None) or get_base_url()
    token = get_token()
    failures: list[str] = []
    health_status: str | None = None
    ready_status: str | None = None

    try:
        client.base_url = api_url
        client.token = token
        h = client.health()
        health_status = str(h.get("status", "unknown"))
        if health_status not in (
            "ok",
            "healthy",
            "ready",
            "up",
            "alive",
            "unknown",
        ):
            failures.append(f"health status is {health_status}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"health check failed: {exc}")

    try:
        r = client.ready()
        ready_status = str(r.get("status", "unknown"))
        if ready_status not in ("ok", "healthy", "ready", "up", "unknown"):
            failures.append(f"readiness status is {ready_status}")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"readiness check failed: {exc}")

    if not token:
        failures.append("token is not configured")
    if not api_url:
        failures.append("API URL is not configured")

    as_json = bool(getattr(args, "json", False))
    if as_json:
        print_json(
            {
                "ok": not failures,
                "api_url": api_url,
                "token_set": bool(token),
                "health": health_status,
                "ready": ready_status,
                "failures": failures,
            }
        )
        return 0 if not failures else 1

    print("🩺 Проверка состояния Darkmage CLI\n")
    print(f"📍 API URL: {api_url}")
    if token:
        print(
            "🔑 Токен:   "
            + ("*" * (len(token) - 4) + token[-4:] if len(token) > 4 else "***")
        )
    else:
        print("🔑 Токен:   не настроен")
    print()
    print("🏥 Health check:")
    if health_status is not None and not any(
        item.startswith("health") for item in failures
    ):
        print(f"   ✅ /health:  {health_status}")
    else:
        health_error = next(
            (item for item in failures if item.startswith("health")), "unknown error"
        )
        print(f"   ❌ /health:  ошибка — {health_error}")
    print("🚀 Readiness check:")
    if ready_status is not None and not any(
        item.startswith("readiness") or item.startswith("ready")
        for item in failures
    ):
        print(f"   ✅ /ready:   {ready_status}")
    else:
        ready_error = next(
            (
                item
                for item in failures
                if item.startswith("readiness") or item.startswith("ready")
            ),
            "unknown error",
        )
        print(f"   ❌ /ready:   ошибка — {ready_error}")
    print()
    if failures:
        print("⚠️  Есть проблемы:")
        for failure in failures:
            print(f"   • {failure}")
        return 1
    print("Готово к работе.")
    return 0


def cmd_completion(args: argparse.Namespace, client: DarkmageClient) -> None:
    """Генерация скриптов автодополнения для shell (bash, zsh, fish)."""
    shell = args.shell if hasattr(args, "shell") and args.shell else "bash"

    if shell == "bash":
        print(_bash_completion_script())
    elif shell == "zsh":
        print(_zsh_completion_script())
    elif shell == "fish":
        print(_fish_completion_script())
    else:
        print(f"Неизвестная оболочка: {shell}")
        print("Доступные: bash, zsh, fish")


def _bash_completion_script() -> str:
    return """# Darkmage CLI bash completion
# Source this file in your ~/.bashrc:
#   source <(darkmage completion bash)

_darkmage_complete() {
    local cur prev words cword
    _init_completion || return

    case "$prev" in
        darkmage)
            COMPREPLY=( $(compgen -W 'auth me usage memory workspace files session run repl approvals exec process payment admin term tui config git mcp chat health ready doctor completion history parallel login start' -- "$cur") )
            ;;
        auth)
            COMPREPLY=( $(compgen -W 'register login logout interactive' -- "$cur") )
            ;;
        workspace)
            COMPREPLY=( $(compgen -W 'create list get update start stop delete apk godot blender godot-tests tiled-import ldtk-import' -- "$cur") )
            ;;
        files)
            COMPREPLY=( $(compgen -W 'list read edit search download upload cp mv rm export status tree sync' -- "$cur") )
            ;;
        sync)
            COMPREPLY=( $(compgen -W 'pull push diff watch resolve' -- "$cur") )
            ;;
        session)
            COMPREPLY=( $(compgen -W 'create list new all runs files read' -- "$cur") )
            ;;
        run)
            COMPREPLY=( $(compgen -W 'create get message answer context revert review stop list events' -- "$cur") )
            ;;
        approvals)
            COMPREPLY=( $(compgen -W 'approve reject' -- "$cur") )
            ;;
        process)
            COMPREPLY=( $(compgen -W 'start output stop' -- "$cur") )
            ;;
        payment)
            COMPREPLY=( $(compgen -W 'create list' -- "$cur") )
            ;;
        git)
            COMPREPLY=( $(compgen -W 'clone commit push pr' -- "$cur") )
            ;;
        mcp)
            COMPREPLY=( $(compgen -W 'list call' -- "$cur") )
            ;;
        config)
            COMPREPLY=( $(compgen -W 'show set export import' -- "$cur") )
            ;;
        history)
            COMPREPLY=()
            ;;
        *)
            COMPREPLY=()
            ;;
    esac
}
complete -F _darkmage_complete darkmage"""


def _zsh_completion_script() -> str:
    return """# Darkmage CLI zsh completion
# Source this file in your ~/.zshrc:
#   source <(darkmage completion zsh)

#compdef darkmage

_darkmage_complete() {
    local -a commands
    commands=(
        'auth:Authentication commands'
        'me:Current user info'
        'usage:Spend windows'
        'memory:User memory management'
        'workspace:Workspace management'
        'files:Workspace files'
        'session:Session management'
        'run:Task runs management'
        'repl:Interactive command shell'
        'approvals:Approve or reject tool calls'
        'exec:One-shot run with final answer'
        'process:Background processes'
        'payment:Payments and billing'
        'admin:Admin commands'
        'term:Interactive terminal (PTY)'
        'tui:Full TUI client'
        'config:Configuration management'
        'git:Git operations'
        'mcp:MCP tools'
        'chat:Chat completion'
        'health:Liveness check'
        'ready:Readiness check'
        'doctor:Environment diagnostics'
        'completion:Shell completion scripts'
        'history:Command history'
        'parallel:Run commands concurrently'
        'login:Interactive login'
        'start:Start TUI session'
    )
    _describe 'command' commands
}

_darkmage "$@"
"""


def _fish_completion_script() -> str:
    return """# Darkmage CLI fish completion
# Save this file to ~/.config/fish/completions/darkmage.fish

complete -c darkmage -f -a 'auth' -d 'Authentication commands'
complete -c darkmage -f -a 'me' -d 'Current user info'
complete -c darkmage -f -a 'usage' -d 'Spend windows'
complete -c darkmage -f -a 'memory' -d 'User memory management'
complete -c darkmage -f -a 'workspace' -d 'Workspace management'
complete -c darkmage -f -a 'files' -d 'Workspace files'
complete -c darkmage -f -a 'session' -d 'Session management'
complete -c darkmage -f -a 'run' -d 'Task runs management'
complete -c darkmage -f -a 'repl' -d 'Interactive command shell'
complete -c darkmage -f -a 'approvals' -d 'Approve or reject tool calls'
complete -c darkmage -f -a 'exec' -d 'One-shot run with final answer'
complete -c darkmage -f -a 'process' -d 'Background processes'
complete -c darkmage -f -a 'payment' -d 'Payments and billing'
complete -c darkmage -f -a 'admin' -d 'Admin commands'
complete -c darkmage -f -a 'term' -d 'Interactive terminal (PTY)'
complete -c darkmage -f -a 'tui' -d 'Full TUI client'
complete -c darkmage -f -a 'config' -d 'Configuration management'
complete -c darkmage -f -a 'git' -d 'Git operations'
complete -c darkmage -f -a 'mcp' -d 'MCP tools'
complete -c darkmage -f -a 'chat' -d 'Chat completion'
complete -c darkmage -f -a 'health' -d 'Liveness check'
complete -c darkmage -f -a 'ready' -d 'Readiness check'
complete -c darkmage -f -a 'doctor' -d 'Environment diagnostics'
complete -c darkmage -f -a 'completion' -d 'Shell completion scripts'
complete -c darkmage -f -a 'history' -d 'Command history'
complete -c darkmage -f -a 'parallel' -d 'Run commands concurrently'
complete -c darkmage -f -a 'login' -d 'Interactive login'
complete -c darkmage -f -a 'start' -d 'Start TUI session'

# Subcommand completions
complete -c darkmage -f -a 'register login logout interactive' -d 'auth subcommands' -n '__fish_seen_subcommand auth'
complete -c darkmage -f -a 'create list get update start stop delete apk godot blender godot-tests tiled-import ldtk-import' -d 'workspace subcommands' -n '__fish_seen_subcommand workspace'
complete -c darkmage -f -a 'list read edit search download upload cp mv rm export status tree sync' -d 'files subcommands' -n '__fish_seen_subcommand files'
complete -c darkmage -f -a 'pull push diff watch resolve' -d 'sync subcommands' -n '__fish_seen_subcommand sync'
complete -c darkmage -f -a 'create list new all runs files read' -d 'session subcommands' -n '__fish_seen_subcommand session'
complete -c darkmage -f -a 'create get message answer context revert review stop list events' -d 'run subcommands' -n '__fish_seen_subcommand run'
complete -c darkmage -f -a 'approve reject' -d 'approvals subcommands' -n '__fish_seen_subcommand approvals'
complete -c darkmage -f -a 'start output stop' -d 'process subcommands' -n '__fish_seen_subcommand process'
complete -c darkmage -f -a 'create list' -d 'payment subcommands' -n '__fish_seen_subcommand payment'
complete -c darkmage -f -a 'clone commit push pr' -d 'git subcommands' -n '__fish_seen_subcommand git'
complete -c darkmage -f -a 'list call' -d 'mcp subcommands' -n '__fish_seen_subcommand mcp'
complete -c darkmage -f -a 'show set export import' -d 'config subcommands' -n '__fish_seen_subcommand config'
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="darkmage",
        description="CLI for the Darkmage AI platform",
        epilog="One-shot: darkmage -p '...' is shorthand for darkmage exec '...'",
    )
    parser.add_argument(
        "--url", default=None, help="API base URL (default: DARKMAGE_API_URL or http://localhost:8000)"
    )
    parser.add_argument(
        "--runner-url", default=None, help="Runner-manager URL (default: DARKMAGE_RUNNER_URL or http://localhost:8090)"
    )
    parser.add_argument(
        "--runner-token", default=None, help="Runner-manager bearer token (default: DARKMAGE_RUNNER_TOKEN)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Показывать стек-трейс при ошибках",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Вывод в формате JSON",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    def add(name: str, help_text: str, func, parent=sub) -> argparse.ArgumentParser:
        p = parent.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        return p

    # --- auth ---
    auth = sub.add_parser("auth", help="Authentication")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)

    p = auth_sub.add_parser("register", help="Create an account")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--full-name", dest="full_name", default=None)
    p.set_defaults(func=cmd_register)

    p = auth_sub.add_parser("login", help="Log in and save token")
    p.add_argument("email", nargs="?", default=None, help="Email (asked interactively if omitted)")
    p.add_argument("password", nargs="?", default=None, help="Password (asked interactively if omitted)")
    p.set_defaults(func=cmd_login)

    p = auth_sub.add_parser("logout", help="Remove saved token")
    p.set_defaults(func=cmd_logout)

    p = auth_sub.add_parser("interactive", help="Интерактивный вход/регистрация (как в Claude Code)")
    p.set_defaults(func=cmd_auth_interactive)

    # --- user ---
    sub.add_parser("me", help="Current user").set_defaults(func=cmd_me)
    sub.add_parser("usage", help="Spend windows").set_defaults(func=cmd_usage)

    mem = sub.add_parser("memory", help="User memory")
    mem_sub = mem.add_subparsers(dest="memory_command", required=True)
    p = mem_sub.add_parser("get", help="Read memory")
    p.set_defaults(func=cmd_memory_get)
    p = mem_sub.add_parser("put", help="Write memory")
    p.add_argument("content")
    p.set_defaults(func=cmd_memory_put)

    # --- workspaces ---
    ws = sub.add_parser("workspace", help="Workspaces")
    ws_sub = ws.add_subparsers(dest="workspace_command", required=True)

    p = ws_sub.add_parser("create", help="Create workspace")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_ws_create)

    p = ws_sub.add_parser("list", help="List workspaces")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_ws_list)

    p = ws_sub.add_parser("get", help="Get workspace")
    p.add_argument("workspace_id")
    p.set_defaults(func=cmd_ws_get)

    p = ws_sub.add_parser("update", help="Update workspace")
    p.add_argument("workspace_id")
    p.add_argument("--name")
    p.add_argument("--approval-mode", choices=["auto", "ask"])
    p.set_defaults(func=cmd_ws_update)

    p = ws_sub.add_parser("start", help="Start workspace")
    p.add_argument("workspace_id")
    p.set_defaults(func=cmd_ws_start)

    p = ws_sub.add_parser("stop", help="Stop workspace")
    p.add_argument("workspace_id")
    p.set_defaults(func=cmd_ws_stop)

    p = ws_sub.add_parser("delete", help="Delete workspace")
    p.add_argument("workspace_id")
    p.add_argument(
        "--yes", "-y", action="store_true", default=False,
        help="Skip the confirmation prompt (required in non-interactive mode)",
    )
    p.set_defaults(func=cmd_ws_delete)

    # files
    files = sub.add_parser("files", help="Workspace files")
    files_sub = files.add_subparsers(dest="files_command", required=True)

    p = files_sub.add_parser("list", help="List directory")
    p.add_argument("workspace_id")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_ws_files)

    p = files_sub.add_parser("read", help="Read file content")
    p.add_argument("workspace_id")
    p.add_argument("path")
    p.add_argument("--offset", type=int, default=1)
    p.add_argument("--limit", type=int, default=2000)
    p.set_defaults(func=cmd_ws_read)

    p = files_sub.add_parser("edit", help="Request a file edit (editor flow, waits for approval)")
    p.add_argument("workspace_id")
    p.add_argument("path")
    p.add_argument("content", help="New file content, or '-' to read from stdin")
    p.add_argument("--base-content", help="Current file content (fetched automatically if omitted)")
    p.add_argument("--session-id", help="Session to attach the edit run to")
    p.set_defaults(func=cmd_ws_edit)

    p = files_sub.add_parser("search", help="Search files")
    p.add_argument("workspace_id")
    p.add_argument("query")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_ws_search)

    p = files_sub.add_parser("download", help="Download file from workspace to local")
    p.add_argument("workspace_id")
    p.add_argument("remote_path")
    p.add_argument("local_path")
    p.set_defaults(func=cmd_ws_download)

    p = files_sub.add_parser("upload", help="Upload local file to workspace (direct write)")
    p.add_argument("local_path")
    p.add_argument("workspace_id")
    p.add_argument("remote_path")
    p.set_defaults(func=cmd_ws_upload)

    p = files_sub.add_parser("cp", help="Copy file between local and workspace (ws:/path)")
    p.add_argument("workspace_id")
    p.add_argument("source", help="Local path or ws:/remote/path")
    p.add_argument("destination", help="Local path or ws:/remote/path")
    p.set_defaults(func=cmd_files_cp)

    p = files_sub.add_parser("mv", help="Move file between local and workspace (ws:/path)")
    p.add_argument("workspace_id")
    p.add_argument("source", help="Local path or ws:/remote/path")
    p.add_argument("destination", help="Local path or ws:/remote/path")
    p.set_defaults(func=cmd_files_mv)

    p = files_sub.add_parser("rm", help="Remove file from workspace or local")
    p.add_argument("workspace_id")
    p.add_argument("path", help="Local path or ws:/remote/path")
    p.add_argument(
        "--yes", "-y", action="store_true", default=False,
        help="Skip the confirmation prompt (required in non-interactive mode)",
    )
    p.set_defaults(func=cmd_files_rm)

    p = files_sub.add_parser("export", help="Download entire workspace as ZIP")
    p.add_argument("workspace_id")
    p.add_argument("--output", "-o", default=None, help="Output ZIP path (default: darkmage-<id>.zip)")
    p.set_defaults(func=cmd_files_export)

    p = files_sub.add_parser("status", help="Show sync status (local vs workspace)")
    p.add_argument("workspace_id")
    p.add_argument("path", nargs="?", default=".", help="Local directory (default: .)")
    p.set_defaults(func=cmd_files_status)

    p = files_sub.add_parser("tree", help="Show directory tree")
    p.add_argument("workspace_id")
    p.add_argument("path", nargs="?", default=".", help="Directory path (default: .)")
    p.add_argument("--depth", type=int, default=10, help="Max depth (default: 10)")
    p.set_defaults(func=cmd_ws_tree)

    # files sync (two-way synchronisation)
    sync = files_sub.add_parser("sync", help="Two-way sync local directory <-> workspace")
    sync_sub = sync.add_subparsers(dest="sync_command", required=True)

    p = sync_sub.add_parser("pull", help="Pull files from workspace to local")
    p.add_argument("workspace_id")
    p.add_argument("path", nargs="?", default=".", help="Local directory (default: .)")
    p.add_argument(
        "--auto-resolve", choices=["workspace", "local", "ask"], default="workspace",
        help="Conflict resolution (default: workspace wins)",
    )
    p.set_defaults(func=cmd_files_sync_pull)

    p = sync_sub.add_parser("push", help="Push files from local to workspace")
    p.add_argument("workspace_id")
    p.add_argument("path", nargs="?", default=".", help="Local directory (default: .)")
    p.add_argument(
        "--auto-resolve", choices=["local", "workspace", "ask"], default="local",
        help="Conflict resolution (default: local wins)",
    )
    p.set_defaults(func=cmd_files_sync_push)

    p = sync_sub.add_parser("diff", help="Show differences (no transfer)")
    p.add_argument("workspace_id")
    p.add_argument("path", nargs="?", default=".", help="Local directory (default: .)")
    p.set_defaults(func=cmd_files_sync_diff)

    p = sync_sub.add_parser("watch", help="Watch local dir and push changes to workspace")
    p.add_argument("workspace_id")
    p.add_argument("path", nargs="?", default=".", help="Local directory (default: .)")
    p.add_argument(
        "--interval", type=float, default=2.0, help="Polling interval in seconds (default: 2.0)"
    )
    p.set_defaults(func=cmd_files_sync_watch)

    p = sync_sub.add_parser("resolve", help="Resolve a conflict (local or workspace wins)")
    p.add_argument("workspace_id")
    p.add_argument("path", help="Relative path of conflicting file")
    p.add_argument(
        "wins", choices=["local", "workspace"], help="Which version wins"
    )
    p.add_argument(
        "--local-path", default=".", help="Local directory (default: .)"
    )
    p.set_defaults(func=cmd_files_sync_resolve)

    # APK / Godot (runner-manager)
    p = ws_sub.add_parser("apk", help="Build a debug Android APK from workspace web files")
    p.add_argument("workspace_id")
    p.add_argument("--web-dir", default=".", help="Directory with web files inside workspace (default: .)")
    p.add_argument("--output", default="android/app-debug.apk", help="Output .apk path inside workspace")
    p.add_argument("--app-name", default="", help="Application name (max 30 chars)")
    p.add_argument("--app-id", default=None, help="Application ID (default: app.darkmage.p<workspace_id_hex>)")
    p.add_argument("--version-code", type=int, default=1, help="Version code (default: 1)")
    p.set_defaults(func=cmd_ws_build_apk)

    p = ws_sub.add_parser("godot", help="Export a Godot 4 project to a Web build")
    p.add_argument("workspace_id")
    p.add_argument("--project-dir", default=".", help="Project directory inside workspace (default: .)")
    p.add_argument("--output-dir", default="godot-web", help="Output directory inside workspace (default: godot-web)")
    p.set_defaults(func=cmd_ws_export_godot)

    p = ws_sub.add_parser("blender", help="Convert a .blend file to .glb for Godot")
    p.add_argument("workspace_id")
    p.add_argument("blend_path", help="Path to .blend file inside workspace")
    p.add_argument("output", help="Output .glb path inside workspace")
    p.add_argument(
        "--preview", action="store_true", default=False, help="Also render a PNG preview"
    )
    p.add_argument(
        "--no-metadata", action="store_true", default=False, help="Skip metadata extraction"
    )
    p.set_defaults(func=cmd_ws_blender)

    p = ws_sub.add_parser("godot-tests", help="Run Godot Unit Test (GUT) tests headless")
    p.add_argument("workspace_id")
    p.add_argument("--test-dir", default="res://tests", help="Test directory (default: res://tests)")
    p.add_argument(
        "--test-suffix", default="_test.gd", help="Test file suffix (default: _test.gd)"
    )
    p.set_defaults(func=cmd_ws_godot_tests)

    p = ws_sub.add_parser("tiled-import", help="Import a Tiled .tmx map to Godot .tscn")
    p.add_argument("workspace_id")
    p.add_argument("tmx_path", help="Path to .tmx file inside workspace")
    p.add_argument("output", help="Output .tscn path inside workspace")
    p.set_defaults(func=cmd_ws_tiled_import)

    p = ws_sub.add_parser("ldtk-import", help="Import an LDtk .ldtk project to Godot .tscn")
    p.add_argument("workspace_id")
    p.add_argument("ldtk_path", help="Path to .ldtk file inside workspace")
    p.add_argument("output", help="Output .tscn path inside workspace")
    p.set_defaults(func=cmd_ws_ldtk_import)

    # sessions
    sess = sub.add_parser("session", help="Sessions")
    sess_sub = sess.add_subparsers(dest="session_command", required=True)

    p = sess_sub.add_parser("create", help="Create session")
    p.add_argument("workspace_id")
    p.add_argument("--title", default=None)
    p.set_defaults(func=cmd_session_create)

    p = sess_sub.add_parser("list", help="List sessions of a workspace")
    p.add_argument("workspace_id")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_session_list)

    p = sess_sub.add_parser("new", help="Создать новую сессию (в вашей рабочей области)")
    p.add_argument("--title", default=None)
    p.set_defaults(func=cmd_session_new)

    p = sess_sub.add_parser("all", help="Все сессии пользователя")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--archived", action="store_true")
    p.set_defaults(func=cmd_session_all)

    p = sess_sub.add_parser("runs", help="Запуски сессии")
    p.add_argument("session_id")
    p.set_defaults(func=cmd_session_runs)

    p = sess_sub.add_parser("files", help="Файлы сессии")
    p.add_argument("session_id")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_session_files)

    p = sess_sub.add_parser("read", help="Прочитать файл сессии")
    p.add_argument("session_id")
    p.add_argument("path")
    p.set_defaults(func=cmd_session_read)

    # repl
    repl = sub.add_parser("repl", help="Интерактивный режим (REPL)")
    repl.set_defaults(func=cmd_repl)

    # runs
    runs = sub.add_parser("run", help="Runs")
    runs_sub = runs.add_subparsers(dest="run_command", required=True)

    p = runs_sub.add_parser("create", help="Create a run")
    p.add_argument("session_id")
    p.add_argument("--prompt", required=True)
    p.add_argument("--model")
    p.add_argument("--plan-only", action="store_true", dest="plan_only")
    p.add_argument("--thorough", action="store_true", dest="thorough")
    p.add_argument(
        "--image",
        action="append",
        default=[],
        help="Image file to attach (PNG/JPEG/WEBP, max 1.5 MB, up to 3)",
    )
    p.add_argument(
        "--follow",
        action="store_true",
        default=False,
        help="Follow the run, handling approvals/questions interactively",
    )
    p.add_argument(
        "--no-follow",
        action="store_true",
        default=False,
        help="Create the run and exit even on a terminal",
    )
    p.set_defaults(func=cmd_run_create)

    p = runs_sub.add_parser("get", help="Get run")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_run_get)

    p = runs_sub.add_parser("message", help="Send a message to a running task")
    p.add_argument("run_id")
    p.add_argument("text", help="Message text, or '-' to read from stdin")
    p.set_defaults(func=cmd_run_message)

    p = runs_sub.add_parser("answer", help="Answer an ask_user question from the agent")
    p.add_argument("run_id")
    p.add_argument("question_id")
    p.add_argument("answer", nargs="+", help="Answer text(s), one per offered option")
    p.set_defaults(func=cmd_run_answer)

    p = runs_sub.add_parser("context", help="Show run context token usage")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_run_context)

    p = runs_sub.add_parser("revert", help="Revert a finished task")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_run_revert)

    p = runs_sub.add_parser("review", help="Review a finished task's diff")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_run_review)

    p = runs_sub.add_parser("stop", help="Stop a run")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_run_stop)

    p = runs_sub.add_parser("events", help="Stream run events (SSE)")
    p.add_argument("run_id")
    p.add_argument("--last-event-id", type=int, default=None, dest="last_event_id")
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Human-readable colored output (default JSON lines)",
    )
    p.set_defaults(func=cmd_run_events)

    p = runs_sub.add_parser("list", help="List runs in a workspace")
    p.add_argument("workspace_id")
    p.set_defaults(func=cmd_run_list)

    # approvals
    approvals = sub.add_parser(
        "approvals", help="Approve or reject pending tool calls"
    )
    approvals_sub = approvals.add_subparsers(
        dest="approvals_command", required=True
    )

    p = approvals_sub.add_parser(
        "approve", help="Approve a pending tool call (approval_id from events)"
    )
    p.add_argument("tool_call_id")
    p.add_argument(
        "--scope",
        choices=["call", "turn"],
        default="call",
        help="call = this tool call only, turn = the rest of the model turn",
    )
    p.set_defaults(func=cmd_approval_approve)

    p = approvals_sub.add_parser(
        "reject", help="Reject a pending tool call"
    )
    p.add_argument("tool_call_id")
    p.set_defaults(func=cmd_approval_reject)

    # processes
    proc = sub.add_parser("process", help="Background processes (workspace sandbox)")
    proc_sub = proc.add_subparsers(dest="process_command", required=True)

    p = proc_sub.add_parser("start", help="Start a background process")
    p.add_argument("workspace_id")
    p.add_argument("argv", nargs="+", help="Command and arguments (argv, no shell)")
    p.add_argument("--cwd", help="Working directory inside the workspace")
    p.add_argument("--port", type=int, help="Port the process listens on")
    p.set_defaults(func=cmd_process_start)

    p = proc_sub.add_parser("output", help="Get process output")
    p.add_argument("workspace_id")
    p.add_argument("process_id", nargs="?", default=None, help="Process ID (omits to list all)")
    p.set_defaults(func=cmd_process_output)

    p = proc_sub.add_parser("stop", help="Stop a background process")
    p.add_argument("workspace_id")
    p.add_argument("process_id")
    p.set_defaults(func=cmd_process_stop)

    # billing
    billing = sub.add_parser("payment", help="Платежи и тарифы")
    billing_sub = billing.add_subparsers(dest="payment_command", required=True)

    p = billing_sub.add_parser("create", help="Создать запрос на оплату (ссылка на сайт)")
    p.add_argument(
        "--product",
        choices=["standard_30d", "credits"],
        default="standard_30d",
        help="standard_30d — тариф Стандарт на 30 дней, credits — пакет кредитов",
    )
    p.add_argument(
        "--amount-rub",
        type=int,
        default=None,
        help="Сумма в рублях (только для credits; из доступных пакетов настроек сервера)",
    )
    p.set_defaults(func=cmd_payment_create)

    p = billing_sub.add_parser("list", help="Список своих платежей")
    p.set_defaults(func=cmd_payment_list)

    # admin
    admin = sub.add_parser("admin", help="Админские команды (только для владельца)")
    admin_sub = admin.add_subparsers(dest="admin_command", required=True)

    p = admin_sub.add_parser("status", help="Статус сервера и баланс OpenRouter")
    p.set_defaults(func=cmd_admin_status)

    # exec (-p is normalized to this command in main)
    p = sub.add_parser("exec", help="One-shot: создать run, дождаться ответа")
    p.add_argument(
        "prompt",
        nargs="*",
        help="Текст промпта; пусто или '-' — читать stdin",
    )
    p.add_argument("--session", dest="session_id", default=None, help="ID сессии")
    p.add_argument(
        "--output-format",
        dest="output_format",
        choices=["text", "json", "stream-json"],
        default=None,
        help="text (ответ), json (envelope) или stream-json (события)",
    )
    p.add_argument(
        "-o",
        "--output-last-message",
        dest="output_last_message",
        default=None,
        help="Записать финальный ответ в файл (0600)",
    )
    p.add_argument("--model", default=None, help="Модель или alias")
    p.add_argument("--plan-only", action="store_true", default=False)
    p.set_defaults(func=cmd_exec)

    # term
    term = sub.add_parser("term", help="Интерактивный терминал workspace (PTY)")
    term.add_argument("workspace_id")
    term.set_defaults(func=cmd_term)

    # tui
    tui = sub.add_parser("tui", help="Полноценный TUI клиент (Textual)")
    tui.add_argument("workspace_id")
    tui.add_argument("--run-id", default=None, dest="run_id", help="ID run для отслеживания")
    tui.set_defaults(func=cmd_tui)

    # config
    config = sub.add_parser("config", help="Управление конфигом (~/.darkmage-cli/config.json)")
    config_sub = config.add_subparsers(dest="config_command", required=True)

    p = config_sub.add_parser("show", help="Показать текущий конфиг")
    p.add_argument("--json", action="store_true", default=False, help="JSON-вывод")
    p.set_defaults(func=cmd_config_show)

    p = config_sub.add_parser("set", help="Установить параметры конфига")
    p.add_argument("--url", default=None, help="API base URL")
    p.add_argument("--token", default=None, help="Bearer auth token (security: prefer DARKMAGE_TOKEN env var)")
    p.add_argument("--runner-url", default=None, help="Runner-manager URL")
    p.add_argument("--runner-token", default=None, help="Runner-manager bearer token")
    p.add_argument(
        "--verbose", action="store_true", default=False, help="Показать обновлённый конфиг"
    )
    p.set_defaults(func=cmd_config_set)

    p = config_sub.add_parser("export", help="Экспорт конфигурации в JSON-файл")
    p.add_argument("output", help="Путь к выходному файлу")
    p.set_defaults(func=cmd_config_export)

    p = config_sub.add_parser("import", help="Импорт конфигурации из JSON-файла")
    p.add_argument("input", help="Путь к входному файлу")
    p.set_defaults(func=cmd_config_import)

    # git (Phase 3, requires backend GitHub App integration)
    git = sub.add_parser("git", help="Git-операции в workspace (требует бэкенд)")
    git_sub = git.add_subparsers(dest="git_command", required=True)

    p = git_sub.add_parser("clone", help="Клонировать репозиторий в workspace")
    p.add_argument("workspace_id")
    p.add_argument("url")
    p.add_argument("--ref", default=None, help="Ветка или тег")
    p.add_argument("--depth", type=int, default=1, help="Глубина клонирования")
    p.set_defaults(func=cmd_git_clone)

    p = git_sub.add_parser("commit", help="Зафиксировать изменения")
    p.add_argument("workspace_id")
    p.add_argument("message")
    p.add_argument("--branch", default=None, help="Ветка для коммита")
    p.set_defaults(func=cmd_git_commit)

    p = git_sub.add_parser("push", help="Отправить изменения в удалённый репозиторий")
    p.add_argument("workspace_id")
    p.add_argument("--branch", default=None, help="Ветка для пуша")
    p.set_defaults(func=cmd_git_push)

    p = git_sub.add_parser("pr", help="Создать pull request")
    p.add_argument("workspace_id")
    p.add_argument("title")
    p.add_argument("--body", default=None, help="Описание PR")
    p.add_argument("--base", default="main", help="Базовая ветка")
    p.add_argument("--head", default=None, help="Ветка-источник")
    p.set_defaults(func=cmd_git_pr_create)

    # mcp (Phase 3, requires backend MCP server)
    mcp = sub.add_parser("mcp", help="MCP инструменты (требует бэкенд MCP-сервер)")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)

    p = mcp_sub.add_parser("list", help="Список доступных MCP-инструментов")
    p.set_defaults(func=cmd_mcp_list)

    p = mcp_sub.add_parser("call", help="Вызвать MCP-инструмент")
    p.add_argument("tool", help="Имя инструмента")
    p.add_argument("workspace_id", help="ID рабочего пространства")
    p.add_argument(
        "arguments",
        nargs="*",
        help="Аргументы в формате ключ=значение",
    )
    p.set_defaults(func=cmd_mcp_call)

    # chat
    p = sub.add_parser(
        "chat", help="Chat completion (streams by default, --json for scripts)"
    )
    p.add_argument(
        "message",
        nargs="?",
        default=None,
        help="Message text, '-' or omitted to read stdin",
    )
    p.add_argument("--system")
    p.add_argument("--model")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--max-tokens", type=int, default=None, dest="max_tokens")
    p.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Machine-readable envelope on stdout",
    )
    p.add_argument(
        "--no-stream",
        action="store_true",
        default=False,
        dest="no_stream",
        help="Wait for the complete response instead of streaming",
    )
    p.set_defaults(func=cmd_chat)

    # health
    sub.add_parser("health", help="Liveness").set_defaults(func=cmd_health)
    sub.add_parser("ready", help="Readiness").set_defaults(func=cmd_ready)

    doctor = sub.add_parser("doctor", help="Проверка окружения и подключения")
    doctor.add_argument(
        "--url", default=None, help="API base URL (overrides config and env)"
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="JSON-вывод",
    )
    doctor.set_defaults(func=cmd_doctor)

    sub.add_parser("login", help="Войти в систему (интерактивно)").set_defaults(func=cmd_login_alias)
    sub.add_parser("start", help="Запустить интерактивный сеанс (как в Claude Code)").set_defaults(func=cmd_start)
    completion = sub.add_parser("completion", help="Генерация скриптов автодополнения для shell")
    completion.add_argument(
        "shell",
        choices=["bash", "zsh", "fish"],
        default="bash",
        nargs="?",
        help="Тип оболочки (bash, zsh, fish)",
    )
    completion.set_defaults(func=cmd_completion)

    history = sub.add_parser("history", help="История команд CLI")
    history.add_argument(
        "number", nargs="?", type=int, default=None, help="Номер команды для повтора"
    )
    history.set_defaults(func=cmd_history)

    parallel = sub.add_parser(
        "parallel", help="Запуск нескольких команд параллельно"
    )
    parallel.add_argument(
        "commands",
        nargs="+",
        help="Команды для параллельного выполнения (каждая как отдельная строка)",
    )
    parallel.set_defaults(func=cmd_parallel)

    return parser


_SECRET_FLAGS = (
    "--password",
    "-p",
    "--token",
    "--runner-token",
    "--api-key",
    "--apikey",
    "--secret",
    "--client-secret",
    "--refresh-token",
    "--access-token",
    "--auth-token",
    "--bearer",
)


def _mask_secrets(command: str) -> str:
    """Hide secret flag values and login passwords in saved history."""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()

    masked: list[str] = []
    index = 0
    while index < len(parts):
        part = parts[index]
        if part in _SECRET_FLAGS:
            masked.append(part)
            if index + 1 < len(parts):
                masked.append("***")
                index += 2
            else:
                index += 1
            continue
        name, separator, _value = part.partition("=")
        if separator and name in _SECRET_FLAGS:
            masked.append(f"{name}=***")
        else:
            masked.append(part)
        index += 1

    # `darkmage login <email> <password>` / `darkmage auth login ...`.
    if len(parts) >= 3 and parts[0] == "login":
        masked[-1] = "***"
    if len(parts) >= 4 and parts[0] == "auth" and parts[1] == "login":
        masked[-1] = "***"
    return " ".join(masked)


# Backwards-compatible name for callers/tests that used the old helper.
_mask_password = _mask_secrets


def _record_history(command_args: list[str]) -> None:
    """Append a masked command to history with safe directory/file handling."""
    from .security import HISTORY_FILE

    history_file = HISTORY_FILE
    history_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(history_file, "r", encoding="utf-8") as handle:
            history = json.load(handle)
    except (OSError, json.JSONDecodeError):
        history = []

    history.append(
        {
            "command": _mask_secrets(" ".join(command_args)),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
    )
    write_private_json(history_file, history[-100:])


def _normalize_exec_alias(argv: list[str]) -> list[str]:
    """Map `darkmage -p ...` / `darkmage --print ...` to `darkmage exec ...`."""
    if argv and argv[0] in ("-p", "--print"):
        return ["exec"] + argv[1:]
    if argv and argv[0].startswith("--print="):
        return ["exec", argv[0].split("=", 1)[1]] + argv[1:]
    return argv


def main(argv: list[str] | None = None) -> int:
    command_args = list(argv) if argv is not None else sys.argv[1:]
    normalized_argv = _normalize_exec_alias(command_args)
    parser = build_parser()
    args = parser.parse_args(normalized_argv)

    client = DarkmageClient(base_url=args.url)
    if args.runner_url:
        client.runner_url = args.runner_url.rstrip("/")
    if args.runner_token:
        client.runner_token = args.runner_token
    # Advisory only and on stderr, so JSON/one-shot stdout stays clean.
    warn_insecure_url(client.base_url)

    # Если не указана команда — интерактивный вход как в Claude Code:
    #   нет токена  → вход / регистрация
    #   есть токен  → список рабочих зон и запуск TUI
    if not getattr(args, "command", None):
        config = load_config()
        if config.get("token"):
            return cmd_start(args, client)
        else:
            return cmd_auth_interactive(args, client)

    try:
        func = args.func
    except AttributeError:
        parser.print_help()
        return 1

    exit_code = 0
    try:
        result = func(args, client)
        if isinstance(result, int):
            exit_code = result
        # Record command in history (secrets are masked, never stored in plain text).
        try:
            _record_history(command_args)
        except OSError as exc:
            if getattr(args, "verbose", False):
                print(f"history: {exc}", file=sys.stderr)
    except DarkmageError as exc:
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        if getattr(args, "json", False):
            print_json(
                {
                    "schema_version": 1,
                    "error": {
                        "message": str(exc),
                        "status_code": exc.status_code,
                        "retryable": exc.retryable,
                    },
                }
            )
            if exc.status_code in (401, 403):
                exit_code = 3
            elif exc.status_code in (400, 404, 409, 422):
                exit_code = 2
            else:
                exit_code = 1
        else:
            print_error(str(exc))
    finally:
        client.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
