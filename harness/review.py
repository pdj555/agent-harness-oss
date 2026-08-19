from __future__ import annotations

from pathlib import Path

from harness.isolation import Stage
from harness.provider import Provider
from harness.verification import Verification

TEST_DIR_NAMES = {"tests", "test"}


def _is_test_path(rel: str) -> bool:
    path = Path(rel)
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in TEST_DIR_NAMES for part in path.parts)


def _test_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if any(part in {".git", ".harness", "__pycache__"} for part in rel.parts):
            continue
        if _is_test_path(str(rel)):
            found.append(path)
    return found


def inspect_change(stage: Stage) -> list[str]:
    files = stage.changed_files()
    diff = (stage.diff() or "").strip()
    findings: list[str] = []
    if not _test_files(stage.root):
        findings.append("no test files remain in the isolated worktree")
    impl_changed = [name for name in files if not _is_test_path(name)]
    tests_changed = [name for name in files if _is_test_path(name)]
    if not files and not diff:
        findings.append("review found no isolated change")
    if tests_changed and not impl_changed:
        findings.append("tests changed without an implementation change")
    return findings


def run_review(stage: Stage, verification: Verification, provider: Provider) -> dict:
    """Software-gated review. Check results are context, not the verdict."""
    del provider
    files = stage.changed_files()
    findings = inspect_change(stage)
    passed = not findings
    if passed:
        summary = "Implementation changed. Tests remain. No blocking findings."
    else:
        summary = "Review blocked: " + "; ".join(findings)
    return {
        "role": "reviewer",
        "passed": passed,
        "summary": summary,
        "findings": findings,
        "files_reviewed": files,
        "checks_passed": bool(verification.passed),
    }
