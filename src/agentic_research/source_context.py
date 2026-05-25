from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from agentic_research.models import (
    SourceCandidate,
    SourceChunk,
    SourceContent,
    SourceFallbackContext,
    SourceFetchLog,
    SourceFetchResult,
    SourceMap,
)
from agentic_research.tools.web_search import SearchResult


def _source_map_with_fetched_urls(
    source_map: SourceMap,
    source_content: list[SourceContent],
) -> SourceMap:
    fetched_urls_by_source_id = {
        content.source_id: content.url.strip()
        for content in source_content
        if content.url.strip()
    }
    if not fetched_urls_by_source_id:
        return source_map

    changed = False
    sources: list[SourceCandidate] = []
    for source in source_map.sources:
        fetched_url = fetched_urls_by_source_id.get(source.id)
        if fetched_url and fetched_url != source.url:
            sources.append(source.model_copy(update={"url": fetched_url}))
            changed = True
        else:
            sources.append(source)

    if not changed:
        return source_map

    return source_map.model_copy(update={"sources": sources})


def _has_future_dated_marker(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.lower()
    return "future-dated" in normalized or "future dated" in normalized


def _is_fetched_sec_archive_result(result: SourceFetchResult) -> bool:
    if result.status != "fetched":
        return False
    return any(
        "sec.gov/archives/" in (url or "").lower()
        for url in (result.url, result.fetched_url)
    )


def _source_map_with_fetch_verification_notes(
    source_map: SourceMap,
    source_fetch_log: SourceFetchLog | None,
) -> SourceMap:
    if source_fetch_log is None:
        return source_map

    verified_sec_source_ids = {
        result.source_id
        for result in source_fetch_log.results
        if _is_fetched_sec_archive_result(result)
    }
    if not verified_sec_source_ids:
        return source_map

    changed = False
    sources: list[SourceCandidate] = []
    for source in source_map.sources:
        if source.id in verified_sec_source_ids and _has_future_dated_marker(source.notes):
            sources.append(
                source.model_copy(
                    update={"notes": "SEC filing availability verified from fetched text."}
                )
            )
            changed = True
            continue
        sources.append(source)

    gaps = list(source_map.gaps)
    filtered_gaps = [
        gap
        for gap in gaps
        if not (_has_future_dated_marker(gap) and "filing" in gap.lower())
    ]
    if len(filtered_gaps) != len(gaps):
        changed = True

    if not changed:
        return source_map
    return source_map.model_copy(update={"sources": sources, "gaps": filtered_gaps})


def _synthesis_source_evidence_context(
    *,
    source_map: SourceMap,
    source_content: list[SourceContent],
    source_fetch_log: SourceFetchLog | None,
) -> dict[str, Any]:
    source_lookup = {source.id: source for source in source_map.sources}
    fetched_source_ids = [content.source_id for content in source_content]
    fetched_source_id_set = set(fetched_source_ids)
    direct_source_types = {"corporate_filing", "investor_material", "primary_company"}
    fetched_direct_source_ids = [
        source_id
        for source_id in fetched_source_ids
        if source_lookup.get(source_id) is not None
        and source_lookup[source_id].source_type in direct_source_types
    ]
    candidate_direct_source_ids = [
        source.id for source in source_map.sources if source.source_type in direct_source_types
    ]
    failed_or_skipped_source_ids: list[str] = []
    if source_fetch_log is not None:
        failed_or_skipped_source_ids = [
            result.source_id
            for result in source_fetch_log.results
            if result.status in {"failed", "skipped", "fallback"}
        ]

    warnings: list[str] = []
    if candidate_direct_source_ids and not fetched_direct_source_ids:
        warnings.append(
            "Primary/company/investor source candidates were discovered but no readable "
            "direct source content was fetched. Treat target company recent developments and "
            "strategy as unverified unless directly supported by fetched evidence."
        )
    if fetched_source_ids and not fetched_direct_source_ids:
        warnings.append(
            "Fetched source content is secondary or indirect only. State this source "
            "gap and avoid presenting target company current strategy as verified."
        )
    if not fetched_source_ids:
        warnings.append(
            "No fetched source content is available. Use only evidence gaps and open "
            "questions for current or recent-development points."
        )

    return {
        "fetched_source_ids": fetched_source_ids,
        "fetched_direct_source_ids": fetched_direct_source_ids,
        "candidate_direct_source_ids": candidate_direct_source_ids,
        "failed_or_skipped_source_ids": failed_or_skipped_source_ids,
        "secondary_or_indirect_only": bool(fetched_source_id_set and not fetched_direct_source_ids),
        "warnings": warnings,
    }


def _source_content_payload(
    source_content: list[SourceContent],
    *,
    max_total_chars: int = 16000,
    max_chunks_per_source: int = 5,
    max_chunk_chars: int = 1200,
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    remaining_chars = max_total_chars
    for content in source_content:
        if remaining_chars <= 0:
            break
        chunks: list[dict[str, Any]] = []
        for chunk in _select_source_chunks(
            content.chunks,
            max_chunks=max_chunks_per_source,
        ):
            if remaining_chars <= 0:
                break
            text = chunk.text[: min(max_chunk_chars, remaining_chars)]
            remaining_chars -= len(text)
            chunks.append(
                {
                    "source_id": chunk.source_id,
                    "url": chunk.url,
                    "chunk_id": chunk.chunk_id,
                    "index": chunk.index,
                    "text": text,
                }
            )
        payload.append(
            {
                "source_id": content.source_id,
                "url": content.url,
                "content_type": content.content_type,
                "title": content.title,
                "excerpt": content.excerpt,
                "chunks": chunks,
            }
        )
    return payload


def _valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl().rstrip("/")


def _weak_fallback_contexts(
    *,
    source_map: SourceMap,
    raw_search_results: list[SearchResult],
    source_content: list[SourceContent],
    source_fetch_log: SourceFetchLog | None,
) -> list[SourceFallbackContext]:
    if source_fetch_log is None:
        return []

    fetched_source_ids = {content.source_id for content in source_content}
    failed_or_skipped_source_ids = {
        result.source_id
        for result in source_fetch_log.results
        if result.status in {"failed", "skipped"}
    }
    search_result_by_url = {
        _normalized_url(result.url): result
        for result in raw_search_results
        if _valid_http_url(result.url)
    }

    contexts: list[SourceFallbackContext] = []
    for source in source_map.sources:
        if source.id in fetched_source_ids or source.id not in failed_or_skipped_source_ids:
            continue
        if not _valid_http_url(source.url):
            continue
        search_result = search_result_by_url.get(_normalized_url(source.url))
        if search_result is None:
            continue
        if not (search_result.title and search_result.publisher and search_result.snippet):
            continue
        contexts.append(
            SourceFallbackContext(
                source_id=source.id,
                url=source.url,
                title=search_result.title,
                publisher=search_result.publisher,
                snippet=search_result.snippet,
                context_type="search_snippet_only",
                caveats=[
                    "Search-result snippets are not fetched source text.",
                    "Do not use this context for high-confidence factual claims.",
                ],
            )
        )
    return contexts


def _weak_fallback_context_payload(
    fallback_contexts: list[SourceFallbackContext],
) -> list[dict[str, Any]]:
    return [context.model_dump(mode="json") for context in fallback_contexts]


def _source_fetch_log_with_fallbacks(
    source_fetch_log: SourceFetchLog | None,
    fallback_contexts: list[SourceFallbackContext],
) -> SourceFetchLog | None:
    if source_fetch_log is None or not fallback_contexts:
        return source_fetch_log

    fallback_by_source_id = {context.source_id: context for context in fallback_contexts}
    updated_results = []
    for result in source_fetch_log.results:
        fallback = fallback_by_source_id.get(result.source_id)
        if fallback is None or result.status not in {"failed", "skipped"}:
            updated_results.append(result)
            continue
        updated_results.append(
            result.model_copy(
                update={
                    "status": "fallback",
                    "content_type": fallback.context_type,
                    "title": fallback.title,
                    "excerpt": fallback.snippet,
                }
            )
        )
    return SourceFetchLog(results=updated_results)


def _select_source_chunks(
    chunks: list[SourceChunk],
    *,
    max_chunks: int,
) -> list[SourceChunk]:
    if len(chunks) <= max_chunks:
        return list(chunks)
    ranked = sorted(
        enumerate(chunks),
        key=lambda item: (_source_chunk_signal_score(item[1].text), -item[0]),
        reverse=True,
    )
    selected_indexes = sorted(index for index, _chunk in ranked[:max_chunks])
    return [chunks[index] for index in selected_indexes]


def _source_chunk_signal_score(text: str) -> float:
    lowered = text.lower()
    alpha_count = sum(character.isalpha() for character in text)
    digit_count = sum(character.isdigit() for character in text)
    char_count = max(len(text), 1)
    word_count = len(re.findall(r"[a-zA-Z]{4,}", text))
    score = word_count * (alpha_count / char_count)

    for marker in (
        "business",
        "earnings",
        "member",
        "membership",
        "merchandise",
        "net sales",
        "risk",
        "sales",
        "supplier",
        "warehouse",
    ):
        if marker in lowered:
            score += 25

    score -= 40 * lowered.count("us-gaap")
    score -= 40 * lowered.count("fasb.org")
    score -= 10 * lowered.count("0000909832")
    score -= 20 * (digit_count / char_count)
    return score


def _source_fetch_log_payload(source_fetch_log: SourceFetchLog | None) -> dict[str, Any] | None:
    if source_fetch_log is None:
        return None
    return {
        "results": [
            {
                "source_id": result.source_id,
                "url": result.url,
                "status": result.status,
                "content_type": result.content_type,
                "title": result.title,
                "excerpt": result.excerpt,
                "error": result.error,
                "failure_reason": result.failure_reason,
                "text_char_count": result.text_char_count,
                "chunk_count": result.chunk_count,
                "fetched_url": result.fetched_url,
            }
            for result in source_fetch_log.results
        ]
    }

source_map_with_fetched_urls = _source_map_with_fetched_urls
source_map_with_fetch_verification_notes = _source_map_with_fetch_verification_notes
synthesis_source_evidence_context = _synthesis_source_evidence_context
source_content_payload = _source_content_payload
weak_fallback_contexts = _weak_fallback_contexts
weak_fallback_context_payload = _weak_fallback_context_payload
source_fetch_log_with_fallbacks = _source_fetch_log_with_fallbacks
source_fetch_log_payload = _source_fetch_log_payload

__all__ = [
    "source_content_payload",
    "source_fetch_log_payload",
    "source_fetch_log_with_fallbacks",
    "source_map_with_fetch_verification_notes",
    "source_map_with_fetched_urls",
    "synthesis_source_evidence_context",
    "weak_fallback_context_payload",
    "weak_fallback_contexts",
]
