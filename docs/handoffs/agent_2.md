# Handoff — агент 2 (Repository)

## B1 — URL policy, synthetic repositories, fixture source

```text
Задача: B1
Статус: done
Базовый контракт: schema_version 1.0; G0 c1b9c8a (tag g0), origin/main.
Ветка: agent-2-b1-fixture-source
Файлы:
  backend/src/repodoctor/repository/{url,source}.py
  backend/tests/repository/{conftest,test_url,test_fixture_source}.py
  fixtures/repositories/{README.md,index.json,*/snapshot.json}
  docs/handoffs/agent_2.md
Реализовано:
  Строгая HTTPS/github.com owner/repo policy; canonical case; .git/trailing slash.
  Отказ userinfo/ports/query/fragment/extra segments/escapes/control/dot paths.
  Ref отдельно: blank → null, до 200 символов, slash-ветки разрешены;
  encode_ref_segment кодирует один API path segment, включая dot-only сегменты.
  FixtureRepositorySource по общему RepositorySource Protocol.
  6 snapshots с текстами, деревом, byte counts, synthetic SHA и explicit index.
  Unknown repo/ref → доменные ошибки; нет default demo или live HTTP/DNS.
  Новый snapshot на каждый fetch; отдельно передаваемая общая redaction.
  Все fixtures заранее очищены, env template только placeholder.
Проверки (Windows, Python 3.12.3):
  uv sync --frozen → OK, lock/dependencies не изменены.
  uv run ruff check . → All checks passed.
  uv run ruff format --check . → OK.
  uv run pytest tests/repository -q → 102 passed.
  uv run pytest -q → 163 passed (61 baseline + 102 B1).
  Smoke FixtureRepositorySource.fetch → fixture python-cli-demo 5.
Не проверено / вне B1:
  live GitHub/OpenAI, scanner B3, risk rules B4, HTTP wiring A3, Linux/macOS.
Изменения общих контрактов/зависимостей: нет.
Разблокирует: B2, B3; C1/A3 и UI могут брать настоящие synthetic snapshots.
Блокер: нет. A2 sanitizer подключается callback; пока используем очищенную библиотеку.
Следующая задача роли: B2 (GitHubRepositorySource), в этот PR не входит.
```

### Интеграция для агента 1

```python
from repodoctor.repository.source import FixtureRepositorySource

source = FixtureRepositorySource(settings.fixtures_dir)
# После A2: source = FixtureRepositorySource(settings.fixtures_dir, redactor=redact_text)
```

Публичный DTO не менялся: `await source.fetch(AnalysisRequest)` возвращает `RepositorySnapshot`. `fixtures_dir` — корневой `<project>/fixtures`, не дочерний `repositories`. Constructor также работает без аргументов, вычисляя корень независимо от cwd. Подключение в `create_app` остаётся задачей A3.

`FixtureLibraryError` наследует общий `RepoDoctorError` с `INTERNAL_ERROR`; отсутствующий/сломанный локальный файл не маскируется как неизвестный пользовательский repo. Тексты ошибок безопасны, содержимое файлов не выдаётся.

### Входы для агентов 3 и 4

| URL suffix после `https://github.com/repodoctor-fixtures/` | Сценарий |
|---|---|
| `python-cli-demo` | Python requirements, .env.example, внешний CSV, module entrypoint |
| `node-api-demo` | npm scripts/engines, lock, server entrypoint |
| `ml-experiments-demo` | Backend Python + frontend Node, выбор подпроекта |
| `malformed-manifest-demo` | Ошибки JSON/TOML |
| `unknown-stack-demo` | Нет README/manifests/runtime/entrypoint |
| `partial-tree-demo` | Truncated tree, data/GPU hints, отсутствие не доказано |

Разрешённые refs: `null`, `main`, полный SHA snapshot; у Python также `feature/offline-demo`. SHA и coverage относятся к новым файлам fixtures, а не копии API examples G0. Для evidence будущий scanner обязан оставлять `url=null` в fixture mode.

Полное описание, Python-пример и PowerShell smoke: [fixtures README](../../fixtures/repositories/README.md). Ожидаемые факты/находки для будущих scanners находятся в `index.json → repositories[].expected`; это сценарии приёмки, не уже вычисленные результаты B3/B4.
