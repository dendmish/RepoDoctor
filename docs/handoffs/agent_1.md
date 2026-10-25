# Handoff — агент 1 (Platform / Integration)

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
