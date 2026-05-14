# PR Newsjacking Pipeline

Automated PR newsjacking pipeline. Monitors Muck Rack Slack channels across all clients, scores articles against client pitchbooks, matches Tier 1 reporters, drafts personalized pitch emails, creates Google Docs, and posts daily Slack summaries.

Runs Monday–Friday on a schedule. All inference routes through Gemini via Vertex AI — client data stays in the enterprise environment.

## Architecture

Four sequential CrewAI agents per client:

```
Muck Rack Slack channels
  → filters.py       Article extraction + deduplication (cap 10/client)
  → PR-6 Agent       Score articles 1–10 against pitchbook, select top 3 at 7+
  → PR-7 Agent       Match named Tier 1 reporters from internal media lists
  → PR-7s Agent      Web search supplement if <2 Tier 1 reporters found
  → PR-8 Agent       Draft personalized 4-paragraph pitches per angle × reporter
  → crew.py          Create Google Doc + post Slack summary
```

## Scoring Criteria (PR-6)

All four evaluated per article:

1. **External source only** — PR wires and aggregators auto-disqualified
2. **Pitchbook value prop connection** — must tie to a specific named value prop
3. **Recency** — articles older than 7 days cannot score above 6
4. **Journalist credibility** — would a WSJ/Bloomberg/CNBC reporter write a follow-up?

## Output States

| State | Meaning |
|-------|---------|
| `SUCCESS` | 1+ angles scored 7+/10 — Slack alert + Google Doc with full pitches |
| `NO_QUALIFYING_ANGLES` | Articles found but none met the threshold |
| `NO_NEWS` | Zero articles in the past 7 days |
| `ERROR` | Pipeline exception — on-call engineer notified |

## Stack

- Python, CrewAI
- Gemini 2.5 Flash via Vertex AI (custom `GeminiLLM` class)
- Glean API (enterprise search + document reader)
- Slack API (Muck Rack channel monitoring + notifications)
- Google Drive API (pitch doc creation)
- Google Sheets (client config)
- Serper.dev (web search supplement)

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in all values in .env

# Single client
python main.py "Client Name"

# All clients
python main.py

# Fetch news only, no agents
python main.py --dry-run "Client Name"

# Weekday-only schedule mode
python main.py --schedule
```

## Client Configuration

Clients are loaded from a Google Sheet with columns:
`Client Name | Industry | MR Client News ID | MR Industry News ID | MR Competitors ID | Output Channel ID | Pitchbook URL | FAQ URL | Strategy URL`

Each client gets 3–4 dedicated Muck Rack Slack channels monitored by the pipeline.

## Files

| File | Purpose |
|------|---------|
| `config.py` | Env config, `ClientConfig` dataclass, Google Sheets loader, blocked domain list |
| `filters.py` | Reads Muck Rack Slack channels, extracts article links, dedupes, caps at 10 |
| `agents.py` | `GeminiLLM` custom LLM class + four agent builders |
| `tasks.py` | Task builders with full scoring rubrics, reporter standards, JSON output schemas |
| `crew.py` | Orchestrates full pipeline per client, Google Doc creation, Slack notifications |
| `main.py` | CLI entry point — single client, all clients, dry-run, schedule modes |
| `tools.py` | CrewAI tool wrappers: Glean Search, Glean Document Reader, Web Search, Slack |
