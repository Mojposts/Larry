"""Render findings as a Slack-ready digest (mrkdwn) or plain JSON."""

from __future__ import annotations

from collections import defaultdict

from .rules import Finding

ICONS = {
    "sla_breached": ":red_circle:",
    "escalate": ":large_orange_circle:",
    "sla_at_risk": ":large_yellow_circle:",
    "remind": ":white_circle:",
}

SECTION_TITLES = {
    "client": "Waiting on the client — follow up with them",
    "team": "Waiting on us — nudge the developer / QA",
}


def _mention(name: str | None, account_id: str | None, slack_users: dict[str, str]) -> str:
    if not name:
        return "Unassigned"
    slack_id = slack_users.get(account_id or "") or slack_users.get(name)
    return f"<@{slack_id}>" if slack_id else name


def _line(f: Finding) -> str:
    t = f.ticket
    title = t.summary if len(t.summary) <= 70 else t.summary[:67] + "..."
    reasons = "; ".join(f.reasons)
    action = f" → _{f.action}_" if f.action else ""
    return f"{ICONS[f.level]} <{t.url}|{t.key}> {title} · *{t.status}* · {reasons}{action}"


def render_digest(
    findings: list[Finding], board_name: str, slack_users: dict[str, str] | None = None
) -> str:
    slack_users = slack_users or {}
    if not findings:
        return f"*{board_name}*: nothing needs a follow-up today :tada:"

    counts = defaultdict(int)
    for f in findings:
        counts[f.level] += 1
    summary = ", ".join(
        f"{counts[lvl]} {lvl.replace('_', ' ')}"
        for lvl in ("sla_breached", "escalate", "sla_at_risk", "remind")
        if counts[lvl]
    )
    out = [f"*{board_name}: {len(findings)} tickets need a follow-up* ({summary})"]

    for side in ("client", "team"):
        group = [f for f in findings if f.waiting_on == side]
        if not group:
            continue
        out.append(f"\n*{SECTION_TITLES[side]}*")
        by_owner: dict[tuple, list[Finding]] = defaultdict(list)
        for f in group:
            by_owner[(f.ticket.assignee, f.ticket.assignee_id)].append(f)
        for (name, account_id), items in sorted(
            by_owner.items(), key=lambda kv: (-max(f.rank for f in kv[1]), kv[0][0] or "")
        ):
            out.append(f"{_mention(name, account_id, slack_users)} ({len(items)})")
            out.extend(f"  {_line(f)}" for f in items)
    return "\n".join(out)


def findings_to_json(findings: list[Finding]) -> list[dict]:
    return [
        {
            "key": f.ticket.key,
            "summary": f.ticket.summary,
            "status": f.ticket.status,
            "priority": f.ticket.priority,
            "assignee": f.ticket.assignee,
            "board": f.board,
            "waiting_on": f.waiting_on,
            "level": f.level,
            "idle_business_days": round(f.idle_days, 1),
            "reasons": f.reasons,
            "action": f.action,
            "url": f.ticket.url,
        }
        for f in findings
    ]
