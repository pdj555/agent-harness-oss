from __future__ import annotations

import os
import sys
from pathlib import Path

from harness.environment import display_python, project_venv, stage_runtime, venv_python
from harness.isolation import create_stage
from harness.tools import execute
from harness.verification import run_checks
from tests.helpers import copy_sample, git_init, make_venv

APP = "import projdep\n\n\ndef greet(name: str) -> str:\n    return projdep.shout(name)\n"
TEST = "from app import greet\n\n\ndef test_greet():\n    assert greet('ada') == 'ADA!'\n"
DEPENDENCY = "def shout(name: str) -> str:\n    return name.upper() + '!'\n"


def _project(tmp_path: Path) -> Path:
    source = tmp_path / "project"
    source.mkdir()
    (source / "app.py").write_text(APP, encoding="utf-8")
    (source / "test_app.py").write_text(TEST, encoding="utf-8")
    (source / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    make_venv(source, {"projdep": DEPENDENCY})
    git_init(source)
    return source


def test_a_projects_virtualenv_is_found_and_nothing_else_is(tmp_path: Path):
    source = _project(tmp_path)
    bare = tmp_path / "bare"
    (bare / "env").mkdir(parents=True)

    found = project_venv(source)

    assert found == source / ".venv"
    assert venv_python(found) == source / ".venv" / "bin" / "python"
    assert project_venv(bare) is None
    assert project_venv(None) is None


def test_checks_run_with_the_projects_own_dependencies(tmp_path: Path):
    source = _project(tmp_path)
    stage = create_stage(source, tmp_path / "stages", "run-env")

    with_project = run_checks(stage.root, project_root=stage.source)
    without_project = run_checks(stage.root)

    assert with_project.passed is True
    assert with_project.command == ".venv/bin/python -m pytest -q"
    assert without_project.passed is False
    assert "projdep" in without_project.output


def test_the_isolated_copy_is_what_the_projects_interpreter_runs(tmp_path: Path):
    source = _project(tmp_path)
    stage = create_stage(source, tmp_path / "stages", "run-env-isolated")
    (stage.root / "app.py").write_text(
        "import projdep\n\n\ndef greet(name: str) -> str:\n    return 'wrong'\n", encoding="utf-8"
    )

    result = run_checks(stage.root, project_root=stage.source)

    assert result.passed is False
    assert (source / "app.py").read_text(encoding="utf-8") == APP


def test_run_shell_gives_the_agent_the_same_interpreter(tmp_path: Path):
    source = _project(tmp_path)
    stage = create_stage(source, tmp_path / "stages", "run-env-shell")

    output = execute(
        "run_shell", {"command": "python -m pytest -q"}, stage=stage, role="principal"
    )

    assert output.startswith("exit 0")
    assert "1 passed" in output


def test_the_command_environment_activates_the_venv_and_carries_no_credentials(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-reach-a-subprocess")
    source = _project(tmp_path)
    stage = create_stage(source, tmp_path / "stages", "run-env-vars")

    python, env = stage_runtime(stage.root, stage.source)

    assert python == source / ".venv" / "bin" / "python"
    assert env["VIRTUAL_ENV"] == str(source / ".venv")
    assert env["PATH"].split(os.pathsep)[0] == str(source / ".venv" / "bin")
    assert env["HOME"] == str(stage.root / ".home")
    assert "OPENAI_API_KEY" not in env
    assert "sk-must-not-reach-a-subprocess" not in " ".join(env.values())


def test_a_project_without_a_virtualenv_uses_the_harness_interpreter(tmp_path: Path):
    source = copy_sample(tmp_path / "plain")
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-env-plain")

    python, env = stage_runtime(stage.root, stage.source)

    assert python == Path(sys.executable)
    assert "VIRTUAL_ENV" not in env
    assert display_python(python, stage.source) == "python"
    assert run_checks(stage.root, project_root=stage.source).command == "python -m pytest -q"


EDITABLE_FINDER = """
import importlib.util, sys
from importlib.machinery import ModuleSpec

MAPPING = {{"pkg": r"{source}/pkg"}}


class Finder:
    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        if fullname in MAPPING:
            return importlib.util.spec_from_file_location(
                fullname,
                MAPPING[fullname] + "/__init__.py",
                submodule_search_locations=[MAPPING[fullname]],
            )
        return None


def install():
    if not any(finder is Finder for finder in sys.meta_path):
        sys.meta_path.append(Finder)
"""


def test_an_editable_install_does_not_let_tests_read_the_source_tree(tmp_path: Path):
    """The stage must be what runs even when the project is installed editable.

    `pip install -e .` registers a finder pinned to the source tree. If it won,
    verification would judge code the agent never changed.
    """
    source = tmp_path / "editable"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "__init__.py").write_text("ORIGIN = 'source'\n", encoding="utf-8")
    (source / "test_origin.py").write_text(
        "import pkg\n\n\ndef test_origin():\n    assert pkg.ORIGIN == 'stage'\n", encoding="utf-8"
    )
    (source / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    site = make_venv(source)
    (site / "__editable___pkg_finder.py").write_text(
        EDITABLE_FINDER.format(source=source), encoding="utf-8"
    )
    (site / "__editable__.pkg.pth").write_text(
        "import __editable___pkg_finder; __editable___pkg_finder.install()\n", encoding="utf-8"
    )
    git_init(source)
    stage = create_stage(source, tmp_path / "stages", "run-env-editable")
    (stage.root / "pkg" / "__init__.py").write_text("ORIGIN = 'stage'\n", encoding="utf-8")

    result = run_checks(stage.root, project_root=stage.source)

    assert result.passed is True, result.output
    assert (source / "pkg" / "__init__.py").read_text(encoding="utf-8") == "ORIGIN = 'source'\n"
