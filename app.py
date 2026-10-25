import json
import sys
import time

import streamlit as st

from repodoctor import api as rd

st.set_page_config(page_title="RepoDoctor", page_icon=":stethoscope:", layout="wide")

st.title(":stethoscope: RepoDoctor")
st.caption("AI-агент для запуска чужих GitHub-проектов: анализ → план запуска → пробный запуск в Docker → диагностика ошибок")

with st.sidebar:
    st.header("Статус окружения")
    ok_ollama = rd.ollama_ok()
    st.write("Ollama:", "🟢 работает" if ok_ollama else "🔴 не запущен (`ollama serve`)")
    if ok_ollama:
        st.write("Модель:", rd.pick_model())
    import shutil as _sh
    st.write("Docker:", "🟢 работает" if _sh.which("docker") else "🔴 не найден")
    models = rd.installed_models()
    if ok_ollama and models:
        model = st.selectbox("LLM", models, index=0 if "qwen2.5-coder:7b" in models else 0)
        st.session_state["model"] = model

col1, col2 = st.columns([3, 1])
with col1:
    url = st.text_input("Ссылка на GitHub-репозиторий",
                        placeholder="https://github.com/owner/repo")
with col2:
    network_enabled = st.checkbox("Разрешить сеть в контейнере", value=True,
                                  help="Нужна для pip install. Отключите, чтобы проверить офлайн-поведение")

go = st.button("🔍 Анализировать", type="primary", use_container_width=True)

if go:
    if not url.strip():
        st.error("Вставьте ссылку вида https://github.com/owner/repo")
        st.stop()

    with st.spinner("Клонирую и анализирую репозиторий…"):
        t0 = time.time()
        a, checks = rd.inspect_repo(url)
        elapsed = time.time() - t0
    if a is None:
        st.error(checks)
        st.stop()

    st.session_state["analysis"] = a
    st.session_state["checks"] = checks
    st.session_state["plan"] = None
    st.session_state["runresult"] = None
    st.session_state["diag"] = None
    st.success(f"Проанализировано за {elapsed:.1f} с · {a.file_count} файлов · тип: {a.project_type}")

a = st.session_state.get("analysis")
if a is not None:
    checks = st.session_state["checks"]

    st.subheader("Точка входа")
    st.write(a.repo_name or "-", "·", a.project_type, "·",
             f"{len(a.dependencies)} зависимостей" if a.dependencies else "зависимости не распознаны",
             "·", f"Python {a.python_version}" if a.python_version else "версия Python не указана")
    if a.entry_points:
        st.markdown("Найденные точки входа:")
        for ep in a.entry_points[:10]:
            st.code(ep, language="bash")
    else:
        st.warning("Точки входа не найдены в README и корне.")

    t1, t2, t3 = st.tabs(["🩺 Проблемы", "📋 Структура", "📖 README"])

    with t1:
        st.caption(f"Статический анализ: {checks.score}")
        for f in checks.findings:
            icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}[f.level]
            with st.expander(f"{icon} {f.title}"):
                st.write(f.details)
                if f.fix:
                    st.markdown(f"**Как чинить:** {f.fix}")

    with t2:
        st.code(rd.format_tree(a.tree), language="text")

    with t3:
        st.text(a.readme_snippet or "README не найден")

    st.divider()
    colL, colR = st.columns(2)

    with colL:
        st.subheader("🧭 Как запустить (AI-план)")
        if st.button("Сгенерировать пошаговую инструкцию"):
            with st.spinner("Модель думает (локально, может до 2 минут)…"):
                t0 = time.time()
                st.session_state["plan"] = rd.plan_from_analysis(
                    a, checks, model=st.session_state.get("model", ""))
                st.session_state["plan_elapsed"] = time.time() - t0
        plan = st.session_state.get("plan")
        if plan is not None:
            if isinstance(plan, str):
                st.error(plan)
            else:
                st.caption(f"LLM · {st.session_state.get('plan_elapsed', 0):.0f} с")
                for i, step in enumerate(plan.get("instruction", []), 1):
                    st.markdown(f"**Шаг {i}.** {step}")
                for r in plan.get("risks", []):
                    crit = r.get("criticality", "?")
                    st.markdown(f"- **{r.get('title', '')}** ({crit}): {r.get('comment', '')}")
                    if r.get("fix"):
                        st.markdown(f"  Фикс: `{r.get('fix')}`")
            st.session_state["plan_raw"] = plan if isinstance(plan, dict) else {}

    with colR:
        st.subheader("🐳 Пробный запуск в Docker")
        st.caption(
            "Команда собирает одноразовый образ и запускает главную команду проекта "
            "с лимитами CPU/RAM и таймаутом 3 мин. Атаковать хост система не может: "
            "контейнер без монтирований, права по умолчанию.")
        if st.button("🚀 Попытаться запустить", type="secondary"):
            with st.spinner("docker build / docker run (может занять несколько минут)…"):
                t0 = time.time()
                st.session_state["runresult"] = rd.try_run(a, network=network_enabled)
                st.session_state["run_elapsed"] = time.time() - t0
        rr = st.session_state.get("runresult")
        if rr is not None:
            ok_icon = "✅" if rr.ok else "❌"
            st.markdown(f"{ok_icon} **Этап {rr.stage}** · {rr.duration_s:.0f} с" + (f" · образ `{rr.image}`" if rr.image else ""))
            with st.expander("Полный лог запуска"):
                st.code(rr.log or "(пусто)", language="text")
            if not rr.ok and rr.log:
                if st.button("🧑‍⚕️ Диагностировать ошибку из лога", type="primary"):
                    with st.spinner("LLM разбирает лог…"):
                        st.session_state["diag"] = rd.diagnose_log(
                            rr.log, "docker", a,
                            environment="Docker-контейнер",
                            model=st.session_state.get("model", ""))
                    st.rerun()
        st.session_state.setdefault("diag", None)

    st.divider()
    st.subheader("🩹 Диагноз от агента")
    diag = st.session_state.get("diag")
    if diag:
        if isinstance(diag, str):
            st.error(diag)
        else:
            st.markdown(f"**Категория:** {diag.get('category_label', diag.get('category', '—'))}")
            st.markdown(f"**Что случилось:** {diag.get('diagnosis', '—')}")
            st.markdown(f"**Основа вывода:** `{diag.get('root_cause', '—')}`")
            cmds = diag.get("fix_commands") or []
            if cmds:
                st.markdown("**Исправление (команды):**")
                for c in cmds:
                    st.code(c, language="bash")
            if diag.get("fix_explanation"):
                st.markdown(f"**Пояснение:** {diag.get('fix_explanation')}")
            nxt = diag.get("next_steps") or []
            if nxt:
                st.markdown("**Если не поможет:**")
                for s in nxt:
                    st.markdown(f"- {s}")
    else:
        st.info("Здесь появится разбор ошибки: либо из пробного запуска, либо из лога ниже.")

    st.subheader("✍️ Вставьте свой лог ошибки (если запускали сами)")
    pasted = st.text_area("Лог/traceback", height=180,
                          placeholder="Traceback (most recent call last): …",
                          key="pasted_log")
    if st.button("Диагностировать вставленный лог") and pasted.strip():
        with st.spinner("LLM разбирает лог…"):
            st.session_state["diag"] = rd.diagnose_log(
                pasted, "paste", a, model=st.session_state.get("model", ""))
            st.rerun()


if __name__ == "__main__":
    from subprocess import call

    from streamlit.runtime.scriptrunner import get_script_run_ctx

    if get_script_run_ctx() is None:
        raise SystemExit(
            call([sys.executable, "-m", "streamlit", "run", __file__, *sys.argv[1:]])
        )
