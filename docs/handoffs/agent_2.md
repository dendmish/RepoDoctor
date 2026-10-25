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

## B2–B4 — завершены 25.10.2026

```text
Задачи: B2 GitHub source; B3 parsers/evidence; B4 risks/budgets/degradation.
Статус: done для всех трёх задач.
База: main 6446a72, G0/контракты 1.0; D1 подтянута во время реализации.
Файлы:
  repository/{github,selection,text}.py, source.py (factory)
  scanners/{analyzer,common,evidence,python,node,readme,risks}.py
  tests/repository/{test_github,test_scanners}.py, conftest.py (MockTransport guard)
  fixtures/repositories/export_scans.py, */scan.json, README.md
  docs/handoffs/agent_2.md, ROADMAP.md
Изменения общих contracts/OpenAPI/зависимостей/lock-файлов: нет.
Проверки: Windows, CPython 3.12.3, существующий frozen venv.
  python -m pytest -q → 345 passed.
  ruff check backend + exporters → All checks passed.
  ruff format --check backend + exporters → OK.
  export_scans.py → 6 актуальных StaticAnalysis JSON без сети/AI.
  git diff --check → OK.
Разблокирует: репозиторный вход для A3; агенту 3 доступны реальные facts/evidence.
Следующая задача роли: B5 после G2, не закрыта этим smoke.
```

### B2: загрузка и лимиты

- `GitHubRepositorySource(client, token=None, api_version=..., limits=...)` реализует общий `RepositorySource`. Клиент принадлежит composition root, source не закрывает его.
- Последовательность: public metadata → encoded ref commit → commit.tree SHA → recursive tree → отобранные blob SHA. Проверяются canonical identity, decoded SHA/size, UTF-8 и NUL; все HTTP GET идут на фиксированный host без redirects.
- Лимиты по архитектуре: 512 KiB JSON / 8 MiB tree; 20 000 entries, 20 файлов, 64 KiB/file, 256 KiB total; 3 subroots; 28 HTTP calls с retries; 4 blob requests одновременно; 35 s общий deadline.
- GET retry только один при transient transport/502/503/504; на rate limit не ждём и не повторяем. 403 forbidden отличается от rate limit, Retry-After/reset переносится в доменную ошибку. 404 repo/ref, private и empty различаются.
- Byte limit работает на streamed body до JSON decode, включая chunked без Content-Length. Превышение tree лимита даёт metadata-only partial snapshot. Недоступные/невалидные blobs пропускаются с причиной, manifest scan может продолжиться.
- Выбор файлов детерминированный, в два прохода, byte budget применяется в порядке приоритета, независимо от порядка завершения запросов. Lock содержимое не скачивается; markers остаются в tree. Symlink/submodule/real .env/ключи/бинарные данные/LFS не загружаются далее.
- Общая redaction A2 применяется к текстам, все значения `.env.example` скрываются отдельно по продуктовому правилу. Секретные значения и upstream body не логируются.

### B3: scanner и evidence

- `RepositoryAnalyzer().analyze(snapshot)` — чистая детерминированная функция без сети/исполнения кода; исходный snapshot не мутирует.
- Requirements через `packaging.Requirement`, includes только в уже прочитанные файлы с visited-set. Constraint/options/editable/URL/path спецификации отмечаются; constraint files не становятся runtime dependencies.
- TOML через `tomllib`: project dependencies/optional/runtime/scripts; ограниченные Poetry string dependencies/runtime; setup.py и сложные metadata не исполняются, unsupported явно обозначается.
- Node JSON: runtime/dev/optional dependencies, raw semver, engines, packageManager, start/dev scripts. Разделены project roots; явный неподдерживаемый manager не подменяется npm.
- README fenced commands дают только кандидаты; Python file/module должен существовать в tree. Env names, data/GPU hints имеют источники; torch сам по себе не доказывает необходимость GPU.
- Evidence ID стабилен по source/path/lines, excerpt очищен и ≤500 chars. Live URL содержит commit SHA и encoded path; fixture URL=null. Все ссылки проверяются через общий `check_evidence_registry`.
- Для всех шести B1 fixtures сохранены актуальные `scan.json`, их соответствие реализации проверяется тестами. Примеры передаются агентам 1/3/4 как внутренний `StaticAnalysis`, не как API report.

### B4: интерпретация и деградация

Реализованы все 10 rule IDs архитектуры: README_MISSING, MANIFEST_PARSE_FAILED, RUNTIME_UNSPECIFIED, MULTIPLE_PACKAGE_MANAGERS, ENTRYPOINT_UNCLEAR, ENV_CONFIGURATION_REQUIRED, EXTERNAL_DATA_REFERENCED, GPU_REQUIREMENT_UNCLEAR, UNSUPPORTED_DEPENDENCY_SPEC, PARTIAL_COVERAGE.

Risk IDs стабильны, origin=static, severity/confidence и suggested action явно заданы. При partial tree нет утверждения об отсутствии README/данных. Data/GPU hints требуют уточнения, не объявляют запуск невозможным. Конфликт managers проверяется внутри root/ecosystem, явный manifest и однозначный README workflow имеют приоритет над неоднозначными lock hints.

Проверки включают все шесть настоящих fixture → scanner → fallback C1 цепочек. `needs_input` остаётся допустимым результатом: несколько entrypoints, ограничения runtime и неполный workflow не заменяются уверенной придуманной командой. Нет unit-теста, выдающего текст рекомендованной команды за фактически выполненный запуск.

### Подключение для агента 1 / A3

```python
from repodoctor.repository.source import create_repository_source
from repodoctor.scanners.analyzer import RepositoryAnalyzer

source = create_repository_source(settings, shared_github_client)
analyzer = RepositoryAnalyzer()
# source/scanner передаются через существующие DI-порты create_app.
```

Fixture mode не требует HTTP-клиента; live mode требует shared client платформы. Constructor не выполняет live-запросов. Не изменены `main.py`, routes, public/internal DTO, provider C1 или frontend. Их полноценное wiring/интеграция остаётся A3 после C4.

### Реальный read-only smoke (дополнительно к offline tests)

25.10.2026, без GitHub token/AI, напрямую через source → scanner:

| Репозиторий | SHA | Результат |
|---|---|---|
| `dendmish/RepoDoctor` | `6446a72d61b3668e0dd4b3a3dc4bc7e38df29e23` | github, mixed Python+Node, 9 файлов, complete ограниченная выборка, 45 evidence |
| `expressjs/express` | `1c6f1b0fe4000977b9a7b4f34097e4d527dd9824` | github, node, 20 файлов, partial (лимиты monorepo/выборки), 66 evidence |

Это подтверждает live-доступ источника и разбор реальных manifests, но не G2/B5: собранный API/UI ещё не проверен, AI не вызывался, чужой код и рекомендованные команды не запускались.

Не проверено: Linux/macOS runtime, Docker, live AI, полный HTTP/browser E2E. Ограничения: нет dependency resolver/registry audit; сложные Python metadata, Poetry tables/groups, YAML, произвольные README-команды и большие monorepos анализируются частично. Для неизвестных или неоднозначных entrypoints возвращаются вопросы.
