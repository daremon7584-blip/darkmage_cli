from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .client import OdysseyClient, OdysseyError, print_error, print_json


def cmd_register(args: argparse.Namespace, client: OdysseyClient) -> None:
    data = client.register(args.email, args.password, args.full_name)
    print_json(data)


def cmd_login(args: argparse.Namespace, client: OdysseyClient) -> None:
    from .config import set_token

    data = client.login(args.email, args.password)
    token = data.get("access_token")
    if token:
        set_token(token)
        client.token = token
        print(f"Logged in as {args.email}. Token saved.")
    else:
        print_json(data)


def cmd_logout(args: argparse.Namespace, client: OdysseyClient) -> None:
    client.logout()
    print("Logged out.")


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
    print_json(client.workspace_list(args.limit))


def cmd_ws_get(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.workspace_get(args.workspace_id))


def cmd_ws_update(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(
        client.workspace_update(args.workspace_id, args.name, args.approval_mode)
    )


def cmd_ws_start(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.workspace_start(args.workspace_id))


def cmd_ws_stop(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.workspace_stop(args.workspace_id))


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
    print_json(client.run_get(args.run_id))


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
    for r in runs:
        print(
            f"{r.get('id')}  {r.get('status')}  {r.get('model', '-')}  "
            f"{r.get('prompt', '')[:60]}  {r.get('created_at', '')[:16]}"
        )
    if not runs:
        print("Нет ran.")


def cmd_run_stop(args: argparse.Namespace, client: OdysseyClient) -> None:
    print_json(client.run_stop(args.run_id))


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
    from .config import CONFIG_FILE, load_config

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
    from .config import load_config, set_base_url, set_token

    changed = False
    if args.url is not None:
        set_base_url(args.url)
        changed = True
    if args.token is not None:
        set_token(args.token)
        changed = True
    if not changed:
        print("Нечего менять: укажите --url и/или --token")
        return
    print("Конфиг обновлён.")
    if args.verbose:
        print_json(load_config())


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
        help="Принудительный JSON-вывод",
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
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.set_defaults(func=cmd_login)

    p = auth_sub.add_parser("logout", help="Remove saved token")
    p.set_defaults(func=cmd_logout)

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
    p.add_argument("--token", default=None, help="Bearer токен")
    p.add_argument("--verbose", action="store_true", default=False, help="Показать обновлённый конфиг")
    p.set_defaults(func=cmd_config_set)

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
