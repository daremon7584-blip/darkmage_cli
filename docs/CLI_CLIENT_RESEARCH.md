# Arkost CLI — исследование CLI-клиентов LLM-сервисов и план полировки

**Дата:** 09.11.2026.
**Срез нашего кода:** `/root/odyssey-cli`, пакет `darkmage-cli`, команда `darkmage` (после ребрендинга — `arkost`, с алиасом `darkmage`).
**Статус:** исследование + предложение. Код ещё не менялся.
**Связь:** `docs/ROADMAP_GOLDEN_MIDDLE.md` (раздел 16), `ROADMAP_CLI.md` (историческая карта), `COMPARISON_*` (ранние сравнения).

---

## 0. Резюме

**Вердикт:** наш CLI — широкий API-клиент, но ещё не агентский CLI. Как обёртка над REST API он силён: 40+ команд, JSONL-SSE, sync файлов, TUI, APK/Godot. Как «Claude Code в терминале» — нет: `run create` создаёт заявку и выходит, approvals только рисуются, diff/patch не выводятся, сессия не продолжается, TUI больше похож на лог с файловым деревом.

**Рынок сошёлся на трёх режимах:**
1. интерактивный TUI;
2. one-shot (`-p` / `exec`);
3. headless JSON/JSONL для CI.
Плюс обязательные approvals, resume, diff/checkpoint, context/cost meter и контекстный файл репозитория.

**Наши уникальные преимущества, которые надо вывести в UX:**
- серверная approval policy (модель не может расширить права);
- remote sandbox с checkpoint/откатом;
- sync локального репозитория с workspace;
- approvals через Telegram и веб;
- Godot/APK/Blender/Tiled;
- учёт стоимости на сервере.

**Главные разрывы:**
- нет `darkmage exec` / `-p` с финальным ответом и нормальными exit codes;
- approvals нельзя approve/reject из CLI/TUI, хотя backend API есть;
- `run create` не следит за run, нет `--follow`, reconnect;
- нет `run diff`/`run patch`, хотя backend отдаёт patch;
- нет `--continue`/`--resume`/`--fork-session`, привязки к репозиторию;
- TUI: фиксированный sidebar, события как лог, синхронный SSE внутри async, `Ctrl+C` убивает run;
- P0-дефекты безопасности: `term` исполняет удалённый вывод локальным `sh`; токены утекают в `config show --json`, `config export`, history;
- тесты дают false green; `cryptography` не объявлена; нет `--version`, CI, lockfile.

**Оценка:** 5.5/10 как агентский CLI, 8/10 как API-клиент. До 8/10 агентского CLI — 6–8 недель работы, если начать с P0.

---

## 1. Каким должен быть современный CLI LLM-сервиса

### 1.1. Три режима, один контракт

| Режим | Для кого | Пример |
|---|---|---|
| **Interactive** | человек в терминале | `arkost`, `arkost "объясни проект"` |
| **One-shot** | скрипты, быстрые вопросы | `arkost -p "почини тесты"`, `cat logs \| arkost -p "найди причину"` |
| **Headless / CI** | автоматизация, GitHub Actions | `arkost exec "..." --output-format json` |

Опционально четвёртый — **ACP** для Zed/Neovim, но это не первый приоритет.

Все три режима должны использовать **один event-контракт**:

```json
{"schema_version":1,"type":"assistant.delta","seq":42,"run_id":"...","session_id":"...","ts":"2026-11-09T12:00:00Z","data":{"text":"..."}}
{"schema_version":1,"type":"tool.requested","seq":43,"run_id":"...","data":{"tool_call_id":"call_...","name":"write_file","arguments":{}}}
{"schema_version":1,"type":"approval.required","seq":44,"run_id":"...","data":{"approval_id":"...","tool_call_id":"call_...","name":"write_file","arguments":{},"turn_remaining":2}}
{"schema_version":1,"type":"run.completed","seq":50,"run_id":"...","data":{"status":"completed","finish_reason":"stop"}}
```

Финальный envelope:

```json
{
  "schema_version": 1,
  "run_id": "...",
  "session_id": "...",
  "status": "completed",
  "result": "...",
  "structured_output": null,
  "usage": {"prompt_tokens": 1234, "completion_tokens": 456},
  "cost_usd": "0.031",
  "duration_ms": 42000,
  "permission_denials": []
}
```

**Exit codes:** `0` success, `1` runtime/network, `2` usage/config, `3` auth, `4` policy/approval denied, `5` turn/budget limit, `130` SIGINT, `143` SIGTERM. Не надо копировать нестандартные 42/53.

### 1.2. Что обязательно должно быть

| Слой | Требование |
|---|---|
| **Approvals** | карточка с инструментом, аргументами, diff, риском и scope `call`/`turn`; approve/reject; причина отказа доходит до агента |
| **Sessions** | `--continue`, `--resume`, `--fork-session`, picker, привязка к репозиторию; run переживает закрытие терминала |
| **Diff/checkpoint** | `run diff`, `run patch`, `run revert`, per-file revert; явно показывать, что откатывается |
| **Context** | `DARKMAGE.md`/`AGENTS.md`, `@file`, изображения/аудио, компакция, видимый context % |
| **Cost** | model, context %, tokens, cost, budget; сервер — источник истины |
| **Permissions** | 3–4 режима (`plan`, `ask`, `auto`, `deny`), allow/deny tools, серверная policy всегда главнее |
| **TUI** | одна колонка, transcript + composer + status line; tool cards, diff, approvals, queue, interrupt, detach |
| **Extensibility** | MCP/skills/commands на сервере; CLI — view/controller, не локальный runtime |
| **Config/auth** | XDG, keyring, профили, precedence CLI > env > project > user; redaction |
| **Distribution** | pipx/uv, Homebrew, standalone, Termux; `--version`, lockfile, CI, подписанный update |
| **Quality** | JSON errors, exit codes, CLI contract tests, TUI snapshots, SSE reconnect tests, cross-platform CI |

### 1.3. Чего не надо копировать

- OS-sandbox (Seatbelt/bwrap/Landlock) — наша граница в remote sandbox.
- Локальный MCP stdio, hooks/plugins/skills — supply-chain и переносимость; место — на сервере.
- Shadow-git checkpointing — у нас уже есть серверный checkpoint.
- Git worktrees — не маппятся на remote workspace.
- Auto-classifier на каждое действие — лишняя стоимость и непрозрачность.
- 7 permission modes, 40+ slash commands, 100+ флагов.
- Auto-approve по умолчанию, `--yolo`, пароль/токен в argv.
- Auto-commit в пользовательский git.

---

## 2. Ландшафт CLI-клиентов

### 2.1. Официальные клиенты

| CLI | Сильное | Слабое / чему не подражать | Что взять |
|---|---|---|---|
| **Claude Code** | `-p`, `--output-format json/stream-json`, `--resume/--continue/--fork-session`, permission modes, MCP, skills, hooks, checkpoint/rewind, statusline, accessibility | 6 permission modes, много флагов; локальный агент, не remote | контракт one-shot/stream, resume, approval UX, statusline |
| **OpenAI Codex CLI** | `codex exec`, stdin, JSONL events, progress в stderr, sandbox/approval, AGENTS.md, subagents, hooks, `--output-schema` | флаги и конфиг размазаны; локальный sandbox | `exec`, JSONL, progress/stderr, `--output-schema`, `resume` |
| **Gemini CLI** | `-p`, JSON/stream-json, `-r latest`, plan mode, policy engine, extensions, themes, screen-reader | нестандартные exit 42/53; policy workspace-tier местами не работает | `-p`, `--output-format`, `--screen-reader`, policy-идея |

### 2.2. Вторая волна

| CLI | Сильное | Слабое | Что взять |
|---|---|---|---|
| **Aider** | repo map (tree-sitter + PageRank), `/tokens`, lint/test loop, git-дисциплина, architect/editor split | нет MCP/skills/hooks/subagents; auto-commit в пользовательский git; развитие замедлилось | repo map, `/tokens`, lint/test loop, patch output |
| **opencode** | permissions, snapshots, `@file#line`, commands, skills, plugins, MCP, stats, ACP | сложность V1/V2, daemon, client-side policy | ordered permissions, snapshots, `@file#line`, ACP |
| **Goose** | recipes/subrecipes, MCP-first, scheduler, sessions, local models | `auto` по умолчанию, перегруженность | recipes для APK/Godot, scheduler, session fork |
| **GitHub Copilot CLI** | лучший approval UX («раз / ход / запретить + комментарий»), assisted approval, plan/autopilot, cloud sandbox, hooks, custom agents | GitHub lock-in, 100+ флагов, кредиты непрозрачны | approval-диалог, `--max-ai-credits`, plan/autopilot |
| **Cursor CLI** | `/rewind`, `/usage`, auto-review, cloud handoff `&`, worktree, subagents | closed source, сложная тарификация, implicit config | `/rewind`, cost meters, detach/handoff |
| **Continue CLI** | config-as-code, model roles (chat/edit/apply/embed), permissions glob, headless | onboarding через Continue/Anthropic, меньше полировки | model roles, config-as-code, permissions glob |
| **Cline** | checkpoints (shadow git), plan/act, JSON events, schedules, connectors | auto-approve по умолчанию, нет shell allowlist, hub daemon | checkpoints restore modes, plan/act, JSON events |

**Общий вывод:** дифференциатор уже не «доступ к модели», а **trust UX**: approvals, diff, checkpoint, resume, cost, понятный stop. У нас есть серверный trust-слой — его надо показать в CLI, а не строить локальный.

---

## 3. Аудит нашего CLI

### 3.1. Что уже хорошо

- 40+ команд: auth, workspace, files, sessions, runs, process, payments, admin, git, MCP, APK/Godot, chat, doctor, completion, history, parallel, REPL, TUI.
- JSONL-SSE и `--last-event-id`.
- Sync файлов: SHA-256, `.darkmageignore`, конфликты, watch.
- Fernet-шифрование токена, права `0600` на config/key.
- TUI на Textual: event log, composer, file tree, status bar.
- `run revert/review/context/answer/message`, `workspace update --approval-mode`.
- 47 тестов проходят — но см. 3.3.

### 3.2. Чего нет как агентского CLI

| Возможность | Сейчас | Нужно |
|---|---|---|
| One-shot | `run create <session> --prompt ...` → JSON и выход | `arkost -p "..."` / `exec`, follow, финальный ответ |
| Streaming | `run events` отдельной командой | follow по умолчанию на TTY, `--output-format` |
| Approvals | только отображение | `approvals list/show/approve/reject`, TUI-карточка |
| Diff | `run review` JSON | `run diff/patch`, unified diff, per-file |
| Sessions | `session list`, но `run create` требует id | `--continue/--resume/--fork`, picker, repo binding |
| Policy | `workspace update --approval-mode` | `policy show/set/test`, allow/deny tools, объяснение |
| Cost | `usage`, `run context` | status line, `run cost`, budget warning |
| Context file | нет | `DARKMAGE.md`/`AGENTS.md`, `@file`, `arkost init` |
| TUI UX | лог + sidebar | transcript + composer + status, cards, diff |
| Headless | `--json` только до подкоманды, exit codes размыты | JSON envelope, `--json` в любой позиции, error JSON |

### 3.3. Дефекты по коду

#### P0 — до любого релиза

| ID | Дефект | Где | Последствие |
|---|---|---|---|
| **P0-1** | `term` создаёт локальный `sh` на PTY и пишет удалённый вывод в его stdin; ввод пользователя не пересылается | `darkmage_cli/cli.py:1005-1013`, `1052-1063` | Удалённый вывод исполняется локальным shell; `term` не работает как терминал. Критическая RCE-поверхность |
| **P0-2** | `config show --json` печатает расшифрованный токен | `cli.py:1217-1232` | Токен в терминале/CI-логах |
| **P0-3** | `config export` пишет расшифрованный токен в файл без `0600` | `cli.py:1259-1273` | Токен в открытом виде на диске/в бэкапе |
| **P0-4** | History маскирует `--password`, но не `--token`/`--runner-token`; файл `0644` | `cli.py:2167-2186`, `2222-2237` | Токен в history |
| **P0-5** | History пишется без `CONFIG_DIR.mkdir` | `cli.py:2222-2237` | Первый запуск в чистом `HOME`: команда успешна, затем traceback |
| **P0-6** | `pyproject.toml` не объявляет `cryptography`, хотя `security.py` импортирует её на старте | `pyproject.toml:6-10`, `security.py:16` | `pip install .` → падение любой команды |
| **P0-7** | `install.py` использует `shell=True` с интерполяцией server; `install.sh` делает `rm -rf` и `curl \| bash` без pinned SHA | `install.py:22-27`, `install.sh:126-132` | Command injection / supply-chain RCE |

#### P1 — ломает основной сценарий

| ID | Дефект | Где |
|---|---|---|
| P1-1 | Нет approve/reject, хотя backend API есть; `approval_id` выбрасывается | `client.py` (нет методов), `tui.py:306-310`, backend `runs.py:1253,1282` |
| P1-2 | `agent.question` читает `question`, а payload — `questions[]` → пустой вывод | `cli.py:821-822`, `tui.py:330-331` |
| P1-3 | `diff.ready` не рендерится, хотя before/after уже на проводе | `cli.py:799-826`, `tui.py:315-316` |
| P1-4 | `run create` не ждёт, не стримит, не возвращает финальный ответ | `cli.py:829-839` |
| P1-5 | TUI читает синхронный SSE внутри async-worker → блокирует event loop | `tui.py:274-291` |
| P1-6 | TUI: `/run stop` заявлен в help, но не реализован; `Ctrl+C` сразу убивает run | `tui.py:386-427`, `456-464`, `599-605` |
| P1-7 | `--json` работает только до подкоманды; `config show --json` перезаписывает global default | `cli.py:1615-1636`, `212`, `230` |
| P1-8 | Ошибки всегда текст, не JSON; нет `code/request_id/retryable` | `client.py:802-804` |
| P1-9 | `doctor` всегда exit 0 и говорит «Готово к работе» при ошибках | `cli.py:1425-1462` |
| P1-10 | Нет аргументов → интерактивный вход/TUI даже в non-TTY; `EOFError` traceback | `cli.py:2199-2207` |
| P1-11 | `cmd_start` игнорирует `DARKMAGE_TOKEN`, смотрит только файл | `cli.py:130-145` |
| P1-12 | Тесты `test_user_cli.py` не содержат assert; pytest видит «зелёные» | `tests/test_user_cli.py:27-40` |
| P1-13 | `test_config_show_json` закрепляет утечку токена как «норму» | `tests/test_cli.py:577` |
| P1-14 | `monkeypatch` на `config.CONFIG_FILE` не влияет на `security.load_config`; тесты пишут в реальный `~/.darkmage-cli` | `tests/test_cli.py:565,583,600,620` |
| P1-15 | Нет `--version`, `__version__`, lockfile, CI, PyPI; `textual>=0.79` при 8.2.8 | `pyproject.toml:2-13` |
| P1-16 | Нет reconnect/backoff/dedupe SSE; обрыв = выход | `cli.py:912-922`, `client.py:405-441` |
| P1-17 | `workspace delete`, `files rm` без подтверждения/`--yes` | `cli.py:265-267`, `405-418` |
| P1-18 | Completion-скрипты устарели: нет `session new/all/runs/files/read`, `repl`, `start`, `history`, `parallel`, `files tree/status/export` | `cli.py:1491-1606` |

#### P2 — полировка

- Жёсткие ширины таблиц 93–115 символов; ломаются на 80 колонках (`cli.py:215-223`, `726-729`, `889-898`).
- REPL: устаревший help, парсер пересобирается каждый цикл, нет persistent history, `shlex` может бросить `ValueError` (`cli.py:1099-1214`).
- `parallel` не параллелен: sync-функции внутри `asyncio.gather` (`cli.py:1324-1367`).
- `chat` не стримит, печатает usage JSON в stdout (`cli.py:1405-1414`).
- TUI вставляет текст агента в Rich markup без escaping → ANSI/escape injection (`tui.py:303-336`).
- `_events_log` растёт без границы (`tui.py:340`).
- `term` не работает на Windows; нет fallback (`cli.py:988-1082`).
- `chat` не поддерживает stdin/`--json` (`cli.py:1405-1414`).
- Дублирующий `is_configured` с разной семантикой (`config.py:66-67`, `security.py:101-104`).
- `warn_insecure_url` не вызывается (`security.py:126-132`).

### 3.4. Что показывает текущий UX

```text
$ darkmage run create ses_123 --prompt "почини тесты"
{"id": "run_...", "status": "queued"}     # и всё, CLI вышел
$ darkmage run events run_...
[4] approval.required: write_file path=app.py
[5] agent.question:                        # пусто, payload не разобран
```

Это не «агент в терминале», а «отправить заявку и посмотреть лог». Для сравнения, Claude Code/Codex/Gemini в one-shot ждут завершения, стримят события и возвращают финальный ответ/JSON.

---

## 4. Целевой UX Arkost CLI

### 4.1. Грамматика

```bash
# interactive
arkost
arkost "объясни проект"
arkost attach <run-id>

# one-shot / CI
arkost -p "почини тесты"
arkost exec "почини тесты"
cat logs.txt | arkost -p "найди причину"
arkost exec - < prompt.txt

# machine-readable
arkost exec "..." --output-format json
arkost exec "..." --output-format stream-json --include-partial-messages
arkost exec "..." --json-schema schema.json -o answer.json

# sessions
arkost exec "..." --session <id>
arkost exec "..." --continue
arkost exec "..." --resume <id|name> --fork-session --name "alt"

# policy
arkost exec "..." --permission-mode plan
arkost exec "..." --permission-mode ask --allowed-tools "read_file,run_shell_command(git *)"
arkost exec "..." --permission-mode deny --no-input

# approvals
arkost approvals list --run <id>
arkost approvals show <id> --diff
arkost approvals approve <id> --scope turn
arkost approvals reject <id> --reason "Не трогай этот файл"

# review
arkost run diff <id>
arkost run patch <id> > change.patch
arkost run revert <id> --yes
```

### 4.2. Флаги

| Флаг | Значения / смысл |
|---|---|
| `-p, --print` | one-shot, без TUI |
| `--output-format` | `text`, `json`, `stream-json` |
| `--input-format` | `text`, `stream-json` (P1) |
| `--include-partial-messages` | дельты в stream-json |
| `--json-schema FILE` | structured output |
| `-o, --output-last-message FILE` | последний ответ в файл |
| `--model`, `--fallback-model` | alias или ID |
| `--max-turns`, `--max-cost` | серверные лимиты |
| `--permission-mode` | `plan`, `ask`, `auto`, `deny` |
| `--allowed-tools`, `--disallowed-tools`, `--tools` | auto-approve / deny / доступность |
| `--attach`, `--image`, `--audio` | вложения; `@file` в промпте |
| `--session`, `--continue`, `--resume`, `--fork-session`, `--session-id` | continuity |
| `--ephemeral`, `--bare`, `--no-input` | CI-режимы |
| `--idempotency-key` | повторный `exec` не создаёт второй run |
| `--plain`, `--no-color`, `--no-emoji` | accessibility/скрипты |

### 4.3. TUI

```text
┌ workspace · session · run ─────────────────────────────────────┐
│                                                                 │
│  transcript: markdown, tool cards, diffs, approvals             │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ > composer (multiline, @file, /command)                         │
├─────────────────────────────────────────────────────────────────┤
│ model · ctx 12% · 3.4k tok · $0.04 · 00:42 · ● running · 2 queued│
└─────────────────────────────────────────────────────────────────┘
```

- Sidebar скрыт по умолчанию; `Ctrl+B` — overlay сессий/файлов; на <100 колонках не показывать.
- Одна строка статуса вместо header + footer + help-bar.
- Tool cards: имя, аргументы, статус, длительность; `Ctrl+O` — полный вывод.
- Diff: unified, `+/-`, сворачивание >200 строк.
- Approval card:

```text
┌ Approve write_file? ───────────────────────────────────────────┐
│ src/app.py   +12 −3                                            │
│ @@ ...                                                         │
│ [a] once   [A] rest of turn (2)   [r] reject   [d] diff        │
└─────────────────────────────────────────────────────────────────┘
```

Клавиши: `Enter` — отправить/в очередь, `Ctrl+Enter` — очередь сейчас, `Esc` — отменить turn, `Ctrl+C` — остановить run с подтверждением, `Ctrl+B` — detach, `Ctrl+O` — раскрыть tool output, `Ctrl+R` — история, `Ctrl+G` — редактор, `Shift+Tab` — цикл режимов, `Ctrl+K` — palette, `?` — помощь.

**Не делать `Ctrl+C = kill run`** — это самый частый источник боли.

---

## 5. План полировки

### P0 — первые 2 недели

| ID | Работа | Размер | Зависит | Приёмка |
|---|---|---|---|---|
| C0-1 | Убрать локальный `sh` из `term`; соединить WebSocket напрямую со stdin/stdout; Unix guard/Windows fallback | S | — | `term` не создаёт локальный shell; ввод доходит; вывод не исполняется; e2e с фейковым ws |
| C0-2 | Секреты: `config show --json` маскирует; `config export` без секретов по умолчанию + `--include-secrets` и `0600`; history `0600` + маска `--token`; `mkdir`/atomic write | S | — | В export/show/history нет токена; fresh HOME не падает |
| C0-3 | `cryptography` в deps; `--version`/`__version__`; `readme`, `license`, `textual>=8,<9`, lockfile | S | — | Чистый venv: `pip install . && darkmage --version && darkmage health` |
| C0-4 | `exec`/`-p`: create run → follow SSE → final stdout, progress stderr; `--output-format text|json|stream-json`; `-o` | M | C0-3 | `printf 'x' \| darkmage -p '...' --output-format json \| jq -e '.run_id'` |
| C0-5 | JSON envelope + error JSON + exit codes; `--json` в любой позиции; `doctor --json` и nonzero | S/M | C0-4 | 401 → JSON `{error:{code,status,request_id}}`; `doctor` fail → 1 |
| C0-6 | `approvals list/show/approve/reject` + TUI-карточка + diff; `scope=call|turn`; reject reason | M | backend API | approve `write_file` → файл записан; reject reason виден агенту |
| C0-7 | `run diff/patch/revert` + per-file revert; pager; 409 понятно | M | backend `/runs/{id}/patch` | `run patch` применяется `git apply --check`; revert точен |
| C0-8 | Sessions: `--continue/--resume/--fork`, picker, repo binding | M | sessions API | из корня repo `-c -p` продолжает ту же сессию |
| C0-9 | Async SSE + reconnect по `Last-Event-ID` + dedupe; TUI не блокируется | M | C0-4 | обрыв 5–30 с → reconnect без дублей; key latency <100 мс |
| C0-10 | Cost/context meter в statusline + `run cost`/`usage --json` | S | backend cost | model/ctx/cost/elapsed/queue видны; 80% warning |
| C0-11 | `--plain`, `--no-color`, `NO_COLOR`, `--no-emoji` | S | — | без ANSI/emoji; screen reader читает |
| C0-12 | Тесты: убрать false green, temp HOME/config, CLI contract, exit codes, SSE reconnect, TUI snapshots; CI matrix | M | C0-1…11 | CI зелёный на 3 ОС × 4 Python; coverage core >80% |
| C0-13 | Дистрибуция: pipx/uv, wheel/sdist, PyPI Trusted Publishing, `update --check`; убрать `curl\|bash` как основной путь | M | C0-3 | `pipx install`, `uv tool install` ставят одну версию |

### P1 — 30–90 дней

| ID | Работа | Размер | Зависит | Приёмка |
|---|---|---|---|---|
| C1-1 | `DARKMAGE.md`/`AGENTS.md`, `arkost init`, `--context-file`, `--no-context` | M | backend injection | инструкция применяется в новом run |
| C1-2 | `@file`, `#L10-L20`, `--attach`, images/audio | M | attachments API | файл виден агенту, id в run |
| C1-3 | Plan mode + todo panel + `--plan` | M | `plan_only` | plan не пишет; approve → run; todo из events |
| C1-4 | Commands/skills: `.arkost/commands/*.md`, `SKILL.md`, `$ARGUMENTS` | M | server skills | discovery, `!` в sandbox с approval |
| C1-5 | `run review --json` + CI recipe/GitHub Action | S | C0-4/7 | findings + cost; action в CI |
| C1-6 | Per-step checkpoint/rewind (`--to <seq>`) | L | storage | restore files/task/both |
| C1-7 | Policy rules v2: path/URL/MCP, allow/ask/deny, dry-run | M | backend | объяснение одной строкой; audit diff |
| C1-8 | ACP для Zed/Neovim | M | sessions/runs | `arkost acp` работает; approvals через ACP |

### P2 — later

- `attach`/`pair` (второй терминал, web/mobile, QR).
- Recipes + schedules для APK/Godot.
- Server-side plugins/hooks (не клиентские).
- Repo map/index (tree-sitter + PageRank).
- Agent teams/fleet.
- Custom statusline script.

### Backend, который нужен CLI

| ID | Что | Размер | Зачем |
|---|---|---|---|
| B1 | `/models` с context/vision/audio/pricing | S | `--model fast`, `arkost models` |
| B2 | Per-run `approval_mode`, `allowed_tools`, `denied_tools`, `max_turns` | M/L | `--permission-mode` и tool policy |
| B3 | Инъекция `DARKMAGE.md`/`AGENTS.md` в контекст | S/M | context file |
| B4 | `POST /runs/{id}/interrupt` (cancel turn, не run) | M | Esc = прервать turn |
| B5 | Cost/credits в `TaskRunResponse` | S/M | statusline |
| B6 | `Idempotency-Key` на create run | S | повторный `exec` |
| B7 | Session fork/branch | L | `--fork-session` |
| B8 | Event envelope `run_id/parent_run_id/schema_version` | S | subagents/parallel |
| B9 | OAuth device flow + refresh token | M | нормальный login |
| B10 | `GET /runs/{id}/approvals` | S | `approvals list` без replay |

---

## 6. Метрики

| Метрика | Цель |
|---|---|
| Первый успешный run | < 5 мин от установки |
| Time-to-first-token | p50 < 1.5 с, p95 < 5 с |
| Key latency в TUI | p95 < 50 мс |
| Command success (read-only / mutating) | >99% / >95% |
| Approval latency | p50 < 60 с; timeout <5% |
| SSE resume | >99% без дублей/пропусков |
| Revert success | >99% |
| Crash-free sessions | >99.5% |
| Cost accuracy | ±1% к серверу |
| Install success | >98% |
| CI/headless usage | доля runs; ошибки JSON schema = 0 |
| Session resume rate | рост week-over-week |

---

## 7. Что не делать

- Не строить «IDE в терминале»: файловое дерево, git-граф, редактор — вторичны; ядро — диалог, approvals, очередь.
- Не добавлять plugin-систему и MCP-маркетплейс до стабилизации event-контракта и approval-flow.
- Не делать auto-approve по умолчанию.
- Не вводить свой event-протокол без `schema_version/seq/ts/run_id/type/data`.
- Не использовать `curl | bash` как основной канал установки.
- Не делать `--json` глобальным флагом, который работает только в одной позиции.
- Не использовать emoji/цвет как единственный носитель статуса.
- Не поддерживать Python 3.9 и не тянуть неограниченный `textual>=0.79`.
- Не удалять старый конфиг при миграции: читать и предлагать перенос.

---

## 8. Что сделать на этой неделе

1. **День 1:** C0-1 (`term` RCE) + C0-2 (секреты) + C0-3 (deps/version) — это безопасность и устанавливаемость.
2. **День 2:** C0-5 (JSON/exit codes) + C0-12 (тесты/CI) — чтобы дальше не ломать.
3. **День 3–4:** C0-4 (`exec`/`-p`) + C0-9 (async SSE/reconnect) — первый настоящий агентский сценарий.
4. **День 5:** C0-6 (approvals) + C0-7 (diff/patch) — доверие и откат.

После этого CLI можно показывать как «Arkost в терминале», а не «обёртку над API».

---

## 9. Источники

### Официальные CLI

- Claude Code CLI reference: https://code.claude.com/docs/en/cli-reference
- Claude Code headless: https://code.claude.com/docs/en/headless
- Claude Code interactive mode: https://code.claude.com/docs/en/interactive-mode
- Claude Code permission modes: https://code.claude.com/docs/en/permission-modes
- Claude Code status line: https://code.claude.com/docs/en/statusline
- Claude Code checkpointing: https://code.claude.com/docs/en/checkpointing
- Codex CLI: https://learn.chatgpt.com/docs/codex/cli
- Codex non-interactive: https://learn.chatgpt.com/docs/non-interactive-mode
- Codex approvals/security: https://learn.chatgpt.com/docs/agent-approvals-security
- Gemini CLI: https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/cli-reference.md
- Gemini headless: https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/headless.md
- Gemini sessions: https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/session-management.md

### Вторая волна

- Aider docs: https://aider.chat/docs/
- Aider repo map: https://aider.chat/docs/repomap.html
- opencode docs: https://opencode.ai/docs/
- opencode permissions: https://opencode.ai/docs/permissions/
- opencode snapshots: https://opencode.ai/docs/snapshots/
- Goose docs: https://goose-docs.ai/docs/guides/goose-cli-commands
- Goose recipes: https://goose-docs.ai/docs/guides/recipes/subrecipes
- Copilot CLI: https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-cli
- Copilot CLI reference: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
- Cursor CLI: https://cursor.com/docs/cli/overview
- Cursor CLI headless: https://cursor.com/docs/cli/headless
- Continue CLI: https://docs.continue.dev/cli/quickstart
- Cline CLI: https://docs.cline.bot/cli/cli-reference

### Инженерия CLI

- clig.dev: https://clig.dev/
- NO_COLOR: https://no-color.org/
- XDG Base Directory: https://specifications.freedesktop.org/basedir-spec/latest/
- Python keyring: https://keyring.readthedocs.io/en/latest/
- pipx: https://pipx.pypa.io/stable/
- uv tools: https://docs.astral.sh/uv/guides/tools/
- PyPI Trusted Publishing: https://docs.pypi.org/trusted-publishers/
- Textual testing: https://textual.textualize.io/guide/testing/
- Textual command palette: https://textual.textualize.io/guide/command_palette/
- OpenTelemetry GenAI: https://github.com/open-telemetry/semantic-conventions-genai

### Внутренние контракты

- Approve/reject: `app/endpoints/runs.py:1253`, `:1282`
- Answers: `app/endpoints/runs.py:896`
- `approval.required` payload: `app/worker.py:2258`
- `agent.question` payload: `app/worker.py:1210`
- `diff.ready` payload: `app/worker.py:5365-5372`
- Approval timeout 240 с: `app/config.py:183`
- Patch endpoint: `GET /runs/{id}/patch` (см. `API.md`)
- Cost: `TaskRun.cost_usd`, `/users/me/usage`
