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
from agentic_research.source_scoring import canonical_source_need


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


class SearchFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    error_type: str
    error: str


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
        self.last_failures: list[SearchFailure] = []

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        try:
            results = self.provider.search(query, max_results=max_results)
        except Exception as exc:
            self.last_failures.append(
                SearchFailure(
                    query=query,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            )
            return _sec_filing_fallback_results(query, max_results=max_results)
        fallback_results = _sec_filing_fallback_results(
            query,
            max_results=max_results,
        )
        if fallback_results:
            return _dedupe_search_results(
                [*fallback_results, *results],
                max_results=max_results,
            )
        if results:
            return results
        return fallback_results

    def search_many(
        self,
        queries: Sequence[str],
        *,
        max_results_per_query: int = 5,
    ) -> list[SearchResult]:
        self.last_failures = []
        seen_urls: set[str] = set()
        results: list[SearchResult] = []
        for query in queries:
            try:
                query_results = self.search(query, max_results=max_results_per_query)
            except Exception:
                continue
            for result in query_results:
                if result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                results.append(result)
        return results


_LEGAL_SUFFIXES = {
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "ltd",
    "limited",
    "plc",
    "co",
    "company",
    "new",
}


def _normalized_company_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    without_suffixes = [token for token in tokens if token not in _LEGAL_SUFFIXES]
    return without_suffixes or tokens


def _normalize_company_name(value: str) -> str:
    return " ".join(_normalized_company_tokens(value))


def _is_ticker_like_target(value: str) -> bool:
    legal_suffixes = {
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "ltd",
        "limited",
        "plc",
        "co",
        "company",
    }
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    return len(tokens) == 1 or not any(token in legal_suffixes for token in tokens)


def _target_from_sec_query(query: str) -> str | None:
    match = re.match(r"(.+?)\s+SEC\s+", query, flags=re.IGNORECASE)
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
    target_tokens = set(_normalized_company_tokens(target))
    if not target_tokens:
        return None
    ticker_match: dict[str, Any] | None = None
    for entry in _sec_company_entries():
        title = str(entry.get("title") or "")
        ticker = str(entry.get("ticker") or "")
        title_tokens = set(_normalized_company_tokens(title))
        if target_tokens <= title_tokens:
            return entry
        if (
            len(target_tokens) == 1
            and next(iter(target_tokens)) == ticker.lower()
            and _is_ticker_like_target(target)
        ):
            ticker_match = entry
    return ticker_match


def _sec_archive_document_url(
    *,
    cik: str,
    accession_number: str,
    primary_document: str,
) -> str:
    cik_path = str(int(cik))
    accession_path = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/{primary_document}"


def _query_sec_forms(query: str) -> list[str]:
    query_lower = query.lower()
    forms: list[str] = []
    for form in ("10-K", "6-K", "8-K", "10-Q"):
        if form.lower() in query_lower:
            forms.append(form)
    if forms:
        return forms
    if "earnings" in query_lower or "results" in query_lower:
        return ["6-K", "8-K", "10-Q", "10-K"]
    return ["10-K"]


def _sec_archive_index_url(*, cik: str, accession_number: str) -> str:
    cik_path = str(int(cik))
    accession_path = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/index.json"


def _sec_index_document_names(*, cik: str, accession_number: str) -> list[str]:
    data = _sec_json_get(
        _sec_archive_index_url(cik=cik, accession_number=accession_number)
    )
    items = data.get("directory", {}).get("item", [])
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _document_name_matches_recent_results(name: str, query: str) -> bool:
    del query
    text = name.lower()
    result_terms = (
        "pressrelease",
        "press-release",
        "press_release",
        "earnings",
        "results",
        "q4",
        "q3",
        "q2",
        "q1",
        "quarter",
        "mda",
        "md&a",
    )
    return any(term in text for term in result_terms)


def _preferred_sec_document(
    *,
    cik: str,
    accession_number: str,
    primary_document: str,
    query: str,
) -> str:
    try:
        document_names = _sec_index_document_names(
            cik=cik,
            accession_number=accession_number,
        )
    except Exception:
        document_names = []
    for name in document_names:
        if _document_name_matches_recent_results(name, query):
            return name
    return primary_document


def _latest_sec_filing_urls_for_target(
    target: str,
    *,
    forms: list[str],
    query: str,
) -> list[tuple[str, str, str]]:
    entry = _matching_sec_company_entry(target)
    if entry is None:
        return []
    cik = f"{int(entry['cik_str']):010d}"
    submissions = _sec_json_get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = submissions.get("filings", {}).get("recent", {})
    rows = zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
    )
    matches: list[tuple[str, str, str]] = []
    for form, accession_number, primary_document in rows:
        if form not in forms or not accession_number or not primary_document:
            continue
        selected_document = primary_document
        if form in {"6-K", "8-K", "10-Q"} or "earnings" in query.lower() or "results" in query.lower():
            selected_document = _preferred_sec_document(
                cik=cik,
                accession_number=accession_number,
                primary_document=primary_document,
                query=query,
            )
        matches.append(
            (
                form,
                str(entry.get("title") or target),
                _sec_archive_document_url(
                    cik=cik,
                    accession_number=accession_number,
                    primary_document=selected_document,
                ),
            )
        )
        if len(matches) >= 3:
            break
    return matches


def _latest_sec_10k_url_for_target(target: str) -> tuple[str, str] | None:
    matches = _latest_sec_filing_urls_for_target(
        target,
        forms=["10-K"],
        query=f"{target} SEC 10-K",
    )
    if not matches:
        return None
    _form, company_title, filing_url = matches[0]
    return company_title, filing_url


def _sec_filing_fallback_results(
    query: str,
    *,
    max_results: int = 5,
) -> list[SearchResult]:
    query_lower = query.lower()
    if "site:sec.gov" not in query_lower:
        return []
    target = _target_from_sec_query(query)
    if target is None:
        return []
    try:
        latest_filings = _latest_sec_filing_urls_for_target(
            target,
            forms=_query_sec_forms(query),
            query=query,
        )
    except Exception:
        return []
    if not latest_filings:
        return []
    return [
        SearchResult(
            title=f"{company_title} latest Form {form}",
            publisher="U.S. Securities and Exchange Commission",
            url=filing_url,
            snippet=f"Direct SEC Form {form} filing URL for {company_title}.",
        )
        for form, company_title, filing_url in latest_filings
    ][:max_results]


def _publisher_from_url(url: str) -> str:
    host = urlparse(url).netloc.replace("www.", "")
    return host or "Unknown publisher"


def _query_phrase_for_source_type(source_type: str) -> str:
    return {
        "corporate_filing": "annual report filing",
        "recent_sec_filing": "SEC recent filing earnings results site:sec.gov",
        "government_data": "government data",
        "earnings_release": "earnings release",
        "earnings_transcript": "earnings transcript",
        "market_data": "market data valuation",
        "peer_source": "peers competitors valuation",
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


def _dedupe_search_results(
    results: Sequence[SearchResult],
    *,
    max_results: int,
) -> list[SearchResult]:
    seen_urls: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        if result.url in seen_urls:
            continue
        seen_urls.add(result.url)
        deduped.append(result)
        if len(deduped) >= max_results:
            break
    return deduped


_DATE_PATTERN = re.compile(
    r"\b("
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{4})?"
    r")\b",
    flags=re.IGNORECASE,
)


def _feedback_date_text(feedback_text: str | None) -> str | None:
    if not feedback_text:
        return None
    match = _DATE_PATTERN.search(feedback_text)
    if match is None:
        return None
    return " ".join(match.group(1).replace(",", "").split())


def _required_source_categories(plan: ResearchPlan) -> list[str]:
    return _dedupe_preserving_order(
        [canonical_source_need(source_type) for source_type in plan.required_source_types]
    )


def _category_queries(target: str, category: str) -> list[str]:
    if category == "corporate_filing":
        return [f"{target} SEC 10-K annual report site:sec.gov"]
    if category == "recent_sec_filing":
        return [
            f"{target} SEC 6-K earnings results site:sec.gov",
            f"{target} SEC 8-K earnings results site:sec.gov",
            f"{target} SEC 10-Q quarterly results site:sec.gov",
        ]
    phrase = _query_phrase_for_source_type(category)
    return [f"{target} {phrase}"]


def build_source_search_queries(
    charter: ResearchCharter,
    plan: ResearchPlan,
    *,
    feedback_text: str | None = None,
) -> list[str]:
    context = _query_context(charter, plan)
    queries: list[str] = []
    if charter.target_type == "company":
        queries.extend(
            [
                f"{charter.target} SEC 10-K annual report site:sec.gov",
                f"{charter.target} SEC 6-K earnings results site:sec.gov",
                f"{charter.target} official company source",
                f"{charter.target} investor relations financial results",
                f"{charter.target} investor relations investor presentation",
                f"{charter.target} earnings release",
                f"{charter.target} quarterly results",
                f"{charter.target} latest results press release",
                f"{charter.target} earnings transcript",
            ]
        )
        if context == "investor":
            queries.append(f"{charter.target} market data valuation")
    feedback_date = _feedback_date_text(feedback_text)
    if feedback_date is not None and charter.target_type == "company":
        queries.extend(
            [
                f"{charter.target} {feedback_date} earnings release",
                f"{charter.target} {feedback_date} quarterly results",
            ]
        )
    for category in _required_source_categories(plan):
        queries.extend(_category_queries(charter.target, category))
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
