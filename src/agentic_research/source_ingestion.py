from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from urllib.parse import urlparse

import httpx

from agentic_research.models import (
    SourceCandidate,
    SourceChunk,
    SourceContent,
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


SourceFetcher = Callable[[str, float], SourceHttpResponse]

DEFAULT_FETCH_TIMEOUT_SECONDS = 10.0
DEFAULT_HIGH_SCORE_FLOOR = 4.0
DEFAULT_CHUNK_CHAR_LIMIT = 1800
_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}
_HTML_CONTENT_MARKERS = ("text/html", "application/xhtml+xml")
_TEXT_CONTENT_MARKERS = ("text/plain", "text/markdown")
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
        headers={"User-Agent": "agentic-research-framework/0.1"},
    )
    return SourceHttpResponse(
        url=str(response.url),
        status_code=response.status_code,
        headers=dict(response.headers),
        text=response.text,
    )


def _content_type(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value.split(";", 1)[0].strip().lower()
    return None


def _is_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


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
        return selected
    return list(source_map.sources)


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


def _content_and_result(
    *,
    source: SourceCandidate,
    response: SourceHttpResponse,
) -> tuple[SourceContent | None, SourceFetchResult]:
    content_type = _content_type(response.headers)
    if content_type in _PDF_CONTENT_TYPES or _is_pdf_url(response.url):
        return None, SourceFetchResult(
            source_id=source.id,
            url=source.url,
            status="skipped",
            content_type=content_type or "application/pdf",
            error="PDF ingestion is not implemented.",
        )
    if response.status_code >= 400:
        return None, SourceFetchResult(
            source_id=source.id,
            url=source.url,
            status="failed",
            content_type=content_type,
            error=f"HTTP {response.status_code}",
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
        )

    if not text:
        return None, SourceFetchResult(
            source_id=source.id,
            url=source.url,
            status="failed",
            content_type=content_type,
            title=title,
            error="No readable text extracted.",
        )

    chunks = _chunk_text(source_id=source.id, url=source.url, text=text)
    excerpt = _excerpt(text)
    content = SourceContent(
        source_id=source.id,
        url=source.url,
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
        text=text,
        excerpt=excerpt,
        chunks=chunks,
    )


def ingest_source_content(
    source_map: SourceMap,
    *,
    fetcher: SourceFetcher | None = None,
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
        if _is_pdf_url(source.url):
            results.append(
                SourceFetchResult(
                    source_id=source.id,
                    url=source.url,
                    status="skipped",
                    content_type="application/pdf",
                    error="PDF ingestion is not implemented.",
                )
            )
            continue
        try:
            response = fetch(source.url, timeout_seconds)
            content, result = _content_and_result(source=source, response=response)
        except Exception as exc:
            content = None
            result = SourceFetchResult(
                source_id=source.id,
                url=source.url,
                status="failed",
                error=str(exc),
            )
        if content is not None:
            contents.append(content)
        results.append(result)
    return contents, SourceFetchLog(results=results)


__all__ = [
    "DEFAULT_FETCH_TIMEOUT_SECONDS",
    "SourceFetcher",
    "SourceHttpResponse",
    "ingest_source_content",
    "parse_html_to_text",
    "sources_for_ingestion",
]
