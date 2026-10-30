"""Command line entry point: ``python -m larry scan --config config.toml``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from .config import Board, Config, load_config
from .jira import BASE_FIELDS, JiraClient
from .report import findings_to_json, render_digest
from .rules import evaluate_all
from .slack import send_digest
from .tickets import Ticket, ticket_from_issue


class FileSource:
    """Offline source: a JSON file of ``{"<board name>": [issues], "_linked": [issues]}``."""

    def __init__(self, path: str):
        with open(path) as fh:
            self.data = json.load(fh)

    def board_issues(self, board: Board, fields: list[str]) -> list[dict]:
        return self.data.get(board.name, [])

    def issues_by_key(self, keys: list[str], fields: list[str]) -> list[dict]:
        wanted = set(keys)
        return [i for i in self.data.get("_linked", []) if i["key"] in wanted]


class JiraSource:
    def __init__(self, client: JiraClient):
        self.client = client

    def board_issues(self, board: Board, fields: list[str]) -> list[dict]:
        return self.client.search(board.jql, fields)

    def issues_by_key(self, keys: list[str], fields: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(keys), 50):
            chunk = ", ".join(keys[i : i + 50])
            out.extend(self.client.search(f"key in ({chunk})", fields))
        return out


def attach_linked_slas(tickets: list[Ticket], source, config: Config) -> None:
    """Borrow SLA clocks from the linked service desk request for tickets that have none."""
    needed = sorted({k for t in tickets if not t.slas for k in t.linked_requests})
    if not needed:
        return
    linked = {
        i["key"]: ticket_from_issue(i, config.jira_base_url, config.sla_fields)
        for i in source.issues_by_key(needed, BASE_FIELDS + config.sla_fields)
    }
    for t in tickets:
        if t.slas:
            continue
        for key in t.linked_requests:
            req = linked.get(key)
            if req and req.slas:
                t.slas = req.slas
                t.sla_source = key
                break


def scan(config: Config, source, now: datetime) -> list[tuple[Board, list]]:
    fields = BASE_FIELDS + config.sla_fields
    results = []
    for board in config.boards:
        tickets = [
            ticket_from_issue(
                i, config.jira_base_url, config.sla_fields,
                config.sla_link_types, config.sla_link_projects,
            )
            for i in source.board_issues(board, fields)
        ]
        if board.follow_linked_sla:
            attach_linked_slas(tickets, source, config)
        results.append((board, evaluate_all(tickets, board, config, now)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="larry", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scan", help="review tickets and print (or send) follow-up reminders")
    p.add_argument("--config", default="config/kinaxis.toml")
    p.add_argument("--from-file", help="read issues from a saved JSON file instead of Jira")
    p.add_argument("--json", action="store_true", help="print findings as JSON")
    p.add_argument("--send", action="store_true", help="post the digest to Slack (default: preview only)")
    p.add_argument("--now", help="override the current time (ISO 8601), useful for tests")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)

    if args.from_file:
        source = FileSource(args.from_file)
    else:
        missing = [v for v in ("JIRA_EMAIL", "JIRA_API_TOKEN") if not os.environ.get(v)]
        if missing:
            parser.error(f"missing environment variables: {', '.join(missing)}")
        source = JiraSource(
            JiraClient(
                os.environ.get("JIRA_BASE_URL", config.jira_base_url),
                os.environ["JIRA_EMAIL"],
                os.environ["JIRA_API_TOKEN"],
            )
        )

    results = scan(config, source, now)

    if args.json:
        print(json.dumps({b.name: findings_to_json(f) for b, f in results}, indent=2))
        return 0

    for board, findings in results:
        digest = render_digest(findings, board.name, config.slack_users)
        print(digest, end="\n\n")
        if args.send:
            send_digest(
                digest,
                channel=board.slack_channel or config.slack_channel,
                bot_token=os.environ.get("SLACK_BOT_TOKEN"),
                webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
            )
            print(f"(sent to Slack: {board.slack_channel or config.slack_channel or 'webhook'})", file=sys.stderr)
    if not args.send:
        print("(preview only — pass --send to post to Slack)", file=sys.stderr)
    return 0
