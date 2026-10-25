# Handoff — агент 3 (AI / Diagnostics)

## C2/C3 · Волна 2 — выполнено в ветке 25.10.2026

База: `0f1a237` (main с B2–B4), контракт 1.0 без изменений. Обе задачи реализованы
в зоне агента 3; зависимости, composition root, DTO/OpenAPI, routes, scanner и UI
не менялись. Следующий этап агента 3 — **C4**, затем A3 wiring и live acceptance C5.
Ниже C1 сохранён как исторический handoff.

### C2: адаптер, контекст и валидация

- `provider.py`: `OpenAIProvider(settings)` реализует `IntelligenceProvider`
  (`PlanProvider` + `DiagnosisProvider`, `model`). Клиент ленивый и закрывается после
  каждой операции, включая cancellation. Ключ только из Settings; endpoint фиксирован
  `https://api.openai.com/v1`; `OPENAI_BASE_URL` игнорируется. Без credentials или при
  `use_ai=false` клиент не создаётся. Fake/ExampleProvider не выбирается автоматически.
- Фактически проверен SDK **openai 3.37.0**, его сигнатура `AsyncResponses.parse` и
  [официальный Responses Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
  Один `responses.parse(text_format=...)` на операцию; `max_retries=0`, timeout из
  Settings (40 s по умолчанию), внешний `asyncio.timeout`, configurable output tokens,
  `store=false`, без tools и repair loop. Реальные SDK parsing и request schema
  проверены через `httpx.MockTransport`, без запросов OpenAI.
- Отдельные инструкции `prompts/analysis.txt` (`analysis-v1`) и `diagnosis.txt`
  (`diagnosis-v1`); JSON с недоверенными данными передаётся отдельно от instructions.
  Модельные DTO не содержат HTTP metadata, registry/URLs или origin причин/находок.
  Origin, IDs findings/causes и generation выставляет сервер.
- `context.py`: детерминированный repo JSON до 48 000 символов, включая baseline plan.
  Facts вместе с evidence добавляются атомарно, затем findings и redacted excerpts;
  при сокращении есть limitations и warning. Маскирование использует A2 `redact_text`.
- `validation.py`: повторная проверка DTO даже после typed provider, evidence IDs,
  лимиты текста/списков/steps/commands, уникальность step IDs, shell/cwd, источники,
  verification, prerequisites, URL policy и запрещённые команды. Модель не может
  повысить недостаточный baseline до actionable. `requires_review=true` выставляет сервер.
- Консервативная граница C2: команды AI-плана должны **полностью совпадать с командами
  C1 в исходном порядке**, включая cwd/shell и evidence. AI улучшает пояснения,
  вопросы и additional findings; новые произвольные команды не поддержаны. Это
  предотвращает выдуманный entrypoint/runtime и потерю prerequisite; ошибка любой
  существенной части возвращает fallback целиком. Regex policy не является sandbox
  и не доказывает семантическую истинность всех текстовых рекомендаций.
- Refusal, incomplete, отсутствие parsed output, invalid output, 429, network и timeout
  дают безопасные reasons и warnings; upstream body/ключи не возвращаются. Некорректный
  HTTP envelope SDK может классифицировать как provider_unavailable, schema-invalid
  model content — invalid_output. Статические findings не мутируются и сохраняются
  платформой при объединении с additional findings (origin=ai).

### C3: диагностика обработанного лога

- `diagnostics.py`: семь конкретных классов сигнатур + unknown: ModuleNotFoundError,
  FileNotFoundError/ENOENT, явно названная missing env, Python incompatibility,
  Node engine mismatch, занятый порт, CUDA/driver. Одного слова error недостаточно.
- `prepare_log(SanitizedLog)` создаёт `log_N` evidence, path/url=null, excerpt ≤500
  символов. JSON лога ≤16 000 символов. Сохраняются начало, traceback/сигнатуры,
  последние строки; IDs и номера относятся к полному sanitized log. Truncation явный.
- Причины включают manifest/root, repo+log evidence, confidence, fixes и verification.
  Для ModuleNotFoundError сначала проверяется интерпретатор и manifest, distribution
  по import не угадывается. Для файла предлагается проверить cwd и реальные данные;
  для env только имя; runtime сверяется с manifest, конфликт требует вопроса; port
  не приводит к kill, CUDA не приводит к универсальному install.
- Диагностический AI получает bounded repo, plan summary/baseline, обработанные
  command/log и разрешённые диагностические команды. Не больше пяти причин; каждая
  должна ссылаться на log evidence. Invalid IDs/shell/path/commands/пустой ответ
  приводят к локальным причинам или вопросам, mode=fallback.
- Лог/диагностика не записываются в store и не логируются. HTTP DI-тест с настоящими
  A2 services, fixture source B1, scanner B3 и IntelligenceService проверяет redaction
  до анализа, валидный DTO и неизменность сохранённого AnalysisContext.
- Ограничения: сигнатуры намеренно узкие; custom env сообщения могут попасть в unknown.
  Совпадение имени dependency с import не доказывает их тождественность/установку и
  не вызывает pip install import-name. Выбранные excerpts могут не включать весь лог;
  полные пути из traceback остаются в processed evidence, а не становятся shell-командами.

### Проверки и примеры для агентов 1/4

Windows, Python 3.12.15. Из `backend`:

```powershell
.venv/Scripts/python.exe -m pytest -q
# 446 passed (157 intelligence tests; baseline main — 345 tests).
.venv/Scripts/ruff.exe check . ../fixtures/intelligence/export_c1_examples.py ../fixtures/intelligence/export_c2_c3_examples.py ../fixtures/repositories/export_scans.py
# All checks passed!
.venv/Scripts/ruff.exe format --check . ../fixtures/intelligence/export_c1_examples.py ../fixtures/intelligence/export_c2_c3_examples.py ../fixtures/repositories/export_scans.py
# 68 files already formatted.
```

Из корня:

```powershell
backend/.venv/Scripts/python.exe fixtures/intelligence/export_c2_c3_examples.py
# Пять воспроизводимых PlanResult/DiagnosisResult examples; без сети.
git diff --check
# OK.
```

Проверены success/failure реального SDK на mock transport, fixed host/model/timeout/
retries/output budget/schema, отсутствие вызова при disabled/missing credentials,
whole fallback, wrong shell/cwd/evidence/entrypoint, dangerous commands и URL, limits,
cancellation, trimmed traceback и Windows path, known/missing package, env placeholder,
conflicting runtime, 18 комбинаций **шесть scan B3 × три shell** и HTTP redaction/store.

В `fixtures/intelligence`: `plan_ai_synthetic.json`, `diagnosis_rules_module.json`,
`diagnosis_unknown.json`, `diagnosis_ai_synthetic.json`, `diagnosis_ai_timeout.json`.
AI examples явно используют synthetic provider/model и имеют соответствующий warning;
это не live результаты. UI следует показывать generation.mode/reason, warnings,
неопределённость причин и requires_review для команд.

Для A3: внедрять `IntelligenceServiceImpl(OpenAIProvider(settings))`, либо
`IntelligenceServiceImpl()` для полностью локальных правил. Публичные методы и DTO
соответствуют `contracts.ports.IntelligenceService`. Жизненный цикл клиента не требует
изменений app lifespan. При use_ai=false обе операции остаются без AI-сети.

**Live OpenAI не проверен:** `Settings().ai_configured == false`, ключ/модель не заданы.
Не проверялись платные model calls, выполнение команд пользователя или реальные
Linux/macOS shells. C4/C5, production wiring A3 и G1–G3 этим PR не закрываются.

## C1 · Волна 1 — выполнено 25.10.2026

```text
Задача: C1 — fallback-first и fake provider
Статус: done
Базовый контракт: schema_version 1.0, tag g0, commit c1b9c8a
Файлы: backend/src/repodoctor/intelligence/{service,rules,provider}.py,
       backend/tests/intelligence/*, fixtures/intelligence/*,
       docs/handoffs/agent_3.md
Изменения контракта/зависимостей: нет.
Разблокирует: C2, C3; предоставляет fallback-порт для дальнейшей интеграции A3.
Блокер: нет для C1.
Следующая задача: C2 — live adapter, context/prompt, validation и обработка ошибок AI.
```

- [x] `IntelligenceServiceImpl.build_plan(scan, target, use_ai)` возвращает настоящий детерминированный `PlanResult`.
- [x] Windows/PowerShell, Linux/bash, macOS/zsh: соответствующие shell/cwd; Python вызывается из `.venv`, без активации и изменения execution policy.
- [x] Порядок: prerequisites → canonical clone → resolved commit checkout → project root → environment/runtime → install → текстовый env/data/GPU setup → подтверждённая точка входа → verification.
- [x] Python: подтверждённый requirements выбранного root или `pip install .` при прочитанном installable pyproject; Poetry/uv/conda не подменяются на pip.
- [x] npm: `ci` только при lock выбранного root, иначе `install` при подтверждённом npm workflow. Yarn/pnpm и конфликтующие менеджеры требуют уточнения. start/dev берётся из entrypoints со ссылками на package.json; прочитанный scripts дополнительно проверяется.
- [x] Unknown stack/runtime/entrypoint, несколько roots/entrypoints, недоказанная доступность src-модуля дают `needs_input` с полезными подготовительными шагами.
- [x] Шаги имеют evidence или assumptions, verification; команды — shell/cwd и `requires_review=true`. Планировщик ничего не выполняет. Env/data setup не генерирует значения секретов и загрузки по URL из README.
- [x] Приватные `PlanProvider`, `ModelPlanOutput`, `ModelFindingOutput`, безопасный `ProviderError`; детерминированный `FakeProvider` только в tests, с очередью типизированных ответов/ошибок и учётом вызовов.
- [x] Без provider и при `use_ai=false` сетевой клиент не создаётся. Причина отключения пользователем — `disabled_by_user`, `mode=fallback`, `model=null`.
- [x] Существующий evidence registry сохраняется, additional_findings пуст, scan/static findings не мутируются. Платформа должна объединить исходные findings с additional_findings, как предусмотрено контрактом.
- [x] Три сериализованных `PlanResult` для агентов 1/4 в `fixtures/intelligence`, с проверкой DTO, ссылок и режима.

Проверки выполнены на Windows, CPython 3.12.15. Из корня:

```powershell
Set-Location backend
uv sync --frozen
# OK: установлены 35 пакетов из существующего lock, lock/pyproject не изменялись.

.venv/Scripts/python.exe -m pytest -q
# 117 passed in 2.41s: 61 baseline + 56 C1.

.venv/Scripts/ruff.exe check . ../fixtures/intelligence/export_c1_examples.py
# All checks passed!

.venv/Scripts/ruff.exe format --check src/repodoctor/intelligence tests/intelligence ../fixtures/intelligence/export_c1_examples.py
# 11 files already formatted.

.venv/Scripts/python.exe ../fixtures/intelligence/export_c1_examples.py
# Exit 0: три PlanResult JSON обновлены без сети/ключей.

Set-Location ..
git diff --check
# Exit 0.
```

После установки проверки выполнялись напрямую через `.venv`, чтобы не требовать повторного доступа к пользовательскому кэшу uv. Первая sandbox-попытка `uv sync --frozen` не смогла открыть lock кэша; повтор с разрешённым доступом завершился успешно.

Подключение для агента 1:

```python
from repodoctor.intelligence.service import IntelligenceServiceImpl

intelligence = IntelligenceServiceImpl()
# await intelligence.build_plan(scan, target, use_ai=False)
```

Общие DTO, OpenAPI, routes, composition root, зависимости и файлы других агентов не изменялись. В текущий API реализация ещё не подключена: wiring выполняет агент 1 в A3 после C4. Коммит не создавался: commit/lockfile операции в общей папке согласует агент 1.

Примеры для агента 4:

- `fixtures/intelligence/plan_node.json`: bash, `actionable`, npm ci/start.
- `fixtures/intelligence/plan_python_needs_input.json`: PowerShell, подготовка Python; вопрос о доступности src-модуля после установки только requirements.
- `fixtures/intelligence/plan_unknown.json`: zsh, conda workflow, runtime/data/GPU требуют уточнения.

Это внутренние `PlanResult`, а не полные HTTP-ответы. Метаданные анализа добавляет платформа. Во всех примерах `mode=fallback`, `reason=disabled_by_user`, `model=null`, `prompt_version=fallback-v1`. Synthetic URL/SHA явно помечены предупреждением и не выданы за live-репозитории.

Ограничения и не проверенное:

- C1 всегда использует rules. При явно внедрённом provider и `use_ai=true` возвращается `ai_validation_unavailable`, provider не вызывается: C2 ещё должен добавить валидацию модельного содержимого перед его использованием. Fake не подменяет production AI.
- `diagnose` пока явно бросает `NotImplementedError`; правила диагностики относятся к C3. Наличие метода удовлетворяет форме порта, но не означает готовность диагностического пути.
- Поддерживается узкая грамматика Python file/module и npm start/dev; сложные README-команды требуют уточнения. Различающиеся ограничения runtime консервативно требуют подтверждения совместимой версии.
- Установка самого Python-пакета не подразумевается установкой requirements; src-layout требует доказанного packaging workflow.
- Не выполнялись live GitHub/OpenAI, запуск чужих проектов, реальные команды плана на Linux/macOS, HTTP wiring, browser E2E и Docker. Shell-проверки здесь проверяют текст рекомендаций, а не успешность запуска проекта.
- G1/G2/G3 и C2–C5 остаются незакрытыми; C1 сам по себе не означает готовность всего IntelligenceService для A3.
