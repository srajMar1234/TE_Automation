"""User-supplied inputs at runtime (web UI or API) — no YAML required for operators."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DailyExclusionInput:
    """Extra excluded customer groups for this run + optional audit count."""

    additional_excluded_customer_groups: list[str] = field(default_factory=list)
    excluded_customer_groups_reported_total: int | None = None


def parse_excluded_groups_multiline(text: str) -> list[str]:
    """One customer group name per line; ignores empty lines."""
    lines = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s:
            lines.append(s)
    return lines
