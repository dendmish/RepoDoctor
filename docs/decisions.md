# Решения и изменения контракта

Журнал ведёт агент 1. Любое изменение общих DTO, Protocol, examples, OpenAPI или зависимостей сначала записывается сюда (ROADMAP.md, раздел 2, правило 7).

## D-001. Baseline контракта 1.0 (A1, 25.10.2026)

`schema_version = "1.0"`. Источник истины в коде:

- `backend/src/repodoctor/contracts/api.py`: публичные DTO и перечисления;
- `backend/src/repodoctor/contracts/domain.py`: внутренние DTO и доменные ошибки;
- `backend/src/repodoctor/contracts/ports.py`: Protocol-интерфейсы;
- `contracts/examples/*.json`: нормативные примеры;
- `contracts/openapi.json`: генерируется командой `uv run python -m repodoctor.export_openapi ../contracts/openapi.json`, вручную не редактировать.

## D-002. Зафиксированные версии backend

Python 3.12 (`backend/.python-version`). Точные версии в `backend/pyproject.toml` и `backend/uv.lock`:

| Пакет | Версия |
|---|---|
| fastapi | 0.162.0 |
| uvicorn | 0.54.0 |
| pydantic | 2.14.1 |
| pydantic-settings | 2.16.1 |
| httpx | 0.28.1 |
| openai | 3.37.0 |
| packaging | 26.3 |
| pytest (dev) | 9.1.1 |
| pytest-asyncio (dev) | 1.4.0 |
| ruff (dev) | 0.17.2 |
| editables (dev) | 0.6 |
| hatchling (build) | >=1.27,<2 |

Проверено: `uv sync --frozen` и импорт всех пакетов на CPython 3.12.3 (Windows). Новые зависимости добавляет только агент 1 по запросу через handoff.

## D-003. Editable-установка при не-ASCII пути

Путь проекта содержит кириллицу. Python 3.12 на Windows читает `.pth` в кодировке локали (cp1251), поэтому обычная editable-установка теряет путь к `src`. Решение: `dev-mode-exact = true` в hatchling и dev-зависимость `editables`: `.pth` содержит только ASCII-импорт. В Docker (A4) ставить пакет без editable-режима.

## D-004. Коды ошибок для неизвестного маршрута и метода

Добавлены `NOT_FOUND` (404) и `METHOD_NOT_ALLOWED` (405). Причина: архитектура требует JSON 404 в общем envelope для неизвестного `/api/...`, но в таблице кодов нет подходящего. Остальные коды и HTTP-статусы соответствуют таблице раздела 5. Таблица соответствия: `api/errors.py::STATUS_BY_CODE`.

## D-005. Именованные перечисления для inline-литералов

Наборы значений, которые в архитектуре записаны прямо в полях, оформлены как enum (в OpenAPI это именованные схемы):

- `Ecosystem` (`python|node`) для `Dependency.ecosystem` и `RuntimeHint.runtime`;
- `DependencyKind`, `PackageManager`, `EntryPointKind`;
- `RepositoryMode` (`live|fixture`) для `HealthResponse`;
- `ErrorCode`.

Значения не изменились.

## D-006. Инварианты, проверяемые самими DTO

Модель отклоняет нарушения сразу, ещё до сериализации ответа:

- `TargetEnvironment`: только windows/powershell, linux/bash, macos/zsh.
- `Evidence`:
  - `file`: обязательны path и строки;
  - `tree`: обязательен path, строки null;
  - `log`: path и url null, строки обязательны, ID начинается с `log_`;
  - префикс `log_` зарезервирован за log-evidence;
  - `line_end >= line_start`;
  - excerpt не длиннее 500 символов;
  - url только `https://github.com/`.
- Пути repo-relative POSIX: без начального `/`, без `..` и обратных слэшей, корень обозначается `.`.
- `Command.cwd` принимает только `.`, `<repo>` или `<repo>/<subdir>`.
- `AnalysisResponse`:
  - каждый `evidence_ids` есть в `evidence`, ID уникальны;
  - log-evidence не допускается;
  - `command.shell == target.shell`;
  - `expires_at > created_at`.
- `DiagnosisResponse`: целостность ссылок; без causes обязательны questions.
- `RunPlan`: `needs_input` требует хотя бы один вопрос.
- Лимиты:
  - шагов в плане не больше 12;
  - команд в шаге не больше 4;
  - причин в диагностике не больше 5;
  - fixes в причине не больше 12.
- `AnalysisRequest.ref`: пустая строка превращается в null, управляющие символы запрещены. `DiagnosisRequest`: лог 1–30 000 символов и не только пробелы; пустая команда превращается в null.
- ID: канонический UUID4. Время: UTC ISO 8601 с `Z`. Для генерации используйте `format_utc()`.

## D-007. Дополнительные настройки

К полям раздела 12 добавлены:

- `DIAGNOSIS_TIMEOUT_SECONDS=45` (deadline из раздела 10);
- `FIXTURES_DIR` (по умолчанию `<root>/fixtures`, нужен для контейнера в A4);
- `USE_DEV_STUBS=false`.

Секреты хранятся как `SecretStr`. Пустые значения превращаются в null. `ai_configured = OPENAI_API_KEY и OPENAI_MODEL заданы`.

## D-008. Dev-заглушки и состояние «не подключено»

- `services/stubs.py` воспроизводит `contracts/examples`. Работает только при `USE_DEV_STUBS=true`; в production запрещено валидатором Settings.
- Принимает только синтетические URL примеров, остальные получают `REPOSITORY_NOT_FOUND`.
- Каждый ответ начинается с предупреждения `DEV STUB`.
- Без заглушек и без подключённых сервисов анализ и диагностика отвечают `500 INTERNAL_ERROR` («конвейер не подключён»). Валидация входа при этом работает.

## D-009. Точки внедрения

```python
create_app(settings=None, *, source=None, analyzer=None, intelligence=None, store=None,
           analysis_service=None, diagnosis_service=None)
```

- Порты сохраняются в `app.state.ports`.
- Сервисы удовлетворяют `api/dependencies.py::AnalysisHandler` (`analyze(request)`) и `DiagnosisHandler` (`diagnose(analysis_id, request)`).
- В A2 сервисы собираются из портов; подключение реализаций делается только в `main.py`.

## D-010. Доменные ошибки

Модули агентов 2 и 3 бросают подклассы `RepoDoctorError` из `contracts/domain.py`: `RepositoryNotFoundError`, `RefNotFoundError`, `GitHubRateLimitedError(retry_after_seconds=...)`, `GitHubUnavailableError` и другие. HTTP-статус, `retryable` и заголовок `Retry-After` выставляет `api/errors.py`. `message` и `details` должны быть безопасны для показа пользователю.

## D-011. Синтетический владелец примеров

Примеры используют несуществующего владельца `https://github.com/repodoctor-fixtures/...`:

- `python-cli-demo`
- `node-api-demo`
- `ml-experiments-demo`

Рекомендация агенту 2: использовать те же URL в fixture index, чтобы fixture-ответы и examples совпадали по смыслу.
