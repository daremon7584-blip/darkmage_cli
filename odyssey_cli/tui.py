"""Полноценный TUI для Odyssey AI (как Claude Code / Codex).

Разметка экрана:
  ┌─────────────────────────────────────────────────────────────┐
  │  Header: Odyssey AI | workspace | run | API | clock         │
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

import asyncio
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
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

from .client import OdysseyClient, OdysseyError
from . import sync as sync_mod


class OdysseyTUI(App[None]):
    """Полноценный интерактивный TUI клиент для Odyssey AI platform."""

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
        self.client: OdysseyClient | None = None
        self._tree_nodes: dict[str, TreeNode] = {}
        self._events_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Composition
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Container(id="app-container"):
            yield Static(
                f"🚀 Odyssey AI  |  Workspace: {self.workspace_id}  |  "
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
                    "  /help  /sync  /files  /run  /status  /quit   •   "
                    "Ctrl+S синхр · Ctrl+F файлы · Ctrl+R обновить · Ctrl+Q выход",
                    id="composer-hint",
                )

            yield Static(id="status-bar")
            yield Static(id="help-bar")

        yield Footer()

    # ------------------------------------------------------------------
    # Mount / init
    # ------------------------------------------------------------------

    async def on_mount(self) -> None:
        self.client = OdysseyClient(base_url=self.base_url, token=self.token)
        self._update_status("Подключён к API")
        self._update_help(
            "Ctrl+Q выход  •  Ctrl+S синхронизация  •  Ctrl+F файлы  •  Ctrl+R обновить  •  Ctrl+C стоп ran"
        )

        # Загружаем дерево файлов и инфо о воркспейсе
        self.run_worker(self._load_workspace_info(), name="workspace-info", exclusive=True)
        self.run_worker(self._load_file_tree(), name="file-tree", exclusive=True)

        # Запускаем стрим событий (если есть run)
        if self.run_id:
            self.run_worker(self._stream_events(), name="event-stream", exclusive=True)
        else:
            self._write_event(
                "system",
                "Рабочая зона выбрана. Создайте ran: /run create <prompt> или "
                "используйте CLI: odyssey run create <session_id> --prompt '...'",
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
        except OdysseyError as exc:
            self._update_status(f"Ошибка загрузки воркспейса: {exc}")

    async def _load_file_tree(self) -> None:
        if self.client is None:
            return
        try:
            tree = self.query_one("#file-tree", Tree)
            data = self.client.workspace_files(self.workspace_id, ".")
            self._populate_tree(tree.root, data.get("entries", []), ".")
            tree.root.expand()
        except OdysseyError as exc:
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
                node = parent.add(f"📁 {name}", data={"path": path, "kind": "directory"})
                node.expand()
                # Загружаем содержимое директории лениво при раскрытии
                self._tree_nodes[path] = node
            else:
                size_str = f" ({size} B)" if size else ""
                parent.add_leaf(f"📄 {name}{size_str}", data={"path": path, "kind": "file"})

    # ------------------------------------------------------------------
    # Event streaming (SSE)
    # ------------------------------------------------------------------

    async def _stream_events(self) -> None:
        if self.client is None:
            return
        target_id = self.run_id or self.workspace_id
        try:
            async for ev in self._aiter_events(target_id):
                self.call_later(self._display_event, ev)
        except OdysseyError as exc:
            self.call_later(self._show_error, f"Ошибка SSE: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.call_later(self._show_error, f"Неожиданная ошибка: {exc}")

    async def _aiter_events(self, target_id: str) -> Any:
        if self.client is None:
            return
        for ev in self.client.run_events_parsed(target_id):
            yield ev
            await asyncio.sleep(0)

    def _display_event(self, ev: dict[str, Any]) -> None:
        log = self.query_one("#event-log", RichLog)
        etype = ev.get("event", "")
        data = ev.get("data", {})

        if isinstance(data, dict):
            detail = ""
            if etype == "assistant.delta":
                detail = data.get("text", "")
            elif etype == "tool.requested":
                detail = f"🔧 [bold cyan]{data.get('name', '')}[/] {data.get('arguments', {})}"
            elif etype == "tool.output":
                detail = f"📤 [bold green]вывод:[/] {str(data.get('output', ''))[:300]}"
            elif etype == "approval.required":
                detail = (
                    f"⚠️  [bold yellow]ОДОБРЕНИЕ:[/] {data.get('name', '')} "
                    f"path={data.get('path', '')}"
                )
            elif etype == "approval.resolved":
                detail = f"✅ [bold green]Одобрено:[/] {data.get('decision', '')}"
            elif etype == "checkpoint.ready":
                detail = "💾 [bold magenta]Чекпоинт сохранён[/]"
            elif etype == "diff.ready":
                detail = f"📝 [bold magenta]Дифф:[/] {data.get('path', '')}"
            elif etype == "run.completed":
                detail = f"🏁 [bold green]Завершено:[/] {data.get('finish_reason', '')}"
            elif etype == "run.failed":
                detail = f"💥 [bold red]Ошибка:[/] {data.get('error', '')}"
            elif etype == "run.cancelled":
                detail = "🛑 [bold red]Отменено[/]"
            elif etype == "user.message":
                detail = f"[bold white][Вы][/] {data.get('text', '')}"
            elif etype == "context.compacted":
                detail = (
                    f"🗜 [bold blue]Компактировка:[/] "
                    f"{data.get('dropped_messages', '')} сообщений удалено"
                )
            elif etype == "agent.question":
                detail = f"❓ [bold yellow]Вопрос:[/] {data.get('question', '')}"
            elif etype == "agent.answer":
                detail = f"💬 [bold yellow]Ответ:[/] {data.get('answers', [])}"
            else:
                detail = str(data)[:300]
            log.write(f"[{etype}] {detail}")
        else:
            log.write(f"[{etype}] {data}")

        self._events_log.append(ev)

    def _write_event(self, etype: str, detail: str) -> None:
        log = self.query_one("#event-log", RichLog)
        log.write(f"[{etype}] {detail}")

    def _show_error(self, msg: str) -> None:
        log = self.query_one("#event-log", RichLog)
        log.write(f"[bold red][ОШИБКА][/] {msg}")

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _update_status(self, msg: str) -> None:
        try:
            bar = self.query_one("#status-bar", Static)
            bar.update(f"📍 {msg}")
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
            self.query_one("#event-log", RichLog).write(f"[bold white][Вы][/] {text}")
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

        if cmd == "sync":
            self.run_worker(self._cmd_sync(args), name="cmd-sync")
            return

        if cmd == "files":
            self.run_worker(self._cmd_files(args), name="cmd-files")
            return

        log.write(f"[bold red]Неизвестная команда:[/] /{cmd}")

    async def _send_message(self, text: str) -> None:
        if self.client is None or not self.run_id:
            self._show_error("Нет активного ran. Создайте его: /run create <prompt>")
            return
        try:
            self.client.run_message(self.run_id, text)
        except OdysseyError as exc:
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
                f"[bold]Воркспейс:[/] {ws.get('name', '—')}  "
                f"[bold]Статус:[/] {ws.get('status', '—')}  "
                f"[bold]Режим:[/] {ws.get('approval_mode', '—')}"
            )
        except OdysseyError as exc:
            self._show_error(f"Ошибка статуса: {exc}")

    async def _cmd_run(self, args: list[str]) -> None:
        log = self.query_one("#event-log", RichLog)
        if not args or args[0] != "create":
            log.write("[bold red]Использование:[/] /run create <prompt>")
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
            log.write(f"[bold green]✅ Ran создан:[/] {run_id}")
            # Запускаем стрим событий для нового ran
            self.run_worker(self._stream_events(), name=f"event-stream-{run_id}", exclusive=True)
        except OdysseyError as exc:
            self._show_error(f"Ошибка создания ran: {exc}")

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
                log.write(f"  {icon} {entry.get('name', '')}{size_str}")
            if len(entries) > 30:
                log.write(f"  … и ещё {len(entries) - 30}")
        except OdysseyError as exc:
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
            log.write(f"[bold]📄 Файл:[/] {path} ({content.get('size_bytes', 0)} байт)")
            log.write(f"```\n{text[:2000]}{'…' if len(text) > 2000 else ''}\n```")
        except OdysseyError as exc:
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
        except OdysseyError as exc:
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
            if self.run_id and self.client:
                try:
                    self.client.run_stop(self.run_id)
                    self._write_event("system", "Ran остановлен пользователем")
                except OdysseyError as exc:
                    self._show_error(f"Не удалось остановить ran: {exc}")

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
    app = OdysseyTUI(base_url=base_url, token=token, workspace_id=workspace_id, run_id=run_id)
    app.run()
