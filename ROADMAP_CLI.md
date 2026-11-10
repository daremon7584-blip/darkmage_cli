# Darkmage CLI — детальный дорожный карта внедрения функций (актуальная версия)

Цель документа: пошаговый план развития кастомного CLI (`/root/darkmage-cli`) для платформы Darkmage AI (`/root/saas-backend`) с опорой на опыт создания production-CLI (Click/Typer/argparse, структура пакета, конфигурация, аутентификация, вывод, ошибки, тестирование, release).

> **Актуальный следующий этап:** [`docs/CLI_CLIENT_RESEARCH.md`](docs/CLI_CLIENT_RESEARCH.md) — исследование CLI-клиентов LLM-сервисов и план полировки. Там P0: `term` RCE, утечки токенов, `exec`/`-p`, approvals, diff/patch, sessions, async SSE, тесты и дистрибуция. История фаз ниже не отменяет эти P0.
>
> **Про тесты:** «39/47 тестов проходят» — историческая цифра. Аудит показал false green в `tests/test_user_cli.py` (нет assert) и запись тестов в реальный `~/.darkmage-cli`; см. раздел 3.3 нового документа.

Источники:
- `/root/saas-backend/API.md` — контракт REST API
- `/root/saas-backend/app/schemas.py` — Pydantic-схемы
- `/root/saas-backend/DARKMAGE_AI_ROADMAP.md` — бизнес-дорожная карта платформы
- `/root/darkmage-cli/COMPARISON_CLAUDE_CODE.md` — сравнение с Claude Code и оценка сложности
- `/root/darkmage-cli/CLI_IMPLEMENTATION_COMPLEXITY.md` — оценка сложности реализации CLI-функций
- `/root/darkmage-cli/COMPARISON_DARKMAGE_VS_CLAUDE_CODE_CODEX_OPENCODE.md` — сравнение с конкурентами

---

## 0. Текущее состояние (база)

Уже реализовано и установлено:
- Пакет `darkmage-cli` с точкой входа `darkmage` (`pyproject.toml`, `darkmage_cli/`)
- Клиент `DarkmageClient` на `httpx` с базовыми методами (auth, users, workspaces, files, sessions, runs, chat, health, billing, admin, pty, git, mcp)
- CLI-команды через `argparse`
- Конфиг в `~/.darkmage-cli/config.json`, поддержка `DARKMAGE_API_URL` / `DARKMAGE_TOKEN`
- JSON-вывод через `print_json`, ошибки через `print_error` с exit-code 1
- 39 тестов (`tests/test_cli.py`), `ruff check` и `mypy` чистые

### ✅ Завершено (все фазы)

**Phase 1 — быстрые победы (коммит `3ff2707`):**
- `files edit` — прямое редактирование файлов через editor flow
- `run message` — сообщения в ход задачи
- `run revert` — откат задачи
- `run review` — ревью диффа
- `process start|output|stop` — фоновые процессы
- `run create --image` — картинки в задаче

**Phase 2 — среднесрочно (коммит `2a6c232`):**
- `run events --pretty` — человекопонятный цветной вывод SSE с парсингом событий
- `run events` — JSON lines режиме по умолчанию, `--last-event-id` для возобновления
- `run answer <run_id> <question_id> <answer...>` — ответы на вопросы владельцу (ask_user)
- `run context <run_id>` — использование контекстных токенов (context_tokens/context_limit)

**Phase 2b — улучшение CLI (коммиты `ef0a884`, `6c55985`, `c442925`):**
- `admin status` — баланс OpenRouter (только админ)
- `payment create|list` — платёжные запросы и список платежей
- `term <workspace_id>` — интерактивный терминал PTY через WebSocket к runner-manager
- `git clone|commit|push|pr` — Git-операции (клонирование, коммит, push, PR)
- `mcp list|call` — MCP-инструменты (список и вызов)
- Глобальные флаги `--verbose`, `--json`
- Команда `config show|set` — управление `~/.darkmage-cli/config.json`

**Phase 3 — долгосрочно (коммиты `76138e9`, `0810e06`, `bf6aacf`, `a71f33c`):**
- `run list <workspace_id>` — список всех runs в рабочей зоне (саб-агенты / параллельные задачи)
- `tui <workspace_id> [--run-id <id>]` — полноценный TUI клиент на Textual с лентой событий, компоузером, строкой состояния, цветовым кодированием
- Убрано ограничение "один активный run на workspace" в бэкенде — plan_only runs идут параллельно, остальные ставятся в очередь

**Approvals listing (10.11.2026):**
- `approvals list [--limit N] [--json]` — pending approvals по всем своим runs, newest first
- `approvals show <approval_id> [--json]` — tool, run/session, requested time, bounded summary и команды approve/reject
- Таблица укладывается в 80 колонок, пустое состояние и 404 без утечки токена; 11 тестов

**Run patch (10.11.2026):**
- `run patch <run_id> [--stat] [--output PATH] [--no-color] [--force] [--json]` — unified git patch из `GET /runs/{id}/patch`
- Цвета только на TTY, `--no-color` отключает; не-TTY режим сохраняет байты для пайпа
- `--stat` — число файлов, additions/deletions и per-file `+/-`; `--output` пишет точные байты и защищает от перезаписи
- `--json` — `run_id`, `files`, `additions`, `deletions`, `stat[]`, `patch`; пустой патч — пустые массивы
- 402 (подписка), 404, 409 (не завершён/нет чекпоинта) и 413 (патч > 16 MiB) — понятные ошибки без токена; 28 тестов

**Run queue visibility (10.11.2026):**
- `run queue <run_id> [--json]` — статус, позиция, сколько задач впереди, человекочитаемый ETA, дедлайн и trial/paid очередь из аддитивного `queue` в `GET /runs/{id}`
- `run get` добавляет строку `Queue:` при наличии метаданных; `run list` показывает колонку `Очередь` только если хотя бы один run в очереди, и укладывается в 80 колонок (record layout на узких терминалах)
- Не в очереди — дружелюбное сообщение; queued без метаданных (истёк дедлайн/вот-вот заберёт воркер) — `queue information is not available`
- `--json` для `run queue` — сырой объект API, для `run get` — прежний объект; 404/403 без traceback и утечки токена
- bash/zsh/fish completion, help, README; тесты queue text/JSON, not queued, expired/null ETA, trial wording, run get/list, 404, token leak

**Admin skills gate (10.11.2026):**
- `admin skills list [--status ...] [--json]` — список сканов, таблица в 80 колонок (id/name/status/severity/risk/digest prefix/date)
- `admin skills show <scan_id> [--json]` — детали, top-5 findings/issues и подсказки approve/reject
- `admin skills gate <digest> [--json]` — 64 lowercase hex проверяется локально (exit 2), `allowed` только для approved
- `admin skills scan --name NAME [--version V] [--source URL] --report FILE [--json]` — POST нормализованного отчёта сканера; digest берётся из `--digest`, отчёта, локального `skill.source` или содержимого файла
- `admin skills approve <scan_id> [--note TEXT] [--allow-high-risk] [--json]`, `... reject ...` — blocked/high-risk скан требует `--allow-high-risk`; проверка до approve-запроса
- 404 для не-админа рендерится как `Admin only or not found`, 409/422 — понятные ошибки без traceback и токена; bash/zsh/fish completion и help
- 37 тестов; весь CLI suite — 246 тестов

**Admin MCP gateway (10.11.2026):**
- `admin mcp list [--json]` — `GET /admin/mcp/tools`; таблица tool / префикс schema hash / approval status / префикс approved hash / last seen, не шире 80 колонок
- `admin mcp show <tool> [--json]` — детали из списка: approval metadata, оба хеша при расхождении, bounded JSON schema и подсказка approve
- `admin mcp approve <tool> [--hash SHA256] [--yes] [--json]` — hash проверяется локально (64 lowercase hex); с `--hash` CLI сверяет его с текущим и отказывает при mismatch (exit 2, без POST), без `--hash` требует `--yes`, печатает текущий hash и одобряет именно его
- `admin mcp call <tool> --args JSON [--json]` — `POST /admin/mcp/call` для read-only allowlist; malformed/missing JSON отказ локально, tool error → exit 1
- JSON-конверты `schema_version/server/...` для всех команд; 404 не-админа → `Admin only or not found` (exit 2), 409/422 — понятные ошибки без traceback и токена
- bash/zsh/fish completion и help; backend не отдаёт last_seen, поэтому колонка показывает `-` (совместимо с будущим полем)
- 52 теста admin MCP; полный CLI suite — 298 тестов

Все 298 тестов проходят.

---

## 1. Стандарты и best practices CLI (основа для всех фаз)

Перед написанием кода каждой фазы проверить соответствие:

| Область | Требование | Источник практики |
|---|---|---|
| Структура пакета | `pyproject.toml` + `darkmage_cli/` (плоский каталог), точка входа `[project.scripts]` | Python Packaging User Guide, Click/Typer проекты |
| CLI-интерфейс | Подкомманды (subcommands), глобальные флаги `--url`, `--token`, `--verbose`, `--json` | 12-Factor CLI, `argparse` subparsers |
| Конфигурация | Приоритет: CLI-флаг > ENV > `~/.darkmage-cli/config.json` > дефолт | 12-Factor config, XDG Base Directory |
| Аутентификация | Bearer-токен в конфиге, `auth login` сохраняет, `auth logout` удаляет, никогда не печатать токен в логи | OWASP secret storage, CLI security |
| Вывод | `print_json` для machine-readable, pretty-text для человека, `--json` forcing JSON, цвета только если `isatty(stdout)` | Unix CLI philosophy, `rich`/`click.style` |
| Ошибки | Понятное сообщение в stderr, exit-code != 0, стек-трейс только при `--verbose` или `DEBUG=1` | GNU CLI standards, `click.exceptions` |
| Тестирование | Каждая команда — отдельная функция, моки `httpx.Client`, тесты на succès/ошибку/валидацию | `pytest`, `responses`, `CliRunner` |
| Документация | `darkmage --help`, `darkmage <cmd> --help`, README с примерами | Self-documenting CLI |
| Выпуск | SemVer, `CHANGELOG.md`, сборка `pip install -e .` для dev, `pip install .` для release | Semantic Versioning |

---

## 2. Фаза 4 — Быстрые победы (Low, до 1 дня) ✅ ЗАВЕРШЕНО

Все функции реализованы:

### 2.1. Глобальный флаг `--json` для всех команд ✅
**Сложность:** Low
**Статус:** Готово
Все команды поддерживают `--json` для машинного вывода.

### 2.2. Глобальный флаг `--verbose` для всех команд ✅
**Сложность:** Low
**Статус:** Готово
При `--verbose` выводится стек-трейс при ошибках.

### 2.3. Цветной вывод статусов ✅
**Сложность:** Low
**Статус:** Готово
Статусы running/completed/failed/queued/waiting_approval/cancelled/creating/starting/stopped/error/ready выделяются цветом в командах `workspace list|get|start|stop` и `run list|get|start|stop|revert`. Цвета только если `isatty(stdout)`.

### 2.4. Команда `doctor` — проверка окружения ✅
**Сложность:** Low
**Статус:** Готово
Проверка `DARKMAGE_API_URL`, `DARKMAGE_TOKEN`, доступность `/health` и `/ready`, валидность токена.

### 2.5. Поддержка stdin для всех подходящих команд ✅
**Сложность:** Low
**Статус:** Готово
`files edit`, `run message` и другие принимают `-` для чтения из stdin.

### 2.6. Команда `config export\|import` ✅
**Сложность:** Medium
**Статус:** Готово
`config export <файл>` — выписывает конфиг в JSON-файл.
`config import <файл>` — импортирует конфиг из JSON-файла.
Токен и URL сохраняются корректно.

---

## 3. Фаза 5 — Среднесрочно (Medium, 1–3 дня)

### 3.1. Автодополнение (shell completion) для bash/zsh/fish ✅
**Сложность:** Medium
**Статус:** Готово
Команда `darkmage completion <bash|zsh|fish>` генерирует скрипты автодополнения для соответствующей оболочки.
**Критерии приёма:**
- `darkmage completion bash` — скрипт для .bashrc
- `darkmage completion zsh` — скрипт для .zshrc
- `darkmage completion fish` — скрипт для ~/.config/fish/completions/
- Автодополнение работает для всех подкоманд и флагов

### 3.2. Экспорт/импорт файлов workspace (`files upload\|download`) ✅
**Сложность:** Medium
**Статус:** Готово
**Критерии приёма:**
- `files download` — скачивание файла из workspace в локальную файловую систему через `GET /workspaces/{id}/files/content`
- `files upload` — чтение локального файла и отправка в workspace через `POST /workspaces/{id}/file-edits` с `base_content=""`
- Ограничение размера тела запроса учтено (max 256 KiB контента)

### 3.3. Дерево файлов (`files tree`) ✅
**Сложность:** Medium
**Статус:** Готово
Команда `darkmage files tree <workspace_id> [path] [--depth N]`.
**Критерии приёма:**
- Рекурсивный обход каталогов через повторные `files list`
- Отрисовка дерева с отступами (├──, └──, 📁, 📄)
- Ограничение глубины через `--depth` (по умолчанию 10)

### 3.4. История команд CLI ✅
**Сложность:** Medium
**Статус:** Готово
Команда `darkmage history [N]`.
**Критерии приёма:**
- Сохранение последних N команд в `~/.darkmage-cli/history.json`
- Команда `history` для просмотра
- Повтор команды по номеру: `darkmage history 3`

### 3.5. Параллельное выполнение нескольких команд
**Сложность:** Medium
**Критерии приёма:**
- Асинхронное выполнение независимых команд
- Например, `files list` для нескольких workspace одновременно

---

## 4. Фаза 6 — Долгосрочно (High, 3–7 дней)

### 4.1. Интерактивный режим (REPL) без подкоманд
**Сложность:** High
**Критерии приёма:**
- Интерактивный цикл ввода команд с подсказками
- Автодополнение и история
- Требует `prompt_toolkit` или `rich`

### 4.2. Визуализация графа зависимостей задач (runs graph)
**Сложность:** High
**Критерии приёма:**
- Построение графа связанных ran, сессий, workspace с зависимостями
- Накопление состояния в CLI

---

## 5. Требуют бэкенд-эндпоинтов (CLI-обёртка простая, но без бэкенда не работает)

| Функция | Сложность CLI | Статус бэкенда |
|---|---|---|
| `workspace import <url>` | Medium | Нужно бэкенд-эндпоинт импорта репозитория |
| `workspace export <path>` | Medium | Есть `/export` в бэкенде |
| `workspace preview <url>` | Medium | Есть `/preview` в бэкенде |
| `session archive\|restore` | Low | Есть бэкенд-эндпоинты сессий |
| `run patch <run_id>` | Medium | ✅ Готово (CLI): `GET /runs/{id}/patch`, `--stat`, `--output`, `--json`, 402/404/409/413 |
| `run memory-suggestions\|decide` | Low | Есть бэкенд-эндпоинты |

---

## 6. План релиза и метрики

| Фаза | Срок | Категория метрики | Чеклист завершения |
|---|---|---|---|
| 4. Быстрые победы (Low) | 1–2 дня | `feature` | Все команды добавлены, тесты пройдены, `ruff` + `mypy` чистые |
| 5. Среднесрочно (Medium) | 3–6 дней | `feature` | Автодополнение, файлы upload/download, дерево, история, параллелизм — тесты пройдены |
| 6. Долгосрочно (High) | 3–7 дней | `feature` / `tooling` | Интерактивный REPL, граф задач — тесты пройдены |

После каждой завершённой задачи добавить строку в `/root/saas-backend/DEVELOPMENT_METRICS.csv`:
```
<slug>;<category>;<minutes>;<UTC timestamp>;<checks>;<first_pass yes/no>
```

Пример:
```
cli-file-edit;feature;180;2026-10-31T14:00:00Z;lint;pytest;check-fast;yes
```

---

## 7. Чек-лист перед началом каждой фазы

- [ ] Прочитать соответствующий раздел `API.md` и `app/schemas.py`
- [ ] Проверить, что эндпоинт существует в `app/endpoints/*.py`
- [ ] Написать тест с моком `httpx` перед реализацией (TDD)
- [ ] Добавить команду в `build_parser()` в `darkmage_cli/cli.py`
- [ ] Добавить метод в `DarkmageClient` в `darkmage_cli/client.py`
- [ ] Обновить `README.md` с примером использования
- [ ] Запустить `ruff check`, `mypy`, `pytest`
- [ ] Проверить на реальном стенде (если API доступен)
- [ ] Добавить строку в `DEVELOPMENT_METRICS.csv`

---

## 8. Риски и факторы сложности (Darkmage vs Claude Code)

1. **Разделение ролей:** API, worker, runner-manager — разные контейнеры. Любая новая функция требует согласованного выката.
2. **Безопасность:** Docker-сокет только у `runner-manager`. Интерактивная работа с контейнером требует проксирования через runner, не прямого доступа.
3. **gVisor:** Ограничения на файловые операции и сеть в sandbox усложняют проброс терминала и импорт репозиториев.
4. **Политика одобрения (`approval_policy.py`):** Любое изменение файла или команда проходит через durable owner approval. TUI и терминал должны уважать это.
5. **Чекпоинты/откат:** Параллельные записи и интерактивные правки ломают assumptions о едином активном мутирующем run на workspace.

---

## 9. Быстрая ссылка по командам (текущее + запланированное)

```
# Уже доступно
darkmage auth register|login|logout
darkmage me|usage|memory get|put
darkmage workspace create|list|get|update|start|stop|delete
darkmage files list|read|search|edit
darkmage session create|list
darkmage run create|get|message|answer|context|revert|review|stop|events|list
darkmage process start|output|stop
darkmage payment create|list
darkmage admin status
darkmage admin skills list|show|gate|scan|approve|reject ...
darkmage admin mcp list|show|approve|call <tool> [--hash SHA256] [--yes] [--args JSON]
darkmage term <workspace_id>
darkmage tui <workspace_id> [--run-id <id>]
darkmage git clone|commit|push|pr <ws> ...
darkmage mcp list|call <tool> <ws> ...
darkmage config show|set [--json] [--url URL] [--token TOKEN] [--verbose]
darkmage chat "текст"
darkmage health|ready

# Фаза 4 (быстрые победы, Low)
darkmage --json <любая команда>
darkmage --verbose <любая команда>
darkmage doctor
darkmage config export|import
darkmage files edit --content "-" (stdin)
darkmage run message --text "-" (stdin)

# Фаза 5 (среднесрочно, Medium)
darkmage completion install (bash/zsh/fish)
darkmage files download <ws> <remote> <local>
darkmage files upload <local> <ws> <remote>
darkmage files tree <ws> [path]
darkmage history
darkmage <cmd1> && <cmd2> & (параллельно)

# Фаза 6 (долгосрочно, High)
darkmage repl (интерактивный режим)
darkmage runs graph <workspace_id> (визуализация зависимостей)

# Требуют бэкенда
darkmage workspace import <url>
darkmage workspace export <path>
darkmage workspace preview <url>
darkmage session archive|restore
darkmage run patch <run_id>
darkmage run memory-suggestions <run_id> <suggestion_id> <accept|dismiss>
```

---

## 10. Быстрая ссылка по сложности (только CLI)

| Уровень | Срок | Примеры |
|---|---|---|
| **Low** (до 1 дня) | ~18 функций | CRUD команды, конфиг, простые GET/POST, цветной вывод, stdin, doctor |
| **Medium** (1–3 дня) | ~6 функций | SSE-поток, PTY-терминал, файлы upload/download, дерево файлов, история команд, автодополнение, export/import конфига |
| **High** (3–7 дней) | ~2 функции | Интерактивный REPL, граф зависимостей задач |
| **Very High** (1–2 недели) | 0 функций | — |

---

*Документ поддерживается разработчиком. Обновлять после завершения каждой фазы и изменения приоритетов в `DARKMAGE_AI_ROADMAP.md`.*