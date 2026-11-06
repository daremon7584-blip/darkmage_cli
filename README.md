# gameforge-cli

Custom CLI for the [Gameforge AI](https://github.com/) platform (FastAPI backend at `/root/saas-backend`).

## Install

```bash
cd /root/gameforge-cli
pip install -e .
```

## Configure

```bash
export GAMEFORGE_API_URL=http://your-server:8000   # default: http://localhost:8000
export GAMEFORGE_TOKEN=...                         # bearer token for authentication
```

Token is encrypted and saved to `~/.gameforge-cli/config.json` after `gameforge auth login` or `gameforge auth interactive`. The token is encrypted at rest using Fernet (AES-128).

**Never pass the token via command line arguments** — it would be visible in process listings. Use `GAMEFORGE_TOKEN` environment variable instead.

## Quick Start

```bash
# 1. Настроить сервер
gameforge config set --url http://localhost:8000

# 2. Войти (интерактивно, как в Claude Code)
gameforge login

# 3. Открыть интерактивный терминал (TUI)
gameforge tui <workspace_id>

# Или всё в одной команде:
gameforge start
```

## Usage

```bash
gameforge --help
gameforge auth register --email a@b.c --password secret123 --full-name Name
gameforge auth login --email a@b.c --password secret123
gameforge auth logout

gameforge me
gameforge usage
gameforge memory get
gameforge memory put "I prefer Python"

gameforge workspace create --name my-project
gameforge workspace list
gameforge workspace get <id>
gameforge workspace start <id>
gameforge workspace stop <id>
gameforge workspace delete <id>
gameforge workspace update <id> --name new --approval-mode ask

gameforge files list <id> [path]
gameforge files read <id> <path> [--offset 1] [--limit 2000]
gameforge files edit <id> <path> "new content" [--base-content "old"] [--session-id <sid>]
gameforge files download <id> <remote_path> <local_path>
gameforge files upload <local_path> <id> <remote_path>
gameforge files tree <id> [path] [--depth N]
gameforge files search <id> <query> [path]

gameforge session create <workspace_id> [--title "Task"]
gameforge session list <workspace_id>

gameforge run create <session_id> --prompt "Explain this code" [--model ...] [--plan-only] [--thorough] [--image file.png]
gameforge run get <run_id>
gameforge run list <workspace_id>                          # все ran в рабочей зоне (саб-агенты)
gameforge run message <run_id> "additional context"   # or read from stdin with '-'
gameforge run answer <run_id> <question_id> "yes"      # answer an ask_user question
gameforge run context <run_id>                         # show context token usage
gameforge run revert <run_id>
gameforge run review <run_id>
gameforge run stop <run_id>
gameforge run events <run_id> [--last-event-id N] [--pretty]

gameforge process start <workspace_id> <cmd> [args...] [--cwd /workspace] [--port 8080]
gameforge process output <workspace_id> [process_id]
gameforge process stop <workspace_id> <process_id>

gameforge payment create [--product standard_30d|credits] [--amount-rub N]  # ссылка на сайт для оплаты
gameforge payment list                                                       # список своих платежей

gameforge admin status                          # баланс OpenRouter (только админ)
gameforge term <workspace_id>                   # интерактивный терминал (PTY, Phase 3)

gameforge git clone <ws> <url> [--ref main] [--depth 1]   # клон репозитория (Phase 3, бэкенд)
gameforge git commit <ws> "сообщение" [--branch feature]  # коммит (Phase 3, бэкенд)
gameforge git push <ws> [--branch main]                 # пуш (Phase 3, бэкенд)
gameforge git pr <ws> "заголовок" [--body текст] [--base main] [--head feature]  # PR (Phase 3, бэкенд)

# APK / Godot (выполняются на runner-manager, порт 8090)
gameforge workspace apk <workspace_id> [--web-dir DIR] [--output FILE.apk] [--app-name NAME] [--app-id ID] [--version-code N]
                                        # Собрать отладочный Android APK из веб-файлов workspace
gameforge workspace godot <workspace_id> [--project-dir DIR] [--output-dir DIR]
                                        # Экспортировать Godot 4 проект в Web-билд

# Конфиг runner-manager
gameforge config set --runner-url http://localhost:8090   # URL runner-managera
gameforge config set --runner-token <TOKEN>               # bearer токен runner-managера
export GAMEFORGE_RUNNER_URL=http://localhost:8090         # или через env var
export GAMEFORGE_RUNNER_TOKEN=<TOKEN>

gameforge mcp list                                       # список MCP-инструментов (Phase 3, нужен бэкенд)
gameforge mcp call <tool> <workspace_id> ключ=значение ...  # вызов MCP-инструмента (Phase 3, нужен бэкенд)

gameforge config show [--json]              # показать конфиг (~/.gameforge-cli/config.json)
gameforge config set [--url URL] [--verbose]
gameforge config export <файл>              # экспорт конфига в JSON
gameforge config import <файл>              # импорт конфига из JSON
gameforge doctor                            # проверка окружения и подключения
gameforge completion <bash|zsh|fish>        # генерация скриптов автодополнения
gameforge history [N]                       # история команд (повторить команду N)
gameforge history [N]                       # история команд (повторить команду N)

gameforge tui <workspace_id> [--run-id <id>]  # Полноценный TUI клиент (Textual, Phase 3)

gameforge chat "Hello" [--system "You are helpful"] [--model ...] [--temperature 0.7] [--max-tokens 1000]

gameforge health
gameforge ready
```

## Notes

- All mutating commands require a bearer token (set via `gameforge auth login` or `GAMEFORGE_TOKEN`).
- Run events use `text/event-stream` and are printed raw to stdout.
- Errors print to stderr and exit non-zero.

## 🔒 Security

- **Token encryption**: All tokens are encrypted at rest using Fernet (AES-128 with HMAC). The encryption key is stored in `~/.gameforge-cli/.key` with `0o600` permissions.
- **No token in CLI args**: Never pass tokens via command-line arguments (they're visible in `ps aux`). Use `GAMEFORGE_TOKEN` environment variable instead.
- **Config file permissions**: `~/.gameforge-cli/config.json` is stored with `0o600` permissions (owner read/write only).
- **Never share your token**: Treat your bearer token like a password. Anyone with your token can access your workspaces.
