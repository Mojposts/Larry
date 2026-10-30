"""Decide which tickets need a nudge, who owes the next step, and how loud to be."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Board, Config
from .sla import format_duration
from .tickets import Ticket

# Ordered from least to most urgent so findings can be sorted by level.
LEVELS = ["remind", "sla_at_risk", "escalate", "sla_breached"]


@dataclass
class Finding:
    ticket: Ticket
    board: str
    waiting_on: str  # "client" or "team"
    level: str
    idle_days: float
    reasons: list[str] = field(default_factory=list)
    action: str = ""

    @property
    def rank(self) -> int:
        return LEVELS.index(self.level)


def business_days_between(start: datetime, end: datetime) -> float:
    """Elapsed time in days, skipping Saturdays and Sundays."""
    if end <= start:
        return 0.0
    total = timedelta()
    cursor = start
    while cursor < end:
        next_midnight = (cursor + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        step_end = min(next_midnight, end)
        if cursor.weekday() < 5:
            total += step_end - cursor
        cursor = step_end
    return total.total_seconds() / 86400


def _bump(finding: Finding, level: str) -> None:
    if LEVELS.index(level) > finding.rank:
        finding.level = level


def evaluate(ticket: Ticket, board: Board, config: Config, now: datetime) -> Finding | None:
    rule = board.statuses.get(ticket.status)
    if rule and rule.waiting_on == "ignore":
        return None

    if config.business_days:
        idle = business_days_between(ticket.updated, now)
    else:
        idle = max((now - ticket.updated).total_seconds() / 86400, 0.0)

    multiplier = config.priority_multipliers.get(ticket.priority, 1.0)
    finding = Finding(
        ticket=ticket,
        board=board.name,
        waiting_on=rule.waiting_on if rule else "team",
        level="remind",
        idle_days=idle,
        action=rule.action if rule else "",
    )
    flagged = False

    if rule:
        remind_after = rule.remind_after_days * multiplier
        if idle >= remind_after:
            flagged = True
            finding.reasons.append(f"no update in {idle:.0f} business days")
            if rule.escalate_after_days is not None and idle >= rule.escalate_after_days * multiplier:
                _bump(finding, "escalate")

    source = f" (via {ticket.sla_source})" if ticket.sla_source and ticket.sla_source != ticket.key else ""
    for clock in ticket.slas:
        if clock.paused:
            continue
        if clock.breached or clock.remaining_ms < 0:
            flagged = True
            _bump(finding, "sla_breached")
            finding.reasons.append(
                f"{clock.name} breached {format_duration(clock.remaining_ms)} ago{source}"
            )
        elif (
            clock.fraction_left <= config.at_risk_fraction
            or clock.remaining_ms <= config.at_risk_hours * 3_600_000
        ):
            flagged = True
            _bump(finding, "sla_at_risk")
            finding.reasons.append(
                f"{clock.name} due in {format_duration(clock.remaining_ms)}{source}"
            )

    return finding if flagged else None


def evaluate_all(
    tickets: list[Ticket], board: Board, config: Config, now: datetime
) -> list[Finding]:
    findings = [f for t in tickets if (f := evaluate(t, board, config, now))]
    findings.sort(key=lambda f: (-f.rank, -f.idle_days))
    return findings
