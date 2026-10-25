# C4 — review rubric и offline-приёмка, 25.10.2026

Это ручная review-rubric результата по snapshot. Она не доказывает успешный запуск
проекта, защиту от любого prompt injection или качество неизвестной live-модели.
Все логи и model outputs в этой приёмке синтетические, команды не выполнялись.

| Критерий | 0 | 1 | 2 |
|---|---|---|---|
| Groundedness | Выдуманные источники/факты | Часть утверждений не обоснована | Существующие evidence, соответствие manifest/log, допущения явные |
| Применимость shell | Неверные shell/cwd | Применимость части команд требует уточнения | Target shell/cwd соблюдены, команды требуют review |
| Порядок prerequisites | Запуск/исправление до подготовки | Только часть нужной подготовки | Окружение и manifest до запуска; при недостатке фактов корректный вопрос |
| Verification | Проверки нет или заявлено выполненное исправление | Общий вопрос/проверка без конкретного ожидаемого результата | Конкретная проверка версий/пути/вывода, ожидаемое отдельно от выполненного |
| Uncertainty | Уверенная выдумка или ложное «проверено» | Ограничения отражены частично | Честные mode/reason, needs_input/questions, ограничения snapshot/лога |

Пять оценок 0/1/2, максимум 10. Цель ≥8; результат ниже требует исправления и
повторной приёмки. Оценки ниже — review локальных правил и детерминированных
synthetic model outputs, не benchmark OpenAI.

## Результаты

База — шесть `fixtures/repositories/*/scan.json` из B3, bash-план и diagnosis по
выбранному синтетическому логу. Дополнительно automated regression проверяет все
шесть snapshots × PowerShell/bash/zsh, включая production API без ручного DI.

| Snapshot | План: G/S/P/V/U | Diagnosis: G/S/P/V/U | Основание/ограничение |
|---|---|---|---|
| python-cli-demo | 2/2/2/2/2 = 10 | 2/2/2/2/2 = 10 | requirements → environment → install → module; данные требуют уточнения. ModuleNotFoundError → проверка интерпретатора/manifest |
| node-api-demo | 2/2/2/2/2 = 10 | 2/2/2/2/2 = 10 | npm ci по lock; несколько entrypoints и runtime hints требуют уточнения. EBADENGINE сопоставляется с требованиями, без downgrade |
| partial-tree-demo | 2/2/2/2/2 = 10 | 2/2/2/2/2 = 10 | Подготовка с partial coverage, запуск не выдуман. ModuleNotFoundError без подтверждённой зависимости → вопрос о distribution |
| malformed-manifest-demo | 2/2/1/2/2 = 9 | 2/2/2/1/2 = 9 | Только подтверждённые clone/checkout/root и вопрос о workflow; unknown diagnosis запрашивает команду/cwd/traceback |
| ml-experiments-demo | 2/2/1/1/2 = 8 | 2/2/2/1/2 = 9 | Несколько roots: clone/checkout и вопрос о подпроекте, установка/запуск не генерируются; unknown diagnosis |
| unknown-stack-demo | 2/2/1/1/2 = 8 | 2/2/2/1/2 = 9 | Неизвестный workflow: подготовка и вопросы; unknown diagnosis без выдуманной причины |

У node fixture различающиеся ограничения `22.12.0` и `>=22.12.0` консервативно
запрашивают подтверждение совместимой версии. Это лишнее уточнение, а не доказанная
несовместимость. План остаётся needs_input и также требует выбора start/dev.

## Обязательные инварианты

- Ноль ссылок на несуществующий evidence в принятых plan/diagnosis.
- Ноль запрещённых commands; у оставшихся requires_review=true и target shell/cwd.
- Ноль необоснованных утверждений о выполненном запуске/исправлении в выбранных
  ответах. Поле verification описывает ожидаемый результат, а не факт исполнения.
- Static facts/findings/evidence не мутируются при ошибках AI; fallback возвращается
  целиком, без удаления отдельного prerequisite из полуплана.

Подтверждение: `test_adversarial.py`, `test_ai.py`, `test_diagnostics.py`,
`test_integration.py` и `tests/platform/test_wiring.py`. Никаких stochastic assertions
о точной формулировке реальной модели нет.

## Adversarial corpus

`adversarial/README.md`, `log.txt`, `cases.json`, `partial.json.txt`,
`contradictory_facts.json`: README/log injection, invented evidence, curl pipe shell,
wrong shell, bogus app.py, excessive steps, partial/incomplete JSON, empty diagnosis,
противоречивые runtime facts, ложные claims, опасный prose и секрет в model output.

Проверено, что контент остаётся в JSON input, а инструкции передаются отдельно.
Provider не получает секреты Settings в prompt, tools отсутствуют; network/subprocess
выходы, кроме единственного mocked OpenAI request на операцию, заблокированы в тесте.
Это проверка полномочий приложения, не обещание, что модель всегда игнорирует injection.

Content validator распознаёт ограниченные формы claims, runtime/file references и
опасных рекомендаций. Он может отвергнуть допустимую формулировку и не распознаёт
все возможные парафразы. Остальные границы — отсутствие tools/исполнения, фиксированный
endpoint, bounded context/output, список подтверждённых commands и обязательный review.
Live качество/latency и доступность модели остаются задачей C5.
