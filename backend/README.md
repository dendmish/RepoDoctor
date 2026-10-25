# Backend: запуск после A3

Из `backend`, Python 3.12:

```powershell
uv sync --frozen
.venv/Scripts/python.exe -m uvicorn repodoctor.main:app --host 127.0.0.1 --port 8000
```

По умолчанию `REPOSITORY_MODE=fixture`: используются настоящие fixture source,
scanner и intelligence. Запросы принимают только URL из `fixtures/repositories/index.json`.
Ключи не нужны; без полной конфигурации AI работает явный fallback. Пример запроса:

```powershell
$payload = @{
    repo_url = 'https://github.com/repodoctor-fixtures/python-cli-demo'
    target = @{ os = 'windows'; shell = 'powershell' }
    use_ai = $false
} | ConvertTo-Json -Depth 3
$analysis = Invoke-RestMethod http://127.0.0.1:8000/api/v1/analyses -Method Post -ContentType 'application/json' -Body $payload
$diagnosis = @{ log = "ModuleNotFoundError: No module named 'requests'"; use_ai = $false } | ConvertTo-Json
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/analyses/$($analysis.analysis_id)/diagnoses" -Method Post -ContentType 'application/json' -Body $diagnosis
```

Для GitHub установите `REPOSITORY_MODE=live` в корневом `.env` или окружении.
Источник live никогда не заменяется fixture при ошибке. `GITHUB_TOKEN` необязателен.
Загрузчик и scanner анализируют до 100 выбранных текстовых файлов общим объёмом
до 1 МиБ, не более 64 КиБ на файл. Бюджет GitHub — 108 HTTP-запросов за 35 секунд,
включая повторы. Контекст AI ограничивается отдельно; прочитанные файлы не обязательно
передаются модели целиком.
OpenAI включается только при наличии `OPENAI_API_KEY` и `OPENAI_MODEL`; use_ai=false
запрещает AI-вызов при любой конфигурации. Ключи остаются на backend.
`USE_DEV_STUBS=false` — стандартный запуск; legacy stubs запрещены в production.

Проверки из `backend`:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe tests/smoke_offline.py
.venv/Scripts/python.exe -m repodoctor.export_openapi ../contracts/openapi.json
```

Smoke запускает отдельный uvicorn на свободном localhost-порту, очищает credentials
дочернего процесса, проверяет Python/Node analysis → diagnosis, неверный URL и TTL,
затем останавливает сервер. Это backend acceptance; report/diagnosis/export UI D2/D3
ещё отсутствуют, G1 и live acceptance этим smoke не закрываются.
