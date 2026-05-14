import os
from typing import Any

import httpx
from crewai.tools import tool

from config import GLEAN_ACT_AS, GLEAN_API_TOKEN, GLEAN_SERVER_URL, SLACK_BOT_TOKEN


@tool("Glean Search")
def glean_search(query: str, datasource: str = "gdrive") -> str:
    """Search the company's Glean index for internal documents.
    Use this to find media lists, reporter contacts, and client documents.
    Args:
        query: Search keywords (e.g. 'ACME media list reporters')
        datasource: Filter to a datasource - 'gdrive', 'slack', or leave empty for all
    """
    url = f"{GLEAN_SERVER_URL}/rest/api/v1/search"
    headers = {
        "Authorization": f"Bearer {GLEAN_API_TOKEN}",
        "X-Glean-ActAs": GLEAN_ACT_AS,
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "query": query,
        "pageSize": 10,
        "maxSnippetSize": 5000,
        "requestOptions": {"returnLlmContentOverSnippets": True},
    }
    if datasource:
        payload["requestOptions"]["datasourceFilter"] = datasource

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"Glean search error: {e}"

    results = data.get("results", [])
    if not results:
        return "No results found."

    output_parts = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        doc_url = r.get("url", "")
        snippets = r.get("snippets", [])
        text = "\n".join(s.get("text", "") for s in snippets if isinstance(s, dict) and s.get("text"))
        if not text:
            text = "(no content preview available)"
        output_parts.append(f"[{i}] {title}\nURL: {doc_url}\n{text[:2000]}\n")

    return "\n---\n".join(output_parts)


@tool("Glean Document Reader")
def glean_read_document(doc_title: str, search_terms: str = "") -> str:
    """Read the content of a specific internal document via Glean search.
    Use this to read pitchbooks, FAQ docs, strategy docs, and media lists.
    Args:
        doc_title: The document title or name to find
        search_terms: Additional keywords to pull relevant sections
    """
    query = f"{doc_title} {search_terms}".strip()
    url = f"{GLEAN_SERVER_URL}/rest/api/v1/search"
    headers = {
        "Authorization": f"Bearer {GLEAN_API_TOKEN}",
        "X-Glean-ActAs": GLEAN_ACT_AS,
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "pageSize": 1,
        "maxSnippetSize": 10000,
        "requestOptions": {"datasourceFilter": "gdrive", "returnLlmContentOverSnippets": True},
    }

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"Document read error: {e}"

    results = data.get("results", [])
    if not results:
        return f"Document not found: {doc_title}"

    r = results[0]
    title = r.get("title", "Untitled")
    doc_url = r.get("url", "")
    snippets = r.get("snippets", [])
    text = "\n".join(s.get("text", "") for s in snippets if isinstance(s, dict) and s.get("text"))

    if not text:
        return f"Document found ({title}) but content could not be retrieved. URL: {doc_url}"

    return f"DOCUMENT: {title}\nURL: {doc_url}\n\n{text}"


@tool("Web Search")
def web_search(query: str) -> str:
    """Search the web for journalists, reporters, and recent articles.
    Args:
        query: Search query (e.g. 'WSJ reporter covering healthcare 2026')
    """
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        return "Web search unavailable: SERPER_API_KEY not set in .env."

    url = "https://google.serper.dev/search"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": 10}

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"Web search error: {e}"

    results = []
    for item in data.get("organic", []):
        results.append(f"- {item.get('title', '')}\n  {item.get('link', '')}\n  {item.get('snippet', '')}")

    return "\n\n".join(results) if results else "No web results found."


@tool("Post to Slack")
def post_to_slack(channel_id: str, message: str) -> str:
    """Post a message to a Slack channel.
    Args:
        channel_id: The Slack channel ID
        message: The message text to post (supports Slack markdown)
    """
    try:
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": channel_id, "text": message, "unfurl_links": False},
            timeout=10,
        )
        data = resp.json()
        return f"Message posted to {channel_id}" if data.get("ok") else f"Slack error: {data.get('error', 'unknown')}"
    except Exception as e:
        return f"Slack post error: {e}"
