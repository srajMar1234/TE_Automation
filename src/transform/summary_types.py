"""Types for order summary builds."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SummaryMeta:
    """Observed exclusions and optional daily validation."""

    excluded_customer_groups_seen: list[str] = field(default_factory=list)
    """Distinct customer group names that were excluded because they matched exclusion rules."""

    excluded_customer_groups_reported_total: int | None = None
    """User-reported count from daily inputs, if provided."""

    reported_vs_computed_match: bool | None = None
    """True if reported total equals len(excluded_customer_groups_seen); None if not applicable."""
