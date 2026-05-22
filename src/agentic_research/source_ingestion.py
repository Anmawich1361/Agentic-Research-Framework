from __future__ import annotations

import re
import os
from collections.abc import Callable, Mapping
from io import BytesIO
from urllib.parse import urlparse

import httpx

from agentic_research.models import (
    SourceCandidate,
    SourceChunk,
    SourceContent,
    SourceFetchFailureReason,
    SourceFetchLog,
    SourceFetchResult,
    SourceMap,
    StrictModel,
)


class SourceHttpResponse(StrictModel):
    url: str
    status_code: int
    headers: dict[str, str]
    text: str
    content: bytes | None = None


SourceFetcher = Callable[[str, float], SourceHttpResponse]
PDFTextExtractor = Callable[[bytes], str]
SECArchiveResolver = Callable[[str, float], str | None]

DEFAULT_FETCH_TIMEOUT_SECONDS = 10.0
DEFAULT_HIGH_SCORE_FLOOR = 4.0
DEFAULT_CHUNK_CHAR_LIMIT = 1800
_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
_HTML_CONTENT_MARKERS = ("text/html", "application/xhtml+xml")
_TEXT_CONTENT_MARKERS = ("text/plain", "text/markdown")
_SAFE_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 agentic-research-framework/0.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_DEFAULT_SEC_USER_AGENT = "agentic-research-framework/0.1 contact=not-configured"
_NOISE_TAGS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "aside",
    "form",
    "svg",
)


def _httpx_fetch(url: str, timeout_seconds: float) -> SourceHttpResponse:
    response = httpx.get(
        url,
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=_headers_for_url(url),
    )
    return SourceHttpResponse(
        url=str(response.url),
        status_code=response.status_code,
        headers=dict(response.headers),
        text=response.text,
        content=response.content,
    )


def _headers_for_url(url: str) -> dict[str, str]:
    headers = dict(_SAFE_FETCH_HEADERS)
    host = urlparse(url).netloc.lower()
    if host.endswith("sec.gov"):
        headers["User-Agent"] = os.environ.get("SEC_USER_AGENT", _DEFAULT_SEC_USER_AGENT)
    return headers


def _content_type(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value.split(";", 1)[0].strip().lower()
    return None


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _is_valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_sec_filing_source(source: SourceCandidate) -> bool:
    parsed = urlparse(source.url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    return (
        host.endswith("sec.gov")
        and ("/archives/" in path or source.source_type == "corporate_filing")
    )


def _cik_from_sec_archive_url(url: str) -> str | None:
    match = re.search(r"/Archives/edgar/data/(\d+)/", url, flags=re.IGNORECASE)
    if match is None:
        return None
    return f"{int(match.group(1)):010d}"


def _sec_archive_document_url(
    *,
    cik: str,
    accession_number: str,
    primary_document: str,
) -> str:
    cik_path = str(int(cik))
    accession_path = accession_number.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_path}/{accession_path}/{primary_document}"


def resolve_latest_sec_10k_archive_url(url: str, timeout_seconds: float) -> str | None:
    cik = _cik_from_sec_archive_url(url)
    if cik is None:
        return None

    response = httpx.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=_headers_for_url("https://data.sec.gov/"),
    )
    if response.status_code >= 400:
        return None

    data = response.json()
    recent = data.get("filings", {}).get("recent", {})
    rows = zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
    )
    for form, accession_number, primary_document in rows:
        if form != "10-K" or not accession_number or not primary_document:
            continue
        return _sec_archive_document_url(
            cik=cik,
            accession_number=accession_number,
            primary_document=primary_document,
        )
    return None


def _fetch_preference_rank(source: SourceCandidate) -> int:
    if _is_sec_filing_source(source):
        return 0
    if source.source_type == "corporate_filing":
        return 1
    return 2


def _prefer_accessible_official_sources(
    sources: list[SourceCandidate],
) -> list[SourceCandidate]:
    return [
        source
        for _index, source in sorted(
            enumerate(sources),
            key=lambda item: (_fetch_preference_rank(item[1]), item[0]),
        )
    ]


def _source_lookup(source_map: SourceMap) -> dict[str, SourceCandidate]:
    return {source.id: source for source in source_map.sources}


def sources_for_ingestion(
    source_map: SourceMap,
    *,
    high_score_floor: float = DEFAULT_HIGH_SCORE_FLOOR,
) -> list[SourceCandidate]:
    sources_by_id = _source_lookup(source_map)
    selected: list[SourceCandidate] = []
    seen: set[str] = set()
    for score in source_map.scores:
        if not score.include and score.final_score < high_score_floor:
            continue
        source = sources_by_id.get(score.source_id)
        if source is None or source.id in seen:
            continue
        selected.append(source)
        seen.add(source.id)
    if selected:
        return _prefer_accessible_official_sources(selected)
    return _prefer_accessible_official_sources(list(source_map.sources))


def parse_html_to_text(html: str) -> tuple[str | None, str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    title_node = soup.find("title") or soup.find("h1")
    title = title_node.get_text(" ", strip=True) if title_node else None
    content_root = soup.find("main") or soup.find("article") or soup.body or soup
    text = content_root.get_text("\n", strip=True)
    text = _normalize_text(text)
    return title, text


def _normalize_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    collapsed = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


def _excerpt(text: str, *, max_chars: int = 500) -> str | None:
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    return cleaned[:max_chars]


def extract_pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    page_text = [page.extract_text() or "" for page in reader.pages]
    return _normalize_text("\n".join(page_text))


def _chunk_text(
    *,
    source_id: str,
    url: str,
    text: str,
    max_chars: int = DEFAULT_CHUNK_CHAR_LIMIT,
) -> list[SourceChunk]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n") if paragraph.strip()]
    chunks: list[SourceChunk] = []
    current: list[str] = []
    current_length = 0
    for paragraph in paragraphs:
        separator_length = 1 if current else 0
        if current and current_length + separator_length + len(paragraph) > max_chars:
            chunks.append(
                _source_chunk(
                    source_id=source_id,
                    url=url,
                    index=len(chunks),
                    text="\n".join(current),
                )
            )
            current = []
            current_length = 0
        current.append(paragraph)
        current_length += separator_length + len(paragraph)

    if current:
        chunks.append(
            _source_chunk(
                source_id=source_id,
                url=url,
                index=len(chunks),
                text="\n".join(current),
            )
        )
    return chunks


def _source_chunk(*, source_id: str, url: str, index: int, text: str) -> SourceChunk:
    return SourceChunk(
        source_id=source_id,
        url=url,
        chunk_id=f"{source_id}_chunk_{index + 1}",
        index=index,
        text=text,
    )


def _http_failure_reason(response: SourceHttpResponse) -> SourceFetchFailureReason:
    body = response.text.lower()
    block_markers = (
        "access denied",
        "request blocked",
        "captcha",
        "cloudflare",
        "akamai",
        "enable javascript",
        "bot detection",
    )
    if response.status_code == 403:
        return "bot_access_block" if any(marker in body for marker in block_markers) else "http_403"
    if response.status_code in {401, 429} or any(marker in body for marker in block_markers):
        return "bot_access_block"
    return "http_error"


def _exception_failure_reason(exc: Exception) -> SourceFetchFailureReason:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(exc, (httpx.InvalidURL, ValueError)):
        return "bad_url"
    return "fetch_error"


def _pdf_response_content(response: SourceHttpResponse) -> bytes:
    if response.content is not None:
        return response.content
    return response.text.encode("utf-8", errors="ignore")


def _content_and_result(
    *,
    source: SourceCandidate,
    response: SourceHttpResponse,
    pdf_text_extractor: PDFTextExtractor,
) -> tuple[SourceContent | None, SourceFetchResult]:
    content_type = _content_type(response.headers)
    fetched_url = response.url if response.url != source.url else None
    content_url = response.url or source.url
    if response.status_code >= 400:
        return None, SourceFetchResult(
            source_id=source.id,
            url=source.url,
            status="failed",
            content_type=content_type,
            error=f"HTTP {response.status_code}",
            failure_reason=_http_failure_reason(response),
            fetched_url=fetched_url,
        )
    if content_type in _PDF_CONTENT_TYPES or _is_pdf_url(response.url):
        try:
            text = _normalize_text(pdf_text_extractor(_pdf_response_content(response)))
        except Exception as exc:
            return None, SourceFetchResult(
                source_id=source.id,
                url=source.url,
                status="failed",
                content_type=content_type or "application/pdf",
                error=f"PDF extraction failed: {exc}",
                failure_reason="pdf_extraction_failed",
                fetched_url=fetched_url,
            )
        if not text:
            return None, SourceFetchResult(
                source_id=source.id,
                url=source.url,
                status="failed",
                content_type=content_type or "application/pdf",
                error="No readable text extracted from PDF.",
                failure_reason="no_readable_text",
                fetched_url=fetched_url,
            )
        chunks = _chunk_text(source_id=source.id, url=content_url, text=text)
        excerpt = _excerpt(text)
        log_excerpt = _excerpt(text, max_chars=240)
        content = SourceContent(
            source_id=source.id,
            url=content_url,
            content_type=content_type or "application/pdf",
            title=source.title,
            text=text,
            excerpt=excerpt,
            chunks=chunks,
        )
        return content, SourceFetchResult(
            source_id=source.id,
            url=source.url,
            status="fetched",
            content_type=content.content_type,
            title=content.title,
            excerpt=log_excerpt,
            text_char_count=len(text),
            chunk_count=len(chunks),
            fetched_url=fetched_url,
        )

    if content_type is None or any(marker == content_type for marker in _HTML_CONTENT_MARKERS):
        title, text = parse_html_to_text(response.text)
    elif any(marker == content_type for marker in _TEXT_CONTENT_MARKERS):
        title = source.title
        text = _normalize_text(response.text)
    else:
        return None, SourceFetchResult(
            source_id=source.id,
            url=source.url,
            status="skipped",
            content_type=content_type,
            error=f"Unsupported content type: {content_type}",
            failure_reason="unsupported_content_type",
            fetched_url=fetched_url,
        )

    if not text:
        return None, SourceFetchResult(
            source_id=source.id,
            url=source.url,
            status="failed",
            content_type=content_type,
            title=title,
            error="No readable text extracted.",
            failure_reason="no_readable_text",
            fetched_url=fetched_url,
        )

    chunks = _chunk_text(source_id=source.id, url=content_url, text=text)
    excerpt = _excerpt(text)
    log_excerpt = _excerpt(text, max_chars=240)
    content = SourceContent(
        source_id=source.id,
        url=content_url,
        content_type=content_type,
        title=title or source.title,
        text=text,
        excerpt=excerpt,
        chunks=chunks,
    )
    return content, SourceFetchResult(
        source_id=source.id,
        url=source.url,
        status="fetched",
        content_type=content_type,
        title=content.title,
        excerpt=log_excerpt,
        text_char_count=len(text),
        chunk_count=len(chunks),
        fetched_url=fetched_url,
    )


def ingest_source_content(
    source_map: SourceMap,
    *,
    fetcher: SourceFetcher | None = None,
    pdf_text_extractor: PDFTextExtractor = extract_pdf_text,
    sec_filing_resolver: SECArchiveResolver = resolve_latest_sec_10k_archive_url,
    timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
    high_score_floor: float = DEFAULT_HIGH_SCORE_FLOOR,
) -> tuple[list[SourceContent], SourceFetchLog]:
    fetch = fetcher or _httpx_fetch
    contents: list[SourceContent] = []
    results: list[SourceFetchResult] = []
    for source in sources_for_ingestion(
        source_map,
        high_score_floor=high_score_floor,
    ):
        if not _is_valid_http_url(source.url):
            results.append(
                SourceFetchResult(
                    source_id=source.id,
                    url=source.url,
                    status="failed",
                    error="Invalid source URL.",
                    failure_reason="bad_url",
                )
            )
            continue
        try:
            response = fetch(source.url, timeout_seconds)
            if response.status_code >= 400 and _is_sec_filing_source(source):
                resolved_url = sec_filing_resolver(source.url, timeout_seconds)
                if resolved_url and resolved_url != source.url and _is_valid_http_url(resolved_url):
                    response = fetch(resolved_url, timeout_seconds)
            content, result = _content_and_result(
                source=source,
                response=response,
                pdf_text_extractor=pdf_text_extractor,
            )
        except Exception as exc:
            content = None
            result = SourceFetchResult(
                source_id=source.id,
                url=source.url,
                status="failed",
                error=str(exc),
                failure_reason=_exception_failure_reason(exc),
            )
        if content is not None:
            contents.append(content)
        results.append(result)
    return contents, SourceFetchLog(results=results)


__all__ = [
    "DEFAULT_FETCH_TIMEOUT_SECONDS",
    "PDFTextExtractor",
    "SECArchiveResolver",
    "SourceFetcher",
    "SourceHttpResponse",
    "extract_pdf_text",
    "ingest_source_content",
    "parse_html_to_text",
    "resolve_latest_sec_10k_archive_url",
    "sources_for_ingestion",
]
