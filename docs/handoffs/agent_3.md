# Handoff — агент 3 (AI / Diagnostics)

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
