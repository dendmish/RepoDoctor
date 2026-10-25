# C1–C3 — примеры результатов IntelligenceService

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

## C2/C3

| Файл | Сценарий |
|---|---|
| `plan_ai_synthetic.json` | `PlanResult`, валидированный synthetic model output, bash |
| `diagnosis_rules_module.json` | `DiagnosisResult`, ModuleNotFoundError, PowerShell, локальные правила |
| `diagnosis_unknown.json` | Неизвестный лог: вопросы вместо выдуманной причины |
| `diagnosis_ai_synthetic.json` | Валидированный synthetic AI diagnosis; origin=ai |
| `diagnosis_ai_timeout.json` | Ошибка provider: fallback, reason=timeout |

```powershell
backend/.venv/Scripts/python.exe fixtures/intelligence/export_c2_c3_examples.py
```

AI-примеры созданы **явно внедрённым ExampleProvider**, без сети. Название модели
`synthetic-example-model` не означает доступную OpenAI-модель. Поле mode=ai проверяет
валидированный путь orchestration, а предупреждение явно отмечает synthetic output.
Ни один пример не является live acceptance. Это внутренние результаты; ID/время HTTP-ответа
добавляет платформа. Сырой лог не включён, log_ evidence содержит обработанные фрагменты.

Production использует `IntelligenceServiceImpl(OpenAIProvider(settings))` при A3 wiring.
Без provider/credentials или при use_ai=false работает fallback. При сбое provider
возвращаются локальные правила, ExampleProvider/FakeProvider автоматически не выбираются.
