# Нормативные примеры контракта 1.0

Все примеры синтетические: владелец `repodoctor-fixtures` не существует на GitHub. Каждый файл проверяется тестом `backend/tests/platform/test_contracts.py` на соответствие своему DTO. Меняет их только агент 1.

| Файл | DTO | Что показывает |
|---|---|---|
| `request_analysis.json` | `AnalysisRequest` | Python-пример, windows/powershell, AI включён |
| `request_analysis_no_ai.json` | `AnalysisRequest` | ref задан, macos/zsh, `use_ai=false` |
| `request_diagnosis.json` | `DiagnosisRequest` | Traceback с `ModuleNotFoundError` |
| `analysis_python.json` | `AnalysisResponse` | Python, полное покрытие, `generation=ai`, план actionable |
| `analysis_node.json` | `AnalysisResponse` | Node/npm, linux/bash, `generation=fallback` (AI не настроен) |
| `analysis_needs_input.json` | `AnalysisResponse` | Неполное покрытие (truncated tree), план `needs_input`, `disabled_by_user` |
| `diagnosis_python.json` | `DiagnosisResponse` | Причина с log- и repo-evidence, исправление по manifest |
| `diagnosis_unknown.json` | `DiagnosisResponse` | Ошибка не распознана: причин нет, только вопросы |
| `error_invalid_input.json` | `ErrorResponse` | 422, неверная пара OS/shell |
| `error_analysis_not_found.json` | `ErrorResponse` | 404, ID устарел или неизвестен |
| `error_rate_limited.json` | `ErrorResponse` | 429, лимит GitHub, `retryable=true` |

`diagnosis_python.json` ссылается на `analysis_python.json`, `diagnosis_unknown.json` — на `analysis_node.json`. Repo-evidence в диагностике повторяет ID и содержимое из анализа.
