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
darkmage run list <workspace_id>                          # все ran в рабочей зоне (саб-агенты)
darkmage run message <run_id> "additional context"   # or read from stdin with '-'
darkmage run answer <run_id> <question_id> "yes"      # answer an ask_user question
darkmage run context <run_id>                         # show context token usage
darkmage run revert <run_id>
darkmage run review <run_id>
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
