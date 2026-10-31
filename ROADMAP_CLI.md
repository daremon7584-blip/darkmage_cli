# Odyssey CLI — детальный дорожный карта внедрения функций (актуальная версия)

Цель документа: пошаговый план развития кастомного CLI (`/root/odyssey-cli`) для платформы Odyssey AI (`/root/saas-backend`) с опорой на опыт создания production-CLI (Click/Typer/argparse, структура пакета, конфигурация, аутентификация, вывод, ошибки, тестирование, release).

Источники:
- `/root/saas-backend/API.md` — контракт REST API
- `/root/saas-backend/app/schemas.py` — Pydantic-схемы
- `/root/saas-backend/ODYSSEY_AI_ROADMAP.md` — бизнес-дорожная карта платформы
- `/root/odyssey-cli/COMPARISON_CLAUDE_CODE.md` — сравнение с Claude Code и оценка сложности
- `/root/odyssey-cli/CLI_IMPLEMENTATION_COMPLEXITY.md` — оценка сложности реализации CLI-функций
- `/root/odyssey-cli/COMPARISON_ODYSSEY_VS_CLAUDE_CODE_CODEX_OPENCODE.md` — сравнение с конкурентами

---

## 0. Текущее состояние (база)

Уже реализовано и установлено:
- Пакет `odyssey-cli` с точкой входа `odyssey` (`pyproject.toml`, `odyssey_cli/`)
- Клиент `OdysseyClient` на `httpx` с базовыми методами (auth, users, workspaces, files, sessions, runs, chat, health, billing, admin, pty, git, mcp)
- CLI-команды через `argparse`
- Конфиг в `~/.odyssey-cli/config.json`, поддержка `ODYSSEY_API_URL` / `ODYSSEY_TOKEN`
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
- Команда `config show|set` — управление `~/.odyssey-cli/config.json`

**Phase 3 — долгосрочно (коммиты `76138e9`, `0810e06`, `bf6aacf`, `a71f33c`):**
- `run list <workspace_id>` — список всех runs в рабочей зоне (саб-агенты / параллельные задачи)
- `tui <workspace_id> [--run-id <id>]` — полноценный TUI клиент на Textual с лентой событий, компоузером, строкой состояния, цветовым кодированием
- Убрано ограничение "один активный run на workspace" в бэкенде — plan_only runs идут параллельно, остальные ставятся в очередь

Все 39 тестов проходят, `ruff check` и `mypy` чистые.

---

## 1. Стандарты и best practices CLI (основа для всех фаз)

Перед написанием кода каждой фазы проверить соответствие:

| Область | Требование | Источник практики |
|---|---|---|
| Структура пакета | `pyproject.toml` + `odyssey_cli/` (плоский каталог), точка входа `[project.scripts]` | Python Packaging User Guide, Click/Typer проекты |
| CLI-интерфейс | Подкомманды (subcommands), глобальные флаги `--url`, `--token`, `--verbose`, `--json` | 12-Factor CLI, `argparse` subparsers |
| Конфигурация | Приоритет: CLI-флаг > ENV > `~/.odyssey-cli/config.json` > дефолт | 12-Factor config, XDG Base Directory |
| Аутентификация | Bearer-токен в конфиге, `auth login` сохраняет, `auth logout` удаляет, никогда не печатать токен в логи | OWASP secret storage, CLI security |
| Вывод | `print_json` для machine-readable, pretty-text для человека, `--json` forcing JSON, цвета только если `isatty(stdout)` | Unix CLI philosophy, `rich`/`click.style` |
| Ошибки | Понятное сообщение в stderr, exit-code != 0, стек-трейс только при `--verbose` или `DEBUG=1` | GNU CLI standards, `click.exceptions` |
| Тестирование | Каждая команда — отдельная функция, моки `httpx.Client`, тесты на succès/ошибку/валидацию | `pytest`, `responses`, `CliRunner` |
| Документация | `odyssey --help`, `odyssey <cmd> --help`, README с примерами | Self-documenting CLI |
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
Проверка `ODYSSEY_API_URL`, `ODYSSEY_TOKEN`, доступность `/health` и `/ready`, валидность токена.

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
Команда `odyssey completion <bash|zsh|fish>` генерирует скрипты автодополнения для соответствующей оболочки.
**Критерии приёма:**
- `odyssey completion bash` — скрипт для .bashrc
- `odyssey completion zsh` — скрипт для .zshrc
- `odyssey completion fish` — скрипт для ~/.config/fish/completions/
- Автодополнение работает для всех подкоманд и флагов

### 3.2. Экспорт/импорт файлов workspace (`files upload\|download`)
**Сложность:** Medium
**Критерии приёма:**
- `files download <ws> <remote_path> <local_path>` — скачивание файла по API
- `files upload <local_path> <ws> <remote_path>` — чтение локального файла и отправка через API
- Ограничение размера тела запроса учтено

### 3.3. Дерево файлов (`files tree`)
**Сложность:** Medium
**Критерии приёма:**
- Рекурсивный обход каталогов через повторные `files list`
- Отрисовка дерева с отступами
- Ограничение глубины и количества записей

### 3.4. История команд CLI
**Сложность:** Medium
**Критерии приёма:**
- Сохранение последних N команд в `~/.odyssey-cli/history`
- Команда `history` для просмотра
- Повтор команды по номеру

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
| `run patch <run_id>` | Medium | Есть `/patch` в бэкенде |
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
- [ ] Добавить команду в `build_parser()` в `odyssey_cli/cli.py`
- [ ] Добавить метод в `OdysseyClient` в `odyssey_cli/client.py`
- [ ] Обновить `README.md` с примером использования
- [ ] Запустить `ruff check`, `mypy`, `pytest`
- [ ] Проверить на реальном стенде (если API доступен)
- [ ] Добавить строку в `DEVELOPMENT_METRICS.csv`

---

## 8. Риски и факторы сложности (Odyssey vs Claude Code)

1. **Разделение ролей:** API, worker, runner-manager — разные контейнеры. Любая новая функция требует согласованного выката.
2. **Безопасность:** Docker-сокет только у `runner-manager`. Интерактивная работа с контейнером требует проксирования через runner, не прямого доступа.
3. **gVisor:** Ограничения на файловые операции и сеть в sandbox усложняют проброс терминала и импорт репозиториев.
4. **Политика одобрения (`approval_policy.py`):** Любое изменение файла или команда проходит через durable owner approval. TUI и терминал должны уважать это.
5. **Чекпоинты/откат:** Параллельные записи и интерактивные правки ломают assumptions о едином активном мутирующем run на workspace.

---

## 9. Быстрая ссылка по командам (текущее + запланированное)

```
# Уже доступно
odyssey auth register|login|logout
odyssey me|usage|memory get|put
odyssey workspace create|list|get|update|start|stop|delete
odyssey files list|read|search|edit
odyssey session create|list
odyssey run create|get|message|answer|context|revert|review|stop|events|list
odyssey process start|output|stop
odyssey payment create|list
odyssey admin status
odyssey term <workspace_id>
odyssey tui <workspace_id> [--run-id <id>]
odyssey git clone|commit|push|pr <ws> ...
odyssey mcp list|call <tool> <ws> ...
odyssey config show|set [--json] [--url URL] [--token TOKEN] [--verbose]
odyssey chat "текст"
odyssey health|ready

# Фаза 4 (быстрые победы, Low)
odyssey --json <любая команда>
odyssey --verbose <любая команда>
odyssey doctor
odyssey config export|import
odyssey files edit --content "-" (stdin)
odyssey run message --text "-" (stdin)

# Фаза 5 (среднесрочно, Medium)
odyssey completion install (bash/zsh/fish)
odyssey files download <ws> <remote> <local>
odyssey files upload <local> <ws> <remote>
odyssey files tree <ws> [path]
odyssey history
odyssey <cmd1> && <cmd2> & (параллельно)

# Фаза 6 (долгосрочно, High)
odyssey repl (интерактивный режим)
odyssey runs graph <workspace_id> (визуализация зависимостей)

# Требуют бэкенда
odyssey workspace import <url>
odyssey workspace export <path>
odyssey workspace preview <url>
odyssey session archive|restore
odyssey run patch <run_id>
odyssey run memory-suggestions <run_id> <suggestion_id> <accept|dismiss>
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

*Документ поддерживается разработчиком. Обновлять после завершения каждой фазы и изменения приоритетов в `ODYSSEY_AI_ROADMAP.md`.*