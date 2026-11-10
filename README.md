# darkmage-cli

Arkost CLI (Darkmage engine) for the [Arkost AI](https://github.com/daremon7584-blip/arkost_ai) platform (FastAPI backend at `/root/saas-backend`).

## Install

```bash
cd /root/darkmage-cli
pip install -e .
```

## Configure

```bash
export DARKMAGE_API_URL=http://your-server:8000   # default: http://localhost:8000
export DARKMAGE_TOKEN=...                         # bearer token for authentication
```

Token is encrypted and saved to `~/.darkmage-cli/config.json` after `darkmage auth login` or `darkmage auth interactive`. The token is encrypted at rest using Fernet (AES-128).

**Never pass the token via command line arguments** — it would be visible in process listings. Use `DARKMAGE_TOKEN` environment variable instead.

## Quick Start

```bash
# 1. Настроить сервер
darkmage config set --url http://localhost:8000

# 2. Войти (интерактивно, как в Claude Code)
darkmage login

# 3. Открыть интерактивный терминал (TUI)
darkmage tui <workspace_id>

# Или всё в одной команде:
darkmage start

# One-shot без TUI: ответ в stdout, прогресс в stderr
darkmage exec "почини тесты" --output-format text
darkmage -p "объясни проект" --output-format json
cat logs.txt | darkmage -p "найди причину"
```

## Usage

```bash
darkmage --help
darkmage --version
# --json is accepted before or after the subcommand
darkmage --json config show
darkmage config show --json
darkmage auth register --email a@b.c --password secret123 --full-name Name
darkmage auth login --email a@b.c --password secret123
darkmage auth logout

darkmage me
darkmage usage
darkmage memory get
darkmage memory put "I prefer Python"

darkmage workspace create --name my-project
darkmage workspace list
darkmage workspace get <id>
darkmage workspace start <id>
darkmage workspace stop <id>
darkmage workspace delete <id>
darkmage workspace update <id> --name new --approval-mode ask

darkmage files list <id> [path]
darkmage files read <id> <path> [--offset 1] [--limit 2000]
darkmage files edit <id> <path> "new content" [--base-content "old"] [--session-id <sid>]
darkmage files download <id> <remote_path> <local_path>
darkmage files upload <local_path> <id> <remote_path>
darkmage files tree <id> [path] [--depth N]
darkmage files search <id> <query> [path]

darkmage session create <workspace_id> [--title "Task"]
darkmage session list <workspace_id>

# Сессии (новый интерфейс: одна рабочая область на пользователя)
darkmage session new [--title "Моя сессия"]     # создать сессию (песочница запустится сама)
darkmage session all [--limit 50] [--archived]  # все сессии пользователя
darkmage session runs <session_id>             # запуски сессии
darkmage session files <session_id> [path]     # файлы сессии
darkmage session read <session_id> <path>      # прочитать файл сессии

darkmage run create <session_id> --prompt "Explain this code" [--model ...] [--plan-only] [--thorough] [--image file.png]
darkmage run get <run_id>
darkmage run queue <run_id> [--json]                 # queue place, ETA and expiry for a queued run
darkmage run verification <run_id> [--json]          # verification evidence from the terminal event
darkmage run list <workspace_id>                          # все ran в рабочей зоне (саб-агенты)
darkmage run message <run_id> "additional context"   # or read from stdin with '-'
darkmage run answer <run_id> <question_id> "yes"      # answer an ask_user question
darkmage run context <run_id>                         # show context token usage
darkmage run revert <run_id>
darkmage run review <run_id>
darkmage run patch <run_id> [--stat] [--output PATH] [--no-color] [--force] [--json]
darkmage run stop <run_id>
darkmage run events <run_id> [--last-event-id N] [--pretty]

darkmage approvals list [--limit 50] [--json]          # pending approvals across your runs
darkmage approvals show <approval_id> [--json]         # details, bounded summary and command hints
darkmage approvals approve <approval_id> [--scope call|turn]
darkmage approvals reject <approval_id>

darkmage process start <workspace_id> <cmd> [args...] [--cwd /workspace] [--port 8080]
darkmage process output <workspace_id> [process_id]
darkmage process stop <workspace_id> <process_id>

darkmage payment create [--product standard_30d|credits] [--amount-rub N]  # ссылка на сайт для оплаты
darkmage payment list                                                       # список своих платежей

darkmage admin status                          # баланс OpenRouter (только админ)
darkmage admin skills list [--status approved|review|blocked|rejected] [--json]
darkmage admin skills show <scan_id> [--json]  # детали, top-5 findings, подсказки approve/reject
darkmage admin skills gate <digest> [--json]   # allowed=true только для approved
darkmage admin skills scan --name NAME [--version V] [--source URL] --report FILE [--json]
darkmage admin skills approve <scan_id> [--note TEXT] [--allow-high-risk] [--json]
darkmage admin skills reject <scan_id> [--note TEXT] [--json]

darkmage admin mcp list [--json]                     # tools, current/approved schema hashes, status
darkmage admin mcp show <tool> [--json]              # bounded schema + approval metadata
darkmage admin mcp approve <tool> [--hash SHA256] [--yes] [--json]
darkmage admin mcp call <tool> --args '{"key":"value"}' [--json]  # read-only tools only

darkmage term <workspace_id>                   # безопасный relay к удалённому PTY (без локального shell)

darkmage git clone <ws> <url> [--ref main] [--depth 1]   # клон репозитория (Phase 3, бэкенд)
darkmage git commit <ws> "сообщение" [--branch feature]  # коммит (Phase 3, бэкенд)
darkmage git push <ws> [--branch main]                 # пуш (Phase 3, бэкенд)
darkmage git pr <ws> "заголовок" [--body текст] [--base main] [--head feature]  # PR (Phase 3, бэкенд)

# APK / Godot (выполняются на runner-manager, порт 8090)
darkmage workspace apk <workspace_id> [--web-dir DIR] [--output FILE.apk] [--app-name NAME] [--app-id ID] [--version-code N]
                                        # Собрать отладочный Android APK из веб-файлов workspace
darkmage workspace godot <workspace_id> [--project-dir DIR] [--output-dir DIR]
                                        # Экспортировать Godot 4 проект в Web-билд

# Конфиг runner-manager
darkmage config set --runner-url http://localhost:8090   # URL runner-managera
darkmage config set --runner-token <TOKEN>               # bearer токен runner-managера
export DARKMAGE_RUNNER_URL=http://localhost:8090         # или через env var
export DARKMAGE_RUNNER_TOKEN=<TOKEN>

darkmage mcp list                                       # список MCP-инструментов (Phase 3, нужен бэкенд)
darkmage mcp call <tool> <workspace_id> ключ=значение ...  # вызов MCP-инструмента (Phase 3, нужен бэкенд)

darkmage config show [--json]              # показать конфиг (секреты замаскированы)
darkmage config set [--url URL] [--verbose]
darkmage config export <файл>              # экспорт без секретов, файл 0600
darkmage config import <файл>              # импорт конфига из JSON
darkmage doctor                            # проверка окружения и подключения
darkmage completion <bash|zsh|fish>        # генерация скриптов автодополнения
darkmage history [N]                       # история команд (повторить команду N)
darkmage history [N]                       # история команд (повторить команду N)

darkmage tui <workspace_id> [--run-id <id>]  # Полноценный TUI клиент (Textual, Phase 3)

darkmage chat "Hello" [--system "You are helpful"] [--model ...] [--temperature 0.7] [--max-tokens 1000]

darkmage health
darkmage ready
```

### Downloading a run patch

`darkmage run patch <run_id>` prints the unified diff for a finished run. Colors are used only on a TTY; `--no-color` disables them, and non-TTY output is byte-for-byte patch text for piping.

```bash
darkmage run patch <run_id> > changes.patch
darkmage run patch <run_id> --output changes.patch   # refuses to overwrite; add --force
darkmage run patch <run_id> --stat                  # files, +/-, per-file summary
darkmage run patch <run_id> --json                  # run_id/files/additions/deletions/stat/patch
```

The endpoint is subscription-gated (HTTP 402); a missing/foreign run is 404, an unfinished run or missing checkpoint is 409, and patches above the server's 16 MiB limit are 413. Errors print a clear message to stderr and exit non-zero without exposing the token.

### Queue visibility

`darkmage run queue <run_id>` shows where a queued run waits: status, 1-based position, tasks ahead, a humanized wait estimate, the queue deadline and whether it is in the trial or paid queue.

```bash
darkmage run queue <run_id>
darkmage run queue <run_id> --json   # raw GET /runs/{run_id} object
```

A run that is not queued gets a friendly `Not queued` message. A queued run whose deadline expired (or whose queue metadata is otherwise gone) reports that queue information is not available instead of a stale position. `darkmage run get <run_id>` adds a compact `Queue:` line when metadata is present, and `darkmage run list <workspace_id>` shows an `Очередь` column only when at least one listed run is queued. Missing or foreign runs return a clear 404 and never print the token.

### Verification evidence

`darkmage run verification <run_id>` reads the run's event stream, takes the last `run.completed`/`run.failed` event and prints the verification evidence the worker recorded:

```bash
darkmage run verification <run_id>
darkmage run verification <run_id> --json   # run_id/status/finish_reason/verification/report
```

The human summary shows the status (`Проверено`, `Не проверено`, `Требуется проверка`, `Не запускалась`), the check command and exit code, up to eight failure lines, parsed diagnostics (`kind` and counts) and a short explanation for `verification_required` or partial runs. `--json` returns the raw `verification` object plus the run id, normalized status, finish reason and partial/failure report. A run without a terminal `run.completed`/`run.failed` event exits 2 with a clear message; missing/foreign runs return a clear 404/403 without a traceback or token.

### Admin skill gate

`darkmage admin skills` wraps the admin-only pre-install gate (`/admin/skills`). It never executes a skill; it only lists scans, shows a stored scanner report, checks a bundle digest, and records a reviewer decision.

```bash
darkmage admin skills list --status blocked
darkmage admin skills show <scan_id>
darkmage admin skills gate <64-hex-digest>
darkmage admin skills scan --name release-helper --version 0.1.0 \
  --source https://github.com/acme/skills/release-helper --report report.json
darkmage admin skills approve <scan_id> --note "reviewed" --allow-high-risk
darkmage admin skills reject <scan_id> --note "untrusted publisher"
```

- `scan` accepts a normalized scanner report (SkillSpector-compatible `risk_assessment` + `issues`) or a full payload with a nested `report`. The digest is taken from `--digest`, a top-level/nested `digest` field, a local `report.skill.source` path (hashed like the backend wrapper), or finally the report file contents. Prefer `--digest` when the skill bundle hash is known.
- Approving a `blocked` scan requires `--allow-high-risk`. The CLI checks the scan first and refuses locally with exit 2, so no approve request is sent without the override.
- `gate` validates that the digest is exactly 64 lowercase hex characters before calling the API and exits 2 otherwise.
- The list table fits 80 columns; `show` prints at most five findings and full approve/reject hints, wrapping long commands with shell line continuations.
- Admin-only access is enforced by the server. Non-admins get a 404, which the CLI renders as `Admin only or not found: ...` (never a traceback or token). API 409/422 errors are printed clearly with exit 2.
- `--json` returns the raw API object(s): a list for `list`, a scan detail for `show`/`scan`/`approve`/`reject`, and a gate decision for `gate`.

### Admin MCP gateway

`darkmage admin mcp` wraps the admin-only gateway (`/admin/mcp`). It lists the configured MCP server's tools, shows their schema, and approves the exact schema hash the server currently serves. Approval never executes the tool.

```bash
darkmage admin mcp list
darkmage admin mcp show github.search
darkmage admin mcp approve github.search --hash <64-hex-current-hash>
darkmage admin mcp approve github.search --yes   # fetch the hash, print it, approve that exact hash
darkmage admin mcp call github.search --args '{"query":"repo:acme/app bug"}'
```

- `list` prints tool name, schema hash prefix, approval status (`approved` / `changed` / `new`), approved hash prefix and last seen in a table capped at 80 columns. The current backend response does not expose a last-seen timestamp, so that column renders `-` until the API adds one.
- `show` fetches the current tool list, prints approval metadata, the full current/approved hashes when they differ, and a bounded JSON schema (the full parameters are available with `--json`).
- `approve` validates the hash locally as exactly 64 lowercase hex characters. With `--hash`, the CLI first fetches the tool list and refuses locally (exit 2, no POST) if the hash is not the exact current schema hash; the error shows provided, current and approved hashes. Without `--hash`, `--yes` is mandatory: the CLI prints the current hash and requires the explicit flag, then approves that fetched hash. A changed schema is therefore never approved silently.
- `call` accepts a JSON object for `--args` and only works for tools in the server's `MCP_READ_ONLY_TOOLS` allowlist. A tool-level failure returns exit 1.
- Non-admin requests (server 404) render as `Admin only or not found` with exit 2. 409 (schema changed) and 422 (invalid request) errors are clear, token-free and exit 2.
- `--json` prints an envelope with `schema_version`, `server` and the command payload (`tools`, `tool`, `approved`, or `ok`/`result`/`error`). Errors use the shared `{"schema_version":1,"error":{...}}` envelope.

## Notes

- All mutating commands require a bearer token (set via `darkmage auth login` or `DARKMAGE_TOKEN`).
- Run events use `text/event-stream` and are printed raw to stdout.
- Errors print to stderr and exit non-zero.

## 🔒 Security

- **Token encryption**: All tokens are encrypted at rest using Fernet (AES-128 with HMAC). The encryption key is stored in `~/.darkmage-cli/.key` with `0o600` permissions.
- **No token in CLI args**: Never pass tokens via command-line arguments (they're visible in `ps aux`). Use `DARKMAGE_TOKEN` environment variable instead.
- **Config file permissions**: `~/.darkmage-cli/config.json` is stored with `0o600` permissions (owner read/write only).
- **No secret output**: `config show --json`, `config set --verbose`, and `config export` redact tokens; exports are written with mode `0600`.
- **History**: secret flags are masked and `~/.darkmage-cli/history.json` is written with mode `0600`.
- **Remote terminal**: `darkmage term` relays bytes to/from the remote PTY and never pipes remote output into a local shell.
- **Installers**: server arguments are validated; `install.py` never uses `shell=True`; installers update an existing clone instead of `rm -rf`.
- **Never share your token**: Treat your bearer token like a password. Anyone with your token can access your workspaces.

See [SECURITY.md](SECURITY.md) for details and deferred installer supply-chain pinning.
