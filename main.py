"""PR Newsjacking Pipeline — Entry Point

Usage:
    python main.py                     # Run all clients
    python main.py "Client Name"       # Run single client
    python main.py --schedule          # Run on weekday schedule (M-F)
    python main.py --dry-run "Name"    # Fetch news only, no agents
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

import httpx

from config import load_clients, SLACK_BOT_TOKEN
from crew import run_all_clients, run_client
from filters import articles_to_payload, fetch_and_filter

MONITORING_CHANNEL = os.environ.get("SLACK_MONITORING_CHANNEL", "YOUR_MONITORING_CHANNEL_ID")


def _post_daily_summary(results: list[dict], elapsed: float) -> None:
    grouped: dict[str, list[str]] = {"SUCCESS": [], "NO_QUALIFYING_ANGLES": [], "NO_NEWS": [], "ERROR": []}
    for r in results:
        grouped.setdefault(r["status"], []).append(r["client"])

    lines = [f"📊 *Daily Pipeline Summary — {date.today().isoformat()}*\n"]
    icons = {"SUCCESS": "✅", "NO_QUALIFYING_ANGLES": "🟡", "NO_NEWS": "📭", "ERROR": "🔴"}
    labels = {"SUCCESS": "SUCCESS", "NO_QUALIFYING_ANGLES": "NO QUALIFYING ANGLES",
              "NO_NEWS": "NO NEWS", "ERROR": "ERRORS"}

    for status, icon in icons.items():
        if grouped[status]:
            names = ", ".join(sorted(grouped[status]))
            lines.append(f"{icon} *{len(grouped[status])} {labels[status]}* — {names}")

    minutes, seconds = int(elapsed // 60), int(elapsed % 60)
    lines.append(f"\n⏱️ Runtime: {minutes}m {seconds}s")

    try:
        httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": MONITORING_CHANNEL, "text": "\n".join(lines), "unfurl_links": False},
            timeout=10,
        )
    except Exception as e:
        print(f"[summary] Failed to post daily summary: {e}")


def dry_run(client_filter: str) -> None:
    clients = load_clients()
    matches = [c for c in clients if client_filter.lower() in c.name.lower()]
    if not matches:
        print(f"No clients matching '{client_filter}'")
        sys.exit(1)

    for client in matches:
        print(f"{'='*60}\nDRY RUN: {client.name} ({client.industry})\n{'='*60}")
        result = fetch_and_filter(client)
        print(f"Status: {result.status} | Articles: {result.total_found}")
        for i, a in enumerate(result.articles[:5], 1):
            print(f"  {i}. [{a.publish_date}] {a.outlet_name} — {a.title[:70]}")


def run(client_filter: str | None = None) -> None:
    start = datetime.now(timezone.utc)
    print(f"PR Newsjacking Pipeline — {date.today().isoformat()}")
    print(f"Started: {start.strftime('%H:%M:%S UTC')}")

    results = run_all_clients(client_filter)

    end = datetime.now(timezone.utc)
    elapsed = (end - start).total_seconds()

    counts = {s: sum(1 for r in results if r["status"] == s)
              for s in ["SUCCESS", "NO_QUALIFYING_ANGLES", "NO_NEWS", "ERROR"]}
    print(f"\nPIPELINE COMPLETE — {elapsed:.0f}s")
    print(f"  {counts['SUCCESS']} success, {counts['NO_QUALIFYING_ANGLES']} no angles, "
          f"{counts['NO_NEWS']} no news, {counts['ERROR']} errors")

    os.makedirs("output", exist_ok=True)
    output_file = f"output/{date.today().isoformat()}_{client_filter or 'all'}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved: {output_file}")

    _post_daily_summary(results, elapsed)


def main() -> None:
    parser = argparse.ArgumentParser(description="PR Newsjacking Pipeline")
    parser.add_argument("client", nargs="?", help="Client name filter")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--schedule", action="store_true", help="Skip weekends")
    args = parser.parse_args()

    if args.schedule and datetime.now().weekday() >= 5:
        print("Weekend — skipping.")
        sys.exit(0)

    if args.dry_run:
        if not args.client:
            print("--dry-run requires a client name")
            sys.exit(1)
        dry_run(args.client)
    else:
        run(args.client)


if __name__ == "__main__":
    main()
