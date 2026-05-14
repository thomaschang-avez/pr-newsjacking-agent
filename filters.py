import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from config import BLOCKED_DOMAINS, SLACK_BOT_TOKEN, ClientConfig

ARTICLE_CAP = 10
RECENCY_DAYS = 7
SLACK_LINK_REGEX = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")

TIER_1_DOMAINS = {
    "wsj.com", "bloomberg.com", "cnbc.com", "nytimes.com", "ft.com",
    "fortune.com", "reuters.com", "apnews.com", "barrons.com",
    "theinformation.com", "fastcompany.com", "businessinsider.com",
    "axios.com", "techcrunch.com", "forbes.com", "wired.com",
    "washingtonpost.com", "politico.com", "time.com", "theatlantic.com",
}

_VALID_DOMAIN_REGEX = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,24}$")


@dataclass
class Article:
    title: str
    source_url: str
    outlet_name: str
    publish_date: str
    snippet: str


@dataclass
class FilterResult:
    status: str  # HAS_NEWS | NO_NEWS
    client_name: str
    client_industry: str
    articles: list[Article]
    article_count: int
    total_found: int
    message: str | None = None


def _is_blocked(url: str) -> bool:
    url_lower = url.lower()
    return any(domain in url_lower for domain in BLOCKED_DOMAINS)


def _is_tier1(outlet: str) -> bool:
    return any(t in outlet for t in TIER_1_DOMAINS)


def _extract_outlet(url: str) -> str:
    stripped = re.sub(r"https?://(www\.)?", "", url, flags=re.IGNORECASE)
    domain = stripped.split("/")[0].split("?")[0].split("#")[0].strip().lower()
    return domain if _VALID_DOMAIN_REGEX.match(domain) else ""


def _slack_get(url: str, headers: dict, params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            resp = httpx.get(url, headers=headers, params=params, timeout=15)
            data = resp.json()
            if data.get("error") == "ratelimited":
                wait = int(resp.headers.get("Retry-After", 5))
                print(f"[filters] Rate limited — waiting {wait}s")
                time.sleep(wait)
                continue
            return data
        except Exception as e:
            print(f"[filters] Request exception (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2)
    return {}


def _read_channel_history(channel_id: str, oldest_ts: float) -> list[dict]:
    url = "https://slack.com/api/conversations.history"
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    params = {"channel": channel_id, "oldest": str(oldest_ts), "limit": 200}
    messages = []

    data = _slack_get(url, headers, params)
    if not data or not data.get("ok"):
        print(f"[filters] Error for channel {channel_id}: {data.get('error') if data else 'no response'}")
        return []

    messages.extend(data.get("messages", []))
    while data.get("has_more"):
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
        params["cursor"] = cursor
        time.sleep(0.5)
        data = _slack_get(url, headers, params)
        if not data or not data.get("ok"):
            break
        messages.extend(data.get("messages", []))

    return messages


def _extract_articles(messages: list[dict], cutoff_ts: float) -> list[Article]:
    seen_urls: set[str] = set()
    articles: list[Article] = []

    for msg in messages:
        ts = float(msg.get("ts", 0))
        if ts < cutoff_ts:
            continue

        text = msg.get("text", "")
        clean_text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2", text)
        clean_text = re.sub(r"[*_\s]+", " ", clean_text).strip()

        candidates: list[tuple[str, str, str]] = []

        for match in SLACK_LINK_REGEX.finditer(text):
            candidates.append((match.group(1).strip(), match.group(2).strip(), clean_text))

        for attachment in msg.get("attachments", []):
            att_title = attachment.get("title", "").strip()
            att_title_link = attachment.get("title_link", "").strip()
            att_text = attachment.get("text", "").strip()
            snippet = att_text or attachment.get("fallback", "").strip() or clean_text
            if att_title_link:
                candidates.append((att_title_link, att_title or clean_text[:80], snippet))
            for match in SLACK_LINK_REGEX.finditer(att_text):
                candidates.append((match.group(1).strip(), match.group(2).strip(), snippet))

        for url, title, snippet in candidates:
            if url in seen_urls or not url.startswith("http"):
                continue
            if _is_blocked(url):
                continue
            outlet = _extract_outlet(url)
            if not outlet:
                continue
            seen_urls.add(url)
            articles.append(Article(
                title=title[:200].strip(),
                source_url=url,
                outlet_name=outlet,
                publish_date=datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                snippet=snippet[:500].strip(),
            ))

    return articles


def fetch_and_filter(client: ClientConfig) -> FilterResult:
    cutoff_ts = time.time() - (RECENCY_DAYS * 24 * 60 * 60)
    all_messages: list[dict] = []
    for channel_id in client.muck_rack_channel_ids:
        all_messages.extend(_read_channel_history(channel_id, cutoff_ts))
        time.sleep(1)

    if not all_messages:
        return FilterResult(status="NO_NEWS", client_name=client.name,
                            client_industry=client.industry, articles=[], article_count=0,
                            total_found=0, message="No qualifying articles found in the past 7 days.")

    articles = _extract_articles(all_messages, cutoff_ts)
    if not articles:
        return FilterResult(status="NO_NEWS", client_name=client.name,
                            client_industry=client.industry, articles=[], article_count=0,
                            total_found=0, message="No qualifying articles found in the past 7 days.")

    articles.sort(key=lambda a: (0 if _is_tier1(a.outlet_name) else 1, a.publish_date))
    limited = articles[:ARTICLE_CAP]

    return FilterResult(status="HAS_NEWS", client_name=client.name, client_industry=client.industry,
                        articles=limited, article_count=len(limited), total_found=len(articles))


def articles_to_payload(articles: list[Article]) -> str:
    return json.dumps([{
        "title": a.title, "source_url": a.source_url, "outlet_name": a.outlet_name,
        "publish_date": a.publish_date, "snippet": a.snippet,
    } for a in articles])
