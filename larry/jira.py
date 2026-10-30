"""Minimal read-only Jira Cloud REST client (stdlib only)."""

from __future__ import annotations

import base64
import json
import urllib.request

BASE_FIELDS = ["summary", "status", "priority", "assignee", "updated", "issuelinks"]


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.timeout = timeout

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode(),
            headers=self.headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    def search(self, jql: str, fields: list[str], page_size: int = 100) -> list[dict]:
        """Return every issue matching ``jql`` (follows nextPageToken)."""
        issues: list[dict] = []
        token = None
        while True:
            body = {"jql": jql, "fields": fields, "maxResults": page_size}
            if token:
                body["nextPageToken"] = token
            page = self._post("/rest/api/3/search/jql", body)
            issues.extend(page.get("issues", []))
            token = page.get("nextPageToken")
            if page.get("isLast", True) or not token:
                return issues
