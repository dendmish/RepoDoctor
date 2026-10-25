# Синтетическая библиотека репозиториев — B1

Все данные придуманы для RepoDoctor. URL `https://github.com/repodoctor-fixtures/...` — локальные идентификаторы, а не подтверждение существования проектов на GitHub. Загрузчик не обращается к сети и не запускает исходный код.

`index.json` — явный список разрешённых URL, путей к snapshots, refs и ожидаемых фактов для последующих B3/B4/C1. Каждый `snapshot.json` соответствует **общему** `RepositorySnapshot` из G0. Короткие исходные файлы сохранены в поле `files[].content`: это анализируемый текст с настоящими переводами строк, а не заранее подготовленный API-отчёт. Дерево содержит файлы и каталоги, `coverage` показывает реальный объём сохранённых текстов.

## Доступные сценарии

| Идентификатор / URL suffix | Назначение | Ожидаемые сигналы для будущего scanner |
|---|---|---|
| `python-cli-demo` | Python CLI, requirements, версия 3.12, env template, внешний CSV | `requests`, `python-dotenv`, `rich`; `DEMO_API_TOKEN`; `data/input.csv` указан, но не включён |
| `node-api-demo` | npm API, engines, scripts и небольшой согласованный package-lock | Node `>=22.12.0`, `npm ci`, `npm run start`; исходник entrypoint присутствует |
| `ml-experiments-demo` | Monorepo: Python/backend и Node/frontend | Два отдельных roots и managers; нужно выбрать подпроект |
| `malformed-manifest-demo` | Намеренно некорректные JSON и TOML | Ошибка разбора manifests при читаемом README; нельзя выдумать entrypoint |
| `unknown-stack-demo` | Только notes и LICENSE | Нет README, manifests, подтверждённого runtime/entrypoint |
| `partial-tree-demo` | Неполное дерево исследовательского проекта | External data/checkpoint, CUDA hint; отсутствие ресурса в целом repo **не доказано** |

Полный URL получается добавлением suffix к `https://github.com/repodoctor-fixtures/`. Первые три идентификатора сохраняют совместимость по назначению с примерами G0; loader не воспроизводит их AnalysisResponse, SHA и фактические coverage могут отличаться.

## Refs и SHA

- Для всех snapshots разрешены `null`, `main` и полный `repository.resolved_commit`.
- Для `python-cli-demo` дополнительно разрешён `feature/offline-demo`. Это alias того же синтетического commit, не другой снимок.
- Неизвестный repo → `RepositoryNotFoundError`; неизвестный ref → `RefNotFoundError`. Никакого fallback к случайному demo.
- Blob SHA соответствует Git SHA-1 от `blob <byte_length>\0<UTF-8 content>`. Directory и commit SHA — детерминированные **синтетические** идентификаторы; они не представлены как существующие объекты GitHub.
- Порядок tree/files и содержимое стабильны. Каждый fetch возвращает новую модель; мутации вызывающего кода не затрагивают следующие вызовы.

## Использование из Python

Из `backend` после `uv sync --frozen`:

```python
import asyncio

from repodoctor.config import Settings
from repodoctor.contracts.api import AnalysisRequest
from repodoctor.repository.source import FixtureRepositorySource

settings = Settings(_env_file=None)
source = FixtureRepositorySource(settings.fixtures_dir)
request = AnalysisRequest.model_validate({
    "repo_url": "https://github.com/repodoctor-fixtures/python-cli-demo",
    "ref": "feature/offline-demo",
    "target": {"os": "windows", "shell": "powershell"},
    "use_ai": False,
})
snapshot = asyncio.run(source.fetch(request))
print(snapshot.repository.resolved_commit)
print([file.path for file in snapshot.files])
```

Для быстрого smoke из PowerShell, находясь в `backend`:

```powershell
@'
import asyncio
from repodoctor.contracts.api import AnalysisRequest
from repodoctor.repository.source import FixtureRepositorySource
request = AnalysisRequest.model_validate({"repo_url": "https://github.com/repodoctor-fixtures/python-cli-demo", "target": {"os": "windows", "shell": "powershell"}, "use_ai": False})
snapshot = asyncio.run(FixtureRepositorySource().fetch(request))
print(snapshot.source_mode, snapshot.repository.name, snapshot.coverage.files_read)
'@ | uv run python -
```

Ожидается `fixture python-cli-demo 5`. Это проверка источника, ещё не полного конвейера/HTTP-анализа; wiring принадлежит A3.

## Redaction и интеграция

В G0 общего `security.redaction` ещё нет. Все включённые snippets уже очищены; `.env.example` содержит только `[REDACTED]`. Без общей redaction разрешены только заранее очищенные локальные данные. Добавляя fixtures, сначала вручную удалить секреты из **всех** текстов; источник не является универсальным автоматическим scrubber. Значение env template, отличное от пустого/`[REDACTED]`, вызывает ошибку библиотеки.

Когда A2 добавит общую функцию, composition root передаёт её без изменения портов:

```python
from repodoctor.security.redaction import redact_text

source = FixtureRepositorySource(settings.fixtures_dir, redactor=redact_text)
```

Callback имеет сигнатуру `(str) -> tuple[str, int]`. Вызов применяется к каждому тексту; нельзя менять переводы строк, иначе source возвращает `FixtureLibraryError`. `size_bytes` и SHA по контракту описывают исходный текст до дополнительной маскировки. Собственный второй masker не реализован.

`RepositorySnapshot` ещё не содержит evidence. Будущий B3 создаёт его из строк `TextFile` и дерева; в `source_mode=fixture` поля evidence URL должны быть `null`, без фиктивных GitHub-ссылок.

## Граница B1 и продолжение B2–B4

В B1 реализованы URL/ref helpers и fixture source. В B2–B4 добавлены GitHub source, scanner и risk rules; общий контракт G0, OpenAPI, зависимости и lock-файлы не менялись. AI и подключение полного HTTP-конвейера остаются задачами других ролей. Поле `expected` в index описывает контрольные ожидания; scanner tests проверяют их на всех шести снимках.

Проверки из `backend`:

```powershell
uv run pytest tests/repository -q
uv run ruff check src/repodoctor/repository tests/repository
uv run ruff format --check src/repodoctor/repository tests/repository
```

## Source/scanner после B2–B4

```python
from repodoctor.repository.source import create_repository_source
from repodoctor.scanners.analyzer import RepositoryAnalyzer

# Для fixture client не нужен. Для live передать shared httpx.AsyncClient платформы.
source = create_repository_source(settings, client=None)
scan = RepositoryAnalyzer().analyze(await source.fetch(request))
```

`create_repository_source` выбирает строго заданный `settings.repository_mode`: ошибка live не переключает приложение на fixtures. Клиент и его закрытие принадлежат платформе; source использует только `https://api.github.com`, не следует redirect/download_url и читает blobs по SHA фиксированного commit.

`RepositoryLimits` в `repository/selection.py` содержит нормативные budgets. Избыточный tree, пропущенный blob, malformed manifest или неполные данные отражаются в `coverage`/findings; scanner не делает отрицательных выводов о наличии файлов при partial coverage. Python resolver, npm semver resolver, скачивание датасетов и запуск чужого кода отсутствуют.

Каждая папка fixture теперь содержит `scan.json` — настоящий `StaticAnalysis` с facts, findings, evidence и очищенными selected_files. Это внутренний DTO для агентов 1/3/4, не готовый HTTP-ответ и не live-анализ GitHub. Во всех этих примерах `source_mode=fixture`, evidence URL равны `null`.

Перегенерация из `backend`:

```powershell
uv run python ../fixtures/repositories/export_scans.py
```

Тест `test_exported_static_examples_are_current` проверяет, что эти шесть файлов соответствуют scanner, а не устаревшим сохранённым результатам. Номера строк относятся к очищенному тексту; blob SHA и `size_bytes` — к содержимому до дополнительной redaction.

Правила выбора manager: явный `packageManager`/tool-section имеет приоритет; однозначный README workflow — следующий; затем lock markers. В разных roots или ecosystems менеджеры не конфликтуют. Несколько разных Node managers в README без явного выбора остаются неоднозначными. Неизвестный явный manager не заменяется npm. Poetry поддержан ограниченно: строковые зависимости/runtime; сложные таблицы/groups обозначаются как unsupported.

Исходники entrypoints берутся только из ограниченной второй выборки путей, упомянутых в README/manifests; Python module/file entrypoints должны присутствовать в наблюдаемом tree. Произвольные команды README не исполняются и не становятся инструкциями самому RepoDoctor.
