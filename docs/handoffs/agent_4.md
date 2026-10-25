# Handoff — агент 4 (Frontend)

## D1 — каркас UI, generated types, MSW

Задача: D1
Статус: done
Базовый контракт: schema_version 1.0, G0 c1b9c8a.
Рабочая база обновлена fast-forward до main 44b9050 (контракты не изменились).

Файлы: frontend/, .nvmrc, docs/handoffs/agent_4.md.
Backend, DTO, OpenAPI и нормативные examples не изменены.

Реализовано:
- React/TypeScript/Vite shell; accessible URL/ref/OS/shell/use_ai form.
- Три допустимые пары target, автоматический shell, согласие на отправку фрагментов AI.
- generated.ts из OpenAPI; hand-written код использует aliases generated DTO.
- fetch API /api/v1, JSON headers/error envelope, AbortController, 100s/60s
  deadlines, без автоматического повтора POST.
- useAnalysis idle/submitting/success/error, duplicate guard, sequence guard,
  отмена ожидания и cleanup на unmount; поздние success/error не заменяют новый ответ.
- Явный dev-only MSW: нормативные python/node/needs_input/error examples,
  network failure; неизвестные /api endpoints завершаются ошибкой.
- Worker обслуживается только dev middleware, отсутствует в production output.
- UI tests и отдельный D1 mocked browser smoke; документация frontend/README.md.

Версии (точно закреплены, полный список package.json/package-lock.json):
Node 22.22.0; npm 11.6.2; React/react-dom 19.1.1; TypeScript 5.9.2;
Vite 7.3.7; plugin-react 5.0.3; Vitest 4.1.12; jsdom 26.1.0;
Testing Library React 16.3.0 / user-event 14.6.1 / jest-dom 6.8.0;
MSW 2.11.3; Playwright 1.55.1; openapi-typescript 7.9.1.
npm 10.9.4 столкнулся с ошибкой Arborist edgesOut при разрешении optional
peers; npm 11.6.2 успешно выполнил install и чистый npm ci.
Первоначальные Vite/Vitest обновлены до окончательной фиксации зависимостей:
npm audit после обновления — 0 vulnerabilities.

Команды для агента 1 (из frontend/):
- npm ci
- npm run generate:api
- npm run typecheck
- npm test
- npm run build
- npm run dev → http://127.0.0.1:5173; /api → http://localhost:8000
- npx playwright install --no-shell chromium
- npm run test:e2e → только D1 MSW smoke, отдельный порт 5179.

Проверки на Windows / Node 22.22.0 / npm 11.6.2:
- npm ci → успешно.
- npm run generate:api → успешно.
- npm run build (включает typecheck) → успешно.
- npm test → 20 passed в 3 файлах.
- Production asset inspection → worker, setupWorker, synthetic-example-model отсутствуют.
- npm audit → 0 vulnerabilities.
- npm run test:e2e → 2 passed (Chromium): отправка формы, mock provenance, viewport 375px без horizontal overflow, неверный endpoint не даёт success.

Особенность sandbox: Vitest cache rename в системном TEMP дал EPERM.
Повторный успешный прогон выполнен с TEMP/TMP в выделенном рабочем каталоге.
Это настройка окружения проверки; машинные пути не зашиты в проект.

Ограничения:
- MSW возвращает examples без изменений, в том числе target/use_ai-independent
  generation, ID и даты; видимый banner явно обозначает mock.
- Полный report/export/diagnosis UI относятся к D2/D3.
- Реальный backend E2E (D4), live GitHub/AI, Linux/macOS не проверены.
- Успех MSW не означает готовность полного приложения.
- Runtime schema validation всего успешного DTO не добавлена; клиент
  типизирован по OpenAPI, envelope ошибок проверяется во время исполнения.

Изменения контракта: нет. Frontend зависимости зафиксированы в своей зоне.
Разблокирует: D2; агенту 1 переданы scripts/dev URL/build path.
Блокер: нет.
Следующая задача: D2.

## D2/D3 — отчёт, экспорт и диагностика (25.10.2026)

Статус: реализованы и проверены в ветке `agent-4-d2-d3-report-diagnosis`; изменения передаются через PR. База — `main` `0f1a237`; исходные контракты G0 1.0 сохранены. Отметки этого раздела не означают, что PR уже объединён в main или что G1/D4 закрыты.

Файлы: `frontend/src/components/{AnalysisReport,ReportSections,EvidencePanel,CommandBlock,RunPlanView,DiagnosisPanel,ErrorBanner}.tsx`, `hooks/useDiagnosis.ts`, `hooks/useAnalysis.ts`, `lib/{evidence,exportMarkdown}.ts`, App/types/CSS/MSW, новые report/export/diagnosis tests, browser report.spec, Playwright config и frontend README.

### D2

- [x] SummaryCard: repo identity, SHA, target, stack, source/generation modes, reason/model/prompt version, даты и warnings.
- [x] CoverageNotice: partial limitations, реальные counters, пояснение ограниченной выборки без выдуманного процента покрытия.
- [x] FactsPanel: roots/manifests, runtime, managers, сворачиваемые dependency table, entrypoints, env names/data/GPU hints.
- [x] FindingsList: severity текстом/цветом, confidence, origin, rule, suggested action и references.
- [x] RunPlanView/RunSteps: questions до команд, prerequisites, assumptions, порядок, shell/cwd, verification; команды не выдаются за выполненные.
- [x] EvidenceProvider/Panel: собственные registries анализа и диагностики, открытие/focus по ссылке, file/tree/log, missing reference как видимый defect, escaped excerpts.
- [x] HTTPS GitHub allowlist с запретом credentials/нестандартных ports; `noopener noreferrer`. Fixture evidence остаётся локальным даже в старых примерах с synthetic URL.
- [x] Clipboard feedback success/failure; копирование ничего не исполняет.
- [x] Markdown: metadata/provenance/SHA/coverage/facts/findings/plan/sources и полученная diagnosis; HTML/Markdown escaping, code fence длиннее вложенных backticks, безопасное filename, Blob URL cleanup. Исходные log/command не передаются exporter.

### D3

- [x] Controlled log/command form, 30000/2000 chars, counters, reject whitespace, target из анализа, видимый use_ai opt-out и privacy notice.
- [x] Отправка только по submit; ввод только в памяти React, без storage/analytics/console body.
- [x] Independent useDiagnosis, timeout API 60s, duplicate guard, manual retry/cancel, cleanup, ID/sequence guard и reject mismatched analysis response.
- [x] Новый анализ очищает ввод/диагноз; late success/rejection старой операции игнорируется.
- [x] Causes/confidence/origin, fixes/commands/verifications, questions и mode/reason; отсутствует заявление «исправлено».
- [x] Общие ErrorBanner для validation/404/413/429/upstream/network/timeouts/500, safe details и Request ID. Expired context → только явный повтор анализа, лог автоматически не пересылается.
- [x] MSW scenarios для success, unknown/fallback, expired, busy и network; production mock code не запускается.

### Проверки

Windows, Node 22.22.0, npm 11.6.2; версии package/lock не менялись.

```text
npm ci                          → OK, frozen dependencies
npm run typecheck               → OK
npm test                        → 53 passed (20 D1 + 33 D2/D3)
npm run build                   → OK, typecheck + production Vite build
npm run generate:api            → OK, generated.ts без diff
PLAYWRIGHT_BROWSER_CHANNEL=msedge npm run test:e2e
                                → 4 passed, Edge 156 / Chromium engine
Production asset scan           → нет setupWorker / mockServiceWorker / synthetic-example-model
git diff --check                → OK
```

Для изолированного runtime использованы зафиксированные Node/npm в отдельной временной папке; TEMP/TMP перенаправлены в рабочий каталог проверки. Машинные пути не зашиты в проект. Скачанный Chromium 140 не стартовал из-за Windows SideBySide (до выполнения тестов), поэтому добавлен optional `PLAYWRIGHT_BROWSER_CHANNEL`; default остаётся Chromium. Установленный Edge/Chromium прошёл все 4 browser tests.

Визуально просмотрены `report-desktop.png` и `plan-mobile.png`: читаемые metadata/coverage и команды, длинные строки переносятся, горизонтального overflow на 375px нет. Изображения создаёт Playwright в игнорируемом `frontend/test-results/`, в PR не включаются.

Не проверено: настоящий backend D4, live GitHub/AI через интерфейс, Docker, Linux/macOS. Browser сценарии явно используют MSW и не закрывают G1/G2. Backend, DTO, OpenAPI, generated.ts и зависимости не изменены. Runtime validation полного успешного DTO остаётся исходным ограничением D1: фронтенд типизирован по контрактам, backend обязан возвращать валидный DTO.

Для агента 1: `npm run build` выдаёт готовый `frontend/dist`; API остаётся `/api/v1` с прежними request/response. Следующая задача роли — D4 после G1; D5/live demo этим PR не закрываются.
