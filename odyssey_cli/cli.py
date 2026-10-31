from __future__ import annotations

import argparse
import getpass
import json
import sys
from typing import Any, cast

from .client import OdysseyClient, OdysseyError, print_error, print_json
from .config import get_token, load_config, save_config


def cmd_register(args: argparse.Namespace, client: OdysseyClient) -> None:
    data = client.register(args.email, args.password, args.full_name)
    print_json(data)


def cmd_login(args: argparse.Namespace, client: OdysseyClient) -> None:
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


def cmd_logout(args: argparse.Namespace, client: OdysseyClient) -> None:
    client.logout()
    print("Logged out.")


def cmd_auth_interactive(args: argparse.Namespace, client: OdysseyClient) -> None:
    """Интерактивный вход/регистрация как в Claude Code."""

    print("👋 Добро пожаловать в Odyssey AI")
    print()

    # Проверяем, уже есть ли токен
    config = load_config()
    if config.get("token") and config.get("base_url"):
        print(f"Вы уже вошли как токен: {config['token'][:8]}...")
        print("Используйте 'odyssey auth logout' для выхода.")
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
    except OdysseyError as exc:
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
    except OdysseyError as exc:
        print(f"Ошибка регистрации: {exc}")
        return

    # Предлагаем открыть рабочую зону
    print()
    print("🎉 Готово! Теперь вы можете:")
    print("  odyssey workspace list   — посмотреть рабочие зоны")
    print("  odyssey tui <workspace_id> — открыть интерактивный терминал")


def cmd_login_alias(args: argparse.Namespace, client: OdysseyClient) -> None:
    """Alias для auth interactive."""
    cmd_auth_interactive(args, client)


def cmd_start(args: argparse.Namespace, client: OdysseyClient) -> None:
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

    # Показываем рабочие зоны
    print("\n📋 Ваши рабочие зоны:")
    try:
        workspaces = client.workspace_list()
        if not workspaces:
            print("   Рабочие зоны не найдены. Создайте новую: odyssey workspace create --name <имя>")
            return
        for i, ws in enumerate(workspaces, 1):
            status = _color_status(ws.get("status", ""))
            print(f"  {i}. {ws.get('name')} ({ws.get('id')}) [{status}]")
    except OdysseyError as exc:
        print(f"Ошибка получения рабочих зон: {exc}")
        return

    # Выбор рабочей зоны
    choice = input("\nВыберите рабочую зону (номер) или нажмите Enter для отмены: ").strip()
    if not choice:
        print("Отменено.")
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(workspaces):
            print("Неверный номер.")
            return
        workspace_id = workspaces[idx]["id"]
    except ValueError:
        print("Неверный номер.")
        return

    # Запуск TUI
    print(f"\n🚀 Запуск рабочей зоны {workspaces[idx]['name']}...")
    from .tui import run_tui

    run_tui(
        base_url=client.base_url,
        token=client.token,
        workspace_id=workspace_id,
    )


def cmd_me(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.me())


def cmd_usage(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.usage())


def cmd_memory_get(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.memory_get())


def cmd_memory_put(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.memory_put(args.content))


def cmd_ws_create(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.workspace_create(args.name))


def cmd_ws_list(args: argparse.Namespace, client: OdysseyClient) -> None:
    workspaces = client.workspace_list(args.limit)
    if args.json or not sys.stdout.isatty():
        print_json(workspaces)
        return
    print(f"{'ID':<38} {'Имя':<30} {'Статус':<15} {'Режим':<10}")
    print("-" * 85)
    for w in workspaces:
        print(
            f"{w.get('id', ''):<38} "
            f"{w.get('name', ''):<30} "
            f"{_color_status(w.get('status', '')):<15} "
            f"{w.get('approval_mode', ''):<10}"
        )
    if not workspaces:
        print("Нет рабочих зон.")


def cmd_ws_get(args: argparse.Namespace, client: OdysseyClient) -> None:
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


def cmd_ws_update(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(
        client.workspace_update(args.workspace_id, args.name, args.approval_mode)
    )


def cmd_ws_start(args: argparse.Namespace, client: OdysseyClient) -> None:
    data = client.workspace_start(args.workspace_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
        return
    print(f"Рабочая зона запущена: {data.get('id')}")
    print(f"Статус: {_color_status(data.get('status', ''))}")


def cmd_ws_stop(args: argparse.Namespace, client: OdysseyClient) -> None:
    data = client.workspace_stop(args.workspace_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
        return
    print(f"Рабочая зона остановлена: {data.get('id')}")
    print(f"Статус: {_color_status(data.get('status', ''))}")


def cmd_ws_delete(args: argparse.Namespace, client: OdysseyClient) -> None:
    client.workspace_delete(args.workspace_id)
    print(f"Workspace {args.workspace_id} deleted.")


def cmd_ws_files(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.workspace_files(args.workspace_id, args.path))


def cmd_ws_read(args: argparse.Namespace, client: OdysseyClient) -> None:
    data = client.workspace_file_content(
        args.workspace_id, args.path, args.offset, args.limit
    )
    print(data.get("content", ""))


def cmd_ws_edit(args: argparse.Namespace, client: OdysseyClient) -> None:
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


def cmd_ws_search(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.workspace_search(args.workspace_id, args.query, args.path))


def cmd_ws_download(args: argparse.Namespace, client: OdysseyClient) -> None:
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


def cmd_ws_upload(args: argparse.Namespace, client: OdysseyClient) -> None:
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


def cmd_ws_tree(args: argparse.Namespace, client: OdysseyClient) -> None:
    """Show directory tree for workspace."""
    if args.json:
        result = _tree_to_dict(client, args.workspace_id, args.path, 0, args.depth)
        print_json(result)
        return
    print(f"{args.workspace_id}/{args.path}")
    _print_tree(client, args.workspace_id, args.path, "", 0, args.depth)


def _tree_to_dict(
    client: OdysseyClient,
    workspace_id: str,
    path: str,
    depth: int,
    max_depth: int,
) -> dict:
    """Build a nested dict representation of the workspace tree."""
    try:
        data = client.workspace_files(workspace_id, path)
    except OdysseyError:
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
    client: OdysseyClient,
    workspace_id: str,
    path: str,
    prefix: str,
    depth: int,
    max_depth: int,
) -> None:
    """Recursively print directory tree."""
    try:
        data = client.workspace_files(workspace_id, path)
    except OdysseyError as exc:
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


def cmd_session_create(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.session_create(args.workspace_id, args.title))


def cmd_session_list(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.session_list(args.workspace_id, args.limit))


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
            detail = f"{data.get('name', '')} path={data.get('path', '')}"
        elif etype == "approval.resolved":
            detail = f"{data.get('decision', '')} scope={data.get('scope', '')}"
        elif etype == "run.completed":
            detail = f"finish_reason={data.get('finish_reason', '')}"
        elif etype == "run.failed":
            detail = f"error={data.get('error', '')}"
        elif etype == "context.compacted":
            detail = f"dropped={data.get('dropped_messages', '')} before={data.get('tokens_before', '')} after={data.get('tokens_after', '')}"
        elif etype == "agent.question":
            detail = data.get("question", "")
        elif etype == "agent.answer":
            detail = f"answers={data.get('answers', [])}"
        return f"[{eid}] {etype}: {detail}"
    return f"[{eid}] {etype}: {data}"


def cmd_run_create(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(
        client.run_create(
            args.session_id,
            args.prompt,
            args.model,
            args.plan_only,
            args.thorough,
            args.image if args.image else None,
        )
    )


def cmd_run_get(args: argparse.Namespace, client: OdysseyClient) -> None:
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


def cmd_run_message(args: argparse.Namespace, client: OdysseyClient) -> None:
    text = args.text
    if text == "-":
        text = sys.stdin.read().strip()
    print_json(client.run_message(args.run_id, text))


def cmd_run_answer(args: argparse.Namespace, client: OdysseyClient) -> None:
    answers = args.answer if isinstance(args.answer, list) else [args.answer]
    print_json(client.run_answer(args.run_id, args.question_id, answers))


def cmd_run_context(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.run_context(args.run_id))


def cmd_run_revert(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.run_revert(args.run_id))


def cmd_run_review(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.run_review(args.run_id))


def cmd_run_list(args: argparse.Namespace, client: OdysseyClient) -> None:
    runs = client.run_list(args.workspace_id)
    if args.json or not sys.stdout.isatty():
        print_json(runs)
        return
    print(f"{'ID':<38} {'Статус':<15} {'Модель':<20} {'Промпт':<40} {'Создан':<16}")
    print("-" * 115)
    for r in runs:
        print(
            f"{r.get('id', ''):<38} "
            f"{_color_status(r.get('status', '')):<15} "
            f"{r.get('model', '-'):<20} "
            f"{r.get('prompt', '')[:40]:<40} "
            f"{r.get('created_at', '')[:16]}"
        )
    if not runs:
        print("Нет ran.")


def cmd_run_stop(args: argparse.Namespace, client: OdysseyClient) -> None:
    data = client.run_stop(args.run_id)
    if args.json or not sys.stdout.isatty():
        print_json(data)
        return
    print(f"Run остановлен: {data.get('id')}")
    print(f"Статус: {_color_status(data.get('status', ''))}")


def cmd_run_events(args: argparse.Namespace, client: OdysseyClient) -> None:
    last_id = args.last_event_id
    pretty = args.pretty
    for ev in client.run_events_parsed(args.run_id, last_id):
        line = _format_event(ev)
        if pretty:
            print(_color(line, ev.get("event", "")))
        else:
            print(json.dumps(ev, ensure_ascii=False))
        if ev.get("event") in {"run.completed", "run.failed", "run.cancelled"}:
            break


def cmd_process_start(args: argparse.Namespace, client: OdysseyClient) -> None:
    argv = args.argv
    print_json(
        client.process_start(
            args.workspace_id, argv, args.cwd, args.port
        )
    )


def cmd_process_output(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(
        client.process_output(args.workspace_id, args.process_id)
    )


def cmd_process_stop(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.process_stop(args.workspace_id, args.process_id))


def cmd_payment_create(args: argparse.Namespace, client: OdysseyClient) -> None:
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


def cmd_payment_list(args: argparse.Namespace, client: OdysseyClient) -> None:
    payments = client.payment_list()
    for p in payments:
        print(
            f"{p.get('id')}  {p.get('product')}  {p.get('amount_rub')} ₽  "
            f"{p.get('status')}  {p.get('created_at', '')[:16]}"
        )
    if not payments:
        print("Платежей нет.")


def cmd_admin_status(args: argparse.Namespace, client: OdysseyClient) -> None:
    data = client.admin_status()
    balance = data.get("openrouter_balance_usd")
    low = data.get("openrouter_balance_low")
    low_threshold = data.get("openrouter_balance_low_usd")
    print("Статус сервера (админ):")
    if balance is None:
        print("  Баланс OpenRouter: недоступен")
    else:
        print(f"  Баланс OpenRouter: ${balance} USD")
        if low:
            print(f"  ВНИМАНИЕ: баланс ниже порога ${low_threshold} USD")
        else:
            print(f"  Порог низкого баланса: ${low_threshold} USD")


def cmd_term(args: argparse.Namespace, client: OdysseyClient) -> None:
    """Интерактивный терминал workspace (PTY через runner-manager)."""
    import asyncio
    import os
    import pty
    import select
    import subprocess
    import sys
    import termios
    import tty

    import websockets  # type: ignore[import-not-found]

    result = client.pty_create(args.workspace_id)
    session_id = result["session_id"]
    print(f"PTY session {session_id}. Ctrl-D or 'exit' to quit.\n", end="")

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["sh"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    old_settings = termios.tcgetattr(sys.stdin.fileno())

    try:
        tty.setraw(sys.stdin.fileno())
        os.set_blocking(master_fd, False)

        ws_url = (
            client.base_url.replace("http://", "ws://")
            .replace("https://", "wss://")
            + f"/workspaces/{args.workspace_id}/pty/{session_id}"
        )

        extra_headers = (
            {"Authorization": f"Bearer {client.token}"} if client.token else None
        )

        async def run():
            async with websockets.connect(ws_url, additional_headers=extra_headers) as ws:
                loop = asyncio.get_event_loop()

                async def pty_to_ws():
                    while True:
                        await asyncio.sleep(0.01)
                        r, _, _ = await loop.run_in_executor(
                            None, select.select, [master_fd], [], [], 0
                        )
                        if r:
                            try:
                                data = await loop.run_in_executor(
                                    None, os.read, master_fd, 4096
                                )
                                if not data:
                                    break
                                await ws.send(data)
                            except OSError:
                                break

                async def ws_to_pty():
                    try:
                        while True:
                            data = await ws.recv()
                            if isinstance(data, bytes):
                                os.write(master_fd, data)
                            else:
                                os.write(master_fd, data.encode())
                    except (websockets.ConnectionClosed, Exception):  # noqa: S110, BLE001
                        pass

                await asyncio.gather(pty_to_ws(), ws_to_pty())

        asyncio.run(run())
    finally:
        try:
            os.close(master_fd)
        except Exception:  # noqa: S110, BLE001
            pass
        try:
            proc.terminate()
        except Exception:  # noqa: S110, BLE001
            pass
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        except Exception:  # noqa: S110, BLE001
            pass
        try:
            client.pty_stop(args.workspace_id, session_id)
        except Exception:  # noqa: S110, BLE001
            pass


def cmd_tui(args: argparse.Namespace, client: OdysseyClient) -> None:
    """Запустить полноценный TUI клиент (Textual)."""
    from .tui import run_tui

    run_tui(
        base_url=client.base_url,
        token=client.token,
        workspace_id=args.workspace_id,
        run_id=args.run_id,
    )


def cmd_config_show(args: argparse.Namespace, client: OdysseyClient) -> None:
    from .config import load_config
    from .security import CONFIG_FILE

    config = load_config()
    if args.json:
        print_json(config)
        return
    if not config:
        print("Конфиг пуст. Файл: " + str(CONFIG_FILE))
        return
    print(f"Конфиг ({CONFIG_FILE}):")
    for key, value in config.items():
        if key == "token" and value:
            value = value[:8] + "…" + value[-4:] if len(value) > 12 else "***"
        print(f"  {key}: {value}")


def cmd_config_set(args: argparse.Namespace, client: OdysseyClient) -> None:
    from .config import load_config, set_base_url

    changed = False
    if args.url is not None:
        set_base_url(args.url)
        changed = True
    if not changed:
        print("Нечего менять: укажите --url")
        return
    print("Конфиг обновлён.")
    if args.verbose:
        print_json(load_config())


def cmd_config_export(args: argparse.Namespace, client: OdysseyClient) -> None:
    import json

    from .config import load_config

    config = load_config()
    if not config:
        print("Конфиг пуст, нечего экспортировать.")
        return
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"Конфиг экспортирован в {args.output}")
    except OSError as exc:
        print(f"Ошибка записи файла: {exc}")


def cmd_config_import(args: argparse.Namespace, client: OdysseyClient) -> None:
    import json


    try:
        with open(args.input, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Ошибка чтения файла: {exc}")
        return
    save_config(config)
    print(f"Конфиг импортирован из {args.input}")


def cmd_history(args: argparse.Namespace, client: OdysseyClient) -> None:
    """Показать или повторить предыдущие команды CLI."""
    import json

    from .security import CONFIG_DIR

    history_file = CONFIG_DIR / "history.json"
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


def cmd_parallel(args: argparse.Namespace, client: OdysseyClient) -> None:
    """Выполнить несколько команд параллельно."""
    import asyncio
    import shlex

    async def run_one(cmd_str: str) -> tuple[int, str]:
        """Run a single command string and return (exit_code, output)."""
        try:
            parts = shlex.split(cmd_str)
            old_argv = sys.argv
            sys.argv = ["odyssey"] + parts
            try:
                sub_parser = build_parser()
                sub_args = sub_parser.parse_args(parts)
                func = sub_args.func
                sub_client = OdysseyClient(base_url=sub_args.url)
                try:
                    func(sub_args, sub_client)
                finally:
                    sub_client.close()
                return 0, ""
            except SystemExit as exc:
                return int(exc.code) if exc.code is not None else 0, ""
            except Exception as exc:  # noqa: BLE001
                return 1, str(exc)
            finally:
                sys.argv = old_argv
        except SystemExit as exc:
            return int(exc.code) if exc.code is not None else 0, ""
        except Exception as exc:  # noqa: BLE001
            return 1, str(exc)

    async def run_all() -> None:
        tasks = [run_one(cmd) for cmd in args.commands]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                print(f"[{i + 1}] Ошибка: {result}")
            else:
                code: int = result[0]
                status = "OK" if code == 0 else f"Ошибка ({code})"
                print(f"[{i + 1}] {status}: {args.commands[i]}")

    asyncio.run(run_all())


def cmd_git_clone(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.git_clone(args.workspace_id, args.url, args.ref, args.depth))


def cmd_git_commit(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.git_commit(args.workspace_id, args.message, args.branch))


def cmd_git_push(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.git_push(args.workspace_id, args.branch))


def cmd_git_pr_create(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(
        client.git_pr_create(
            args.workspace_id, args.title, args.body, args.base, args.head
        )
    )


def cmd_mcp_list(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.mcp_list())


def cmd_mcp_call(args: argparse.Namespace, client: OdysseyClient) -> None:
    arguments: dict[str, Any] = {}
    if args.arguments:
        for item in args.arguments:
            if "=" not in item:
                print_error(f"Неверный формат аргумента: {item} (ожидается ключ=значение)")
            key, value = item.split("=", 1)
            arguments[key] = value
    print_json(client.mpc_call(args.tool, arguments, args.workspace_id))


def cmd_chat(args: argparse.Namespace, client: OdysseyClient) -> None:
    messages = [{"role": "user", "content": args.message}]
    if args.system:
        messages.insert(0, {"role": "system", "content": args.system})
    data = client.chat_completion(messages, args.model, args.temperature, args.max_tokens)
    for choice in data.get("choices", []):
        msg = choice.get("message", {})
        print(msg.get("content", ""))
    if data.get("usage"):
        print_json(data["usage"])


def cmd_health(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.health())


def cmd_ready(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.ready())


def cmd_doctor(args: argparse.Namespace, client: OdysseyClient) -> None:
    """Проверка окружения и подключения к серверу Odyssey."""
    print("🩺 Проверка состояния Odyssey CLI\n")

    # 1. Конфигурация
    config = load_config()
    api_url = args.url or config.get("base_url", "http://localhost:8000")
    token = get_token()

    print(f"📍 API URL: {api_url}")
    if token:
        print(f"🔑 Токен:   {'*' * (len(token) - 4) + token[-4:] if len(token) > 4 else '***'}")
    else:
        print("🔑 Токен:   не настроен")

    print()

    # 2. Health check
    print("🏥 Health check:")
    try:
        client.base_url = api_url
        client.token = token
        h = client.health()
        print(f"   ✅ /health:  {h.get('status', 'unknown')}")
    except Exception as exc:  # noqa: BLE001
        print(f"   ❌ /health:  ошибка — {exc}")

    # 3. Ready check
    print("🚀 Readiness check:")
    try:
        r = client.ready()
        print(f"   ✅ /ready:   {r.get('status', 'unknown')}")
    except Exception as exc:  # noqa: BLE001
        print(f"   ❌ /ready:   ошибка — {exc}")

    print()
    print("Готово к работе." if config.get("base_url") and config.get("token") else "⚠️  Настройте URL и токен через 'odyssey config set'.")


def cmd_completion(args: argparse.Namespace, client: OdysseyClient) -> None:
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
    return """# Odyssey CLI bash completion
# Source this file in your ~/.bashrc:
#   source <(odyssey completion bash)

_odyssey_complete() {
    local cur prev words cword
    _init_completion || return

    case "$prev" in
        odyssey)
            COMPREPLY=( $(compgen -W 'auth me usage memory workspace files session run process payment admin term tui config git mcp chat health ready doctor completion' -- "$cur") )
            ;;
        auth)
            COMPREPLY=( $(compgen -W 'register login logout' -- "$cur") )
            ;;
        workspace)
            COMPREPLY=( $(compgen -W 'create list get update start stop delete' -- "$cur") )
            ;;
        files)
            COMPREPLY=( $(compgen -W 'list read edit search' -- "$cur") )
            ;;
        session)
            COMPREPLY=( $(compgen -W 'create list' -- "$cur") )
            ;;
        run)
            COMPREPLY=( $(compgen -W 'create get message answer context revert review stop list events' -- "$cur") )
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
        *)
            COMPREPLY=()
            ;;
    esac
}
complete -F _odyssey_complete odyssey"""


def _zsh_completion_script() -> str:
    return """# Odyssey CLI zsh completion
# Source this file in your ~/.zshrc:
#   source <(odyssey completion zsh)

#compdef odyssey

_odyssey_complete() {
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
    )
    _describe 'command' commands
}

_odyssey "$@"
"""


def _fish_completion_script() -> str:
    return """# Odyssey CLI fish completion
# Save this file to ~/.config/fish/completions/odyssey.fish

complete -c odyssey -f -a 'auth' -d 'Authentication commands'
complete -c odyssey -f -a 'me' -d 'Current user info'
complete -c odyssey -f -a 'usage' -d 'Spend windows'
complete -c odyssey -f -a 'memory' -d 'User memory management'
complete -c odyssey -f -a 'workspace' -d 'Workspace management'
complete -c odyssey -f -a 'files' -d 'Workspace files'
complete -c odyssey -f -a 'session' -d 'Session management'
complete -c odyssey -f -a 'run' -d 'Task runs management'
complete -c odyssey -f -a 'process' -d 'Background processes'
complete -c odyssey -f -a 'payment' -d 'Payments and billing'
complete -c odyssey -f -a 'admin' -d 'Admin commands'
complete -c odyssey -f -a 'term' -d 'Interactive terminal (PTY)'
complete -c odyssey -f -a 'tui' -d 'Full TUI client'
complete -c odyssey -f -a 'config' -d 'Configuration management'
complete -c odyssey -f -a 'git' -d 'Git operations'
complete -c odyssey -f -a 'mcp' -d 'MCP tools'
complete -c odyssey -f -a 'chat' -d 'Chat completion'
complete -c odyssey -f -a 'health' -d 'Liveness check'
complete -c odyssey -f -a 'ready' -d 'Readiness check'
complete -c odyssey -f -a 'doctor' -d 'Environment diagnostics'
complete -c odyssey -f -a 'completion' -d 'Shell completion scripts'

# Subcommand completions
complete -c odyssey -f -a 'register login logout' -d 'auth subcommands' -n '__fish_seen_subcommand auth'
complete -c odyssey -f -a 'create list get update start stop delete' -d 'workspace subcommands' -n '__fish_seen_subcommand workspace'
complete -c odyssey -f -a 'list read edit search' -d 'files subcommands' -n '__fish_seen_subcommand files'
complete -c odyssey -f -a 'create list' -d 'session subcommands' -n '__fish_seen_subcommand session'
complete -c odyssey -f -a 'create get message answer context revert review stop list events' -d 'run subcommands' -n '__fish_seen_subcommand run'
complete -c odyssey -f -a 'start output stop' -d 'process subcommands' -n '__fish_seen_subcommand process'
complete -c odyssey -f -a 'create list' -d 'payment subcommands' -n '__fish_seen_subcommand payment'
complete -c odyssey -f -a 'clone commit push pr' -d 'git subcommands' -n '__fish_seen_subcommand git'
complete -c odyssey -f -a 'list call' -d 'mcp subcommands' -n '__fish_seen_subcommand mcp'
complete -c odyssey -f -a 'show set export import' -d 'config subcommands' -n '__fish_seen_subcommand config'
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odyssey",
        description="CLI for the Odyssey AI platform",
    )
    parser.add_argument(
        "--url", default=None, help="API base URL (default: ODYSSEY_API_URL or http://localhost:8000)"
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
    sub = parser.add_subparsers(dest="command", required=True)

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

    p = files_sub.add_parser("upload", help="Upload local file to workspace")
    p.add_argument("local_path")
    p.add_argument("workspace_id")
    p.add_argument("remote_path")
    p.set_defaults(func=cmd_ws_upload)

    p = files_sub.add_parser("tree", help="Show directory tree")
    p.add_argument("workspace_id")
    p.add_argument("path", nargs="?", default=".", help="Directory path (default: .)")
    p.add_argument("--depth", type=int, default=10, help="Max depth (default: 10)")
    p.set_defaults(func=cmd_ws_tree)

    # sessions
    sess = sub.add_parser("session", help="Sessions")
    sess_sub = sess.add_subparsers(dest="session_command", required=True)

    p = sess_sub.add_parser("create", help="Create session")
    p.add_argument("workspace_id")
    p.add_argument("--title", default=None)
    p.set_defaults(func=cmd_session_create)

    p = sess_sub.add_parser("list", help="List sessions")
    p.add_argument("workspace_id")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_session_list)

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
    config = sub.add_parser("config", help="Управление конфигом (~/.odyssey-cli/config.json)")
    config_sub = config.add_subparsers(dest="config_command", required=True)

    p = config_sub.add_parser("show", help="Показать текущий конфиг")
    p.add_argument("--json", action="store_true", default=False, help="JSON-вывод")
    p.set_defaults(func=cmd_config_show)

    p = config_sub.add_parser("set", help="Установить параметры конфига")
    p.add_argument("--url", default=None, help="API base URL")
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
    p = sub.add_parser("chat", help="Chat completion")
    p.add_argument("message")
    p.add_argument("--system")
    p.add_argument("--model")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--max-tokens", type=int, default=None, dest="max_tokens")
    p.set_defaults(func=cmd_chat)

    # health
    sub.add_parser("health", help="Liveness").set_defaults(func=cmd_health)
    sub.add_parser("ready", help="Readiness").set_defaults(func=cmd_ready)
    sub.add_parser("doctor", help="Проверка окружения и подключения").set_defaults(func=cmd_doctor)
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    client = OdysseyClient(base_url=args.url)
    try:
        func = args.func
    except AttributeError:
        parser.print_help()
        return 1

    try:
        func(args, client)
        # Record command in history
        import json

        from .security import CONFIG_DIR

        history_file = CONFIG_DIR / "history.json"
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (OSError, json.JSONDecodeError):
            history = []
        history.append({"command": " ".join(sys.argv[1:]), "timestamp": str(__import__("datetime").datetime.now())})
        # Keep only last 100 entries
        history = history[-100:]
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except OdysseyError as exc:
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        print_error(str(exc))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
