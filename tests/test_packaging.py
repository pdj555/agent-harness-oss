from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_FILES = {
    "harness/sample-repo/README.md",
    "harness/sample-repo/test_tracker.py",
    "harness/sample-repo/tracker.py",
}


def test_direct_wheel_includes_only_allowlisted_demo_files(tmp_path: Path):
    source = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git", ".harness", ".venv", "__pycache__", "build", "dist"
        ),
    )
    ignored_env = source / "examples" / "sample-repo" / ".env"
    ignored_env.write_text("API_KEY=must-not-enter-wheel\n", encoding="utf-8")
    output = tmp_path / "dist"

    built = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(output)],
        cwd=source,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert built.returncode == 0, built.stdout + built.stderr
    wheel = next(output.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        packaged_demo = {
            name for name in archive.namelist() if name.startswith("harness/sample-repo/")
        }
    assert packaged_demo == DEMO_FILES


def test_secret_scan_rejects_sensitive_file_in_wheel(tmp_path: Path):
    wheel = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("harness/sample-repo/.env", "API_KEY=must-not-ship\n")

    scanned = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "scan_secrets.py"), str(wheel)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert scanned.returncode == 1
    assert "harness/sample-repo/.env" in scanned.stdout
