from __future__ import annotations

import base64
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from .config import get_base_url, get_token


class OdysseyError(Exception):
    pass


class OdysseyClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self.token = token or get_token()
        self._client = httpx.Client(timeout=60.0)

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        kwargs.setdefault("headers", {}).update(self._headers())
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            raise OdysseyError(f"Cannot reach {url}: {exc}") from exc
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
            raise OdysseyError(
                f"{resp.status_code} {resp.reason_phrase} for {resp.request.method} {resp.url.path}: {detail}"
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
            raise OdysseyError("Provide --name or --approval-mode")
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
                    raise OdysseyError(f"Image not found: {image_path}")
                data = p.read_bytes()
                if len(data) > 1_500_000:
                    raise OdysseyError(f"Image too large (>1.5 MB): {image_path}")
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
        self, run_id: str, last_event_id: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Stream parsed SSE events from /runs/{run_id}/events.

        Yields dicts with keys: id, event, data, _at.
        Stops after the run reaches a terminal state.
        """
        headers = dict(self._headers())
        headers["Accept"] = "text/event-stream"
        if last_event_id is not None:
            headers["Last-Event-ID"] = str(last_event_id)
        with self._client.stream(
            "GET", f"{self.base_url}/runs/{run_id}/events", headers=headers
        ) as resp:
            self._raise_for_status(resp)
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                if raw_line.startswith(":"):
                    continue  # keep-alive
                if raw_line.startswith("id: "):
                    event_id = raw_line[4:]
                elif raw_line.startswith("event: "):
                    event_type = raw_line[7:]
                elif raw_line.startswith("data: "):
                    try:
                        payload = json.loads(raw_line[6:])
                    except json.JSONDecodeError:
                        payload = {"raw": raw_line[6:]}
                    yield {
                        "id": event_id,
                        "event": event_type,
                        "data": payload,
                    }
                    event_id = ""
                    event_type = ""

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

    # --- chat ---
    def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
        }
        if model is not None:
            body["model"] = model
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        resp = self._request("POST", "/chat/completion", json=body)
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    # --- health ---
    def health(self) -> dict:
        resp = self._request("GET", "/health")
        self._raise_for_status(resp)
        return self._json_or_text(resp)

    def ready(self) -> dict:
        resp = self._request("GET", "/ready")
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

    def close(self) -> None:
        self._client.close()


def _image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise OdysseyError("Unsupported image format (PNG, JPEG, WEBP only)")


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def print_error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)
