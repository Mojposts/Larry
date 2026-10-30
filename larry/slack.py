"""Post a digest to Slack via a bot token (chat.postMessage) or an incoming webhook."""

from __future__ import annotations

import json
import urllib.request


def _post_json(url: str, payload: dict, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def send_digest(text: str, channel: str | None, bot_token: str | None, webhook_url: str | None) -> None:
    if bot_token:
        if not channel:
            raise ValueError("a Slack channel is required when posting with a bot token")
        body = json.loads(
            _post_json(
                "https://slack.com/api/chat.postMessage",
                {"channel": channel, "text": text, "unfurl_links": False, "mrkdwn": True},
                {"Authorization": f"Bearer {bot_token}"},
            )
        )
        if not body.get("ok"):
            raise RuntimeError(f"Slack error: {body.get('error')}")
    elif webhook_url:
        _post_json(webhook_url, {"text": text, "unfurl_links": False})
    else:
        raise ValueError("set SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL to send reminders")
