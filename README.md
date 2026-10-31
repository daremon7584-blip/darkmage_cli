# odyssey-cli

Custom CLI for the [Odyssey AI](https://github.com/) platform (FastAPI backend at `/root/saas-backend`).

## Install

```bash
cd /root/odyssey-cli
pip install -e .
```

## Configure

```bash
export ODYSSEY_API_URL=http://your-server:8000   # default: http://localhost:8000
export ODYSSEY_TOKEN=...                         # or log in via the CLI
```

Token is saved to `~/.odyssey-cli/config.json` after `odyssey auth login`.

## Usage

```bash
odyssey --help
odyssey auth register --email a@b.c --password secret123 --full-name Name
odyssey auth login --email a@b.c --password secret123
odyssey auth logout

odyssey me
odyssey usage
odyssey memory get
odyssey memory put "I prefer Python"

odyssey workspace create --name my-project
odyssey workspace list
odyssey workspace get <id>
odyssey workspace start <id>
odyssey workspace stop <id>
odyssey workspace delete <id>
odyssey workspace update <id> --name new --approval-mode ask

odyssey files list <id> [path]
odyssey files read <id> <path> [--offset 1] [--limit 2000]
odyssey files edit <id> <path> "new content" [--base-content "old"] [--session-id <sid>]
odyssey files search <id> <query> [path]

odyssey session create <workspace_id> [--title "Task"]
odyssey session list <workspace_id>

odyssey run create <session_id> --prompt "Explain this code" [--model ...] [--plan-only] [--thorough] [--image file.png]
odyssey run get <run_id>
odyssey run message <run_id> "additional context"   # or read from stdin with '-'
odyssey run answer <run_id> <question_id> "yes"      # answer an ask_user question
odyssey run context <run_id>                         # show context token usage
odyssey run revert <run_id>
odyssey run review <run_id>
odyssey run stop <run_id>
odyssey run events <run_id> [--last-event-id N] [--pretty]

odyssey process start <workspace_id> <cmd> [args...] [--cwd /workspace] [--port 8080]
odyssey process output <workspace_id> [process_id]
odyssey process stop <workspace_id> <process_id>

odyssey payment create [--product standard_30d|credits] [--amount-rub N]  # ссылка на сайт для оплаты
odyssey payment list                                                       # список своих платежей

odyssey admin status                          # баланс OpenRouter (только админ)
odyssey term <workspace_id>                   # интерактивный терминал (заглушка Phase 3)

odyssey git clone <ws> <url> [--ref main] [--depth 1]   # клон репозитория (Phase 3, нужен бэкенд)
odyssey git commit <ws> "сообщение" [--branch feature]  # коммит (Phase 3, нужен бэкенд)
odyssey git push <ws> [--branch main]                 # пуш (Phase 3, нужен бэкенд)
odyssey git pr <ws> "заголовок" [--body текст] [--base main] [--head feature]  # PR (Phase 3, нужен бэкенд)

odyssey mcp list                                       # список MCP-инструментов (Phase 3, нужен бэкенд)
odyssey mcp call <tool> ключ=значение ...              # вызов MCP-инструмента (Phase 3, нужен бэкенд)

odyssey chat "Hello" [--system "You are helpful"] [--model ...] [--temperature 0.7] [--max-tokens 1000]

odyssey health
odyssey ready
```

## Notes

- All mutating commands require a bearer token (set via `odyssey auth login` or `ODYSSEY_TOKEN`).
- Run events use `text/event-stream` and are printed raw to stdout.
- Errors print to stderr and exit non-zero.
