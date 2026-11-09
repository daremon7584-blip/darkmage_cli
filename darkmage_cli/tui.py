"""Полноценный TUI для Darkmage AI (как Claude Code / Codex).

Разметка экрана:
  ┌─────────────────────────────────────────────────────────────┐
  │  Header: Darkmage AI | workspace | run | API | clock         │
  ├──────────┬───────────────────────────────────────────────────┤
  │          │                                                   │
  │  Sidebar │  Основная область: лента событий (SSE)            │
  │  - Файлы │    в реальном времени                             │
  │  - Инфо  │  └ сообщения агента, вызовы инструментов          │
  │          │                                                   │
  ├──────────┴───────────────────────────────────────────────────┤
  │  Компоузер ввода (Enter — отправить, / — команды)            │
  ├─────────────────────────────────────────────────────────────┤
  │  Статусная строка                                             │
  └─────────────────────────────────────────────────────────────┘

Горячие клавиши:
  Ctrl+Q — выход
  Ctrl+S — синхронизировать файлы (push/pull)
  Ctrl+F — сфокусировать панель файлов
  Ctrl+R — обновить список файлов
  Ctrl+C — прервать текущий run
  Tab    — переключить фокус между панелями
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    Tree,
)
from textual.widgets.tree import TreeNode

from .client import DarkmageClient, DarkmageError
from .events import (
    approval_card,
    approval_summary,
    format_diff,
    question_card,
    question_items,
)
from . import sync as sync_mod

# Keep memory bounded for a long-running attached stream.
MAX_EVENTS_LOG = 1000

# C0/C1 control characters except tab and newline. ESC (0x1b) is the important
# one: agent output must never be able to move the cursor or inject ANSI codes.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x0d\x0e-\x1f\x7f-\x9f]")


def strip_control(value: Any) -> str:
    """Remove terminal control characters from untrusted text."""
    return _CONTROL_CHARS_RE.sub("", str(value))


def safe_markup(value: Any, limit: int | None = None) -> str:
    """Sanitize untrusted text and escape it for Rich markup."""
    text = strip_control(value)
    if limit is not None:
        text = text[:limit]
    return escape(text)


class DarkmageTUI(App[None]):
    """Полноценный интерактивный TUI клиент для Darkmage AI platform."""

    BINDINGS = [
        # Ctrl+C detaches the local stream; it never kills a server-side run.
        Binding("ctrl+c", "detach_stream", "Detach stream", show=False, priority=True),
    ]

    CSS = """
    #app-container {
        height: 1fr;
        layout: vertical;
    }

    #header-bar {
        height: 3;
        padding: 0 1;
        color: $text;
    }

    #main-split {
        height: 1fr;
        layout: horizontal;
    }

    #sidebar {
        width: 34;
        border: solid $accent;
        padding: 0 1;
        background: $surface;
    }

    #sidebar-title {
        height: 1;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #file-tree {
        height: 1fr;
        border: solid $panel;
        margin-bottom: 1;
    }

    #sidebar-info {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
    }

    #main-panel {
        height: 1fr;
        layout: vertical;
        padding: 0 1;
    }

    #event-log {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }

    #composer-container {
        height: 5;
        border: solid $accent;
        padding: 0 1;
    }

    #composer {
        height: 3;
        margin-bottom: 1;
    }

    #composer-hint {
        height: 1;
        color: $text-muted;
    }

    #status-bar {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #help-bar {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        base_url: str,
        token: str | None,
        workspace_id: str,
        run_id: str | None = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url
        self.token = token
        self.workspace_id = workspace_id
        self.run_id = run_id
        self.client: DarkmageClient | None = None
        self._tree_nodes: dict[str, TreeNode] = {}
        self._events_log: list[dict[str, Any]] = []
        self.pending_approval: dict[str, Any] | None = None
        self.pending_question: dict[str, Any] | None = None
        self._stream_worker: Any = None

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Container(id="app-container"):
            yield Static(
                f"🚀 Darkmage AI  |  Workspace: {self.workspace_id}  |  "
                f"Run: {self.run_id or '—'}  |  API: {self.base_url}",
                id="header-bar",
            )

            with Horizontal(id="main-split"):
                with Vertical(id="sidebar"):
                    yield Static("📁 Файлы", id="sidebar-title")
                    yield Tree("workspace", id="file-tree")
                    yield Static("ℹ Информация", id="sidebar-info-title")
                    yield VerticalScroll(
                        Label("Загрузка…", id="sidebar-info-content"),
                        id="sidebar-info",
                    )

                with Vertical(id="main-panel"):
                    yield RichLog(id="event-log", wrap=True, auto_scroll=True, markup=True)

            with Container(id="composer-container"):
                yield Input(
                    placeholder="Сообщение в задачу (Enter — отправить, / — команды)...",
                    id="composer",
                )
                yield Label(
                    "  /help  /sync  /files  /run  /approve  /reject  /answer  /status  /quit   •   "
                    "Ctrl+S синхр · Ctrl+F файлы · Ctrl+R обновить · Ctrl+C отвязать · Ctrl+Q выход",
                    id="composer-hint",
                )

            yield Static(id="status-bar")
            yield Static(id="help-bar")

        yield Footer()

    # ------------------------------------------------------------------
    # Mount / init
    # ------------------------------------------------------------------

    async def on_mount(self) -> None:
        self.client = DarkmageClient(base_url=self.base_url, token=self.token)
        self._update_status("Подключён к API")
        self._update_help(
            "Ctrl+Q выход  •  Ctrl+S синхронизация  •  Ctrl+F файлы  •  "
            "Ctrl+R обновить  •  Ctrl+C отвязать поток (run продолжается)"
        )

        # Загружаем дерево файлов и инфо о воркспейсе
        self.run_worker(self._load_workspace_info(), name="workspace-info", exclusive=True)
        self.run_worker(self._load_file_tree(), name="file-tree", exclusive=True)

        # Запускаем стрим событий (если есть run)
        if self.run_id:
            self._start_stream()
        else:
            self._write_event(
                "system",
                "Рабочая зона выбрана. Создайте ran: /run create <prompt> или "
                "используйте CLI: darkmage run create <session_id> --prompt '...'",
            )

    async def _load_workspace_info(self) -> None:
        if self.client is None:
            return
        try:
            ws = self.client.workspace_get(self.workspace_id)
            content = self.query_one("#sidebar-info-content", Label)
            content.update(
                f"Имя: {ws.get('name', '—')}\n"
                f"ID: {self.workspace_id}\n"
                f"Статус: {ws.get('status', '—')}\n"
                f"Режим: {ws.get('approval_mode', '—')}\n"
                f"Создан: {ws.get('created_at', '—')[:16] if ws.get('created_at') else '—'}"
            )
        except DarkmageError as exc:
            self._update_status(f"Ошибка загрузки воркспейса: {exc}")

    async def _load_file_tree(self) -> None:
        if self.client is None:
            return
        try:
            tree = self.query_one("#file-tree", Tree)
            data = self.client.workspace_files(self.workspace_id, ".")
            self._populate_tree(tree.root, data.get("entries", []), ".")
            tree.root.expand()
        except DarkmageError as exc:
            self._write_event("error", f"Не удалось загрузить файлы: {exc}")

    def _populate_tree(
        self, parent: TreeNode, entries: list[dict[str, Any]], base_path: str
    ) -> None:
        """Рекурсивно заполняет дерево файлов."""
        for entry in entries:
            name = entry.get("name", "")
            kind = entry.get("kind", "file")
            size = entry.get("size_bytes", 0)
            path = f"{base_path}/{name}" if base_path != "." else name

            if kind == "directory":
                node = parent.add(
                    f"📁 {safe_markup(name)}",
                    data={"path": path, "kind": "directory"},
                )
                node.expand()
                # Загружаем содержимое директории лениво при раскрытии
                self._tree_nodes[path] = node
            else:
                size_str = f" ({size} B)" if size else ""
                parent.add_leaf(
                    f"📄 {safe_markup(name)}{size_str}",
                    data={"path": path, "kind": "file"},
                )

    # ------------------------------------------------------------------
    # Event streaming (SSE)
    # ------------------------------------------------------------------

    def _start_stream(self) -> None:
        if self.client is None or not self.run_id:
            return
        if self._stream_worker is not None:
            try:
                self._stream_worker.cancel()
            except Exception:  # noqa: BLE001, S110
                pass
        # The SSE reader is synchronous; keep it off the UI event loop (P1-5).
        self._stream_worker = self.run_worker(
            self._stream_events,
            name=f"event-stream-{self.run_id}",
            thread=True,
            exclusive=True,
        )

    def _stream_events(self) -> None:
        client = self.client
        run_id = self.run_id
        if client is None or not run_id:
            return
        try:
            for ev in client.run_events_parsed(run_id):
                if not self._call_from_thread_safe(self._display_event, ev):
                    return
        except DarkmageError as exc:
            self._call_from_thread_safe(self._show_error, f"Ошибка SSE: {exc}")
        except Exception as exc:  # noqa: BLE001
            self._call_from_thread_safe(
                self._show_error, f"Неожиданная ошибка: {exc}"
            )

    def action_detach_stream(self) -> None:
        self._detach_stream()

    def _detach_stream(self) -> None:
        if self._stream_worker is not None:
            try:
                self._stream_worker.cancel()
            except Exception:  # noqa: BLE001, S110
                pass
            self._stream_worker = None
            self._write_event(
                "system",
                "Поток отвязан; run продолжается на сервере. "
                "/run stop — остановить run.",
            )
        else:
            self._write_event("system", "Нет активного потока событий.")

    def _call_from_thread_safe(self, callback: Any, *args: Any) -> bool:
        try:
            self.call_from_thread(callback, *args)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _display_event(self, ev: dict[str, Any]) -> None:
        log = self.query_one("#event-log", RichLog)
        etype = ev.get("event", "")
        data = ev.get("data", {})

        if isinstance(data, dict):
            if etype == "assistant.delta":
                log.write(safe_markup(data.get("text", "")))
            elif etype == "tool.requested":
                log.write(
                    f"🔧 [bold cyan]{safe_markup(data.get('name', ''))}[/] "
                    f"{safe_markup(data.get('arguments', {}))}"
                )
            elif etype == "tool.output":
                log.write(
                    f"📤 [bold green]вывод:[/] "
                    f"{safe_markup(data.get('output', ''), 300)}"
                )
            elif etype == "approval.required":
                if data.get("auto"):
                    self.pending_approval = None
                    log.write(Text(strip_control(approval_card(data)), style="green"))
                else:
                    self.pending_approval = data
                    log.write(
                        Text(strip_control(approval_card(data)), style="bold yellow")
                    )
                    log.write(
                        "  /approve  /approve turn  /reject  /diff  "
                        f"· {safe_markup(approval_summary(data))}"
                    )
            elif etype == "approval.resolved":
                approval_id = data.get("approval_id")
                if (
                    self.pending_approval is not None
                    and approval_id
                    and str(self.pending_approval.get("approval_id")) == str(approval_id)
                ):
                    self.pending_approval = None
                log.write(
                    f"✅ [bold green]Одобрение:[/] "
                    f"{safe_markup(data.get('decision', ''))} "
                    f"scope={safe_markup(data.get('scope', 'call'))}"
                )
            elif etype == "checkpoint.ready":
                log.write("💾 [bold magenta]Чекпоинт сохранён[/]")
            elif etype == "diff.ready":
                log.write(Text(strip_control(format_diff(data)), style="magenta"))
            elif etype == "run.completed":
                self.pending_approval = None
                self.pending_question = None
                log.write(
                    f"🏁 [bold green]Завершено:[/] "
                    f"{safe_markup(data.get('finish_reason', ''))}"
                )
            elif etype == "run.failed":
                self.pending_approval = None
                self.pending_question = None
                log.write(
                    f"💥 [bold red]Ошибка:[/] "
                    f"{safe_markup(data.get('error', ''))}"
                )
            elif etype == "run.cancelled":
                self.pending_approval = None
                self.pending_question = None
                log.write("🛑 [bold red]Отменено[/]")
            elif etype == "user.message":
                log.write(
                    f"[bold white][Вы][/] {safe_markup(data.get('text', ''))}"
                )
            elif etype == "context.compacted":
                log.write(
                    f"🗜 [bold blue]Компактировка:[/] "
                    f"{safe_markup(data.get('dropped_messages', ''))} сообщений удалено"
                )
            elif etype == "agent.question":
                self.pending_question = data
                log.write(
                    Text(strip_control(question_card(data)), style="bold yellow")
                )
                log.write(
                    "  Ответьте в компоузере или /answer <текст> (несколько — через |)"
                )
            elif etype == "agent.answer":
                question_id = data.get("question_id")
                if (
                    self.pending_question is not None
                    and question_id
                    and str(self.pending_question.get("question_id")) == str(question_id)
                ):
                    self.pending_question = None
                log.write(
                    f"💬 [bold yellow]Ответ:[/] "
                    f"{safe_markup(data.get('answers', []))}"
                )
            else:
                log.write(
                    f"[{safe_markup(etype)}] {safe_markup(data, 300)}"
                )
        else:
            log.write(f"[{safe_markup(etype)}] {safe_markup(data)}")

        self._remember_event(ev)

    def _remember_event(self, ev: dict[str, Any]) -> None:
        """Append an event while keeping the in-memory log bounded."""
        self._events_log.append(ev)
        overflow = len(self._events_log) - MAX_EVENTS_LOG
        if overflow > 0:
            del self._events_log[:overflow]

    def _write_event(self, etype: str, detail: str) -> None:
        log = self.query_one("#event-log", RichLog)
        log.write(f"[{safe_markup(etype)}] {safe_markup(detail)}")

    def _show_error(self, msg: str) -> None:
        log = self.query_one("#event-log", RichLog)
        log.write(f"[bold red][ОШИБКА][/] {safe_markup(msg)}")

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _update_status(self, msg: str) -> None:
        try:
            bar = self.query_one("#status-bar", Static)
            bar.update(f"📍 {safe_markup(msg)}")
        except Exception:  # noqa: BLE001
            pass

    def _update_help(self, msg: str) -> None:
        try:
            bar = self.query_one("#help-bar", Static)
            bar.update(msg)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "composer":
            return
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        if text.startswith("/"):
            await self._handle_command(text)
        else:
            self.query_one("#event-log", RichLog).write(
                f"[bold white][Вы][/] {safe_markup(text)}"
            )
            await self._send_message(text)

    async def _handle_command(self, text: str) -> None:
        parts = text[1:].split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:]

        log = self.query_one("#event-log", RichLog)

        if cmd in ("quit", "q", "exit"):
            self.exit()
            return

        if cmd == "help":
            log.write(
                "[bold]Доступные команды:[/]\n"
                "  /run create <prompt>  — создать ran\n"
                "  /run stop             — остановить ran\n"
                "  /approve [turn]       — одобрить ожидающий tool call\n"
                "  /reject               — отклонить ожидающий tool call\n"
                "  /answer <a|b|...>     — ответить на вопрос агента\n"
                "  /diff                 — показать diff ожидающего approval\n"
                "  /sync pull            — скачать файлы из воркспейса\n"
                "  /sync push            — загрузить файлы в воркспейс\n"
                "  /sync diff            — показать различия\n"
                "  /files list           — список файлов воркспейса\n"
                "  /status               — статус воркспейса\n"
                "  /quit                 — выход\n"
            )
            return

        if cmd == "status":
            self.run_worker(self._cmd_status(), name="cmd-status")
            return

        if cmd == "run":
            self.run_worker(self._cmd_run(args), name="cmd-run")
            return

        if cmd == "approve":
            self.run_worker(self._cmd_approve(args), name="cmd-approve")
            return

        if cmd == "reject":
            self.run_worker(self._cmd_reject(args), name="cmd-reject")
            return

        if cmd == "answer":
            self.run_worker(self._cmd_answer(args), name="cmd-answer")
            return

        if cmd == "diff":
            self._show_pending_diff()
            return

        if cmd == "sync":
            self.run_worker(self._cmd_sync(args), name="cmd-sync")
            return

        if cmd == "files":
            self.run_worker(self._cmd_files(args), name="cmd-files")
            return

        log.write(f"[bold red]Неизвестная команда:[/] /{safe_markup(cmd)}")

    async def _send_message(self, text: str) -> None:
        if self.client is None or not self.run_id:
            self._show_error("Нет активного ran. Создайте его: /run create <prompt>")
            return
        if self.pending_question is not None:
            await self._cmd_answer([text])
            return
        try:
            self.client.run_message(self.run_id, text)
        except DarkmageError as exc:
            self._show_error(f"Не удалось отправить сообщение: {exc}")

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def _cmd_status(self) -> None:
        log = self.query_one("#event-log", RichLog)
        if self.client is None:
            return
        try:
            ws = self.client.workspace_get(self.workspace_id)
            log.write(
                f"[bold]Воркспейс:[/] {safe_markup(ws.get('name', '—'))}  "
                f"[bold]Статус:[/] {safe_markup(ws.get('status', '—'))}  "
                f"[bold]Режим:[/] {safe_markup(ws.get('approval_mode', '—'))}"
            )
        except DarkmageError as exc:
            self._show_error(f"Ошибка статуса: {exc}")

    async def _cmd_run(self, args: list[str]) -> None:
        log = self.query_one("#event-log", RichLog)
        sub = args[0].lower() if args else "create"

        if sub == "stop":
            if self.client is None or not self.run_id:
                log.write("[bold red]Нет активного ran.[/]")
                return
            try:
                data = self.client.run_stop(self.run_id)
                log.write(
                    f"[bold green]🛑 Run остановлен:[/] "
                    f"{safe_markup(data.get('id', self.run_id))}"
                )
            except DarkmageError as exc:
                self._show_error(f"Не удалось остановить ran: {exc}")
            return

        if sub != "create":
            log.write(
                "[bold red]Использование:[/] /run create <prompt> | /run stop"
            )
            return
        prompt = " ".join(args[1:])
        if not prompt:
            log.write("[bold red]Укажите текст задачи.[/]")
            return

        if self.client is None:
            return
        # Находим последнюю сессию в воркспейсе или создаём новую
        try:
            sessions = self.client.session_list(self.workspace_id)
            session_id = None
            if sessions:
                session_id = sessions[0].get("id")
            if not session_id:
                s = self.client.session_create(self.workspace_id, title="TUI сессия")
                session_id = s.get("id")
            if not session_id:
                self._show_error("Не удалось создать сессию")
                return

            run = self.client.run_create(session_id, prompt)
            run_id = run.get("id")
            self.run_id = run_id
            log.write(f"[bold green]✅ Ran создан:[/] {safe_markup(run_id)}")
            # Запускаем стрим событий для нового ran
            self._start_stream()
        except DarkmageError as exc:
            self._show_error(f"Ошибка создания ran: {exc}")

    async def _cmd_approve(self, args: list[str]) -> None:
        log = self.query_one("#event-log", RichLog)
        if self.client is None:
            return
        if self.pending_approval is None:
            log.write("[bold red]Нет ожидающего approval.[/]")
            return
        approval_id = str(self.pending_approval.get("approval_id") or "")
        if not approval_id:
            self._show_error("В событии approval нет approval_id")
            return
        scope = (
            "turn"
            if args and args[0].lower() in ("turn", "rest", "all")
            else "call"
        )
        try:
            result = self.client.tool_call_approve(approval_id, scope)
        except DarkmageError as exc:
            if exc.status_code == 409:
                self.pending_approval = None
                log.write(
                    "[bold yellow]Approval уже разрешён другим клиентом; "
                    "продолжаем поток.[/]"
                )
                return
            self._show_error(f"Не удалось одобрить {approval_id}: {exc}")
            return
        self.pending_approval = None
        log.write(
            f"[bold green]✅ Одобрено:[/] {safe_markup(result.get('name', 'tool call'))} "
            f"({safe_markup(approval_id)}) scope={safe_markup(scope)}"
        )

    async def _cmd_reject(self, args: list[str]) -> None:
        log = self.query_one("#event-log", RichLog)
        if self.client is None:
            return
        if self.pending_approval is None:
            log.write("[bold red]Нет ожидающего approval.[/]")
            return
        approval_id = str(self.pending_approval.get("approval_id") or "")
        if not approval_id:
            self._show_error("В событии approval нет approval_id")
            return
        try:
            result = self.client.tool_call_reject(approval_id)
        except DarkmageError as exc:
            if exc.status_code == 409:
                self.pending_approval = None
                log.write(
                    "[bold yellow]Approval уже разрешён другим клиентом; "
                    "продолжаем поток.[/]"
                )
                return
            self._show_error(f"Не удалось отклонить {approval_id}: {exc}")
            return
        self.pending_approval = None
        log.write(
            f"[bold yellow]⛔ Отклонено:[/] "
            f"{safe_markup(result.get('name', 'tool call'))} ({safe_markup(approval_id)})"
        )

    async def _cmd_answer(self, args: list[str]) -> None:
        log = self.query_one("#event-log", RichLog)
        if self.client is None or not self.run_id:
            self._show_error("Нет активного ran.")
            return
        if self.pending_question is None:
            log.write("[bold red]Нет ожидающего вопроса агента.[/]")
            return
        question_id = str(self.pending_question.get("question_id") or "")
        items = question_items(self.pending_question)
        if not question_id or not items:
            self._show_error("В событии agent.question нет question_id/questions")
            return
        text = " ".join(args).strip()
        if not text:
            log.write("[bold red]Использование:[/] /answer <ответ> (несколько — a|b)")
            return
        if len(items) > 1:
            answers = [part.strip() for part in text.split("|") if part.strip()]
            if len(answers) != len(items):
                log.write(
                    f"[bold red]Нужно {len(items)} ответа(ов), разделённых |.[/]"
                )
                return
        else:
            answers = [text]
        try:
            self.client.run_answer(self.run_id, question_id, answers)
        except DarkmageError as exc:
            if exc.status_code == 409:
                self.pending_question = None
                log.write(
                    "[bold yellow]Вопрос уже отвечен; продолжаем поток.[/]"
                )
                return
            self._show_error(f"Не удалось ответить: {exc}")
            return
        self.pending_question = None
        log.write(f"[bold green]💬 Ответ отправлен:[/] {safe_markup(answers)}")

    def _show_pending_diff(self) -> None:
        log = self.query_one("#event-log", RichLog)
        if self.pending_approval is None:
            log.write("[bold red]Нет ожидающего approval с diff.[/]")
            return
        log.write(Text(format_diff(self.pending_approval, max_lines=1000), style="magenta"))

    async def _cmd_sync(self, args: list[str]) -> None:
        log = self.query_one("#event-log", RichLog)
        sub = args[0].lower() if args else "status"
        local_dir = Path(".").resolve()
        patterns = sync_mod.load_ignore_patterns(local_dir)

        if self.client is None:
            return

        if sub == "pull":
            log.write("[bold]📥 Pull файлов из воркспейса…[/]")
            result = sync_mod.sync_pull(
                self.client, self.workspace_id, local_dir, patterns,
                auto_resolve="workspace",
            )
            log.write(
                f"[bold green]✅ Pull:[/] {result['downloaded']} скачано, "
                f"{result['skipped']} пропущено, {len(result['errors'])} ошибок"
            )
        elif sub == "push":
            log.write("[bold]📤 Push файлов в воркспейс…[/]")
            result = sync_mod.sync_push(
                self.client, self.workspace_id, local_dir, patterns,
                auto_resolve="local",
            )
            log.write(
                f"[bold green]✅ Push:[/] {result['uploaded']} загружено, "
                f"{result['skipped']} пропущено, {len(result['errors'])} ошибок"
            )
        elif sub == "diff":
            diff = sync_mod.sync_diff(self.client, self.workspace_id, local_dir, patterns)
            log.write(f"[bold]📊 Diff:[/] identical={len(diff['identical'])}, "
                      f"only_local={len(diff['only_local'])}, "
                      f"only_workspace={len(diff['only_workspace'])}, "
                      f"conflicts={len(diff['conflicts'])}")
        else:
            log.write("[bold red]Использование:[/] /sync pull|push|diff")

    async def _cmd_files(self, args: list[str]) -> None:
        log = self.query_one("#event-log", RichLog)
        if self.client is None:
            return
        try:
            data = self.client.workspace_files(self.workspace_id, ".")
            entries = data.get("entries", [])
            log.write(f"[bold]📁 Файлы в воркспейсе ({len(entries)}):[/]")
            for entry in entries[:30]:
                kind = entry.get("kind", "file")
                size = entry.get("size_bytes", 0)
                icon = "📁" if kind == "directory" else "📄"
                size_str = f" ({size} B)" if size and kind == "file" else ""
                log.write(f"  {icon} {safe_markup(entry.get('name', ''))}{size_str}")
            if len(entries) > 30:
                log.write(f"  … и ещё {len(entries) - 30}")
        except DarkmageError as exc:
            self._show_error(f"Ошибка списка файлов: {exc}")

    # ------------------------------------------------------------------
    # Tree interactions
    # ------------------------------------------------------------------

    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Клик на файле в дереве — читаем его содержимое."""
        node = event.node
        data = node.data
        if not data or data.get("kind") != "file":
            return
        path = data.get("path", "")
        if self.client is None:
            return
        try:
            content = self.client.workspace_file_content(self.workspace_id, path)
            text = content.get("content", "")
            log = self.query_one("#event-log", RichLog)
            log.write(
                f"[bold]📄 Файл:[/] {safe_markup(path)} "
                f"({content.get('size_bytes', 0)} байт)"
            )
            # File content is rendered as plain Text, never parsed as markup.
            preview = strip_control(text[:2000])
            if len(text) > 2000:
                preview += "…"
            log.write(Text(preview))
        except DarkmageError as exc:
            self._show_error(f"Не удалось прочитать файл: {exc}")

    async def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Ленивая загрузка содержимого директории при раскрытии."""
        node = event.node
        data = node.data
        if not data or data.get("kind") != "directory":
            return
        path = data.get("path", "")
        if self.client is None:
            return
        try:
            data_resp = self.client.workspace_files(self.workspace_id, path)
            # Удаляем placeholder, если был, и заполняем реальными записями
            node.remove_children()
            self._populate_tree(node, data_resp.get("entries", []), path)
        except DarkmageError as exc:
            self._show_error(f"Не удалось загрузить директорию: {exc}")

    # ------------------------------------------------------------------
    # Key bindings
    # ------------------------------------------------------------------

    async def on_key(self, event: Key) -> None:
        if event.key == "ctrl+q":
            self.exit()
        elif event.key == "ctrl+s":
            self.run_worker(self._cmd_sync(["pull"]), name="cmd-sync-pull")
        elif event.key == "ctrl+f":
            self.query_one("#file-tree", Tree).focus()
        elif event.key == "ctrl+r":
            self.run_worker(self._load_file_tree(), name="file-tree-refresh")
        elif event.key == "ctrl+c":
            # Never kill a server-side run from a stray Ctrl+C. Detach the
            # local stream; /run stop is the explicit destructive action.
            event.prevent_default()
            event.stop()
            self._detach_stream()

    async def on_unmount(self) -> None:
        if self.client:
            self.client.close()


def run_tui(
    base_url: str,
    token: str | None,
    workspace_id: str,
    run_id: str | None = None,
) -> None:
    """Запустить TUI приложение."""
    app = DarkmageTUI(base_url=base_url, token=token, workspace_id=workspace_id, run_id=run_id)
    app.run()
