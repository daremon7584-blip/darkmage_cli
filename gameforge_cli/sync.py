"""Two-way file synchronisation between local filesystem and Gameforge workspace.

Features:
  * pull  — download workspace files to local directory
  * push  — upload local files to workspace
  * diff  — show differences between local and workspace
  * watch — watch local directory and push changes automatically
  * conflict detection via SHA-256 checksums
  * progress bars for long transfers
  * skip lists (.gameforgeignore, .git, __pycache__, node_modules, .venv)
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import GameforgeClient, GameforgeError


# ---------------------------------------------------------------------------
# Default ignore patterns (like .gitignore but for Gameforge sync)
# ---------------------------------------------------------------------------
DEFAULT_IGNORE_PATTERNS = [
    ".git",
    ".git/",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".venv",
    "venv/",
    "node_modules",
    ".npm",
    ".cache",
    ".DS_Store",
    "Thumbs.db",
    ".gameforge",
    ".gameforge-cli",
    "*.log",
    "*.tmp",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
]


def load_ignore_patterns(local_dir: Path) -> list[str]:
    """Load ignore patterns from .gameforgeignore if present, plus defaults."""
    patterns = list(DEFAULT_IGNORE_PATTERNS)
    ignore_file = local_dir / ".gameforgeignore"
    if ignore_file.is_file():
        try:
            for line in ignore_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        except OSError:
            pass
    return patterns


def should_ignore(rel_path: str, patterns: list[str]) -> bool:
    """Return True if rel_path matches any ignore pattern."""
    for pat in patterns:
        if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(rel_path, "/" + pat):
            return True
        # Also match any path component
        parts = rel_path.replace("\\", "/").split("/")
        for part in parts:
            if fnmatch.fnmatch(part, pat):
                return True
    return False


def sha256_of_file(path: Path) -> str:
    """SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_local_files(local_dir: Path, patterns: list[str]) -> list[tuple[Path, str]]:
    """Return list of (absolute_path, relative_path) for non-ignored files."""
    results: list[tuple[Path, str]] = []
    for root, dirs, files in os.walk(local_dir):
        # Filter dirs in-place so os.walk does not descend into ignored dirs
        dirs[:] = [d for d in dirs if not should_ignore(d, patterns)]
        for name in files:
            abs_path = Path(root) / name
            rel_path = abs_path.relative_to(local_dir).as_posix()
            if should_ignore(rel_path, patterns):
                continue
            results.append((abs_path, rel_path))
    return results


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------


class Progress:
    """Simple terminal progress bar with percentage."""

    def __init__(self, total: int, label: str = "", width: int = 30) -> None:
        self.total = max(total, 1)
        self.done = 0
        self.label = label
        self.width = width
        self._start = time.monotonic()
        self._is_tty = sys.stdout.isatty()

    def update(self, n: int | None = None, label: str | None = None) -> None:
        if n is not None:
            self.done = min(n, self.total)
        if label is not None:
            self.label = label
        self._render()

    def increment(self, label: str | None = None) -> None:
        self.done = min(self.done + 1, self.total)
        if label is not None:
            self.label = label
        self._render()

    def _render(self) -> None:
        if not self._is_tty:
            return
        ratio = self.done / self.total
        filled = int(self.width * ratio)
        bar = "█" * filled + "░" * (self.width - filled)
        pct = ratio * 100
        elapsed = time.monotonic() - self._start
        rate = self.done / elapsed if elapsed > 0 else 0
        sys.stdout.write(
            f"\r{self.label} |{bar}| {pct:5.1f}% ({self.done}/{self.total}) {rate:.1f} files/s"
        )
        sys.stdout.flush()
        if self.done >= self.total:
            sys.stdout.write("\n")

    def finish(self) -> None:
        self.done = self.total
        self._render()


# ---------------------------------------------------------------------------
# Workspace <-> local file listing
# ---------------------------------------------------------------------------


@dataclass
class FileEntry:
    path: str
    size_bytes: int
    checksum: str | None = None
    is_dir: bool = False


@dataclass
class SyncState:
    local_files: dict[str, FileEntry] = field(default_factory=dict)
    workspace_files: dict[str, FileEntry] = field(default_factory=dict)
    to_upload: list[str] = field(default_factory=list)
    to_download: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    identical: list[str] = field(default_factory=list)
    only_local: list[str] = field(default_factory=list)
    only_workspace: list[str] = field(default_factory=list)


def list_local_files(local_dir: Path, patterns: list[str]) -> dict[str, FileEntry]:
    """Build a dict of relative_path -> FileEntry for local files."""
    entries: dict[str, FileEntry] = {}
    for abs_path, rel_path in walk_local_files(local_dir, patterns):
        try:
            st = abs_path.stat()
            entries[rel_path] = FileEntry(
                path=rel_path,
                size_bytes=st.st_size,
                checksum=sha256_of_file(abs_path),
            )
        except OSError:
            continue
    return entries


def list_workspace_files(client: GameforgeClient, workspace_id: str) -> dict[str, FileEntry]:
    """Build a dict of relative_path -> FileEntry for workspace files (recursive)."""
    entries: dict[str, FileEntry] = {}
    _collect_workspace_entries(client, workspace_id, ".", entries)
    return entries


def _collect_workspace_entries(
    client: GameforgeClient, workspace_id: str, path: str, entries: dict[str, FileEntry]
) -> None:
    """Recursively collect workspace file entries."""
    try:
        data = client.workspace_files(workspace_id, path)
    except GameforgeError:
        return
    for item in data.get("entries", []):
        name = item.get("name", "")
        kind = item.get("kind", "file")
        entry_path = f"{path}/{name}" if path != "." else name
        if kind == "directory":
            _collect_workspace_entries(client, workspace_id, entry_path, entries)
        else:
            entries[entry_path] = FileEntry(
                path=entry_path,
                size_bytes=item.get("size_bytes", 0),
            )


def compute_sync_state(
    local_dir: Path,
    client: GameforgeClient,
    workspace_id: str,
    patterns: list[str],
) -> SyncState:
    """Compare local and workspace files and produce a sync plan."""
    local = list_local_files(local_dir, patterns)
    workspace = list_workspace_files(client, workspace_id)

    state = SyncState(local_files=local, workspace_files=workspace)

    local_paths = set(local.keys())
    workspace_paths = set(workspace.keys())

    state.only_local = sorted(local_paths - workspace_paths)
    state.only_workspace = sorted(workspace_paths - local_paths)
    common = local_paths & workspace_paths

    for rel in sorted(common):
        lf = local[rel]
        wf = workspace[rel]
        # Compare by size and checksum (workspace may not have checksum yet)
        if lf.checksum and wf.checksum and lf.checksum == wf.checksum:
            state.identical.append(rel)
        elif lf.size_bytes == wf.size_bytes:
            # Same size but no checksums to compare — treat as potential conflict
            state.conflicts.append(rel)
        else:
            # Different sizes — newer wins based on user choice later
            state.conflicts.append(rel)

    # Files only in local -> upload
    state.to_upload = state.only_local
    # Files only in workspace -> download
    state.to_download = state.only_workspace

    return state


# ---------------------------------------------------------------------------
# Pull / Push / Diff / Watch
# ---------------------------------------------------------------------------


def sync_pull(
    client: GameforgeClient,
    workspace_id: str,
    local_dir: Path,
    patterns: list[str] | None = None,
    auto_resolve: str = "workspace",  # "workspace" | "local" | "ask"
) -> dict[str, Any]:
    """Download workspace files that are missing or different locally.

    Returns a summary dict with counts.
    """
    if patterns is None:
        patterns = load_ignore_patterns(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    state = compute_sync_state(local_dir, client, workspace_id, patterns)

    progress = Progress(len(state.to_download) + len(state.conflicts), label="Pulling")
    downloaded = 0
    skipped = 0
    errors: list[str] = []

    def handle(rel: str, source: str) -> None:
        nonlocal downloaded, skipped
        local_path = local_dir / rel
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = client.workspace_file_content(workspace_id, rel)
            content = data.get("content", "")
            local_path.write_text(content, encoding="utf-8")
            downloaded += 1
            progress.update(downloaded + skipped, label=f"Pulling {source}: {rel}")
        except GameforgeError as exc:
            errors.append(f"{rel}: {exc}")
            skipped += 1
            progress.update(downloaded + skipped, label=f"Pulling {source}: {rel} (error)")

    for rel in state.to_download:
        handle(rel, "workspace")

    for rel in state.conflicts:
        if auto_resolve == "workspace":
            handle(rel, "conflict(workspace wins)")
        elif auto_resolve == "local":
            skipped += 1
            progress.update(downloaded + skipped, label=f"Pulling: {rel} (local kept)")
        else:
            # ask: default to workspace for non-interactive, log conflict
            errors.append(f"{rel}: conflict — use 'gameforge files sync resolve <path>'")
            skipped += 1
            progress.update(downloaded + skipped, label=f"Pulling: {rel} (conflict)")

    progress.finish()
    return {
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
        "conflicts": state.conflicts,
        "identical": len(state.identical),
    }


def sync_push(
    client: GameforgeClient,
    workspace_id: str,
    local_dir: Path,
    patterns: list[str] | None = None,
    auto_resolve: str = "local",  # "local" | "workspace" | "ask"
) -> dict[str, Any]:
    """Upload local files that are missing or different in the workspace.

    Returns a summary dict with counts.
    """
    if patterns is None:
        patterns = load_ignore_patterns(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    state = compute_sync_state(local_dir, client, workspace_id, patterns)

    total = len(state.to_upload) + len(state.conflicts)
    progress = Progress(total, label="Pushing")
    uploaded = 0
    skipped = 0
    errors: list[str] = []

    def handle(rel: str, source: str) -> None:
        nonlocal uploaded, skipped
        local_path = local_dir / rel
        try:
            content = local_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{rel}: cannot read ({exc})")
            skipped += 1
            progress.update(uploaded + skipped, label=f"Pushing {source}: {rel} (skip)")
            return
        try:
            client.workspace_file_put(workspace_id, rel, content)
            uploaded += 1
            progress.update(uploaded + skipped, label=f"Pushing {source}: {rel}")
        except GameforgeError as exc:
            errors.append(f"{rel}: {exc}")
            skipped += 1
            progress.update(uploaded + skipped, label=f"Pushing {source}: {rel} (error)")

    for rel in state.to_upload:
        handle(rel, "local")

    for rel in state.conflicts:
        if auto_resolve == "local":
            handle(rel, "conflict(local wins)")
        elif auto_resolve == "workspace":
            skipped += 1
            progress.update(uploaded + skipped, label=f"Pushing: {rel} (workspace kept)")
        else:
            errors.append(f"{rel}: conflict — use 'gameforge files sync resolve <path>'")
            skipped += 1
            progress.update(uploaded + skipped, label=f"Pushing: {rel} (conflict)")

    progress.finish()
    return {
        "uploaded": uploaded,
        "skipped": skipped,
        "errors": errors,
        "conflicts": state.conflicts,
        "identical": len(state.identical),
    }


def sync_diff(
    client: GameforgeClient,
    workspace_id: str,
    local_dir: Path,
    patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Show differences between local and workspace without transferring."""
    if patterns is None:
        patterns = load_ignore_patterns(local_dir)
    state = compute_sync_state(local_dir, client, workspace_id, patterns)
    return {
        "identical": state.identical,
        "only_local": state.only_local,
        "only_workspace": state.only_workspace,
        "conflicts": state.conflicts,
        "to_upload": state.to_upload,
        "to_download": state.to_download,
    }


def sync_watch(
    client: GameforgeClient,
    workspace_id: str,
    local_dir: Path,
    patterns: list[str] | None = None,
    interval: float = 2.0,
) -> None:
    """Watch local directory for changes and push them to workspace.

    Runs until interrupted (Ctrl-C). Simple polling-based watcher.
    """
    import select

    if patterns is None:
        patterns = load_ignore_patterns(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    print(f"👀 Watching {local_dir} for changes (Ctrl-C to stop)...")
    print(f"   Workspace: {workspace_id}")
    print(f"   Ignore patterns: {', '.join(patterns[:6])}{'...' if len(patterns) > 6 else ''}")
    print()

    last_state: dict[str, float] = {}  # rel_path -> mtime

    try:
        while True:
            current_state: dict[str, float] = {}
            changed: list[str] = []

            for abs_path, rel_path in walk_local_files(local_dir, patterns):
                try:
                    mtime = abs_path.stat().st_mtime
                    current_state[rel_path] = mtime
                    if last_state.get(rel_path) != mtime:
                        changed.append(rel_path)
                except OSError:
                    continue

            # Detect deletions
            for rel_path in last_state:
                if rel_path not in current_state:
                    changed.append(f"[deleted] {rel_path}")

            last_state = current_state

            for rel_path in changed:
                if rel_path.startswith("[deleted]"):
                    actual = rel_path[len("[deleted] "):]
                    print(f"🗑  Deleted locally: {actual}")
                    try:
                        client.workspace_file_delete(workspace_id, actual)
                        print(f"   ✅ Removed from workspace")
                    except GameforgeError as exc:
                        print(f"   ❌ Failed to delete: {exc}")
                else:
                    print(f"📝 Changed locally: {rel_path}")
                    try:
                        content = (local_dir / rel_path).read_text(encoding="utf-8")
                        client.workspace_file_put(workspace_id, rel_path, content)
                        print(f"   ✅ Pushed to workspace")
                    except (OSError, UnicodeDecodeError) as exc:
                        print(f"   ❌ Cannot read: {exc}")
                    except GameforgeError as exc:
                        print(f"   ❌ Push failed: {exc}")

            if changed:
                print()

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n👋 Watcher stopped.")

