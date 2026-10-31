"""Интерактивный TUI для Odyssey AI (Phase 3).

Полноценный терминальный интерфейс на базе Textual:
- Лента событий (SSE) в реальном времени
- Компоузер внизу для ввода сообщений
- Статусная строка с информацией о workspace и run
"""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Input, Label, RichLog

from .client import OdysseyClient, OdysseyError


class OdysseyTUI(App[None]):
    """Интерактивный TUI клиент для Odyssey AI platform."""

    CSS = """
    #main {
        height: 1fr;
        border: solid $accent;
        margin: 1;
    }
    #event-log {
        height: 1fr;
    }
    #composer {
        height: 3;
        border: solid $accent;
        margin: 1;
        padding: 1;
    }
    #status {
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            RichLog(id="event-log", wrap=True, auto_scroll=True, markup=False),
            id="main",
        )
        yield Input(placeholder="Сообщение в задачу (Enter — отправить)...", id="composer")
        yield Label(id="status")
        yield Footer()

    async def on_mount(self) -> None:
        self.client = OdysseyClient(base_url=self.base_url, token=self.token)
        status = self.query_one("#status", Label)
        status.update(
            f"Workspace: {self.workspace_id}  |  Run: {self.run_id or 'не выбран'}  |  "
            f"API: {self.base_url}"
        )
        self.run_worker(self._stream_events(), name="event-stream", exclusive=True)

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
        """Асинхронный итератор над SSE событиями."""
        if self.client is None:
            return
        # run_events_parsed возвращает генератор; оборачиваем в async
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
                detail = f"{data.get('name', '')} {data.get('arguments', {})}"
            elif etype == "tool.output":
                detail = str(data.get("output", ""))[:200]
            elif etype == "approval.required":
                detail = f"⚠️  ОДОБРЕНИЕ: {data.get('name', '')} path={data.get('path', '')}"
            elif etype == "approval.resolved":
                detail = f"✅ Одобрено: {data.get('decision', '')}"
            elif etype == "checkpoint.ready":
                detail = "💾 Чекпоинт сохранён"
            elif etype == "checkpoint.resolved":
                detail = f"♻️  Чекпоинт: {data.get('decision', '')}"
            elif etype == "diff.ready":
                detail = f"📝 Дифф: {data.get('path', '')}"
            elif etype == "run.completed":
                detail = f"🏁 Завершено: {data.get('finish_reason', '')}"
            elif etype == "run.failed":
                detail = f"💥 Ошибка: {data.get('error', '')}"
            elif etype == "run.cancelled":
                detail = "🛑 Отменено"
            elif etype == "user.message":
                detail = f"[Вы] {data.get('text', '')}"
            elif etype == "context.compacted":
                detail = f"🗜  Компактировка: {data.get('dropped_messages', '')} сообщений удалено"
            elif etype == "agent.question":
                detail = f"❓ Вопрос: {data.get('question', '')}"
            elif etype == "agent.answer":
                detail = f"💬 Ответ: {data.get('answers', [])}"
            else:
                detail = str(data)[:200]
            log.write(f"[{etype}] {detail}")
        else:
            log.write(f"[{etype}] {data}")

    def _show_error(self, msg: str) -> None:
        log = self.query_one("#event-log", RichLog)
        log.write(f"[ОШИБКА] {msg}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "composer":
            return
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.query_one("#event-log", RichLog).write(f"[Вы] {text}")
        if self.client and self.run_id:
            try:
                self.client.run_message(self.run_id, text)
            except OdysseyError as exc:
                self.query_one("#event-log", RichLog).write(f"[Ошибка отправки] {exc}")
            except Exception as exc:  # noqa: BLE001
                self.query_one("#event-log", RichLog).write(f"[Ошибка отправки] {exc}")

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
