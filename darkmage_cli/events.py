"""Rendering helpers for run events shared by the CLI and the TUI.

The backend event payloads are the source of truth:

* ``approval.required``: ``approval_id``, ``tool_call_id``, ``name``,
  ``arguments`` and, for file edits, ``before_content`` / ``before_exists``.
* ``agent.question``: ``question_id`` and ``questions: [{question, options}]``.
* ``diff.ready``: ``path``, ``before_content``, ``before_exists`` and
  ``after_content``.

Keeping the parsing here means the plain CLI and the TUI cannot drift apart
again (P1-2/P1-3 in docs/CLIENT_RESEARCH).
"""

from __future__ import annotations

import difflib
import json
from typing import Any

TERMINAL_EVENTS = frozenset({"run.completed", "run.failed", "run.cancelled"})

_DIFF_LIMIT = 400
_CARD_DIFF_LIMIT = 80


def question_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise the two question payload shapes into a list of questions.

    The backend emits ``questions: [{question, options: [{label, description}]}]``.
    Older/simplified events (and tests) may still carry a single ``question``
    string, so both forms are accepted.
    """
    questions = data.get("questions")
    items: list[dict[str, Any]] = []
    if isinstance(questions, list):
        for entry in questions:
            if isinstance(entry, dict):
                text = entry.get("question") or entry.get("text") or entry.get("label")
                options = entry.get("options")
                normalised_options: list[dict[str, str]] = []
                if isinstance(options, list):
                    for option in options:
                        if isinstance(option, dict):
                            label = option.get("label") or option.get("value")
                            if label is None:
                                continue
                            description = option.get("description") or ""
                            normalised_options.append(
                                {"label": str(label), "description": str(description)}
                            )
                        elif option is not None:
                            normalised_options.append(
                                {"label": str(option), "description": ""}
                            )
                if text is not None:
                    items.append(
                        {"question": str(text), "options": normalised_options}
                    )
            elif entry is not None:
                items.append({"question": str(entry), "options": []})
    if not items:
        single = data.get("question") or data.get("text")
        if single:
            items.append({"question": str(single), "options": []})
    return items


def question_text(data: dict[str, Any]) -> str:
    """One-line summary of an ``agent.question`` payload (includes options)."""
    items = question_items(data)
    if not items:
        return ""
    parts: list[str] = []
    multiple = len(items) > 1
    for index, item in enumerate(items, 1):
        prefix = f"{index}. " if multiple else ""
        text = prefix + item["question"]
        labels = [option["label"] for option in item.get("options") or []]
        if labels:
            text += " [" + " / ".join(labels) + "]"
        parts.append(text)
    return "  ".join(parts)


def question_card(data: dict[str, Any]) -> str:
    """Multi-line human-readable question card used by the TUI and prompts."""
    items = question_items(data)
    question_id = data.get("question_id")
    lines = ["Agent question:"]
    if question_id:
        lines[0] += f" (id={question_id})"
    if not items:
        lines.append("  (empty payload)")
        return "\n".join(lines)
    multiple = len(items) > 1
    for index, item in enumerate(items, 1):
        prefix = f"{index}. " if multiple else "  "
        lines.append(f"{prefix}{item['question']}")
        for option_index, option in enumerate(item.get("options") or [], 1):
            description = (
                f" — {option['description']}" if option.get("description") else ""
            )
            lines.append(f"     {option_index}. {option['label']}{description}")
    return "\n".join(lines)


def _content_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, str):
        value = str(value)
    return value.splitlines()


def format_diff(
    data: dict[str, Any],
    *,
    max_lines: int = _DIFF_LIMIT,
    context: int = 3,
) -> str:
    """Render a unified diff from a ``diff.ready`` or ``approval.required`` payload."""
    path = str(data.get("path") or "")
    arguments = data.get("arguments")
    if not path and isinstance(arguments, dict):
        path = str(arguments.get("path") or "")
    before_value = data.get("before_content")
    after_value = data.get("after_content")
    if isinstance(arguments, dict):
        if before_value is None:
            before_value = arguments.get("before_content")
        if after_value is None:
            after_value = arguments.get("content")
    before = _content_lines(before_value)
    after = _content_lines(after_value)
    before_exists = data.get("before_exists")
    if before_exists is False:
        before = []
    fromfile = f"a/{path}" if path and before_exists is not False else "/dev/null"
    tofile = f"b/{path}" if path else "b/file"
    diff = list(
        difflib.unified_diff(
            before,
            after,
            fromfile=fromfile,
            tofile=tofile,
            n=context,
            lineterm="",
        )
    )
    if not diff:
        return f"{path or 'file'}: no changes"
    if len(diff) > max_lines:
        omitted = len(diff) - max_lines
        diff = diff[:max_lines] + [f"... diff truncated ({omitted} more lines) ..."]
    return "\n".join(diff)


def approval_target(data: dict[str, Any]) -> str:
    """Best-effort target of an approval (file path, command, URL, ...)."""
    arguments = data.get("arguments")
    if isinstance(arguments, dict):
        for key in ("path", "command", "url", "query", "pattern"):
            value = arguments.get(key)
            if value:
                return str(value)
        if "changes" in arguments and isinstance(arguments["changes"], list):
            paths = [
                str(change.get("path"))
                for change in arguments["changes"]
                if isinstance(change, dict) and change.get("path")
            ]
            if paths:
                return ", ".join(paths)
    return str(data.get("path") or "")


def approval_summary(data: dict[str, Any]) -> str:
    """One-line summary that always keeps the approval_id visible."""
    name = str(data.get("name") or "tool")
    target = approval_target(data)
    parts = [name]
    if target:
        parts.append(target)
    approval_id = data.get("approval_id")
    if approval_id:
        parts.append(f"approval_id={approval_id}")
    if data.get("auto"):
        parts.append("auto")
    if data.get("turn_remaining"):
        parts.append(f"turn_remaining={data['turn_remaining']}")
    return " ".join(parts)


def approval_card(data: dict[str, Any], *, diff_lines: int = _CARD_DIFF_LIMIT) -> str:
    """Approval card with arguments/diff preview shown before deciding."""
    name = str(data.get("name") or "tool")
    target = approval_target(data)
    lines = [f"Approval required: {name}" + (f"  ({target})" if target else "")]
    if data.get("auto"):
        lines.append("  (auto-approved by the server approval policy)")
        return "\n".join(lines)

    arguments = data.get("arguments")
    if isinstance(arguments, dict) and arguments:
        if not target or "path" not in arguments:
            preview = json.dumps(arguments, ensure_ascii=False, default=str)
            lines.append(f"  arguments: {preview[:500]}")

    has_diff = any(
        key in data for key in ("before_content", "after_content")
    ) or (isinstance(arguments, dict) and "content" in arguments)
    if has_diff:
        diff_data = dict(data)
        if "after_content" not in diff_data and isinstance(arguments, dict):
            diff_data["after_content"] = arguments.get("content")
        if "path" not in diff_data and isinstance(arguments, dict):
            diff_data["path"] = arguments.get("path")
        preview = format_diff(diff_data, max_lines=diff_lines)
        lines.append(preview)

    if data.get("turn_remaining"):
        lines.append(
            f"  Rest of this turn available: {data['turn_remaining']} more call(s)"
        )
    approval_id = data.get("approval_id")
    if approval_id:
        lines.append(f"  approval_id: {approval_id}")
    return "\n".join(lines)
