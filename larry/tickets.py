"""Turn raw Jira REST issue JSON into the small Ticket shape the rules work with."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .sla import SlaClock, parse_sla


@dataclass
class Ticket:
    key: str
    summary: str
    status: str
    priority: str
    assignee: str | None
    assignee_id: str | None
    updated: datetime
    url: str
    slas: list[SlaClock] = field(default_factory=list)
    linked_requests: list[str] = field(default_factory=list)
    sla_source: str | None = None  # key of the issue the SLA clocks came from


def parse_jira_time(value: str) -> datetime:
    # Jira sends e.g. 2026-08-14T10:22:31.123-0400; fromisoformat wants -04:00.
    if len(value) > 5 and value[-5] in "+-" and value[-3] != ":":
        value = f"{value[:-2]}:{value[-2:]}"
    return datetime.fromisoformat(value)


def linked_keys(fields: dict, link_types: list[str], projects: list[str]) -> list[str]:
    keys = []
    for link in fields.get("issuelinks") or []:
        if link_types and link.get("type", {}).get("name") not in link_types:
            continue
        other = link.get("outwardIssue") or link.get("inwardIssue")
        if not other:
            continue
        key = other.get("key", "")
        if projects and key.split("-")[0] not in projects:
            continue
        keys.append(key)
    return keys


def ticket_from_issue(
    issue: dict,
    base_url: str,
    sla_fields: list[str],
    link_types: list[str] | None = None,
    link_projects: list[str] | None = None,
) -> Ticket:
    f = issue.get("fields", {})
    assignee = f.get("assignee") or {}
    slas = [c for c in (parse_sla(f.get(fid)) for fid in sla_fields) if c]
    return Ticket(
        key=issue["key"],
        summary=f.get("summary", ""),
        status=(f.get("status") or {}).get("name", ""),
        priority=(f.get("priority") or {}).get("name", ""),
        assignee=assignee.get("displayName"),
        assignee_id=assignee.get("accountId"),
        updated=parse_jira_time(f["updated"]),
        url=f"{base_url}/browse/{issue['key']}",
        slas=slas,
        linked_requests=linked_keys(f, link_types or [], link_projects or []),
        sla_source=issue["key"] if slas else None,
    )
