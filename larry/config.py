"""Load the TOML config that describes boards, status rules and who gets reminded."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

WAITING_ON = {"client", "team", "ignore"}


@dataclass
class StatusRule:
    waiting_on: str
    remind_after_days: float
    escalate_after_days: float | None = None
    action: str = ""


@dataclass
class Board:
    name: str
    jql: str
    statuses: dict[str, StatusRule]
    follow_linked_sla: bool = False
    slack_channel: str | None = None


@dataclass
class Config:
    jira_base_url: str
    sla_fields: list[str]
    sla_link_types: list[str]
    sla_link_projects: list[str]
    at_risk_fraction: float
    at_risk_hours: float
    priority_multipliers: dict[str, float]
    business_days: bool
    boards: list[Board]
    slack_channel: str | None
    slack_users: dict[str, str] = field(default_factory=dict)


def _status_rule(name: str, raw: dict) -> StatusRule:
    waiting_on = raw.get("waiting_on", "team")
    if waiting_on not in WAITING_ON:
        raise ValueError(f"status '{name}': waiting_on must be one of {sorted(WAITING_ON)}")
    return StatusRule(
        waiting_on=waiting_on,
        remind_after_days=float(raw.get("remind_after_days", 3)),
        escalate_after_days=(
            float(raw["escalate_after_days"]) if "escalate_after_days" in raw else None
        ),
        action=raw.get("action", ""),
    )


def parse_config(data: dict) -> Config:
    jira = data.get("jira", {})
    sla = data.get("sla", {})
    slack = data.get("slack", {})
    boards = [
        Board(
            name=b["name"],
            jql=b["jql"],
            statuses={k: _status_rule(k, v) for k, v in b.get("statuses", {}).items()},
            follow_linked_sla=bool(b.get("follow_linked_sla", False)),
            slack_channel=b.get("slack_channel"),
        )
        for b in data.get("boards", [])
    ]
    if not boards:
        raise ValueError("config needs at least one [[boards]] entry")
    return Config(
        jira_base_url=jira.get("base_url", "").rstrip("/"),
        sla_fields=list(jira.get("sla_fields", [])),
        sla_link_types=list(jira.get("sla_link_types", [])),
        sla_link_projects=list(jira.get("sla_link_projects", [])),
        at_risk_fraction=float(sla.get("at_risk_fraction", 0.25)),
        at_risk_hours=float(sla.get("at_risk_hours", 4)),
        priority_multipliers={k: float(v) for k, v in data.get("priority_multipliers", {}).items()},
        business_days=bool(data.get("business_days", True)),
        boards=boards,
        slack_channel=slack.get("channel"),
        slack_users=dict(slack.get("users", {})),
    )


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as fh:
        return parse_config(tomllib.load(fh))
