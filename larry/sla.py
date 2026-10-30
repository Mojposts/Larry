"""Parse Jira Service Management SLA fields into something we can reason about."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class SlaClock:
    name: str
    breached: bool
    paused: bool
    goal_ms: int
    remaining_ms: int
    breach_time: datetime | None

    @property
    def fraction_left(self) -> float:
        """Share of the goal still remaining (negative once breached)."""
        if self.goal_ms <= 0:
            return 0.0
        return self.remaining_ms / self.goal_ms


def _epoch(value: dict | None) -> datetime | None:
    if not value or "epochMillis" not in value:
        return None
    return datetime.fromtimestamp(value["epochMillis"] / 1000, tz=timezone.utc)


def parse_sla(raw: dict | None) -> SlaClock | None:
    """Return the ongoing cycle of an SLA field, or None when the clock has stopped.

    Jira returns SLA fields as ``{"name": ..., "ongoingCycle": {...}, "completedCycles": [...]}``.
    Only the ongoing cycle tells us whether the ticket still needs attention.
    """
    if not raw or not isinstance(raw, dict):
        return None
    cycle = raw.get("ongoingCycle")
    if not cycle:
        return None
    return SlaClock(
        name=raw.get("name", "SLA"),
        breached=bool(cycle.get("breached")),
        paused=bool(cycle.get("paused")),
        goal_ms=int((cycle.get("goalDuration") or {}).get("millis", 0)),
        remaining_ms=int((cycle.get("remainingTime") or {}).get("millis", 0)),
        breach_time=_epoch(cycle.get("breachTime")),
    )


def format_duration(ms: int) -> str:
    """Human-friendly duration such as ``3d 4h`` or ``45m``."""
    minutes = abs(ms) // 60_000
    days, rem = divmod(minutes, 60 * 24)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{mins}m"
