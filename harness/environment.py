"""The environment a stage runs commands in.

A project's tests need the project's dependencies. The harness has its own
interpreter with its own packages, so running a real repository's suite with it
fails on the first import of anything the repository installed. When the source
tree carries a virtualenv, commands in the stage run with that interpreter and
that `bin` directory on PATH instead.

The stage itself never contains the virtualenv: it is ignored, so it is neither
copied nor overlaid. The interpreter is read from the source tree and used with
the stage as the working directory, so the code under test is the isolated
copy, not the original.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

VENV_DIR_NAMES = (".venv", "venv", ".virtualenv", "env")
VENV_PYTHON_PATHS = (("bin", "python"), ("bin", "python3"), ("Scripts", "python.exe"))


def project_venv(root: Path | None) -> Path | None:
    """The project's own virtualenv directory, if the tree carries one."""
    if root is None:
        return None
    for name in VENV_DIR_NAMES:
        candidate = root / name
        if (candidate / "pyvenv.cfg").is_file() and venv_python(candidate):
            return candidate
    return None


def venv_python(venv: Path) -> Path | None:
    for parts in VENV_PYTHON_PATHS:
        candidate = venv.joinpath(*parts)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def stage_runtime(stage_root: Path, project_root: Path | None = None) -> tuple[Path, dict[str, str]]:
    """The interpreter and the filtered environment for commands run in a stage.

    The environment carries no provider credentials and keeps HOME inside the
    stage, so nothing a command writes to HOME lands in the user's tree.
    """
    venv = project_venv(project_root)
    python = (venv_python(venv) if venv else None) or Path(sys.executable)
    path = os.environ.get("PATH", "/usr/bin:/bin")
    env = {
        "PATH": f"{python.parent}{os.pathsep}{path}" if venv else path,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": str(stage_root / ".home"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if venv:
        env["VIRTUAL_ENV"] = str(venv)
    stage_root.joinpath(".home").mkdir(exist_ok=True)
    return python, env


def display_python(python: Path, project_root: Path | None) -> str:
    """How to name the interpreter in evidence, without absolute paths."""
    if project_root is not None:
        try:
            return str(python.relative_to(project_root.resolve()))
        except ValueError:
            pass
    return "python"
