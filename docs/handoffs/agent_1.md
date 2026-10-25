# Handoff — агент 1 (Platform / Integration)

## A3 — wiring модулей, выполнено в ветке feat/c4-a3-hardening-wiring, 25.10.2026

Обновление после merge: [PR №9](https://github.com/dendmish/RepoDoctor/pull/9) объединён в `main` (`7add9dd`), A3 выполнен. D2/D3 также объединены через PR №8; упоминания об отсутствующем UI ниже описывают состояние исходной ветки до этого merge. G1 остаётся открытым до общей браузерной проверки без MSW.

База: `d04094c`, контракт 1.0; B4 и C2/C3 в main, C4 завершён в этой же ветке.
Production backend wiring выполнен. **G1 не закрыт:** report/evidence/export D2 и
diagnosis UI D3 отсутствуют, поэтому browser analyze → report → log → diagnosis →
export пока невозможно принять. Владельцы оставшегося UI — агент 4, D2/D3; browser
real-backend acceptance — D4 после G1. A4/C5 и live acceptance не выполнялись.

Изменения: `main.py`, `export_openapi.py`, `tests/platform/{test_app,test_wiring}.py`,
`tests/smoke_offline.py`, `backend/README.md`, комментарий `.env.example`, handoffs/roadmap.
Public DTO, OpenAPI content, generated TS и зависимости не изменены.

- `create_app()` подключает реальный fixture source по умолчанию, RepositoryAnalyzer,
  IntelligenceServiceImpl и общий MemoryAnalysisStore/OperationLimiter. Явные handlers
  и ports имеют приоритет; legacy dev stubs остаются только явной development-опцией,
  запрещены Settings в production и не импортируются стандартным production-путём.
- REPOSITORY_MODE=live создаёт GitHubRepositorySource в lifespan с общим fixed-host
  AsyncClient. На shutdown и при ошибке startup клиент закрывается, state очищается.
  Ошибки GitHub не заменяют источник fixture, даже если URL есть в fixture index.
- OpenAIProvider создаётся только при обоих key/model, сам клиент остаётся ленивым.
  Без конфигурации — fallback, при use_ai=false нет вызовов OpenAI. Секреты только в
  Settings/headers, не prompt/response/health.
- 18 production API комбинаций (шесть fixtures × три shell) проверяют настоящие
  source → scanner → fallback → store → sanitizer → diagnosis. Проверены schema/IDs,
  timestamps, modes, coverage, shell/review, dependency и missing env finding,
  потребность уточнения неизвестного entrypoint и неизменность store после лога.
- Дополнительно: invalid URL/unknown fixture/ref/expired analysis, production без
  import stubs, missing key/model, обе AI HTTP-операции через SDK MockTransport,
  GitHub success/404/500/rate limit на transport mock, shared client/lifecycle и
  приоритет явно внедрённого source. GitHub/AI transport mocks — **не live acceptance**.
- Экспорт OpenAPI отделён от runtime-конвейера: не требует fixtures, клиентов или
  startup, перегенерация дала нулевой diff. Frontend-клиент обновлять не требуется.

Проверки из `backend` (Windows, Python 3.12.15):

```powershell
.venv/Scripts/python.exe -m pytest -q
# 503 passed.
.venv/Scripts/ruff.exe check . ../fixtures/intelligence/export_c1_examples.py ../fixtures/intelligence/export_c2_c3_examples.py ../fixtures/repositories/export_scans.py
# All checks passed!
.venv/Scripts/ruff.exe format --check . ../fixtures/intelligence/export_c1_examples.py ../fixtures/intelligence/export_c2_c3_examples.py ../fixtures/repositories/export_scans.py
# 72 files already formatted.
.venv/Scripts/python.exe -m repodoctor.export_openapi ../contracts/openapi.json
# OK; git diff --exit-code -- ../contracts/openapi.json — no diff.
.venv/Scripts/python.exe tests/smoke_offline.py
# Настоящий uvicorn/localhost: Python analysis 201 → diagnosis 200;
# Node analysis 201 → diagnosis 200; invalid URL 422; expired analysis 404.
# source=fixture, mode=fallback, dev stubs выключены, внешних API-вызовов нет.
```

Smoke-скрипт выбирает свободный localhost-порт, явно очищает credentials child process,
останавливает сервер в finally и не запускает код анализируемого проекта. Обычный
pytest его не собирает; инструкция ручного запуска — [backend/README.md](../../backend/README.md).
HTTP smoke проверяет backend, а не отсутствующий UI. G1 требует завершить D2/D3 и
пройти browser flow с выключенным MSW; G2 требует отдельные live/сборочные проверки.

## A1 — каркас и контрактный baseline

```text
Задача: A1
Статус: done
Базовый контракт: schema_version 1.0, commit 9698dd4 (тег g0 на следующем коммите с этим handoff)
Файлы: backend/pyproject.toml, backend/uv.lock, backend/.python-version,
       backend/src/repodoctor/{__init__,config,main,export_openapi}.py,
       backend/src/repodoctor/contracts/{api,domain,ports}.py,
       backend/src/repodoctor/api/{routes,errors,dependencies}.py,
       backend/src/repodoctor/services/stubs.py,
       backend/tests/platform/*, contracts/examples/*, contracts/openapi.json,
       .env.example, .gitignore, .gitattributes, docs/decisions.md
Реализовано: DTO/enum/Protocol из разделов 5–6; Settings; create_app с точками
       внедрения; health; skeleton-маршруты анализа и диагностики; единый
       ErrorResponse; dev-only stubs; 11 нормативных примеров; экспорт OpenAPI.
Проверки (Windows, CPython 3.12.3, uv 0.12.19):
       uv sync --frozen                → OK, 35 пакетов
       uv run ruff check .             → All checks passed
       uv run ruff format --check .    → 23 files already formatted
       uv run pytest -q                → 61 passed
       uv run python -m repodoctor.export_openapi ../contracts/openapi.json → OK, без сети и ключей
       uvicorn smoke (127.0.0.1)       → health 200; без stubs анализ 500 INTERNAL_ERROR
                                          («не подключён»); с USE_DEV_STUBS=true
                                          анализ 201 → диагностика 200; /api/v1/nope → JSON 404
Не проверено: Linux/macOS; Docker; любые live GitHub/OpenAI вызовы (вне scope A1).
Изменения контракта/зависимостей: baseline; уточнения D-004…D-011 в docs/decisions.md.
Разблокирует: G0 → A2, B1, C1, D1.
Блокер: нет.
Следующая задача: A2 (routes/store/limiter/body limit/redaction).
```

## G0 — контракты заморожены

Чеклист из ROADMAP.md, раздел 5:

- [x] Структура backend и frontend определена, импорт пакета работает.
- [x] Все public/internal DTO и Protocol из архитектуры реализованы.
- [x] API examples: Python analysis, Node analysis, fallback/needs_input, diagnosis, ErrorResponse.
- [x] Каждый example валидируется соответствующим DTO (тест `test_every_example_validates_against_its_dto`).
- [x] OpenAPI экспортируется без ключей и сети; тест проверяет, что закоммиченный файл актуален.
- [x] Backend stub для health/analysis/diagnosis есть, явно dev-only (`USE_DEV_STUBS`, предупреждение `DEV STUB`, `source_mode=fixture`).
- [x] Версии Python-зависимостей зафиксированы (D-002). Frontend lock фиксирует агент 4 в D1.
- [x] Commit ID, команды установки и пути к примерам переданы (этот файл).

**G0 объявлен.** Базовая точка — git-тег `g0`.

### Установка и проверка (из корня репозитория)

Нужны Python 3.12 и [uv](https://docs.astral.sh/uv/).

```powershell
Copy-Item .env.example .env
Set-Location backend
uv sync --frozen
uv run pytest -q
uv run ruff check .
```

Запуск API с dev-заглушками (только для разработки):

```powershell
# в .env: USE_DEV_STUBS=true
uv run uvicorn repodoctor.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Пересборка OpenAPI после изменения контракта (делает только агент 1):

```powershell
uv run python -m repodoctor.export_openapi ../contracts/openapi.json
```

### Что использовать каждому агенту

| Агент | Что брать | Где |
|---|---|---|
| 2 | `AnalysisRequest`, `RepositorySnapshot`, `TreeEntry`, `TextFile`, `StaticAnalysis`, `RepositorySource`, `StaticAnalyzer`, доменные ошибки, `Settings.fixtures_dir`, `SYMLINK_MODE`/`SUBMODULE_MODE` | `contracts/domain.py`, `contracts/ports.py`, `config.py` |
| 3 | `StaticAnalysis`, `PlanResult`, `AnalysisContext`, `SanitizedLog`, `DiagnosisResult`, `IntelligenceService`, лимиты `MAX_PLAN_STEPS`/`MAX_COMMANDS_PER_STEP`/`MAX_DIAGNOSIS_CAUSES`, `Settings.ai_configured`/`openai_*`/`ai_*` | `contracts/api.py`, `contracts/domain.py`, `contracts/ports.py`, `config.py` |
| 4 | `contracts/openapi.json` → `openapi-typescript`; примеры для MSW; stub backend на `127.0.0.1:8000` при `USE_DEV_STUBS=true`; dev CORS для `localhost:5173` | `contracts/`, этот файл |

### Ограничения stubs и skeleton

- Stubs возвращают только примеры для трёх синтетических URL `https://github.com/repodoctor-fixtures/{python-cli-demo,node-api-demo,ml-experiments-demo}`. Окружение из запроса не применяется, вместо этого в `warnings` добавляется предупреждение.
- Хранилище stubs — словарь в памяти без TTL. Настоящий store с TTL/LRU делается в A2.
- Ещё нет: ограничения размера body (413), limiter (429 SERVER_BUSY), deadlines, redaction, общего AsyncClient. Всё это входит в A2.
- Без подключённых сервисов и без stubs анализ и диагностика отвечают 500 INTERNAL_ERROR.
- Особенность окружения: путь проекта содержит кириллицу, поэтому editable-установка работает через `editables` (D-003).

## A2 — API, lifecycle, memory store и ограничения

```text
Задача: A2
Статус: done (ветка agent-1-platform, PR в main)
Базовый контракт: schema_version 1.0, тег g0; контракт и openapi.json не менялись
Файлы: backend/src/repodoctor/services/{analysis,diagnosis,store}.py,
       backend/src/repodoctor/security/{redaction,limits}.py,
       backend/src/repodoctor/observability.py, backend/src/repodoctor/main.py,
       backend/tests/platform/{fakes,test_redaction,test_store_limits,test_services}.py,
       docs/decisions.md (D-012…D-015)
Реализовано:
  - AnalysisService: слот → fetch → scan (to_thread) → build_plan → сборка ответа
    (UUID4, UTC, schema 1.0, dedupe evidence/findings) → store.put; deadline 85 s → 504.
  - DiagnosisService: store.get (404 ANALYSIS_NOT_FOUND) → sanitize_log + redact command →
    intelligence.diagnose; deadline 45 s → 504; сырой лог не сохраняется и не логируется.
  - MemoryAnalysisStore: OrderedDict, TTL 1800 s по monotonic, LRU, 30 записей,
    512 KiB на контекст, purge при put/get; внедряемые clock/id factories.
  - OperationLimiter: 2 слота на анализ и диагностику, fail-fast 429 SERVER_BUSY,
    освобождение в finally (ошибка, таймаут, отмена).
  - BodyLimitMiddleware: 128 KiB, включая chunked; дочитывание до 1 MiB для честного 413.
  - redact_text / sanitize_log: auth headers, bearer, GitHub/OpenAI/AWS/Slack/Google/JWT
    токены, credential URL, private key blocks, NAME_SECRET=value; число строк сохраняется.
  - RequestContextMiddleware: request_id, X-Request-ID, структурный лог запроса.
  - Lifespan: общий httpx.AsyncClient для GitHub; CORS только в development.
Проверки (Windows, CPython 3.12.3):
  uv run ruff check .          → All checks passed
  uv run ruff format --check . → OK
  uv run pytest -q             → 116 passed (3 прогона подряд, стабильно)
  export_openapi               → без diff (контракт не менялся)
  uvicorn smoke                → health 200 + X-Request-ID; 200 KB body → 413 JSON;
                                 битый JSON → 422; лог содержит только id/method/path/status/ms
Не проверено: Linux/macOS; настоящие модули агентов 2/3 (будут подключены в A3).
Изменения контракта/зависимостей: нет.
Разблокирует: A3 (после B4 и C4).
Блокер: нет.
Следующая задача: A3 — подключение модулей и G1.
```

### Для агентов 2 и 3

- **Redaction:** `from repodoctor.security.redaction import redact_text, sanitize_log`.
  - `redact_text(text) -> (masked, count)` — чистая функция, число строк сохраняется. Агент 2 применяет её к содержимому `TextFile` до передачи дальше.
  - Агент 3 получает лог уже очищенным (`SanitizedLog`) и сам sanitizer не дублирует.
- **Подключение:** `create_app(settings, source=..., analyzer=..., intelligence=...)` — больше ничего не нужно, store и limiter создаются автоматически. Общий GitHub-клиент доступен как `app.state.github_client` после старта lifespan.
- **Исключения:** модули бросают доменные ошибки (`contracts/domain.py`). Любое другое исключение превращается в 500 INTERNAL_ERROR без деталей.
- **Тесты:** тестовые двойники лежат в `backend/tests/platform/fakes.py`. Их можно взять за образец, но не импортировать из чужих тестовых пакетов.
