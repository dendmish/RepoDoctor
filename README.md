<div align="center">

# :stethoscope: RepoDoctor

**AI-агент для запуска чужих GitHub-проектов**

Hackathon · Тема №4 · Open Source × AI

[Проблема](#-проблема) · [Что делает](#-что-делает-repodoctor) · [Быстрый старт](#-быстрый-старт) · [Как это работает](#-как-это-работает) · [Демо-сценарий](#-демо-сценарий-для-защиты) · [Архитектура](#-архитектура)

</div>

---

## 🔥 Проблема

Разработчик находит интересный GitHub-репозиторий (особенно исследовательский ML-код), но не понимает,
как его запустить:

- устаревшие зависимости (`tensorflow==1.x`, `torch<1.13`);
- датасеты и чекпоинты, которых нет в репозитории;
- неполная документация, команды из README не работают;
- ошибки окружения, о которых написано только в traceback.

## 💡 Решение

Пользователь вставляет ссылку на репозиторий. RepoDoctor:

1. **анализирует** структуру, README и зависимости;
2. **находит типовые проблемы** с окружением и данными (статический анализ, без LLM — быстро и детерминированно);
3. **генерирует пошаговую инструкцию запуска** (локальная LLM через Ollama);
4. **реально пробует запустить проект** в изолированном Docker-контейнере и собирает лог;
5. **диагностирует ошибку** — по логу запуска или вставленному пользователем traceback'у — и предлагает конкретные команды исправления.

> 🧨 Ключевая фишка: агент не просто «рассуждает» про код — он **запускает проект и чинит по факту**, как
> опытный инженер при разборе чужих ML-репозиториев.

## ⚡ Что делает RepoDoctor

| Возможность | Инструмент | Что на выходе |
|---|---|---|
| Клонирование репо | git + GitHub tarball fallback (кэш клонов) | локальная копия |
| Статический анализ | парсинг `requirements.txt` / `environment.yml` / `pyproject.toml` / `setup.py` / `package.json` / `Cargo.toml` / `go.mod` / `pom.xml` / CMake / Makefile | зависимости, верс. Python/Go, точки входа |
| Детектор проблем | правила, без LLM | 🔴 критичные / 🟡 предупр. / 🔵 инфо |
| Пошаговая инструкция | Ollama (LLM, локально) | шаги + комментарии к рискам |
| Пробный запуск | Docker + шаблоны Dockerfile по экосистеме: **Python, Node.js, Rust (cargo), Go, Java (Maven/Gradle), C/C++ (CMake/Make), Ruby**; свой Dockerfile репо используется как есть | реальный лог запуска |
| Диагностика ошибки | LLM + контекст проекта | категория, корневая причина, команды фикс |

## 🚀 Быстрый старт

Требования: **Python 3.11+**, **Docker**, **[Ollama](https://ollama.com)**.

```bash
# 1. Зависимости
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Модель Ollama (один раз, ~4.7 GB)
ollama serve &                 # если демон ещё не запущен
ollama pull qwen2.5-coder:7b

# 3. Приложение
.venv/bin/streamlit run app.py
# → http://localhost:8501
```

### 🐳 Docker: как «потянуть» и запустить

Публичный образ приложения публикуется CI-ом в GHCR (workflow `docker-publish`),
после мержа PR доступен любой:

```bash
docker pull ghcr.io/dendmish/repodoctor:mvp-flat

# приложению нужны два «моста» с хостом:
#  · Ollama (модели тяжёлые, качать в контейнер каждый раз нет смысла на демо)
#  · docker.sock — чтобы сам запускать чужие проекты в песочнице
docker run -d --name repodoctor-app -p 8501:8501 \
  -e OLLAMA_URL=http://host.docker.internal:11434 \
  -e REPODOCTOR_SANDBOX=/sandbox \
  --add-host=host.docker.internal:host-gateway \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/dendmish/repodoctor:latest

# Ollama на хосте должна слушать не только 127.0.0.1:
OLLAMA_HOST=0.0.0.0 ollama serve &
```

Или одним движением через compose (в репо есть `docker-compose.yml` — берёт те же
env и mounts):

```bash
docker compose up -d     # http://localhost:8501
```

> Запуск чужих проектов из контейнерного RepoDoctor работает через смонтированный
> `docker.sock`: sandbox-образ собирается из stdin-tar (`docker build - < ctx.tar`),
> поэтому запускаемый проект не требует общих путей между контейнером приложения и хостом.
> Лимиты CPU/RAM и таймауты те же, что и в native-режиме.


## 🧠 Как это работает

```
┌──────────────┐    ┌───────────────┐    ┌────────────────┐
│ GitHub URL   │───▶│ clone + static│───▶│  Отчёт: риски,  │
│              │    │ analysis      │    │  точки входа    │
└──────────────┘    └───────┬───────┘    └───────┬────────┘
                            │                    │
                   ┌────────▼────────┐   ┌───────▼─────────┐
                   │ LLM: планзапуска│   │ Docker: build+run│
                   │ (Ollama, local) │   │ sandbox + лимиты │
                   └─────────────────┘   └───────┬─────────┘
                                                 │ лог ошибки
                                         ┌───────▼─────────┐
                                         │ LLM: диагностика │
                                         │ причина + фикс   │
                                         └─────────────────┘
```

## 🎬 Демо-сценарий для защиты

1. Вставляем ссылку на ML-репозиторий без `requirements.txt`, данные которого в репо отсутствуют.
2. Смотрим структурный отчёт: 🔴 «Нет файла зависимостей», 🔴 «Отсутствуют пути к данным».
3. Кнопка **«Как запустить»** → пошаговая инструкция с конкретными командами.
4. Кнопка **«Попытаться запустить»** → `docker build` / `run` → реальный лог ошибки
   (`ModuleNotFoundError` / `FileNotFoundError: ./data/...`).
5. Кнопка **«Диагностировать»** → категория ошибки, строка-доказательство из лога, команды исправления.
   Или вставляем свой traceback — агент разбирает так же.

<details>
<summary><b>🔍 Пример реального прогона</b></summary>

На репозитории `dennybritz/cnn-text-classification-tf`:

- статический анализ: нет `requirements.txt`; в коде пути к данным
  `./data/rt-polaritydata/rt-polarity.pos/.neg`, файлов в репо нет;
- docker-запуск упал с реальной ошибкой:
```
Traceback (most recent call last):
  File "/app/train.py", line 3, in <module>
    import tensorflow as tf
ModuleNotFoundError: No module named 'tensorflow'
```
- диагноз агента: категория `missing_package`, корневая строка лога,
  команда исправления `pip install tensorflow==...` + следующий шаг.

<details>
<summary><b>✅ Проверялось и на не-Python (live-прогоны)</b></summary>

| Репо | Экосистема | Результат |
|---|---|---|
| `itchyny/gojq` | Go | ✅ build + run, exit 0 |
| `meta-rust/rust-hello-world` | Rust | ✅ build + run, exit 0 |
| `jameskbride/cmake-hello-world` | C/CMake | ✅ build + run, exit 0 |
| `rahulshettyacademy/MavenHelloWorld` | Java/Maven | ✅ build; run честно упал: jar без manifest → материал для диагностики |
| `openshift/ruby-hello-world` | Ruby | ⚪ Dockerfile автора сломан → агент пересобрал своим шаблоном; gem-зоопарк не добит (по запросу) |

Дополнительно: если у репо есть свой Dockerfile и он не собирается/не стартует — агент
автоматически пересобирает проект своим шаблоном и помечает это в логе.

</details>

</details>

## 🏗 Architecture

```
app.py                  # Streamlit UI (анализ · план · docker-run · диагностика)
repodoctor/
├── clone.py            # git shallow-clone + codeload tarball + кэш клонов
├── analyze.py          # структура, зависимости, точки входа, скан путей к данным
├── checks.py           # детектор типовых проблем (правила, без LLM)
├── runner.py           # sandbox-копия → Dockerfile → docker build/run → зеркала образов
├── llm.py              # обёртка Ollama (выбор модели, JSON-парсер)
├── diagnose.py         # диагностика лога ошибки через LLM
└── api.py              # фасад: inspect_repo / plan_from_analysis / try_run
prompts/
├── plan.md             # промпт пошаговой инструкции
└── diagnose.md         # промпт диагностики лога
examples/               # сохранённые логи прогонов
```

## 🛡 Ограничения и безопасность

- чужой код исполняется **в одноразовом Docker-контейнере**: `--rm`, без монтирований хост-каталогов;
- лимиты ресурсов: `--cpus 2`, `--memory 1g` при запуске, таймауты build/run;
- флаг **«Разрешить сеть»** в UI — можно выключить, чтобы проверить офлайн-поведение;
- статический анализ код не исполняет — только чтение;
- LLM работает локально (Ollama) — код репозитория не отправляется в облачные API;
- в Docker-режиме приложения песочница строится через stdin-tar, поэтому контейнер RepoDoctor
  не требует общих путей с хостом — только `docker.sock`.

## 🧬 Стек

Python 3.14 · Streamlit · Ollama (`qwen2.5-coder:7b`, переключается в UI) · Docker · GitHub API

## 🤖 AI-использование

Код и промпты подготовлены с участием AI-ассистента (opencode + GLM), прогоны и сценарии проверены
на реальных публичных репозиториях.

---

<div align="center">Made for the hackathon · Open Source × AI</div>
