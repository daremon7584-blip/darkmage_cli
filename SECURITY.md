# Security notes

This file documents the client-side security guarantees that matter before a
release, plus the supply-chain work that is still deferred.

## `term` does not execute remote output locally

`darkmage term <workspace_id>` connects the remote workspace PTY WebSocket
directly to the local terminal:

- local stdin bytes are sent to the remote WebSocket;
- remote output bytes are written to local stdout verbatim;
- no local `sh`, `subprocess`, or pseudo-terminal is created;
- `Ctrl-]` detaches locally (`exit` in the remote shell also works).

The command is Unix-only (Linux/macOS/WSL) and requires an interactive TTY. On
Windows, use `darkmage tui` or `run create`/`run events`.

## Secrets in config and history

- `darkmage config show --json` prints a redacted config; token, runner token,
  passwords, API keys, and similar credential fields are replaced with
  `***REDACTED***`.
- `darkmage config set --verbose` uses the same redaction.
- `darkmage config export <file>` always writes a redacted JSON file. The file
  is written atomically with mode `0600`; a plaintext token is never exported.
- Importing a redacted export does not overwrite a live token with the
  placeholder: redacted fields are skipped.
- `darkmage history` masks `--password`, `-p`, `--token`, `--runner-token`,
  `--api-key`, `--secret`, and equivalent credential flags (both
  `--flag value` and `--flag=value` forms).
- History creates `~/.darkmage-cli` on first use, writes atomically, and keeps
  the history file at mode `0600`.

## Installers

- `install.py` runs every command as an argv list, never with `shell=True`.
- Both `install.py` and `install.sh` validate the server argument as a DNS name
  or IPv4 address before it is interpolated into URLs or shell rc lines.
- Installers update an existing clone only when it is a git checkout of the
  expected repository, and otherwise fail closed. They no longer `rm -rf`
  `~/darkmage_cli`.
- `install.sh` supports `DARKMAGE_INSTALL_DRY_RUN=1` for a safe validation-only
  run.

## Deferred supply-chain work

Full supply-chain pinning is **not** implemented yet:

- `install.sh` and `install-darkmage-termux.sh` are still documented with a
  `curl | bash` invocation, and that invocation cannot verify the script's
  checksum. Prefer downloading the script, reviewing it, and running it from a
  trusted checkout.
- The git clone tracks the default branch; there is no pinned commit or signed
  release artifact yet.
- PyPI/Homebrew/pipx distribution with SHA-256 verification and `pip install`
  lockfiles remain future work.

Until then, treat installer URLs as trusted input and verify the checkout
before running the CLI with production credentials.
