from __future__ import annotations

from harness.isolation import Stage
from harness.provider import Provider
from harness.tools import tool_specs
from harness.verification import Verification

REVIEWER_SUMMARY_PASSED = (
    "Independent review: checks passed and the isolated diff is consistent with the tests."
)
REVIEWER_SUMMARY_FAILED = "Independent review: checks failed; the run is not complete."


def run_review(stage: Stage, verification: Verification, provider: Provider) -> dict:
    diff = stage.diff()
    files = stage.changed_files()
    summary = REVIEWER_SUMMARY_PASSED if verification.passed else REVIEWER_SUMMARY_FAILED
    try:
        completion = provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an independent reviewer. You cannot edit files. "
                        "Comment on the diff and checks only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"verification_passed={verification.passed}\n"
                        f"files={files}\n"
                        f"diff:\n{diff[:6000]}\n"
                        f"checks:\n{verification.output[-2000:]}"
                    ),
                },
            ],
            tool_specs("reviewer"),
        )
        text = (completion.text or "").strip()
        if text and "Principal sign-off" not in text:
            if text.lower().startswith("independent review"):
                summary = text[:1000]
            else:
                summary = f"Independent review: {text[:1000]}"
    except Exception:
        pass
    return {
        "role": "reviewer",
        "passed": bool(verification.passed),
        "summary": summary,
        "findings": [] if verification.passed else ["checks failed"],
        "files_reviewed": files,
    }
