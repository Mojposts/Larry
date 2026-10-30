# Larry

Larry reviews Jira board tickets and service desk requests against our SLAs and tells the team who needs a follow-up: the **client** (e.g. UAT sign-off we're waiting on) or **us** (a developer or QA nudge). It's an RD Day project (October 2026, "Choose Your Own Adventure"), piloted on the **Kinaxis 2026 Support & Maintenance** board (`KIN26SUP`).

Larry only **reads** Jira. It never edits tickets, and it prints a preview unless you pass `--send`.

## How it works

1. **Fetch** open tickets for each board in the config (one JQL query per board).
2. **Borrow the SLA clock.** Client boards like `KIN26SUP` have no SLA fields; the SLA lives on the linked FSI Service Desk request (`FSISD`, link type *Problem/Incident*). Larry follows that link and reads the JSM SLA fields:
   - `customfield_10045`: Time to resolution
   - `customfield_10046`: Time to first response
3. **Apply status rules.** Each status says who owes the next step and how long it can sit idle (business days since the last update):

   | Status | Waiting on | Remind after | Escalate after |
   | --- | --- | --- | --- |
   | Ready for Client UAT | client | 3 | 10 |
   | QA | team | 2 | 5 |
   | In Progress | team | 5 | 10 |
   | Selected for Development | team | 10 | 20 |
   | Backlog | ignored | | |

   Highest/Urgent tickets use half those thresholds and High uses ¾.
4. **Flag SLA risk.** A ticket is *at risk* with under 25% of its SLA goal (or under 4 hours) left, and *breached* once it's past due. Paused SLA clocks are skipped.
5. **Post one digest per board**, split into "Waiting on the client" and "Waiting on us", grouped by assignee (with Slack @mentions if mapped), most urgent first:

   🔴 SLA breached · 🟠 escalate (idle well past the limit) · 🟡 SLA at risk · ⚪ reminder

## Run it

Requires Python 3.11+ and no third-party packages.

```bash
export JIRA_EMAIL=you@fenix-solutions.com
export JIRA_API_TOKEN=...   # https://id.atlassian.com/manage-profile/security/api-tokens

python -m larry scan                       # preview the digest in the terminal
python -m larry scan --json                # machine-readable findings
python -m larry scan --send                # post to Slack (needs SLACK_BOT_TOKEN or SLACK_WEBHOOK_URL)
python -m larry scan --from-file snap.json # run offline against a saved snapshot
```

## Configure

Everything is in [`config/kinaxis.toml`](config/kinaxis.toml): JQL per board, status rules, SLA thresholds, priority multipliers, the Slack channel and the Jira-to-Slack user mapping. To add another client, copy the `[[boards]]` block with that project's JQL and statuses. An FSISD service desk board (Pending = waiting on the client) is included but commented out.

## Schedule it

`.github/workflows/reminders.yml` runs the scan from GitHub Actions. Add the repo secrets `JIRA_EMAIL`, `JIRA_API_TOKEN` and `SLACK_BOT_TOKEN` (or `SLACK_WEBHOOK_URL`), then trigger it manually (preview by default). The weekday 9am schedule is commented out until the rules and channel are agreed.

## Tests

```bash
pip install pytest && python -m pytest -q
```

## Ideas for next steps

- Use the last *public comment* time instead of `updated`, so bulk edits don't reset the idle clock.
- Draft the actual client follow-up message with Claude, ready to paste into the service desk request.
- Send personal Slack DMs to each assignee as well as the channel digest.
- Weekly trend report: breaches per client and average time in "Ready for Client UAT".
