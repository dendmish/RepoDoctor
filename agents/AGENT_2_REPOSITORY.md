# Агент 2 — GitHub, структура, зависимости и доказательства

Сначала прочитай [архитектуру](../ARCHITECTURE.md) и [roadmap](../ROADMAP.md). Порядок: **B1 → B2 → B3 → B4 → B5**. Результат роли — достоверный `StaticAnalysis` на фиксированном commit, пригодный для AI и UI.

## Владение и границы

Твои каталоги: `backend/src/repodoctor/repository/`, `scanners/`, `backend/tests/repository/`, `fixtures/repositories/`, собственный handoff. Используешь общие DTO/Protocol агента 1 и redaction из `security/`. Python dependency changes запрашиваешь у агента 1. Не создаёшь собственные API endpoint, frontend, AI provider или storage.

Код исследуемого repo никогда не исполняется. Нет clone, git subprocess, pip install, npm install, import setup.py, загрузки по README links, разыменования symlink или рекурсивных submodules. Статическое предположение отделяется от доказанного факта.

## B1. URL policy, fixture source и синтетические репозитории

**До начала:** G0, доступны `AnalysisRequest`, `RepositorySnapshot`, `TextFile`, `TreeEntry`, `RepositorySource`. До G0 можно продумать содержимое fixtures, но не закреплять собственную форму DTO.

**Артефакты:** `url.py`, `source.py` с fixture implementation, fixture index и 5–6 небольших snapshots, unit-tests.

**Приёмка:** одинаковый input даёт один и тот же snapshot, неподдерживаемые адреса отклоняются до сети, synthetic данные помечены.

### Промпт B1

```text
Реализуй B1 RepoDoctor в своей зоне repository/fixtures/tests. Контракты бери
из contracts, не копируй их в свой пакет. Реальную сеть в этой задаче не используй.

1. Сделай normalize_repo_url на urllib.parse: только HTTPS/github.com,
   owner/repo, optional .git и trailing slash. Отклоняй userinfo, query, fragment,
   ports, extra segments, encoded slash/backslash, control characters и dot paths.
   Owner/repo валидируй отдельными allowlist regex; сохрани canonical URL.
2. Ref обрабатывай отдельно: nullable, max 200, без control characters.
   Не запрещай легальный slash в branch: при запросе он кодируется одним segment.
   URL /tree/branch возвращает полезную подсказку использовать поле ref.
3. Определи fixture index с синтетическими URL, например
   https://github.com/repodoctor-fixtures/python-missing-data. Эти адреса —
   локальные identifiers, не утверждение о существовании repo в GitHub.
   Не публикуй фиктивную evidence-ссылку: в fixture mode url=null, UI показывает
   synthetic origin. Metadata URL остаётся идентификатором выбранного fixture.
4. Создай snapshots: Python requirements + пропущенный CSV + .env.example;
   Node package.json + package-lock marker + scripts/engines;
   monorepo с Python/backend и Node/frontend; malformed manifest;
   unknown stack/no README; partial tree с внешним dataset hint.
5. Для каждого snapshot сохрани понятные короткие исходные файлы и metadata,
   deterministic synthetic commit/blob SHAs, line numbering и expected facts.
   Не добавляй реальные ключи, большие данные, бинарники или чужие исходники.
6. FixtureRepositorySource.fetch возвращает общий RepositorySnapshot.
   Отсутствующий fixture URL/ref — доменная ошибка, не случайный default report.
   Все paths repo-relative; mode/type и sizes правдоподобны.
7. Используй общую redaction, если готова A2; пока зависит от согласованной
   функции/DI, не создавай второй несовместимый sanitizer. Значения .env.example
   synthetic, но контракт требует скрывать значения и в fixture mode.
8. Тестируй accepted/rejected URL таблицей, canonicalization, ref slash,
   unknown fixture, одинаковость результатов, отсутствие live HTTP calls.
9. Передай агентам 1/3/4 fixture IDs, команду загрузки и ожидаемые проблемы.
   Запиши handoff B1 и разблокируй их offline работу.

Выход: реалистичный стабильный вход для scanner/AI/UI и строгая URL boundary.
```

## B2. GitHubRepositorySource

**До начала:** B1; доступны httpx и общие domain errors/config. Нужен fake HTTP transport для тестов; live token пока необязателен.

**Артефакты:** `github.py`, `selection.py`, ограничения чтения, сетевые unit-tests.

**Приёмка:** metadata/commit/tree/blobs относятся к одному commit, все сетевые/размерные бюджеты соблюдаются, частичная загрузка отражена в coverage.

### Промпт B2

```text
Реализуй B2 — bounded read-only GitHub source. Следуй разделу 7 ARCHITECTURE.md.
Не делай git clone и не скачивай содержимое с произвольных host.

1. Внедри httpx.AsyncClient с base host api.github.com, timeouts, redirects=false,
   User-Agent и опциональным server token. Никогда не используй repo_url как
   произвольный URL для fetch, не следуй download_url из внешнего ответа.
2. Реализуй последовательность metadata → commit(ref/default branch) → tree SHA
   → recursive tree → selected blob SHAs. У metadata проверь private=false.
   Сохрани canonical owner/name из metadata только после повторной валидации.
3. Раздели not found repo, not found ref, empty repo, rate limit и generic upstream
   failure. Для 403 оцени headers/message, не считай любой 403 rate-limit.
   При redirect верни безопасную подсказку использовать canonical URL.
4. Читай HTTP body потоково с лимитом до JSON decode: tree 8 MiB, прочие 512 KiB.
   Tree ограничь 20000 entries; truncated flag/local limit → partial coverage.
   Если tree не помещается, верни metadata-only snapshot с ясным limitation.
5. Selection: root README/manifests первыми, затем до трёх subroots по depth/path,
   затем runtime/env templates и доказанные entrypoint files. Tie-break path.
   Max 20 files, 64 KiB/file, 256 KiB total. Размер из tree — предварительный,
   после base64 decode проверяй снова. Budget reservation должен быть корректен
   при четырёх одновременных blob-запросах: результат не зависит от порядка arrival.
6. Пропускай symlink/submodule/binary/real .env/secrets/dataset/checkpoint и
   excluded directories. Lock markers используй по tree, не скачивай большой lock.
   UTF-8 decode strict, NUL → skip; malformed base64/encoding → skip + limitation.
7. Суммарно максимум 28 HTTP calls включая retry, 4 blob requests одновременно,
   deadline source 35 секунд. GET retry максимум один при transient errors,
   только если осталось время/бюджет. Не sleep на rate limit.
8. Redact выбранные тексты до передачи snapshot дальше; сохраняй line count.
   Exclude raw response bodies/token from logs. Coverage считает реальные read
   bytes/selected/read files и конкретные причины пропуска.
9. Напиши transport tests: public success, private, 404 ref/repo, empty, 301,
   truncated tree, large/chunked response, oversize decoded blob, invalid base64,
   symlink, 403 forbidden vs rate limit, timeout, retry/call budget, same commit.
10. Передай source factory агенту 1. Live проверку можно сделать дополнительно,
    но успех mock transport не называй реальным доступом к GitHub.

Выход: ограниченный, предсказуемый загрузчик с полезной частичной деградацией.
```

## B3. Парсеры Python/Node/README и evidence registry

**До начала:** B1; нормативные facts/evidence DTO. B2 обычно уже завершён, но парсеры работают только с snapshot, без сети.

**Артефакты:** `python.py`, `node.py`, `readme.py`, `analyzer.py`, тесты извлечения.

**Приёмка:** facts воспроизводимы, каждый важный вывод имеет реальный источник, исполняемые metadata не запускаются.

### Промпт B3

```text
Реализуй B3 — чистый StaticAnalyzer.analyze(snapshot) -> StaticAnalysis.
Только входные тексты/tree, никаких сетевых запросов, subprocess или imports repo.

1. Выдели project roots по manifests, stack python/node/mixed/unknown. Сохраняй
   root в каждом manager/entrypoint/dependency, не смешивай backend/frontend.
2. Создай evidence registry с детерминированными IDs по source/path/line range.
   File evidence относится к реальным строкам redacted file. Tree evidence не
   имеет line numbers. GitHub URLs формируй по commit и encoded path; fixture
   URLs для evidence=null. Excerpt ≤500 символов, без secret values.
3. Requirements разбери построчно packaging.Requirement. Раздели обычные packages,
   comments, options, include -r/-c, URL/editable/path. Include разрешён только
   в уже загруженный text и с visited-set. Не выполняй resolver/network lookup.
4. TOML разбери tomllib: project.dependencies/optional-dependencies/requires-python;
   runtime version files отдельными hints. Poetry поля поддерживай только явным
   кодом, неизвестное отмечай limitation. setup.py не исполняй и не eval.
5. package.json разбери JSON: dependencies/dev/optional, scripts, engines.node,
   packageManager. Lock hints по выбранному root. npm semver оставь raw string.
   Не принимай script body за разрешение серверу исполнить shell.
6. README извлекай ограниченными блоками: headings, fenced commands, setup/data/
   GPU/env упоминания. EntryPoint только по источнику/существующему пути или
   package script. Не делай python main.py только из факта наличия Python.
7. .env.example: извлеки имена env vars, значения не показывай. Data/GPU hints
   снабди evidence. Torch dependency — hint, не доказанное требование видеокарты.
8. Parse errors превращай в MANIFEST_PARSE_FAILED с path/source evidence,
   остальные файлы продолжай. Неподдерживаемые dependency forms явно обозначай.
9. Тестируй Python/Node/mixed/unknown, optional/dev, malformed JSON/TOML,
   recursive includes, npm scripts, path с пробелом, строки после redaction,
   deterministic output и отсутствие invented evidence.
10. Передай агенту 3 пример StaticAnalysis по каждому fixture. Любое недостающее
    поле согласуй с агентом 1, не помещай скрытые extensions в DTO.

Выход: проверяемые факты и источники, на которых можно строить инструкции.
```

## B4. Правила рисков, полнота и окончательная интеграция

**До начала:** B2+B3; есть работающий source и scanner; известно, что означает complete/partial.

**Артефакты:** `risks.py`, полная analyzer assembly, source+scanner regression tests.

**Приёмка:** обязательные rule IDs реализованы, partial coverage не порождает ложные утверждения об отсутствии данных, модуль готов для A3.

### Промпт B4

```text
Реализуй B4 — интерпретацию риска без необоснованных обещаний и финальный hardening.

1. Реализуй десять rule IDs архитектуры. Каждое правило возвращает Finding
   с severity/confidence/origin=static, evidence_ids и конкретным suggested_action.
   Стабильный finding ID выведи из rule/root/path, не используй случайный UUID.
2. README_MISSING допускается, если достоверно осмотрен нужный tree/root;
   при неполноте лучше PARTIAL_COVERAGE. ENTRYPOINT_UNCLEAR не превращай
   автоматически в blocker запуска всех проектов.
3. MULTIPLE_PACKAGE_MANAGERS сравнивает hints внутри одного root. packageManager
   и README могут объяснять выбор; не объединяй pnpm frontend и pip backend в
   ложный конфликт. Зафиксируй правило приоритета и uncertainty.
4. EXTERNAL_DATA_REFERENCED ссылается на README/code строку. Отсутствие path
   в tree означает возможный внешний ресурс, не потерю файла. При truncated
   tree нельзя делать отрицательный факт. ENV rule показывает только имена.
5. RUNTIME_UNSPECIFIED и GPU_REQUIREMENT_UNCLEAR дают вопросы/проверки; не
   добавляй произвольную версию Python/CUDA и не проверяй package age по догадке.
6. Собери StaticAnalysis со facts/findings/evidence/coverage/selected_files.
   Проверь, что все IDs существуют, все excerpts redacted, selections bounded.
   Убери дубликаты hints/findings без потери разных sources.
7. Добавь combined tests source+scanner: partial tree, missing README,
   multiple roots, malformed file среди хороших, отсутствие полезных файлов,
   prompt injection в README трактуется только как текст, никакой сети после fetch.
8. Проверь все лимиты и ошибки B2 повторно только там, где менял код.
   Не заявляй perf гарантии без измерения; запиши fixture durations/counts.
9. Передай агенту 1 B4 handoff: constructor/factory, тестовая команда, known
   limitations, fixture IDs; агенту 3 — финальные facts/evidence examples.

Выход: модуль готов к A3, live и fixture дают одинаковую форму данных.
```

## B5. Live acceptance

**До начала:** G2-сборка доступна; live GitHub доступ проверяем, а не предполагаем. Эта задача уточняет качество на реальных repo, не заменяет unit-tests.

**Артефакты:** acceptance-записи в собственном handoff, воспроизводимые repo/ref и defects владельцам.

**Приёмка:** два реальных repo проверены, каждое существенное утверждение сопоставлено с файлами; ограничения прозрачны.

### Промпт B5

```text
Выполни B5 — проверь живой анализ Python и npm репозитория через собранный API.

1. Выбери небольшие публичные repos с понятными README/manifests. Проверяй
   доступность сейчас; не полагайся на старое имя/branch или synthetic URLs.
2. Зафиксируй owner/repo, ref, resolved commit, дату и target. Прогони анализ
   в REPOSITORY_MODE=live. Не вставляй token в command history/отчёт.
3. Сопоставь metadata/tree/manifest facts с реальными файлами того же commit.
   Проверь минимум 5 evidence references, lines/URLs, manager и entrypoint.
4. Запиши coverage, files_read/selected, limitations. Отдельно оцени, не стала
   частичная выборка причиной неверного вывода о датасете/README/runtime.
5. Если нашли баг — минимальный synthetic regression в своей зоне, исправление,
   локальный тест и повтор только затронутого live сценария при необходимости.
6. Передай агенту 4 один стабильный demo repo/ref и ожидаемые находки. RepoDoctor
   не запускает этот проект; не утверждай, что запуск проверен автоматически.
7. Запиши итог B5: подтверждено, не проверено, ограничения, точные команды.
   Если сеть недоступна, укажи blocked live вместо подмены fixture-результатом.

Выход: подтверждённая работа repository слоя и реалистичный материал для защиты.
```
