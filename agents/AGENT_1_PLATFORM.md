# Агент 1 — платформа, контракты и интеграция

Читать сначала [архитектуру](../ARCHITECTURE.md) и [roadmap](../ROADMAP.md). Ты координатор совместимости четырёх частей, а не исполнитель всех задач команды. Очерёдность: **A1 → A2 → A3 → A4 → A5**.

## Зона владения и результат роли

Владеешь backend contracts/config/main/api/services/security, platform/integration tests, Python manifests/lock, root build/config, CI, contracts/examples/OpenAPI, README/runbook/decisions. Не меняешь реализацию `repository/`, `scanners/`, `intelligence/` и `frontend/` вместо владельцев. Общие изменения синхронизируешь через G0 и handoffs.

Результат: приложение запускается из чистого checkout, принимает реальные HTTP-запросы, соединяет модули 2/3/4 и выдерживает ошибки. Не добавляй Postgres/Redis/очереди/авторизацию: это вне MVP.

## A1. Каркас и контрактный baseline

**До начала:** доступен workspace; прочитаны все перечисления, DTO и Protocol из архитектуры; Git status проверен. Приложения может ещё не быть.

**Что создать:** Python package, Pydantic DTO, Protocol, app factory, health, dev-only stubs, нормативные examples, OpenAPI exporter, начальный backend lock. В `decisions.md` записать baseline version 1.0 и зависимости.

**Приёмка:** backend импортируется без ключей, health=200, examples валидны, OpenAPI воспроизводим; агенты 2–4 могут начать работу от G0.

### Промпт A1

```text
Реализуй A1 RepoDoctor. ARCHITECTURE.md — нормативный контракт; не изменяй его
самовольно ради удобства scaffold. Твоя зона: platform и общие schemas.

1. Осмотри корень и Git status. Если repo пуст, создай backend/src/repodoctor,
   тестовую структуру и общие docs; не создавай лишний вложенный RepoDoctor.
2. Создай pyproject для Python 3.12 с hatchling, FastAPI/Uvicorn, Pydantic 2,
   pydantic-settings, httpx, openai, packaging и dev pytest/asyncio/Ruff.
   Установи совместимые точные версии через uv, сохрани uv.lock. Не заявляй
   совместимость до установки/import smoke. Пакет должен работать из src layout.
3. Реализуй api.py, domain.py и ports.py. Перенеси все поля, enum, nullable,
   limits и сигнатуры из разделов 5–6 архитектуры. Extra запретить. Не оставляй
   DTO в виде Any/dict. Внутренние модели отдели от provider-output моделей.
4. Реализуй Settings: env из корня независимо от cwd, строгие режимы, положительные
   лимиты, без печати ключей. Создай .env.example и .gitignore, исключи .env,
   caches, venv, node_modules и runtime artifacts. Не исключай lock-файлы.
5. Создай create_app с lifespan и injection points для source/analyzer/
   intelligence/store. Создай dev stubs в services/stubs.py, не в чужих модулях.
   Stub никогда не становится production-реализацией по умолчанию.
6. Подготовь валидные JSON examples: Python analysis, Node analysis,
   needs_input/fallback, diagnosis и безопасная ошибка. Во всех examples
   evidence_ids существуют, timestamps/UUID/target согласованы. Synthetic
   repository ссылки и происхождение помечены явно.
7. Сделай export_openapi CLI без сети и ключей. Health и skeleton endpoints
   описывают настоящий request/response/error контракт, даже пока внутри stubs.
8. Напиши короткие contract tests: examples → DTO, enums, несовместимая OS/shell,
   extra fields, API schema доступна без live dependencies. Запусти lint/tests.
9. Обнови handoff агента 1: команды, результаты, commit, contract paths,
   ограничения stubs. Объяви G0 только при прохождении всего checklist roadmap.

Не реализуй GitHub scanner/AI логику, frontend package или произвольный API.
Выход: минимальный проверенный baseline, пригодный для параллельной работы.
```

## A2. API, lifecycle, memory store и ограничения

**До начала:** A1/G0 завершён. Реальные модули 2/3 не требуются: используются DI test doubles.

**Что создать:** routes, AnalysisService/DiagnosisService, memory TTL store, общий limiter, deadlines, sanitizer, body limit, exception handlers, platform tests.

**Приёмка:** Happy path и все контрактные ошибки проверены; ключи/сырой лог не появляются в ответах ошибок и logs; store TTL и cancellation корректны.

### Промпт A2

```text
Реализуй A2 по замороженным контрактам. Работай в api/services/security/config.
Модули source/scanner/intelligence пока подменяй Protocol-compatible fakes.

1. Сделай AnalysisService: принять validated request → захватить общий слот →
   await source.fetch → analyzer.analyze → await intelligence.build_plan →
   собрать response с UUID/UTC/schema version → store.put → вернуть 201.
   Итоговый evidence registry дедуплицируй по ID, не теряй static findings.
2. Сделай DiagnosisService: проверить store ID/TTL → очистить log и command →
   вызвать diagnose на сохранённом context → добавить metadata → вернуть 200.
   Сырой лог не сохранять. Unknown/expired ID отдаёт ANALYSIS_NOT_FOUND.
3. Реализуй store на OrderedDict: TTL 1800 s, максимум 30, LRU access,
   monotonic clock для expiry и UTC expires_at для API. Внедряемые clock/ID
   factories позволят тестировать без sleep. Ограничь размер context 512 KiB.
4. Реализуй единый limiter на две тяжёлые операции без неограниченной очереди.
   Анализ и diagnosis делят лимит. Deadline 85/45 секунд, release в finally
   при timeout/error/cancel. Не блокируй event loop time.sleep/requests.
5. Реализуй ASGI body limit 128 KiB и для chunked body. Не доверяй только
   Content-Length. Field validation: log ≤30000, command ≤2000, URL/ref limits.
6. Сделай redaction как общую чистую функцию: token/password/env assignments,
   bearer headers, credential URLs, private key blocks. Сохраняй число строк,
   возвращай redactions_count. Не логируй match value; тестируй synthetic secrets.
7. Единый ErrorResponse для validation, domain exceptions, 404 API routes,
   upstream failures и unexpected 500. request_id генерировать на сервере;
   не возвращать traceback/сырой request body. Корректно проставляй retryable.
8. Настрой lifecycle shared AsyncClient, DI, CORS только dev localhost origins.
   В structured server logs оставь IDs/timings/counts/status, убери body/prompt.
9. Проверь через test client: successful analysis/diagnosis, fallback,
   missing ID, TTL/eviction, whitespace log, oversized/chunked payload,
   validation envelope, limiter contention, cancellation освобождает слот,
   secret redaction, exception sanitization. Не используй live сеть.
10. Передай агентам 2/3 redaction API и composition expectations; агенту 4 —
    работающие HTTP examples. Contract delta оформляй единым согласованным пакетом.

Выход: безопасная и проверенная оболочка API, готовая принять настоящие модули.
```

## A3. Подключение модулей и G1

**До начала:** A2, B4 и C4 готовы; D3 либо готов, либо можно сначала проверить API. Все реализации соответствуют одному baseline.

**Что создать:** production DI wiring и integration tests на synthetic fixtures.

**Приёмка:** настоящий источник fixtures → scanner → fallback → UI/diagnosis; нет замаскированных stubs и расхождений DTO.

### Промпт A3

```text
Выполни A3: собери вертикальный срез RepoDoctor из модулей четырёх агентов.
Не переписывай их внутренности; дефекты возвращай владельцу с воспроизведением.

1. Проверь handoffs B4/C4/D3 и базовый commit контрактов. Последовательно
   интегрируй изменения; не запускай параллельные merge/rebase в одной папке.
2. В composition root подключи FixtureRepositorySource или GitHubRepositorySource
   по Settings, настоящий StaticAnalyzer и IntelligenceService. OpenAI provider
   создавай только при полной конфигурации; отсутствие ключа даёт fallback.
3. Проверь, что production не импортирует dev stubs, а fixture source допускает
   только свой index. REPOSITORY_MODE=live не подменяется fixture при сбое сети.
4. Запусти offline анализ Python и Node fixture, затем diagnosis по каждому.
   Проверь schema_version, IDs, source/generation modes, evidence references,
   OS/shell, timestamps, store context и coverage.
5. Создай integration tests на API с реальными scanner/fallback и fixture source,
   а не mock готового AnalysisResponse. Тестируй semantically: missing env finding,
   известный dependency, существующий evidence, потребность уточнения entrypoint.
6. Перегенерируй OpenAPI и передай агенту 4. Если diff неожиданен, исправь источник
   схемы до regenerating клиента. Не маскируй ошибку через Any/cast.
7. С агентом 4 пройди G1 в браузере с выключенным MSW: analyze → report → log →
   diagnosis → export. Отдельно неверный URL и expired analysis.
8. Зафиксируй G1 или перечисли конкретные failed checks/владельцев. В handoff
   отдели воспроизведённый backend integration от ещё не выполненных live tests.

Выход: полный полезный offline сценарий; этот результат ещё не доказывает live AI.
```

## A4. Сборка, CI, контейнер и live smoke

**До начала:** G1; frontend имеет проверяемые build/test scripts; для live нужны сеть и разрешённые ключи в env.

**Что создать:** CI pipeline, Dockerfile, compose, runbook, read-only live smoke command.

**Приёмка:** frozen install, unit/integration/browser checks, реальный публичный repo и доступный AI; каждый пропуск явно отмечен.

### Промпт A4

```text
Реализуй A4. Зафиксируй воспроизводимость существующего приложения, не расширяй MVP.

1. Сделай GitHub Actions jobs: Python 3.12 + uv sync --frozen + Ruff + pytest;
   Node baseline + npm ci + typecheck + test --run + build; OpenAPI regeneration
   и проверка diff; browser offline E2E с отдельной установкой Chromium.
   В PR/default CI не требуй API keys и не делай платных запросов.
2. Обеспечь единый скрипт export_openapi. Generated TS обновляет агент 4;
   CI проверяет, что схемы/клиент не устарели. Не редактируй generated файл вручную.
3. Создай multi-stage Dockerfile: frontend build → Python runtime + static assets.
   Non-root, один worker, без secrets в build args/image, без установки чужих repo.
   Добавь .dockerignore, не включай .env/.git/node_modules/fixtures secrets.
4. Compose передаёт env и публикует только localhost:8000, healthcheck через API.
   Fixture mode должен работать в контейнере: явно скопируй synthetic fixtures
   в согласованный runtime path и проверь путь относительно package/config.
5. Проверь порядок static/API routing: неизвестный /api/v1/... — JSON 404,
   assets доступны, главная открывается. API same-origin, dev proxy отдельно.
6. На чистой установке выполни README-команды Windows и доступный container path.
   Если Docker daemon недоступен, не отмечай runtime-check passed.
7. Совместно с агентом 2 выбери небольшие public Python/npm repos, зафиксируй SHA.
   Выполни live source smoke, запиши только metadata/counts/coverage, не ключи.
8. Совместно с агентом 3 выполни реальный AI plan и diagnosis при настроенной модели.
   Запиши model/date/status и quality notes. Отсутствующий доступ — незакрытая
   live часть G2; fallback tests её не заменяют.
9. Обнови runbook: установка, .env, режимы, 404/rate-limit/AI timeout, TTL/restart,
   остановка/повторный запуск, ограничение одного worker. Обнови G2 checklist.

Выход: проверяемая сборка и честный статус live, с воспроизводимыми командами.
```

## A5. Финальная приёмка

**До начала:** B5, C5, D5; выполненные gates и список оставшихся ограничений.

**Что создать:** финальная README-инструкция и acceptance matrix в runbook; последний согласованный commit.

**Приёмка:** новый участник запускает проект без обращения к истории чата; команда понимает, что реально проверено.

### Промпт A5

```text
Выполни A5 — выпуск MVP RepoDoctor. Новые функции больше не добавляй.

1. Собери handoffs четырёх агентов. Для F01–F11 укажи implemented/tested/not tested/
   blocked и evidence команды или проверки. Не заменяй тесты описанием намерений.
2. Проверь весь путь из чистого checkout: frozen installs, API, UI, analyze,
   evidence, diagnosis, export. Используй выбранный target и demo repo/ref.
3. Проверь absence secrets в tracked files/frontend bundle/application logs
   без вывода самих значений. Убедись, что use_ai=false исключает provider calls.
4. Проверь контрактную целостность: examples, OpenAPI, generated TS и backend
   одной версии. Удали случайные debug stubs из production wiring.
5. Обнови README как руководство пользователя: требования, exact commands,
   env setup, fixture/live distinction, ограничения, troubleshooting, demo link.
   Сохрани ссылки на архитектуру и агентские руководства.
6. Пройди G3 checklist. Если live AI или container не проверены, перечисли это
   явно и не объявляй соответствующий gate выполненным. Demo может иметь
   ограниченный статус при работающем offline пути.
7. Зафиксируй итоговый commit и передай краткий release report: что работает,
   как запустить, какие проверки прошли, оставшиеся риски/ограничения.

Выход: рабочий интегрированный MVP или точное объяснение оставшихся блокеров,
но никогда заявление о готовности только на основании написанных файлов.
```
