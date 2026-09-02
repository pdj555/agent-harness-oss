from __future__ import annotations

import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "sample-repo"


def copy_sample(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("tracker.py", "test_tracker.py", "README.md"):
        shutil.copy(FIXTURE / name, dest / name)
    return dest


def git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=dev@example.com",
            "-c",
            "user.name=Developer",
            "commit",
            "-m",
            "initial",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )


def make_venv(root: Path, packages: dict[str, str] | None = None) -> Path:
    """Build a real virtualenv for `root` without paying for `python -m venv`.

    A directory is a virtualenv when it holds `pyvenv.cfg` and an interpreter,
    so this is the genuine article: imports resolve against its site-packages.
    Returns the site-packages directory.
    """
    base = Path(sys.executable).resolve()
    venv = root / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(base)
    (venv / "pyvenv.cfg").write_text(
        f"home = {base.parent}\ninclude-system-site-packages = false\n"
        f"version = {sys.version.split()[0]}\n",
        encoding="utf-8",
    )
    site = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    site.mkdir(parents=True)
    # Let the project's interpreter reach the test runner, the way a real
    # project virtualenv has pytest installed into it.
    (site / "runner.pth").write_text(sysconfig.get_paths()["purelib"] + "\n", encoding="utf-8")
    for name, body in (packages or {}).items():
        (site / f"{name}.py").write_text(body, encoding="utf-8")
    return site
