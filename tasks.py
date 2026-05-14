from datetime import date
from crewai import Agent, Task
from config import ClientConfig
from filters import Article


def build_pr6_task(agent: Agent, client: ClientConfig, articles: list[Article]) -> Task:
    """PR-6: Score articles, return only 7+ qualifiers."""
    articles_block = "\n".join(
        f"- TITLE: {a.title}\n  SOURCE_URL: {a.source_url}\n  OUTLET: {a.outlet_name}\n"
        f"  PUBLISH_DATE: {a.publish_date}\n  SNIPPET: {a.snippet[:300]}"
        for a in articles
    )

    doc_context = f"Pitchbook: {client.pitchbook_url}"
    if client.has_faq:
        doc_context += f"\nFAQ: {client.faq_url}"
    doc_context += f"\nStrategy: {client.strategy_url}"

    return Task(
        description=(
            f"Evaluate newsjacking opportunities for {client.name} in the {client.industry} space.\n\n"
            f"CLIENT DOCUMENTS (use Glean Document Reader):\n{doc_context}\n\n"
            f"NEWS ARTICLES TO SCORE:\n{articles_block}\n\n"
            f"SCORING CRITERIA — all four must be evaluated for every article:\n"
            f"1. EXTERNAL SOURCE ONLY: PR wires, Google Docs, press release domains — score 0, auto-disqualify.\n"
            f"2. PITCHBOOK VALUE PROP CONNECTION: Must connect to a SPECIFIC named value prop from {client.name}'s pitchbook.\n"
            f"3. RECENCY: Published within 7 days? Articles older than 7 days cannot score above 6.\n"
            f"4. JOURNALIST CREDIBILITY TEST: Would a real journalist at WSJ, Bloomberg, Fortune, CNBC, NYT write a follow-up?\n\n"
            f"SCORING RUBRIC:\n"
            f"Score 0: Internal source — auto-disqualified\n"
            f"Score 1-4: Loosely related to {client.industry}, no specific value prop connection\n"
            f"Score 5-6: Industry relevant but not tight enough to pitch\n"
            f"Score 7-8: Directly ties to specific {client.name} value prop, credible outlet, within 7 days\n"
            f"Score 9-10: Breaking news in {client.name}'s exact wheelhouse, pitch-ready today\n\n"
            f"SELECTION RULES: Return ONLY articles scoring 7+. Maximum 3 angles. "
            f"If zero qualify, return NO_QUALIFYING_ANGLES."
        ),
        expected_output=(
            "For each qualifying angle (7+ score):\n\n"
            "ANGLE [number]:\n"
            "HEADLINE: [original article headline]\n"
            "SOURCE_URL: [URL from the articles above ONLY]\n"
            "OUTLET: [publication name]\n"
            "PUBLISH_DATE: [article publish date]\n"
            "RELEVANCE_SCORE: [integer 7-10]\n"
            f"CLIENT_ANGLE: [2-3 sentences connecting to a SPECIFIC {client.name} value prop]\n"
            "TALKING_POINT: [1-2 sentences a spokesperson could say]\n\n"
            "If zero angles qualified output exactly:\nNO_QUALIFYING_ANGLES"
        ),
        agent=agent,
    )


def build_pr7_task(agent: Agent, client: ClientConfig) -> Task:
    """PR-7: Media list builder. Find reporters for each qualifying angle."""
    return Task(
        description=(
            f"Match newsjacking angles for {client.name} to the best reporters.\n\n"
            f"1. Search Glean for {client.name}'s media lists.\n"
            f"2. For each qualifying angle, identify up to 5 reporters.\n\n"
            f"TIER 1 — Always lead with these. Minimum 2 per angle:\n"
            f"WSJ, Bloomberg, CNBC, NYT, FT, Fortune, Reuters, AP, Barron's, "
            f"The Information, Fast Company, Business Insider, Axios, TechCrunch\n\n"
            f"TIER 2 — Only after Tier 1 slots filled:\n"
            f"Industry trades relevant to {client.industry} only\n\n"
            f"NEVER include opinion columnists, contributors, or PR sources.\n"
            f"VERIFIED reporters from existing media list always rank above web-sourced.\n\n"
            f"If the previous step output NO_QUALIFYING_ANGLES, pass through unchanged."
        ),
        expected_output=(
            "For each angle:\n\n"
            "ANGLE [number]:\n"
            "HEADLINE: [from previous step]\n"
            "SOURCE_URL: [from previous step]\n"
            "RELEVANCE_SCORE: [from previous step]\n"
            "CLIENT_ANGLE: [from previous step]\n"
            "TALKING_POINT: [from previous step]\n"
            "REPORTERS:\n"
            "1. NAME: [name] | OUTLET: [outlet] | BEAT: [beat] | "
            "EMAIL: [email or not_available] | STATUS: [VERIFIED or UNVERIFIED]\n"
            "[up to 5 reporters per angle]\n\n"
            "If fewer than 2 Tier 1 reporters found, add warning flag.\n"
            "If input was NO_QUALIFYING_ANGLES output exactly: NO_QUALIFYING_ANGLES"
        ),
        agent=agent,
    )


def build_pr7_supplement_task(agent: Agent, client: ClientConfig) -> Task:
    """PR-7 supplement: Web search for additional Tier 1 reporters."""
    return Task(
        description=(
            f"Search the web for journalists who have covered {client.name}'s angle topics in the past 90 days.\n\n"
            f"ONLY run if the previous step flagged fewer than 2 Tier 1 reporters. "
            f"If the media list is sufficient, output: \"No additional search needed\"\n\n"
            f"If input was NO_QUALIFYING_ANGLES, output: NO_QUALIFYING_ANGLES\n\n"
            f"For each journalist include: Full name, Outlet, Specific beat, Link to a recent article."
        ),
        expected_output=(
            "SUPPLEMENT FOR ANGLE [number]:\n"
            "1. NAME: [name] | OUTLET: [outlet] | BEAT: [beat] | ARTICLE: [url]\n\n"
            "If media list was sufficient: \"No additional search needed\"\n"
            "If input was NO_QUALIFYING_ANGLES: NO_QUALIFYING_ANGLES"
        ),
        agent=agent,
    )


def build_pr8_task(agent: Agent, client: ClientConfig) -> Task:
    """PR-8: Draft personalized pitches for each angle x reporter pair."""
    return Task(
        description=(
            f"Draft newsjacking pitch emails for {client.name} in the {client.industry} space.\n\n"
            f"CLIENT DOCUMENT (use Glean Document Reader): Pitchbook: {client.pitchbook_url}\n\n"
            f"For EACH angle, for EACH reporter (up to 5), draft ONE pitch email.\n\n"
            f"PITCH FORMAT — 4 paragraphs maximum:\n"
            f"P1 — THE HOOK: Open with the industry trend the news signals. Do NOT cite the specific article.\n"
            f"P2 — THE ANGLE: Connect the trend to {client.name}'s specific value proposition.\n"
            f"P3 — THE TALKING POINT: Offer a specific data point from the pitchbook.\n"
            f"P4 — THE ASK: Clear direct ask. One sentence. Offer availability.\n\n"
            f"RULES: Max 4 paragraphs. Never fabricate quotes or stats. "
            f"Never cite internal documents. Personalize each pitch to reporter's beat."
        ),
        expected_output=(
            "Output ONLY valid JSON. No markdown. No code fences.\n\n"
            "{\n"
            f'  "client": "{client.name}",\n'
            f'  "run_date": "{date.today().isoformat()}",\n'
            '  "angles": [\n'
            "    {\n"
            '      "headline": "...", "source_url": "...", "outlet": "...",\n'
            '      "relevance_score": 0, "client_angle": "...", "talking_point": "...",\n'
            '      "media_list": [\n'
            "        {\n"
            '          "reporter": "...", "outlet": "...", "beat": "...",\n'
            '          "email": "...", "verified": true,\n'
            '          "subject_line": "...", "pitch": "full 4-paragraph pitch"\n'
            "        }\n"
            "      ]\n"
            "    }\n"
            "  ]\n"
            "}"
        ),
        agent=agent,
    )
