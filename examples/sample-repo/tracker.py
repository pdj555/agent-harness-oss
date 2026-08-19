"""Classify work-item priority from impact and urgency.

Both scores are integers from 1 to 5 inclusive.

- high:   impact >= 4 and urgency >= 4
- medium: not high, and impact >= 3 or urgency >= 3
- low:    everything else
"""

from __future__ import annotations


def classify_priority(impact: int, urgency: int) -> str:
    if not 1 <= impact <= 5 or not 1 <= urgency <= 5:
        raise ValueError("impact and urgency must be between 1 and 5")
    # Bug: high and low labels are reversed. Tests pin the documented spec.
    if impact >= 4 and urgency >= 4:
        return "low"
    if impact >= 3 or urgency >= 3:
        return "medium"
    return "high"
