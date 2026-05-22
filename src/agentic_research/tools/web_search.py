from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
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
_DEFAULT_SEC_USER_AGENT = "agentic-research-framework/0.1 contact=not-configured"
_SEC_SEARCH_HEADERS = {
    "User-Agent": os.environ.get("SEC_USER_AGENT", _DEFAULT_SEC_USER_AGENT),
    "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
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
        try:
            results = self.provider.search(query, max_results=max_results)
        except Exception:
            return _sec_filing_fallback_results(query, max_results=max_results)
        if results:
            return results
        return _sec_filing_fallback_results(query, max_results=max_results)

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


def _normalize_company_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _target_from_sec_query(query: str) -> str | None:
    match = re.match(r"(.+?)\s+SEC\s+10-K\b", query, flags=re.IGNORECASE)
    if match is None:
        return None
    target = match.group(1).strip()
    return target or None


def _sec_json_get(url: str, *, timeout_seconds: float = 10) -> Any:
    response = httpx.get(
        url,
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=_SEC_SEARCH_HEADERS,
    )
    response.raise_for_status()
    return response.json()


def _sec_company_entries() -> list[dict[str, Any]]:
    data = _sec_json_get("https://www.sec.gov/files/company_tickers.json")
    if not isinstance(data, dict):
        return []
    return [entry for entry in data.values() if isinstance(entry, dict)]


def _matching_sec_company_entry(target: str) -> dict[str, Any] | None:
    target_normalized = _normalize_company_name(target)
    if not target_normalized:
        return None
    for entry in _sec_company_entries():
        title = str(entry.get("title") or "")
        ticker = str(entry.get("ticker") or "")
        title_normalized = _normalize_company_name(title)
        if target_normalized == ticker.lower() or target_normalized in title_normalized:
            return entry
    return None


def _sec_archive_document_url(
    *,
    cik: str,
    accession_number: str,
    primary_document: str,
) -> str:
    cik_path = str(int(cik))
    accession_path = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/{primary_document}"


def _latest_sec_10k_url_for_target(target: str) -> tuple[str, str] | None:
    entry = _matching_sec_company_entry(target)
    if entry is None:
        return None
    cik = f"{int(entry['cik_str']):010d}"
    submissions = _sec_json_get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = submissions.get("filings", {}).get("recent", {})
    rows = zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
    )
    for form, accession_number, primary_document in rows:
        if form != "10-K" or not accession_number or not primary_document:
            continue
        return (
            str(entry.get("title") or target),
            _sec_archive_document_url(
                cik=cik,
                accession_number=accession_number,
                primary_document=primary_document,
            ),
        )
    return None


def _sec_filing_fallback_results(
    query: str,
    *,
    max_results: int = 5,
) -> list[SearchResult]:
    if "site:sec.gov" not in query.lower() or "10-k" not in query.lower():
        return []
    target = _target_from_sec_query(query)
    if target is None:
        return []
    try:
        latest_filing = _latest_sec_10k_url_for_target(target)
    except Exception:
        return []
    if latest_filing is None:
        return []
    company_title, filing_url = latest_filing
    return [
        SearchResult(
            title=f"{company_title} latest Form 10-K",
            publisher="U.S. Securities and Exchange Commission",
            url=filing_url,
            snippet=f"Direct SEC Form 10-K filing URL for {company_title}.",
        )
    ][:max_results]


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
