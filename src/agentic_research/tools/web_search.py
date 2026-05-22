from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from agentic_research.models import ResearchCharter, ResearchPlan


_SAFE_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 agentic-research-framework/0.1"
    ),
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    publisher: str
    url: str
    snippet: str
    publication_date: str | None = None


class SearchProvider(Protocol):
    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]: ...


class StaticSearchProvider:
    def __init__(self, results_by_query: Mapping[str, Sequence[SearchResult]]) -> None:
        self._results_by_query = {
            query: list(results) for query, results in results_by_query.items()
        }

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        return self._results_by_query.get(query, [])[:max_results]


class DuckDuckGoSearchProvider:
    """Small search-result wrapper; it does not fetch or parse target documents."""

    def __init__(self, *, timeout_seconds: float = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        response = httpx.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers=_SAFE_SEARCH_HEADERS,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []
        for item in soup.select(".result"):
            link = item.select_one(".result__a")
            if link is None:
                continue
            url = str(link.get("href") or "").strip()
            title = link.get_text(" ", strip=True)
            if not title or not url:
                continue

            snippet_node = item.select_one(".result__snippet")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
            results.append(
                SearchResult(
                    title=title,
                    publisher=_publisher_from_url(url),
                    url=url,
                    snippet=snippet,
                )
            )
            if len(results) >= max_results:
                break
        return results


class WebSearchClient:
    def __init__(self, provider: SearchProvider | None = None) -> None:
        self.provider = provider or DuckDuckGoSearchProvider()

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        return self.provider.search(query, max_results=max_results)

    def search_many(
        self,
        queries: Sequence[str],
        *,
        max_results_per_query: int = 5,
    ) -> list[SearchResult]:
        seen_urls: set[str] = set()
        results: list[SearchResult] = []
        for query in queries:
            for result in self.search(query, max_results=max_results_per_query):
                if result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                results.append(result)
        return results


def _publisher_from_url(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    return host or "Unknown publisher"


def _query_phrase_for_source_type(source_type: str) -> str:
    return {
        "corporate_filing": "annual report filing",
        "government_data": "government data",
        "earnings_transcript": "earnings transcript",
        "investor_material": "investor presentation",
        "primary_company": "official company primary source",
        "industry_primer": "industry primer",
        "competitor_source": "competitors",
        "trade_publication": "trade publication",
        "news": "recent news",
        "whitepaper": "whitepaper",
        "expert_blog": "expert analysis",
    }.get(source_type, source_type.replace("_", " "))


def _query_context(charter: ResearchCharter, plan: ResearchPlan) -> str:
    text = " ".join(
        [
            charter.research_lens,
            charter.deliverable,
            *charter.key_questions,
            *plan.research_questions,
            *plan.checkpoint_questions,
        ]
    ).lower()
    if "supplier" in text:
        return "supplier"
    if "investor" in text or "investment" in text:
        return "investor"
    if "interview" in text:
        return "interview"
    return charter.research_lens.replace("_", " ")


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def build_source_search_queries(charter: ResearchCharter, plan: ResearchPlan) -> list[str]:
    context = _query_context(charter, plan)
    queries: list[str] = []
    if charter.target_type == "company":
        queries.append(f"{charter.target} SEC 10-K annual report site:sec.gov {context} meeting")
    for source_type in plan.required_source_types:
        phrase = _query_phrase_for_source_type(source_type)
        queries.append(f"{charter.target} {phrase} {context} meeting")
    return _dedupe_preserving_order(queries)


def create_web_search_tool(search_client: WebSearchClient | None = None):
    from agents import function_tool

    client = search_client or WebSearchClient()

    @function_tool(name_override="web_search")
    def web_search(
        query: str = Field(description="Search query for source discovery."),
        max_results: int = Field(default=5, ge=1, le=10),
    ) -> list[dict[str, str | None]]:
        """Search the web for source candidates without scraping result documents."""
        return [
            result.model_dump(mode="json")
            for result in client.search(query, max_results=max_results)
        ]

    return web_search
