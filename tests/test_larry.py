from datetime import datetime, timezone

from larry.cli import FileSource, scan
from larry.config import parse_config
from larry.report import render_digest
from larry.rules import business_days_between
from larry.sla import format_duration, parse_sla

NOW = datetime(2026, 10, 30, 13, 0, tzinfo=timezone.utc)  # a Friday

CONFIG = {
    "jira": {
        "base_url": "https://example.atlassian.net",
        "sla_fields": ["customfield_10045"],
        "sla_link_types": ["Problem/Incident"],
        "sla_link_projects": ["SD"],
    },
    "priority_multipliers": {"Urgent": 0.5},
    "slack": {"users": {"Dana Dev": "U123"}},
    "boards": [
        {
            "name": "Support",
            "jql": "project = SUP",
            "follow_linked_sla": True,
            "statuses": {
                "Ready for Client UAT": {
                    "waiting_on": "client",
                    "remind_after_days": 3,
                    "escalate_after_days": 10,
                    "action": "Chase sign-off",
                },
                "In Progress": {"waiting_on": "team", "remind_after_days": 5},
                "Backlog": {"waiting_on": "ignore"},
            },
        }
    ],
}


def sla_field(remaining_ms, goal_ms=288_000_000, breached=None, paused=False):
    return {
        "name": "Time to resolution",
        "ongoingCycle": {
            "breached": remaining_ms < 0 if breached is None else breached,
            "paused": paused,
            "goalDuration": {"millis": goal_ms},
            "remainingTime": {"millis": remaining_ms},
            "breachTime": {"epochMillis": 1793000000000},
        },
    }


def issue(key, status, updated, priority="Standard", assignee="Dana Dev", links=None, **extra):
    fields = {
        "summary": f"{key} summary",
        "status": {"name": status},
        "priority": {"name": priority},
        "assignee": {"displayName": assignee, "accountId": f"acc-{assignee}"} if assignee else None,
        "updated": updated,
        "issuelinks": links or [],
    }
    fields.update(extra)
    return {"key": key, "fields": fields}


def link(key, type_name="Problem/Incident"):
    return {"type": {"name": type_name}, "outwardIssue": {"key": key}}


class Source(FileSource):
    def __init__(self, data):
        self.data = data


def run(issues, linked=()):
    config = parse_config(CONFIG)
    [(board, findings)] = scan(config, Source({"Support": issues, "_linked": list(linked)}), NOW)
    return {f.ticket.key: f for f in findings}


def test_parse_sla_and_duration():
    clock = parse_sla(sla_field(-90_000_000))
    assert clock.breached and clock.remaining_ms == -90_000_000
    assert format_duration(clock.remaining_ms) == "1d 1h"
    assert parse_sla({"name": "x", "completedCycles": []}) is None


def test_business_days_skip_weekend():
    fri = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    mon = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
    assert round(business_days_between(fri, mon), 2) == 1.0


def test_status_rules_and_ignore():
    found = run([
        issue("SUP-1", "Ready for Client UAT", "2026-10-20T09:00:00.000-0400"),  # 8 bd -> remind
        issue("SUP-2", "Ready for Client UAT", "2026-10-01T09:00:00.000-0400"),  # >10 bd -> escalate
        issue("SUP-3", "In Progress", "2026-10-28T09:00:00.000-0400"),  # fresh
        issue("SUP-4", "Backlog", "2026-01-01T09:00:00.000-0500"),  # ignored
    ])
    assert set(found) == {"SUP-1", "SUP-2"}
    assert found["SUP-1"].level == "remind" and found["SUP-1"].waiting_on == "client"
    assert found["SUP-2"].level == "escalate"


def test_priority_multiplier_nudges_sooner():
    found = run([issue("SUP-5", "In Progress", "2026-10-27T09:00:00.000-0400", priority="Urgent")])
    assert "SUP-5" in found  # 3 business days >= 5 * 0.5


def test_linked_sla_is_borrowed():
    linked = [
        {"key": "SD-9", "fields": {"summary": "req", "status": {"name": "Pending"},
                                    "updated": "2026-10-29T09:00:00.000-0400",
                                    "customfield_10045": sla_field(-3_600_000)}},
        {"key": "SD-10", "fields": {"summary": "req", "status": {"name": "To Do"},
                                     "updated": "2026-10-29T09:00:00.000-0400",
                                     "customfield_10045": sla_field(3_600_000)}},
        {"key": "SD-11", "fields": {"summary": "req", "status": {"name": "Pending"},
                                     "updated": "2026-10-29T09:00:00.000-0400",
                                     "customfield_10045": sla_field(-3_600_000, paused=True)}},
    ]
    found = run(
        [
            issue("SUP-6", "In Progress", "2026-10-29T09:00:00.000-0400", links=[link("SD-9")]),
            issue("SUP-7", "In Progress", "2026-10-29T09:00:00.000-0400", links=[link("SD-10")]),
            issue("SUP-8", "In Progress", "2026-10-29T09:00:00.000-0400", links=[link("SD-11")]),
            issue("SUP-9", "In Progress", "2026-10-29T09:00:00.000-0400", links=[link("SD-9", "Relates")]),
        ],
        linked,
    )
    assert found["SUP-6"].level == "sla_breached"
    assert "via SD-9" in found["SUP-6"].reasons[0]
    assert found["SUP-7"].level == "sla_at_risk"
    assert "SUP-8" not in found  # paused clock is not nagged about
    assert "SUP-9" not in found  # link type not configured


def test_digest_groups_and_mentions():
    config = parse_config(CONFIG)
    findings = list(run([
        issue("SUP-1", "Ready for Client UAT", "2026-10-01T09:00:00.000-0400"),
        issue("SUP-2", "In Progress", "2026-10-01T09:00:00.000-0400", assignee=None),
    ]).values())
    text = render_digest(findings, "Support", config.slack_users)
    assert "Waiting on the client" in text and "Waiting on us" in text
    assert "<@U123>" in text and "Unassigned" in text
    assert "<https://example.atlassian.net/browse/SUP-1|SUP-1>" in text
    assert render_digest([], "Support").endswith(":tada:")
