# Агент 4 — интерфейс, пользовательский путь и демонстрация

Сначала прочитай [архитектуру](../ARCHITECTURE.md) и [roadmap](../ROADMAP.md). Порядок: **D1 → D2 → D3 → D4 → D5**. Твоя задача — сделать результаты backend понятными и провести полный путь пользователя, включая ошибки.

## Владение и ограничения

Весь `frontend/`, `.nvmrc`, `docs/demo.md`, свой handoff. Backend/DTO меняет агент 1, semantic findings — агент 2, AI output — агент 3. Ты сообщаешь дефекты с воспроизведением и не прячешь их UI-заглушками.

React 19 + TypeScript + Vite 7, обычный CSS. Без router, UI framework, axios и лишнего state manager. API типы генерируются из OpenAPI, HTTP — fetch. MSW разрешён только dev/tests; финальный E2E проверяет реальный локальный backend.

## D1. Каркас UI, API types и mock contracts

**До начала:** G0, доступны `contracts/openapi.json` и examples. Реальный backend пока может быть stub.

**Артефакты:** Vite проект, lock, generated types, API client, формы, hooks, MSW, UI tests.

**Приёмка:** форма отправляет правильный request, режимы loading/success/error работают на mocks, production не запускает MSW.

### Промпт D1

```text
Реализуй D1 RepoDoctor в frontend/ и .nvmrc. Не меняй backend DTO и API routes.

1. Создай React+TypeScript+Vite 7 проект с совместимыми конкретными dependency
   versions; Node 22 не ниже 22.12. Зафиксируй .nvmrc, package-lock и engines.
   Установи Vitest/jsdom/Testing Library/MSW/Playwright/openapi-typescript.
   Не используй latest после freeze и не добавляй лишние библиотеки.
2. Настрой scripts dev/build/typecheck/test/test:e2e/generate:api. API types
   генерируй из ../contracts/openapi.json в src/api/generated.ts. В hand-written
   code используй aliases generated types, не независимые ручные DTO.
3. Реализуй fetch client: base /api/v1, JSON headers, response/error parsing,
   AbortController, analysis timeout 100s, diagnosis 60s. Не повторяй POST
   автоматически — это может дублировать внешние AI-вызовы.
4. Vite dev proxy /api → localhost:8000. В production same-origin. Ключей API
   в VITE env нет. Конфигурация mocks только development/test explicit flag.
5. Сделай accessible форму URL/ref/OS/shell/use_ai. Допускай только три пары
   target из API; выбор ОС автоматически выставляет поддержанную shell.
   Подпись use_ai объясняет отправку фрагментов внешней модели.
6. State useAnalysis: idle/submitting/success/error. Disable duplicate submit,
   не рисуй фиктивные проценты/стадии. Spinner и ожидаемая длительность; при
   timeout пользователь может повторить вручную. Abort не обещает отмену сервера.
7. MSW handlers используют нормативные examples, разные success/fallback/error
   scenarios. Они не ловят production requests и не маскируют неверные endpoint.
8. Тесты формы: required URL, target pairing, payload shape, loading, error,
   retry/manual resubmit, response races. Старый response не перетирает новый.
9. Проверь typecheck/test/build. Передай агенту 1 scripts и dev URL, запиши D1
   handoff с выбранными версиями. Не объявляй full app working на MSW alone.

Выход: интерфейсный каркас, не зависящий от окончания backend реализации.
```

## D2. Отчёт, доказательства, команды и экспорт

**До начала:** D1; валидные analysis examples для Python, Node, partial и needs_input.

**Артефакты:** SummaryCard, CoverageNotice, FactsPanel, FindingsList, RunPlanView, EvidencePanel, CommandBlock, Markdown export.

**Приёмка:** пользователь различает факт и предположение, может увидеть источник, скопировать команду и скачать корректный Markdown.

### Промпт D2

```text
Реализуй D2 — полный экран AnalysisResponse. Отображай данные контракта,
не достраивай собственную 'диагностику' в браузере.

1. Верх отчёта: repo name/link, commit SHA, target, stack, source_mode,
   generation.mode/reason. Fixture и fallback видны всегда, не только tooltip.
2. Coverage блок: partial notice, limitations, files_read/selected, пояснение,
   что complete означает завершённую ограниченную выборку. Не рисуй процент
   прочитанного репозитория из этих чисел.
3. FactsPanel группирует project roots, manifests, dependencies, runtime,
   managers, env names и data/GPU hints. Для длинных списков collapse/search
   можно сделать локально, не скрывай смысловые ограничения.
4. FindingsList: severity label + title + description + confidence + origin +
   recommended action + evidence IDs как кнопки/ссылки. Severity показывай
   текстом и цветом, не только красным/зелёным.
5. RunPlanView сохраняет порядок steps. У каждого prerequisites/assumptions,
   description, cwd, shell, commands, verification, sources. needs_input/questions
   заметны до команды запуска. Над планом поясни: команды ещё не выполнялись.
6. EvidencePanel lookup по registry. File/tree/log различаются, source text
   выводится escaped как React text. URL разрешай только https github.com;
   synthetic evidence без URL отображай как локальный пример. Нет raw HTML
   rendering или dangerouslySetInnerHTML для repo/model content.
7. CommandBlock: pre/code, wrap/горизонтальный scroll, copy button с feedback
   и обработкой Clipboard API failure. Copy не исполняет команду. Показывай
   cwd и shell, объясни <repo> как папку клонированного проекта.
8. exportMarkdown собирает report DTO: metadata/modes/coverage/findings/plan/
   sources и optional latest diagnosis. Никакого raw log. Безопасный filename,
   корректные code fences даже при backticks в тексте, URL не превращаются в HTML.
9. Tests: missing evidence не падает и виден как defect, partial/fallback banners,
   needs_input, malicious HTML как текст, copy success/failure, Markdown содержит
   modes/SHA/источники и не содержит input-log/secret; filename sanitization.
10. Проверь layout на desktop и узком экране. Передай screenshots/описание
    фактической UI-проверки и D2 handoff, не называй mocked data live результатом.

Выход: понятный полный отчёт, пригодный для демонстрации и самостоятельного чтения.
```

## D3. Лог, diagnosis, ошибки и повторные попытки

**До начала:** D2; diagnosis/error examples из G0 и уточнения C3 при наличии.

**Артефакты:** ErrorLogForm, DiagnosisPanel, useDiagnosis, общие error/empty states.

**Приёмка:** diagnosis привязана к текущему analysis, исходный лог не экспортируется и не сохраняется между сессиями; типовые сбои объяснены.

### Промпт D3

```text
Реализуй D3 — пользователь вставляет лог после успешного анализа и получает
DiagnosisResponse. Не отправляй лог до submit и не вызывай AI непосредственно.

1. Log form доступна при analysis_id. Поля: log textarea, optional command,
   use_ai. Target берётся из анализа и отображается; не подменяй его локально.
   Максимум 30000/2000 chars с counter; whitespace-only не отправлять.
2. Рядом короткая просьба удалить ключи/личные данные и объяснение, что при AI
   обработанный текст передаётся модели. Не обещай идеальную автоматическую очистку.
3. Храни input log только в React state. Нет localStorage/sessionStorage,
   analytics или console.log body. Export использует лишь response diagnosis.
4. useDiagnosis: independent submitting/error/success; блок повторных submits,
   timeout 60s, ручной retry. При новом анализе сбрасывай old diagnosis/log state;
   поздние ответы связывай с captured analysis_id и request sequence.
5. DiagnosisPanel: summary, generation mode/reason, causes с confidence/origin,
   explanation, evidence, fixes/commands/verifications и questions. Ответ не
   называется 'ошибка исправлена': пользователь должен выполнить проверку.
6. Обработай ANALYSIS_NOT_FOUND: объяснить TTL/restart и предложить повторный
   анализ repo. Ничего не повторять автоматически с потерянным контекстом.
7. Общий error banner маппит INVALID_INPUT, RATE_LIMITED, SERVER_BUSY,
   upstream/timeouts и generic INTERNAL_ERROR. Показывает request_id для связи,
   retry только когда осмысленно. Не рендери details как HTML.
8. MSW cases: success AI, fallback timeout, unknown error/questions, empty log,
   expired ID, 429, connection error, stale response. Test через user actions,
   проверяй JSON payload и visible state, не implementation details hooks.
9. Убедись, что Markdown включает последнюю diagnosis и её evidence, но не
   введённый исходный log/command сверх безопасного response content.
10. Передай агенту 1 готовый frontend build и D3 handoff для G1. Отметь отдельно,
    какие сценарии пока прошли только MSW и ждут D4.

Выход: завершённый пользовательский сценарий на согласованных mock-контрактах.
```

## D4. Реальный backend и браузерный E2E

**До начала:** G1 backend с fixture source и настоящим scanner/fallback, MSW можно выключить. A3 завершён.

**Артефакты:** Playwright tests, webServer configuration, regression reports, CI script handoff.

**Приёмка:** browser → local API → реальные модули → browser проходит без внешних ключей; mocks не подменяют backend.

### Промпт D4

```text
Выполни D4 — интеграцию UI с настоящим backend. Основной E2E offline:
fixture repository source + настоящий scanner + настоящий rules fallback.

1. Выключи MSW и любые client response stubs. Запусти backend fixture mode,
   frontend с dev proxy или собранный same-origin путь; проверь /health.
2. Настрой Playwright webServer под отдельные test ports, не завершай посторонние
   процессы. Передай env без ключей; в CI reuseExistingServer=false, чтобы
   случайный live server не сделал тесты сетевыми/платными.
3. Python E2E: выбрать fixture URL/target/use_ai=false → дождаться отчёта →
   проверить source_mode=fixture, generation=fallback, missing-data finding,
   существующий evidence, shell command → вставить known log → diagnosis.
4. Node E2E: manager/scripts/lock-aware install, command shell/cwd, Markdown
   download. Проверяй содержание файла: SHA/modes/source refs, без raw log.
5. Negative E2E: неправильный URL, неизвестный fixture, whitespace log,
   повторное нажатие, смена analysis очищает диагноз. TTL и rate-limit можно
   проверить отдельным controlled API test setup; не ждать 30 минут в браузере.
6. Проверь production build static path совместно с A4: assets и API работают,
   неизвестный /api route не возвращает HTML. Dev MSW не попал в production startup.
7. Найденные schema/backend/AI дефекты передавай владельцу: request, expected,
   observed, screenshot/trace без секретов. Не скрывай ошибки cast Any и UI mocks.
8. Прогони typecheck/unit/build/E2E после исправлений. Передай агенту 1 точные
   команды, install Chromium step и фактические результаты для CI/G2.

Выход: доказанный сквозной путь, отличный от демонстрации заранее готового JSON.
```

## D5. Полировка и защита

**До начала:** G2 или явно ограниченный статус live; B5/C5 передали demo repo/ref и проверенную историю.

**Артефакты:** `docs/demo.md`, финальные UX fixes, screenshots при необходимости, собственный acceptance handoff.

**Приёмка:** история укладывается в 3–5 минут, сеть не единственная возможность показать продукт, честно отражены границы AI.

### Промпт D5

```text
Выполни D5 — подготовь RepoDoctor к защите без расширения архитектуры.

1. Проверь keyboard-only flow, labels/focus, error announcements, contrast,
   desktop и узкий viewport. Длинные URL/tracebacks/commands не ломают экран.
   Исправляй в своей зоне, backend defects сообщай владельцу.
2. Составь docs/demo.md: требования/env, способ запуска, repo/ref/target,
   точный сценарий, подготовленный обезличенный log, ожидаемые findings/steps,
   что говорить об evidence и limitations. Не помещай ключи или реальные личные логи.
3. Сценарий 3–5 минут: проблема чужого repo → URL → sources/risks → инструкция →
   ошибка пользователя → diagnosis/fix/verification → export → ограничения.
   Историю привяжи к подтверждённому источнику, не придумай 'реальный случай'.
4. Раздели режимы демонстрации: live GitHub + live AI; live GitHub + fallback;
   offline synthetic fixture + fallback. Для каждого объясни точный переключатель
   и видимый badge, никогда не называй offline режим live.
5. Подготовь резервный fixture для потери сети. Переключение source требует
   осознанной конфигурации/рестарта; приложение не должно тайно менять ответы.
6. Репетируй с секундомером или измерением длительности; если live слишком
   медленный, заранее открытый отчёт помечай как ранее полученный, а не новый вызов.
7. Подготовь ответы жюри: почему bounded pipeline, что реально анализируется,
   зачем evidence/SHA, почему не исполняем чужой код, отличие fallback от AI,
   что следующим этапом (sandbox/private repos/auth) и почему это вне MVP.
8. Прогони затронутые UI tests и финальный E2E. Передай агенту 1 D5 report:
   проверено, не проверено, known issues, demo instructions и G3 readiness.

Выход: понятная честная демонстрация рабочего приложения и практичный demo runbook.
```
