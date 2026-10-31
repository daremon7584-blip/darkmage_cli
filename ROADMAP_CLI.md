# Odyssey CLI — детальный дорожный карта внедрения функций

Цель документа: пошаговый план развития кастомного CLI (`/root/odyssey-cli`) для платформы Odyssey AI (`/root/saas-backend`) с опорой на опыт создания production-CLI (Click/Typer/argparse, структура пакета, конфигурация, аутентификация, вывод, ошибки, тестирование,_release).

Источники:
- `/root/saas-backend/API.md` — контракт REST API
- `/root/saas-backend/app/schemas.py` — Pydantic-схемы
- `/root/saas-backend/ODYSSEY_AI_ROADMAP.md` — бизнес-дорожная карта платформы
- `/root/odyssey-cli/COMPARISON_CLAUDE_CODE.md` — сравнение с Claude Code и оценка сложности

---

## 0. Текущее состояние (база)

Уже реализовано и установлено:
- Пакет `odyssey-cli` с точкой входа `odyssey` (`pyproject.toml`, `odyssey_cli/`)
- Клиент `OdysseyClient` на `httpx` с базовыми методами (auth, users, workspaces, files, sessions, runs, chat, health)
- CLI-команды через `argparse`: `auth register/login/logout`, `me`, `usage`, `memory get|put`, `workspace create|list|get|update|start|stop|delete`, `files list|read|search`, `session create|list`, `run create|get|stop|events`, `chat`, `health`, `ready`
- Конфиг в `~/.odyssey-cli/config.json`, поддержка `ODYSSEY_API_URL` / `ODYSSEY_TOKEN`
- JSON-вывод через `print_json`, ошибки через `print_error` с exit-code 1

Что нужно сделать перед началом новой фазы:
- [ ] Добавить тесты (`pytest` + `responses`/`httpx_mock`) для всех команд
- [ ] Добавить `./scripts/check-fast.sh` analog (lint: `ruff`, typing: `mypy`, тесты)
- [ ] Добавить `README.md` usage примеры (уже есть базовый)

---

## 1. Стандарты и best practices CLI (основа для всех фаз)

Перед написанием кода каждой фазы проверить соответствие:

| Область | Требование | Источник практики |
|---|---|---|
| Структура пакета | `pyproject.toml` + `src/odyssey_cli/` (не плоский каталог), точка входа `[project.scripts]` | Python Packaging User Guide, Click/Typer проекты |
| CLI-интерфейс | Подкомманды (subcommands), глобальные флаги `--url`, `--token`, `--verbose`, `--json` | 12-Factor CLI, `argparse` subparsers |
| Конфигурация | Приоритет: CLI-флаг > ENV > `~/.odyssey-cli/config.json` > дефолт | 12-Factor config, XDG Base Directory |
| Аутентификация | Bearer-токен в конфиге, `auth login` сохраняет, `auth logout` удаляет, никогда не печатать токен в логи | OWASP secret storage, CLI security |
| Вывод | `print_json` для machine-readable, pretty-text для человека, `--json` forcing JSON, цвета только если `isatty(stdout)` | Unix CLI philosophy, `rich`/`click.style` |
| Ошибки | Понятное сообщение в stderr, exit-code != 0, стек-трейс только при `--verbose` или `DEBUG=1` | GNU CLI standards, `click.exceptions` |
| Тестирование | Каждая команда — отдельная функция, моки `httpx.Client`, тесты на succès/ошибку/валидацию | `pytest`, `responses`, `CliRunner` |
| Документация | `odyssey --help`, `odyssey <cmd> --help`, README с примерами | Self-documenting CLI |
| Выпуск | SemVer, `CHANGELOG.md`, сборка `pip install -e .` для dev, `pip install .` для release | Semantic Versioning |

---

## 2. Фаза 1 — Быстрые победы (Low, дни)

Все функции уже имеют готовые API-эндпоинты в `/root/saas-backend`. Нужно только добавить CLI-обёртки.

### 1.1. Прямое редактирование файлов без задачи
**Команды:** `odyssey files edit <workspace_id> <path> --content "..."` и `odyssey files write <workspace_id> <path> --content "..."` (или через stdin)
**API:** `GET/PUT /workspaces/{id}/files/content` — уже есть в `schemas.WorkspaceFileEditRequest`
**Критерии приёма:**
- `files read` уже работает
- `files edit` принимает `--content` или читает stdin, отправляет `base_content` (текущее) + `content` (новое)
- `files write` создаёт файл, если не существует
- Уважает `approval_mode` workspace: в `ask` выводит предупреждение, что нужна aprobация владельца (через `/tool-calls/{id}/approve`), в `auto` применяет если команда allowlisted
-_EXIT code 0 при succès, 422/409 пробрасываются как понятная ошибка_

**Зависимости:** 없음 (API готово)
**Оценка:** 1–2 дня

### 1.2. Сообщения в ход задачи (`/runs/{id}/messages`)
**Команда:** `odyssey run message <run_id> --text "дополнение"` или `odyssey run message <run_id> -` (stdin)
**API:** `POST /runs/{id}/messages` (событие `user.message`)
**Критерии приёма:**
- Текст 1–4000 символов, валидация на пустоту и NUL-байты
- Сообщение принимается только для run в статусе `running` или `waiting_approval`
- Выводит подтверждение с `run_id` и статусом
- Ошибка 409, если run завершён

**Зависимости:** API эндпоинт сообщений должен быть проверен в `app/endpoints/runs.py`
**Оценка:** 1 день

### 1.3. Откат задачи (revert)
**Команда:** `odyssey run revert <run_id>`
**API:** `POST /runs/{id}/revert`
**Критерии приёма:**
- Проверка, что run терминальный (`completed`/`failed`/`cancelled`) и workspace запущен
- Вывод нового статуса checkpoint (`reverted`) и события `checkpoint.resolved`
- Ошибка 409, если workspace остановлен или есть активный run

**Зависимости:** API готов (`API.md` стр. 196)
**Оценка:** 1 день

### 1.4. Ревью диффа (review)
**Команда:** `odyssey run review <run_id>`
**API:** `POST /runs/{id}/review`
**Критерии приёма:**
- Вывод `{"model": "...", "findings": [...], "cost_usd": "..."}`
- Пустой список findings = проблем не найдено
- Ошибка 409 для running run или без изменений файлов

**Зависимости:** API готов (`API.md` стр. 192)
**Оценка:** 1 день

### 1.5. Фоновые процессы (process)
**Команды:** `odyssey process start <workspace_id> --cmd "python app.py"`, `odyssey process output <workspace_id> <process_id>`, `odyssey process stop <workspace_id> <process_id>`
**API:** `start_process`, `process_output`, `stop_process` (упомянуто в roadmap)
**Критерии приёма:**
- `start` возвращает `process_id`, статус, URL вывода
- `output` опрашивает новые строки (polling),支持 `--follow` для стрима
- `stop` завершает процесс, освобождает слот (макс 2 на проект, 30 мин)

**Зависимости:** API фоновых процессов в воркере (уже описано в roadmap)
**Оценка:** 2–3 дня

### 1.6. Картинки в задаче
**Команда:** `odyssey run create <session_id> --prompt "..." --image /path/to/file.png [--image ...]` (до 3)
**API:** `TaskImage` с base64, валидация сигнатур PNG/JPEG/WEBP, max 1.5 MB
**Критерии приёма:**
- Читает локальный файл, кодирует base64, проверяет magic bytes
- Максимум 3 изображения, суммарно не более лимита тела запроса
- Передаёт в `TaskRunCreate.images`

**Зависимости:** `schemas.TaskImage` уже есть
**Оценка:** 2 дня

---

## 3. Фаза 2 — Среднесрочно (Low-Medium / Medium, 1–4 недели)

### 2.1. Интерактивные вопросы владельцу (ask_user)
**Контекст:** Агент во время run может выдать событие `approval.required` с типом вопроса (1–4 варианта answers, таймаут 4 мин, не более 3 раз за задачу).
**Команды:** `odyssey run answer <run_id> --question-id <id> --answer "вариант"` или интерактивный режим `odyssey run watch <run_id>` который показывает вопросы и ждет ввода.
**Критерии приёма:**
- Во время `run events` CLI распознаёт события с вопросами и приостанавливает вывод, предлагая выбрать вариант
- Ответ отправляется через API (нужен эндпоинт ответа на вопрос — проверить в `app/endpoints/runs.py`)
- Таймаут 4 мин — после истечения вопрос считается пропущенным ("Решай сам")
- Лимит 3 вопроса на задачу

**Зависимости:** Нужно уточнить API для ответа на `ask_user` (возможно, через tool-call approve или отдельный эндпоинт)
**Оценка:** 1–2 недели

### 2.2. Управление контекстом и компактировка
**Команды:** `odyssey run context <run_id>` (показать `context_tokens` / `context_limit`), `odyssey run summary <run_id>` (показать компактированное саммари)
**API:** Поля `context_tokens`, `context_limit` в `TaskRunResponse`, событие `context.compacted`
**Критерии приёма:**
- Отображение процента заполнения контекста
- Предупреждение приapproach к лимиту (например, > 80%)
- Показ последнего саммари после компактировки

**Зависимости:** Логика компактировки уже в воркере (`context.compacted`)
**Оценка:** 1 неделя

### 2.3. Улучшение вывода run events (SSE)
**Команда:** `odyssey run events <run_id> --watch --pretty`
**Критерии приёма:**
- Парсинг SSE (`id`, `event`, `data`) вместо вывода raw text
- Цветовое кодирование событий: `assistant.delta` (зелёный), `tool.requested` (синий), `approval.required` (жёлтый), `run.completed` (зеленый bold), `run.failed` (красный)
- Поддержка `Last-Event-ID` для возобновления после обрыва
- `--follow` для непрерывного стрима до терминального состояния

**Зависимости:** API `/runs/{id}/events` готово
**Оценка:** 1 неделя

### 2.4. Администрирование и биллинг (опционально)
**Команды:** `odyssey payment create --product standard_30d`, `odyssey payment receipt <id> --url https://...`, `odyssey admin status` (только для админов)
**API:** `billing.router` (`/billing/...`)
**Критерии приёма:**
- Создание платежа с кодом для перевода Т-Банк
- Обновление квитанции (Receipt URL)
- Админская проверка баланса OpenRouter

**Зависимости:** `app/endpoints/billing.py`
**Оценка:** 1–2 недели

---

## 4. Фаза 3 — Долгосрочно (High, 1–3 месяца каждая)

### 3.1. Интерактивный терминал (PTY к sandbox)
**Сложность:** High
**Проблема:** Команды сейчас выполняются как одноразовые argv через `run_command`. Нужно persistent PTY-сеанс.
**Решение:**
- Добавить API-эндпоинт в runner-manager для PTY-проброса (WebSocket или long-polling)
- CLI использует `pty` модуль Python + `httpx` для потокового ввода/вывода
- Обработка `SIGINT` (Ctrl+C), `SIGTSTP`, изменение размера терминала (`TIOCGWINSZ`)
- gVisor: проброс через runner-manager, не прямой доступ к Docker-сокету
**Критерии приёма:** `odyssey term <workspace_id>` открывает интерактивную сессию, работает `ls`, `cd`, `python`, выход по `exit` или `Ctrl+D`
**Оценка:** 1–3 месяца

### 3.2. Git-операции (коммит, push, PR, ветки)
**Сложность:** High
**Проблема:** Нет GitHub App, нет git-клиента в sandbox по умолчанию, sandbox изолирован.
**Решение:**
- Регистрация GitHub App в настройках Odyssey (Owner)
- OAuth-токены пользователя хранятся зашифрованно на сервере
- В sandbox устанавливается git, операции выполняются через runner-manager с примонтированным workspace volume
- CLI: `odyssey git clone <url>`, `odyssey git commit -m "..."`, `odyssey git push`, `odyssey pr create`
**Критерии приёма:** Клонирование приватного репозитория в workspace, коммит изменений, создание PR через GitHub API
**Оценка:** 1–3 месяца

### 3.3. MCP / подключение внешних инструментов
**Сложность:** High
**Решение:**
- Реализовать MCP-сервер внутри Odyssey (stdio или HTTP)
- Реестр инструментов: файловые операции, команды, чат, запуск run
- Аутентификация MCP-клиентов через тот же Bearer-токен
- Все вызовы через `approval_policy.py` — модель не может расширить права
**Критерии приёма:** Подключение Claude Code или другого MCP-клиента к `odyssey mcp serve`, выполнение файловой операции через протокол
**Оценка:** 1–3 месяца

### 3.4. Саб-агенты и параллельные задачи
**Сложность:** High
**Проблема:** Один активный run на workspace, общий чекпоинт.
**Решение:**
- Изменение planner/воркера: поддержка нескольких ran на workspace с изоляцией файловых изменений
- Конфликты чекпоинтов разрешаются пошагово или через last-write-wins с предупреждением
- CLI: `odyssey run spawn <session_id> --prompt "..." --as-subagent`
**Критерии приёма:** Два параллельных агента в одном workspace не ломают чекпоинты друг друга
**Оценка:** 1–3 месяца

### 3.5. Полноценный TUI (замена чистого CLI)
**Сложность:** High
**Решение:**
- Переписать интерфейс на `Textual` или `Rich` + `prompt_toolkit`
- Компоузер внизу, лента шагов посередине, правая панель с файлами/диффами
- Интеграция с SSE-событиями как лентой в реальном времени
- Одобрение действий в TUI (кнопки Approve/Reject)
**Критерии приёма:** `odyssey tui` запускает полноценный интерфейс, equivalente web-интерфейсу Odyssey
**Оценка:** 1–3 месяца

---

## 5. Планリリース и метрики

| Фаза | Срок | Категория метрики | Чеклист завершения |
|---|---|---|---|
| 1. Быстрые победы | 1 неделя | `feature` | Все 6 команд добавлены, тесты пройдены, `check-fast.sh` зелёный |
| 2. Среднесрочно | 3–6 недель | `feature` | ask_user, контекст, pretty SSE, оплата — работают с моками и на стенде |
| 3. Долгосрочно | 3–9 месяцев | `feature` / `tooling` | Терминал, Git, MCP, саб-агенты, TUI — по одной на итерацию |

После каждой завершённой задачи добавить строку в `/root/saas-backend/DEVELOPMENT_METRICS.csv`:
```
<slug>;<category>;<minutes>;<UTC timestamp>;<checks>;<first_pass yes/no>
```

Пример:
```
cli-file-edit;feature;180;2026-10-31T14:00:00Z;lint;pytest;check-fast;yes
```

---

## 6. Чек-лист перед началом каждой фазы

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

## 7. Риски и факторы сложности (Odyssey vs Claude Code)

1. **Разделение ролей:** API, worker, runner-manager — разные контейнеры. Любая новая функция требует согласованного выката.
2. **Безопасность:** Docker-сокет только у `runner-manager`. Интерактивная работа с контейнером требует проксирования через runner, не прямого доступа.
3. **gVisor:** Ограничения на файловые операции и сеть в sandbox усложняют проброс терминала и импорт репозиториев.
4. **Политика одобрения (`approval_policy.py`):** Любое изменение файла или команда проходит через durable owner approval. TUI и терминал должны уважать это.
5. **Чекпоинты/откат:** Параллельные записи и интерактивные правки ломают assumptions о едином активном мутирующем run на workspace.

---

## 8. Быстрая ссылка по командам (текущее + запланированное)

```
# Уже доступно
odyssey auth register|login|logout
odyssey me|usage|memory get|put
odyssey workspace create|list|get|update|start|stop|delete
odyssey files list|read|search
odyssey session create|list
odyssey run create|get|stop|events
odyssey chat "текст"
odyssey health|ready

# Фаза 1 (добавить)
odyssey files edit|write <ws> <path> --content ...
odyssey run message <run_id> --text ...
odyssey run revert <run_id>
odyssey run review <run_id>
odyssey process start|output|stop <ws> ...
odyssey run create ... --image file.png

# Фаза 2
odyssey run answer <run_id> --question-id ... --answer ...
odyssey run context|summary <run_id>
odyssey run events <run_id> --watch --pretty
odyssey payment create|receipt ...

# Фаза 3
odyssey term <workspace_id>
odyssey git clone|commit|push|pr ...
odyssey mcp serve
odyssey run spawn ...
odyssey tui
```

---

*Документ поддерживается разработчиком. Обновлять после завершения каждой фазы и изменения приоритетов в `ODYSSEY_AI_ROADMAP.md`.*
