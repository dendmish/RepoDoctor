# C1 — примеры fallback-планов

Результаты настоящего `IntelligenceServiceImpl.build_plan`, тип `PlanResult`, контракт 1.0.
Входы — синтетические `contracts/examples/analysis_*.json`; `use_ai=false`.
Это артефакты для интеграции агентов 1 и 4, нормативные HTTP-примеры остаются в `contracts/examples`.

| Файл | Вход | Ожидаемый результат |
|---|---|---|
| `plan_node.json` | `analysis_node.json` | `actionable`: npm ci по lock, npm start по scripts; bash |
| `plan_python_needs_input.json` | `analysis_python.json` | `needs_input`: предложена установка requirements, но доступность src-модуля после неё не доказана; PowerShell |
| `plan_unknown.json` | `analysis_needs_input.json` | `needs_input`: conda workflow, версия Python, данные и GPU требуют уточнения; zsh |

`actionable` означает достаточность плана по данным снимка. Команды не исполнялись.
Синтетические GitHub URL и SHA не подтверждают доступность репозитория в сети.
Для всех примеров: `generation.mode=fallback`, `reason=disabled_by_user`, `model=null`.

Перегенерация из корня после `uv sync --frozen` в backend:

```powershell
backend/.venv/Scripts/python.exe fixtures/intelligence/export_c1_examples.py
```

Для C1 live provider не используется даже при явном внедрении: до C2 отсутствует
валидация модельного содержимого. `FakeProvider` расположен исключительно в
`backend/tests/intelligence/fakes.py`; он не подключается при ошибках production.
