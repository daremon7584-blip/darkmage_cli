from __future__ import annotations

import base64
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from .config import get_base_url, get_runner_token, get_runner_url, get_token

TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
TERMINAL_EVENTS = frozenset({"run.completed", "run.failed", "run.cancelled"})


def _chat_events_from_payload(payload: Any) -> Iterator[dict[str, Any]]:
    """Normalize an OpenAI-style chat chunk/completion into CLI events."""
    if not isinstance(payload, dict):
        return
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        text = None
        delta = choice.get("delta")
        if isinstance(delta, dict):
            text = delta.get("content")
        if text is None:
            message = choice.get("message")
            if isinstance(message, dict):
                text = message.get("content")
        if text:
            yield {"type": "delta", "text": str(text)}
    usage = payload.get("usage")
    if isinstance(usage, dict):
        yield {"type": "usage", "usage": usage}


class _PatchText(str):
    """Decoded patch text that keeps the exact response bytes.

    ``GET /runs/{id}/patch`` returns ``text/x-patch``.  The CLI prints the
    decoded text, but ``--output`` must write the original bytes so the file
    can be fed straight to ``git apply``.  Subclassing ``str`` keeps the public
    ``run_patch() -> str`` contract while retaining the raw body.
    """

    raw: bytes

    def __new__(cls, raw: bytes) -> "_PatchText":
        obj = super().__new__(cls, raw.decode("utf-8", errors="replace"))
        obj.raw = raw
        return obj


class DarkmageError(Exception):
    """API/transport error with enough context for retry decisions."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class DarkmageClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self.runner_url = get_runner_url().rstrip("/")
        self.token = token or get_token()
        self.runner_token = get_runner_token()
        self._client = httpx.Client(timeout=60.0)

    def _headers(self, *, runner: bool = False) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if runner:
            token = self.runner_token
        else:
            token = self.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(self, method: str, path: str, *, runner: bool = False, **kwargs: Any) -> httpx.Response:
        base = self.runner_url if runner else self.base_url
        url = f"{base.rstrip('/')}{path}"
        kwargs.setdefault("headers", {}).update(self._headers(runner=runner))
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            raise DarkmageError(
                f"Cannot reach {url}: {exc}", retryable=True
            ) from exc
        return resp

    def _json_or_text(self, resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail", "") if isinstance(body, dict) else str(body)
            except ValueError:
                detail = resp.text
            retryable = resp.status_code == 429 or resp.status_code >= 500
            raise DarkmageError(
                f"{resp.status_code} {resp.reason_phrase} for {resp.request.method} {resp.url.path}: {detail}",
                status_code=resp.status_code,
                retryable=retryable,
            )

    # --- auth ---
    def register(self, email: str, password: str, full_name: str | None = None) -> dict:
        resp = self._request(
            "POST",
            "/auth/register",
            json={"email": email, "password": password, "full_name": full_name},
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def login(self, email: str, password: str) -> dict:
        resp = self._request(
            "POST",
            "/auth/login",
            json={"email": email, "password": password},
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def logout(self) -> None:
        from .config import set_token

        set_token(None)
        self.token = None

    # --- users ---
    def me(self) -> dict:
        resp = self._request("GET", "/users/me")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def usage(self) -> dict:
        resp = self._request("GET", "/users/me/usage")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def memory_get(self) -> dict:
        resp = self._request("GET", "/users/me/memory")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def memory_put(self, content: str) -> dict:
        resp = self._request(
            "PUT", "/users/me/memory", json={"content": content}
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- workspaces ---
    def workspace_create(self, name: str) -> dict:
        resp = self._request("POST", "/workspaces", json={"name": name})
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_list(self, limit: int = 50) -> list[dict]:
        resp = self._request("GET", "/workspaces", params={"limit": limit})
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_get(self, workspace_id: str) -> dict:
        resp = self._request("GET", f"/workspaces/{workspace_id}")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_update(
        self,
        workspace_id: str,
        name: str | None = None,
        approval_mode: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if approval_mode is not None:
            body["approval_mode"] = approval_mode
        if not body:
            raise DarkmageError("Provide --name or --approval-mode")
        resp = self._request("PATCH", f"/workspaces/{workspace_id}", json=body)
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_start(self, workspace_id: str) -> dict:
        resp = self._request("POST", f"/workspaces/{workspace_id}/start")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_stop(self, workspace_id: str) -> dict:
        resp = self._request("POST", f"/workspaces/{workspace_id}/stop")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_delete(self, workspace_id: str) -> None:
        resp = self._request("DELETE", f"/workspaces/{workspace_id}")
        self._raise_for_status(resp)

    # --- files ---
    def workspace_files(self, workspace_id: str, path: str = ".") -> dict:
        resp = self._request(
            "GET", f"/workspaces/{workspace_id}/files", params={"path": path}
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_file_content(
        self, workspace_id: str, path: str, offset: int = 1, limit: int = 2000
    ) -> dict:
        resp = self._request(
            "GET",
            f"/workspaces/{workspace_id}/files/content",
            params={"path": path, "offset": offset, "limit": limit},
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_file_edit(
        self,
        workspace_id: str,
        path: str,
        content: str,
        base_content: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """Request a file edit through the editor flow (creates a run waiting
        for owner approval)."""
        # Fetch current content if base_content not supplied.
        if base_content is None:
            current = self.workspace_file_content(workspace_id, path)
            base_content = current.get("content", "")
        body: dict[str, Any] = {
            "path": path,
            "base_content": base_content,
            "content": content,
        }
        if session_id is not None:
            body["session_id"] = session_id
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/file-edits", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_file_download(self, workspace_id: str, remote_path: str, local_path: str) -> dict:
        """Download a file from workspace to local filesystem."""
        data = self.workspace_file_content(workspace_id, remote_path)
        content = data.get("content", "")
        try:
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as exc:
            raise DarkmageError(f"Cannot write to {local_path}: {exc}")
        return {
            "workspace_id": workspace_id,
            "remote_path": remote_path,
            "local_path": local_path,
            "size_bytes": data.get("size_bytes", 0),
        }

    def workspace_file_put(self, workspace_id: str, path: str, content: str) -> dict:
        """Directly write (overwrite) a file in the workspace without approval flow."""
        resp = self._request(
            "PUT",
            f"/workspaces/{workspace_id}/files/content",
            params={"path": path},
            json={"content": content},
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_file_delete(self, workspace_id: str, path: str) -> dict:
        """Directly delete a file from the workspace without approval flow."""
        resp = self._request(
            "DELETE",
            f"/workspaces/{workspace_id}/files/content",
            params={"path": path},
        )
        self._raise_for_status(resp)
        return {"workspace_id": workspace_id, "path": path, "status": "deleted"}

    def workspace_file_upload(self, local_path: str, workspace_id: str, remote_path: str) -> dict:
        """Upload a local file to workspace (direct write, no approval flow)."""
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            raise DarkmageError(f"Cannot read {local_path}: {exc}")
        return self.workspace_file_put(workspace_id, remote_path, content)

    def workspace_file_upload_binary(self, local_path: str, workspace_id: str, remote_path: str) -> dict:
        """Upload a binary file to workspace (base64 encoded via edit flow)."""
        try:
            data = Path(local_path).read_bytes()
        except OSError as exc:
            raise DarkmageError(f"Cannot read {local_path}: {exc}")
        if len(data) > 1_500_000:
            raise DarkmageError(f"File too large (>1.5 MB): {local_path}")
        import base64
        return self.workspace_file_edit(
            workspace_id=workspace_id,
            path=remote_path,
            content=base64.b64encode(data).decode("ascii"),
            base_content="",
        )

    def workspace_export_zip(self, workspace_id: str) -> dict:
        """Download the entire workspace as a ZIP archive."""
        # This is a streaming endpoint; return metadata so caller can stream.
        resp = self._request(
            "GET",
            f"/workspaces/{workspace_id}/export.zip",
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_search(
        self, workspace_id: str, query: str, path: str = "."
    ) -> dict:
        resp = self._request(
            "GET",
            f"/workspaces/{workspace_id}/files/search",
            params={"query": query, "path": path},
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- sessions ---
    def session_create(
        self, workspace_id: str, title: str | None = None
    ) -> dict:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/sessions", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def session_list(self, workspace_id: str, limit: int = 50) -> list[dict]:
        resp = self._request(
            "GET", f"/workspaces/{workspace_id}/sessions", params={"limit": limit}
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- global sessions (one workspace per user, sessions are the projects) ---
    def session_new(self, title: str | None = None) -> dict:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        resp = self._request("POST", "/sessions", json=body)
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def session_all(self, limit: int = 50, archived: bool = False) -> list[dict]:
        resp = self._request(
            "GET", "/sessions", params={"limit": limit, "archived": str(archived).lower()}
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def session_runs(self, session_id: str) -> list[dict]:
        resp = self._request("GET", f"/sessions/{session_id}/runs")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def session_files(self, session_id: str, path: str = ".") -> dict:
        resp = self._request(
            "GET", f"/sessions/{session_id}/files", params={"path": path}
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def session_read_file(self, session_id: str, path: str) -> dict:
        resp = self._request(
            "GET",
            f"/sessions/{session_id}/files/content",
            params={"path": path},
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- runs ---
    def run_create(
        self,
        session_id: str,
        prompt: str,
        model: str | None = None,
        plan_only: bool = False,
        thorough: bool = False,
        images: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"prompt": prompt, "plan_only": plan_only}
        if model is not None:
            body["model"] = model
        if thorough:
            body["thorough"] = thorough
        if images:
            image_list: list[dict[str, str]] = []
            for image_path in images:
                p = Path(image_path)
                if not p.is_file():
                    raise DarkmageError(f"Image not found: {image_path}")
                data = p.read_bytes()
                if len(data) > 1_500_000:
                    raise DarkmageError(f"Image too large (>1.5 MB): {image_path}")
                mime = _image_mime(data)
                image_list.append(
                    {
                        "media_type": mime,
                        "data_base64": base64.b64encode(data).decode("ascii"),
                    }
                )
            body["images"] = image_list
        resp = self._request(
            "POST", f"/sessions/{session_id}/runs", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def run_get(self, run_id: str) -> dict:
        resp = self._request("GET", f"/runs/{run_id}")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def run_stop(self, run_id: str) -> dict:
        resp = self._request("POST", f"/runs/{run_id}/stop")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def approval_list(
        self,
        limit: int = 50,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> list:
        """Pending approvals across the current user's runs, newest first.

        ``run_id``/``session_id`` narrow the list server-side; ownership is
        still enforced, so a foreign id returns an empty list.
        """
        params: dict[str, object] = {"limit": limit}
        if run_id:
            params["run_id"] = run_id
        if session_id:
            params["session_id"] = session_id
        resp = self._request("GET", "/approvals", params=params)
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def approval_get(self, approval_id: str) -> dict:
        """One owner-scoped approval by its safe approval id."""
        resp = self._request("GET", f"/approvals/{approval_id}")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def tool_call_approve(self, tool_call_id: str, scope: str = "call") -> dict:
        """Approve a pending tool call (``scope`` is ``call`` or ``turn``)."""
        if scope not in ("call", "turn"):
            raise DarkmageError("Approval scope must be 'call' or 'turn'")
        resp = self._request(
            "POST",
            f"/tool-calls/{tool_call_id}/approve",
            json={"scope": scope},
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def tool_call_reject(self, tool_call_id: str) -> dict:
        """Reject a pending tool call; the agent receives ``approval_rejected``."""
        resp = self._request("POST", f"/tool-calls/{tool_call_id}/reject")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def run_events(self, run_id: str, last_event_id: str | None = None) -> str:
        headers = dict(self._headers())
        headers["Accept"] = "text/event-stream"
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        resp = self._client.get(
            f"{self.base_url}/runs/{run_id}/events", headers=headers
        )
        self._raise_for_status(resp)
        return resp.text

    def run_events_parsed(
        self,
        run_id: str,
        last_event_id: int | None = None,
        *,
        max_retries: int = 6,
        initial_backoff: float = 0.5,
        max_backoff: float = 30.0,
    ) -> Iterator[dict[str, Any]]:
        """Stream parsed SSE events from /runs/{run_id}/events.

        Yields dicts with keys: id, event, data, _at. The stream reconnects with
        bounded exponential backoff and ``Last-Event-ID`` after a dropped
        connection; already yielded sequence numbers are deduplicated so a run
        is never lost just because the terminal output was interrupted.
        Stops after the run reaches a terminal state.
        """
        last_sequence = _event_sequence(last_event_id) or 0
        consecutive_failures = 0

        while True:
            error: DarkmageError | None = None
            try:
                for event in self._iter_sse_events(
                    run_id, last_sequence if last_sequence else None
                ):
                    consecutive_failures = 0
                    sequence = _event_sequence(event.get("id"))
                    if sequence is not None:
                        if sequence <= last_sequence:
                            # Server replayed the boundary event after reconnect.
                            continue
                        last_sequence = sequence
                    yield event
                    if event.get("event") in TERMINAL_EVENTS:
                        return
            except DarkmageError as exc:
                if not exc.retryable:
                    raise
                error = exc
            except httpx.RequestError as exc:
                error = DarkmageError(
                    f"SSE stream interrupted: {exc}", retryable=True
                )
            except httpx.StreamError as exc:
                error = DarkmageError(
                    f"SSE stream interrupted: {exc}", retryable=True
                )
            except OSError as exc:
                error = DarkmageError(
                    f"SSE stream interrupted: {exc}", retryable=True
                )

            # A clean EOF without a terminal event means the server closed the
            # connection (deploy, proxy timeout). Reconnect unless the run has
            # actually finished; the terminal event may simply have been lost.
            if self._run_is_finished(run_id):
                return

            consecutive_failures += 1
            if consecutive_failures > max_retries:
                if error is not None:
                    raise error
                raise DarkmageError(
                    f"SSE stream for {run_id} closed after "
                    f"{max_retries} reconnect attempts",
                    retryable=True,
                )
            delay = min(
                max_backoff, initial_backoff * (2 ** (consecutive_failures - 1))
            )
            if delay > 0:
                time.sleep(delay)

    def _iter_sse_events(
        self, run_id: str, last_event_id: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """One connection to the SSE endpoint (no reconnect logic)."""
        headers = dict(self._headers())
        headers["Accept"] = "text/event-stream"
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        with self._client.stream(
            "GET", f"{self.base_url}/runs/{run_id}/events", headers=headers
        ) as resp:
            self._raise_for_status(resp)
            event_id = ""
            event_type = ""
            data_lines: list[str] = []
            for raw_line in resp.iter_lines():
                if raw_line == "":
                    if data_lines:
                        payload_text = "\n".join(data_lines)
                        try:
                            payload = json.loads(payload_text)
                        except json.JSONDecodeError:
                            payload = {"raw": payload_text}
                        event = {
                            "id": event_id,
                            "event": event_type,
                            "data": payload,
                        }
                        event_id = ""
                        event_type = ""
                        data_lines = []
                        yield event
                    continue
                if raw_line.startswith(":"):
                    continue  # keep-alive / comment
                field, separator, value = raw_line.partition(":")
                if not separator:
                    continue
                if value.startswith(" "):
                    value = value[1:]
                if field == "id":
                    event_id = value
                elif field == "event":
                    event_type = value
                elif field == "data":
                    data_lines.append(value)
            if data_lines:
                payload_text = "\n".join(data_lines)
                try:
                    payload = json.loads(payload_text)
                except json.JSONDecodeError:
                    payload = {"raw": payload_text}
                yield {"id": event_id, "event": event_type, "data": payload}

    def _run_is_finished(self, run_id: str) -> bool:
        try:
            run = self.run_get(run_id)
        except DarkmageError:
            return False
        return (
            isinstance(run, dict)
            and str(run.get("status") or "") in TERMINAL_RUN_STATUSES
        )

    def run_answer(self, run_id: str, question_id: str, answers: list[str]) -> dict:
        resp = self._request(
            "POST",
            f"/runs/{run_id}/questions/{question_id}",
            json={"answers": answers},
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def run_context(self, run_id: str) -> dict:
        run = self.run_get(run_id)
        return {
            "run_id": run_id,
            "status": run.get("status"),
            "context_tokens": run.get("context_tokens"),
            "context_limit": run.get("context_limit"),
            "prompt_tokens": run.get("prompt_tokens"),
            "completion_tokens": run.get("completion_tokens"),
        }

    def run_message(self, run_id: str, text: str) -> dict:
        resp = self._request(
            "POST", f"/runs/{run_id}/messages", json={"text": text}
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def run_revert(self, run_id: str) -> dict:
        resp = self._request("POST", f"/runs/{run_id}/revert")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def run_review(self, run_id: str) -> dict:
        resp = self._request("POST", f"/runs/{run_id}/review")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def run_patch(self, run_id: str) -> str:
        """Download a finished run's changes as a unified git patch.

        The response is ``text/x-patch`` (not JSON).  HTTP errors keep their
        status and detail from :meth:`_raise_for_status`, so callers can map
        402/404/409/413 to friendly messages; the bearer token never enters
        the exception text.
        """
        resp = self._request(
            "GET",
            f"/runs/{run_id}/patch",
            headers={"Accept": "text/x-patch"},
        )
        self._raise_for_status(resp)
        content = getattr(resp, "content", None)
        if not isinstance(content, (bytes, bytearray)):
            content = str(getattr(resp, "text", "") or "").encode("utf-8")
        return _PatchText(bytes(content))

    def run_list(self, workspace_id: str) -> list[dict]:
        resp = self._request(
            "GET", f"/workspaces/{workspace_id}/runs"
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def run_list_for_session(self, session_id: str) -> list[dict]:
        resp = self._request("GET", f"/sessions/{session_id}/runs")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- chat ---
    def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> dict:
        body = self._chat_body(messages, model, temperature, max_tokens)
        resp = self._request("POST", "/chat/completion", json=body)
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    @staticmethod
    def _chat_body(
        messages: list[dict[str, str]],
        model: str | None,
        temperature: float,
        max_tokens: int | None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
        }
        if model is not None:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if stream:
            body["stream"] = True
        return body

    def chat_completion_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized chat deltas as they arrive.

        The server currently returns a regular JSON completion; newer/streaming
        deployments may return OpenAI-style ``text/event-stream`` chunks. Both
        are handled, so the command works against either version. Events are
        ``{"type": "delta", "text": ...}``, ``{"type": "usage", "usage": {...}}``
        and a final ``{"type": "done"}``.
        """
        body = self._chat_body(
            messages, model, temperature, max_tokens, stream=True
        )
        headers = dict(self._headers())
        headers["Accept"] = "text/event-stream, application/json"
        url = f"{self.base_url}/chat/completion"
        try:
            with self._client.stream(
                "POST",
                url,
                json=body,
                headers=headers,
            ) as resp:
                if resp.status_code >= 400:
                    # Streaming responses must be read before
                    # _raise_for_status can inspect a JSON error body.
                    resp.read()
                    self._raise_for_status(resp)
                content_type = resp.headers.get("content-type", "").lower()
                if "text/event-stream" in content_type:
                    for raw_line in resp.iter_lines():
                        line = raw_line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data:"):
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                payload = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                        elif line.startswith("{"):
                            try:
                                payload = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                        else:
                            continue
                        yield from _chat_events_from_payload(payload)
                else:
                    resp.read()
                    try:
                        payload = resp.json()
                    except ValueError as exc:
                        raise DarkmageError(
                            "Chat server returned a non-JSON response"
                        ) from exc
                    if not isinstance(payload, dict):
                        raise DarkmageError(
                            "Chat server returned an invalid response"
                        )
                    yield from _chat_events_from_payload(payload)
        except (httpx.RequestError, httpx.StreamError, OSError) as exc:
            raise DarkmageError(
                f"Cannot reach {url}: {exc}", retryable=True
            ) from exc
        yield {"type": "done"}

    # --- health ---
    def health(self) -> dict:
        resp = self._request("GET", "/health")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def ready(self) -> dict:
        resp = self._request("GET", "/ready")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- billing ---
    def payment_create(
        self, product: str = "standard_30d", amount_rub: int | None = None
    ) -> dict:
        body: dict[str, Any] = {"product": product}
        if amount_rub is not None:
            body["amount_rub"] = amount_rub
        resp = self._request("POST", "/billing/payments", json=body)
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def payment_list(self) -> list[dict]:
        resp = self._request("GET", "/billing/payments")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- admin ---
    def admin_status(self) -> dict:
        resp = self._request("GET", "/admin/status")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- git (Phase 3, requires backend GitHub App integration) ---
    def git_clone(self, workspace_id: str, url: str, ref: str | None = None, depth: int = 1) -> dict:
        body: dict[str, Any] = {"url": url, "depth": depth}
        if ref is not None:
            body["ref"] = ref
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/git/clone", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def git_commit(
        self, workspace_id: str, message: str, branch: str | None = None
    ) -> dict:
        body: dict[str, Any] = {"message": message}
        if branch is not None:
            body["branch"] = branch
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/git/commit", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def git_push(self, workspace_id: str, branch: str | None = None) -> dict:
        body: dict[str, Any] = {}
        if branch is not None:
            body["branch"] = branch
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/git/push", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def git_pr_create(
        self,
        workspace_id: str,
        title: str,
        body: str | None = None,
        base: str = "main",
        head: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"title": title, "base": base}
        if body is not None:
            payload["body"] = body
        if head is not None:
            payload["head"] = head
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/git/pr", json=payload
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- mcp (Phase 3, requires backend MCP server) ---
    def mcp_list(self) -> dict:
        resp = self._request("GET", "/mcp/tools")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def mpc_call(
        self, tool: str, arguments: dict[str, Any], workspace_id: str | None = None
    ) -> dict:
        body: dict[str, Any] = {"tool": tool, "arguments": arguments}
        if workspace_id is not None:
            body["workspace_id"] = workspace_id
        resp = self._request(
            "POST", "/mcp/call", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- pty (Phase 3, interactive terminal) ---
    def pty_create(self, workspace_id: str, cwd: str | None = None) -> dict:
        body: dict[str, Any] = {}
        if cwd is not None:
            body["cwd"] = cwd
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/pty", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def pty_stop(self, workspace_id: str, session_id: str) -> dict:
        resp = self._request(
            "DELETE", f"/workspaces/{workspace_id}/pty/{session_id}"
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def process_start(
        self, workspace_id: str, argv: list[str], cwd: str | None = None, port: int | None = None
    ) -> dict:
        body: dict[str, Any] = {"argv": argv}
        if cwd is not None:
            body["cwd"] = cwd
        if port is not None:
            body["port"] = port
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/processes", json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def process_output(
        self, workspace_id: str, process_id: str | None = None
    ) -> dict:
        params: dict[str, Any] = {}
        if process_id is not None:
            params["process_id"] = process_id
        resp = self._request(
            "GET", f"/workspaces/{workspace_id}/processes", params=params
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def process_stop(self, workspace_id: str, process_id: str) -> dict:
        resp = self._request(
            "POST", f"/workspaces/{workspace_id}/processes/{process_id}/stop"
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- APK / Godot (runner-manager, port 8090) ---
    def workspace_build_apk(
        self,
        workspace_id: str,
        web_dir: str = ".",
        output: str = "android/app-debug.apk",
        app_name: str = "",
        app_id: str | None = None,
        version_code: int = 1,
    ) -> dict:
        """Build a debug Android APK from the workspace's web files via runner-manager."""
        body: dict[str, Any] = {
            "web_dir": web_dir,
            "output": output,
            "app_name": app_name,
            "version_code": version_code,
        }
        if app_id:
            body["app_id"] = app_id
        resp = self._request("POST", f"/v1/workspaces/{workspace_id}/apk", runner=True, json=body)
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_export_godot(
        self,
        workspace_id: str,
        project_dir: str = ".",
        output_dir: str = "godot-web",
    ) -> dict:
        """Export a Godot 4 project to a Web build via runner-manager."""
        body: dict[str, Any] = {
            "project_dir": project_dir,
            "output_dir": output_dir,
        }
        resp = self._request(
            "POST", f"/v1/workspaces/{workspace_id}/godot", runner=True, json=body
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_blender(
        self,
        workspace_id: str,
        blend_path: str,
        output: str,
        preview: bool = False,
        metadata: bool = True,
    ) -> dict:
        """Convert a .blend file to .glb for Godot via runner-manager."""
        body: dict[str, Any] = {
            "blend_path": blend_path,
            "output": output,
            "preview": preview,
            "metadata": metadata,
        }
        resp = self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/blender",
            runner=True,
            json=body,
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_godot_tests(
        self,
        workspace_id: str,
        test_dir: str = "res://tests",
        test_suffix: str = "_test.gd",
    ) -> dict:
        """Run Godot Unit Test (GUT) tests headless via runner-manager."""
        body: dict[str, Any] = {
            "test_dir": test_dir,
            "test_suffix": test_suffix,
        }
        resp = self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/godot-tests",
            runner=True,
            json=body,
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_tiled_import(
        self, workspace_id: str, tmx_path: str, output: str
    ) -> dict:
        """Import a Tiled .tmx map into a Godot .tscn scene via runner-manager."""
        body: dict[str, Any] = {
            "tmx_path": tmx_path,
            "output": output,
        }
        resp = self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/tiled-import",
            runner=True,
            json=body,
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def workspace_ldtk_import(
        self, workspace_id: str, ldtk_path: str, output: str
    ) -> dict:
        """Import an LDtk .ldtk project into a Godot .tscn scene via runner-manager."""
        body: dict[str, Any] = {
            "ldtk_path": ldtk_path,
            "output": output,
        }
        resp = self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/ldtk-import",
            runner=True,
            json=body,
        )
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def close(self) -> None:
        self._client.close()


def _event_sequence(value: Any) -> int | None:
    """Parse an SSE event id (run event sequence) into an integer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise DarkmageError("Unsupported image format (PNG, JPEG, WEBP only)")


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def print_error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)
