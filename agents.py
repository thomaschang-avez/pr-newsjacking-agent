from __future__ import annotations

import json
import os
import concurrent.futures
from typing import Any

from crewai import Agent
from crewai.llm import BaseLLM
from dotenv import load_dotenv
from google import genai
from google.oauth2 import service_account
from pydantic import Field, PrivateAttr

from config import GEMINI_PROJECT, GEMINI_LOCATION, ClientConfig
from tools import glean_read_document, glean_search, post_to_slack, web_search

load_dotenv()


class GeminiLLM(BaseLLM):
    """Routes all CrewAI agent inference through Gemini via Vertex AI.
    Glean tools handle all retrieval — client data stays in the enterprise environment.
    """

    model: str = Field(default="gemini-2.5-flash")
    _client: Any = PrivateAttr()

    def model_post_init(self, __context: Any) -> None:
        service_account_json = os.environ.get("GEMINI_SERVICE_ACCOUNT")
        if service_account_json:
            creds = service_account.Credentials.from_service_account_info(
                json.loads(service_account_json),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self._client = genai.Client(
                vertexai=True, project=GEMINI_PROJECT, location=GEMINI_LOCATION, credentials=creds,
            )
        else:
            self._client = genai.Client(vertexai=True, project=GEMINI_PROJECT, location=GEMINI_LOCATION)

    def call(self, messages: str | list[dict], tools: list | None = None,
             callbacks: list | None = None, available_functions: dict[str, Any] | None = None,
             **kwargs: Any) -> str:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        system_instruction = None
        content_parts: list[str] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
            elif role == "assistant":
                content_parts.append(f"[ASSISTANT]\n{content}")
            else:
                content_parts.append(content)

        if tools:
            tool_descriptions = []
            for t in tools:
                if isinstance(t, dict):
                    func = t.get("function", t)
                    name = func.get("name", "unknown")
                    desc = func.get("description", "")
                    params = func.get("parameters", {})
                    tool_descriptions.append(f"- {name}: {desc}\n  Parameters: {params}")
            if tool_descriptions:
                content_parts.append(
                    "\n[AVAILABLE TOOLS]\n" + "\n".join(tool_descriptions) + "\n\n"
                    "To use a tool, respond with:\n"
                    "Action: <tool_name>\nAction Input: <json arguments>\n"
                )

        full_content = "\n\n".join(content_parts)
        config: dict = {"max_output_tokens": 16384}
        if system_instruction:
            config["system_instruction"] = system_instruction

        def _call_gemini():
            return self._client.models.generate_content(
                model=self.model, contents=full_content, config=config if config else None,
            )

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_gemini)
                response = future.result(timeout=150)
            return response.text
        except concurrent.futures.TimeoutError:
            return "Error: Gemini API call timed out after 150 seconds."
        except Exception as e:
            return f"Error: Gemini API call failed: {e}"

    def get_context_window_size(self) -> int:
        return 1_000_000


def create_gemini_llm() -> GeminiLLM:
    return GeminiLLM(model="gemini-2.5-flash")


def build_news_analyst(client: ClientConfig) -> Agent:
    """PR-6: Scores articles against client value props. Selects top 3 angles at 7+."""
    return Agent(
        role="Senior PR News Analyst",
        goal=(
            f"Evaluate newsjacking opportunities for {client.name} in the "
            f"{client.industry} space. Score every article against the four criteria. "
            f"Return ONLY articles scoring 7+ out of 10. Maximum 3 angles. "
            f"If zero qualify, return NO_QUALIFYING_ANGLES."
        ),
        backstory=(
            "You are a senior PR strategist who knows exact editorial standards: "
            "only angles that tie to a SPECIFIC named value proposition from the "
            "client's pitchbook pass. Loose industry relevance is never enough. "
            "You never force an angle."
        ),
        llm=create_gemini_llm(),
        tools=[glean_read_document],
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )


def build_media_list_builder(client: ClientConfig) -> Agent:
    """PR-7: Finds and ranks reporters from internal media lists."""
    return Agent(
        role="PR Media List Strategist",
        goal=(
            f"Match newsjacking angles for {client.name} to the best reporters. "
            f"Find named beat reporters at Tier 1 outlets (WSJ, Bloomberg, CNBC, NYT, "
            f"FT, Fortune, Reuters, AP, Barron's, The Information, Fast Company, "
            f"Business Insider, Axios, TechCrunch). Minimum 2 Tier 1 per angle. "
            f"Maximum 5 reporters per angle. VERIFIED from media list ranks above UNVERIFIED."
        ),
        backstory=(
            "You want named individuals, not outlet logos. You challenge vague tier "
            "classifications. You never include opinion columnists, contributors, or PR "
            "sources. Only individual journalists with confirmed bylines."
        ),
        llm=create_gemini_llm(),
        tools=[glean_search, glean_read_document],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )


def build_web_search_supplement(client: ClientConfig) -> Agent:
    """PR-7 supplement: Finds additional Tier 1 reporters via web search."""
    return Agent(
        role="Journalist Discovery Researcher",
        goal=(
            f"Find named staff writers and beat reporters at Tier 1 outlets who have "
            f"published articles about {client.name}'s newsjacking angle topics in "
            f"the past 90 days. Return full name, outlet, beat, and link to a recent "
            f"article. Do NOT include opinion columnists or contributors."
        ),
        backstory=(
            "You supplement the internal media list with fresh journalist discoveries. "
            "You only run if the media list builder flagged fewer than 2 Tier 1 reporters."
        ),
        llm=create_gemini_llm(),
        tools=[web_search],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )


def build_pitch_drafter(client: ClientConfig) -> Agent:
    """PR-8: Drafts personalized pitch emails for each angle x reporter pair."""
    return Agent(
        role="Senior PR Pitch Writer",
        goal=(
            f"Draft newsjacking pitch emails for {client.name} in the {client.industry} "
            f"space. Each pitch is 4 paragraphs maximum: hook (the news), angle "
            f"(client value prop), talking point (from pitchbook), ask (one sentence). "
            f"Match {client.name}'s pitchbook tone exactly."
        ),
        backstory=(
            "You write tight, approvable pitches. You never fabricate quotes, stats, "
            "or claims not in the pitchbook. Shorter is better. Pitches that require "
            "heavy editing get rejected."
        ),
        llm=create_gemini_llm(),
        tools=[glean_read_document],
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )
