from __future__ import annotations

from datetime import date
from typing import Any

from agentic_research.models import SourceCandidate, SourceMap, SourceScore
from agentic_research.settings import load_yaml_config


SOURCE_NEED_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "corporate_filing",
        (
            "10-k",
            "10 k",
            "10q",
            "10-q",
            "annual report",
            "form 10",
            "sec filing",
            "filing",
        ),
    ),
    (
        "investor_material",
        (
            "investor presentation",
            "investor presentations",
            "investor material",
            "investor materials",
            "shareholder",
            "investor day",
        ),
    ),
    (
        "primary_company",
        (
            "company website",
            "company site",
            "website",
            "supplier",
            "vendor",
            "product page",
        ),
    ),
    (
        "earnings_transcript",
        (
            "earnings transcript",
            "earnings call",
            "quarterly call",
            "transcript",
        ),
    ),
    (
        "trade_publication",
        (
            "trade publication",
            "trade publications",
            "trade news",
            "merchandising",
            "category-level",
            "category level",
        ),
    ),
    (
        "industry_primer",
        (
            "industry report",
            "industry primer",
            "market primer",
            "market report",
            "association report",
            "consulting report",
        ),
    ),
    (
        "competitor_source",
        (
            "competitor website",
            "competitor source",
            "competitor sources",
            "competitive source",
        ),
    ),
    (
        "government_data",
        (
            "government data",
            "government source",
            "regulatory data",
            "bls",
            "census",
            "fred",
            "world bank",
        ),
    ),
    (
        "expert_blog",
        (
            "expert blog",
            "analyst blog",
            "newsletter",
        ),
    ),
    (
        "whitepaper",
        (
            "whitepaper",
            "white paper",
            "technical report",
        ),
    ),
    (
        "news",
        (
            "news",
            "press coverage",
            "media coverage",
            "recent coverage",
        ),
    ),
)


def _source_taxonomy() -> dict[str, Any]:
    return load_yaml_config("source_taxonomy.yaml").get("source_types", {})


def _scoring_config() -> dict[str, Any]:
    return load_yaml_config("scoring.yaml")


def _parse_publication_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def recency_score(publication_date: str | None, as_of: date | None = None) -> int:
    config = _scoring_config().get("recency_rules", {})
    as_of = as_of or date.today()
    parsed = _parse_publication_date(publication_date)

    if parsed is None:
        return int(config.get("older_or_unknown", 1))

    age = as_of.year - parsed.year
    if age <= 0:
        return int(config.get("current_year", 5))
    if age == 1:
        return int(config.get("previous_year", 4))
    if age <= 3:
        return int(config.get("two_to_three_years_old", 3))
    if age <= 5:
        return int(config.get("four_to_five_years_old", 2))
    return int(config.get("older_or_unknown", 1))


def canonical_source_need(required_source_type: str) -> str:
    normalized = " ".join(required_source_type.strip().lower().replace("_", " ").split())
    source_types = set(_source_taxonomy())
    canonical_candidate = normalized.replace(" ", "_")
    if canonical_candidate in source_types:
        return canonical_candidate

    for canonical, aliases in SOURCE_NEED_ALIASES:
        if any(alias in normalized for alias in aliases):
            return canonical

    return canonical_candidate


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _source_map_note(*, mock: bool) -> str:
    if mock:
        return "Deterministic mock source map. Mock mode does not perform live discovery."
    return "Live checkpoint source map built from discovered sources."


def _default_authority(source: SourceCandidate) -> int:
    taxonomy = _source_taxonomy()
    defaults = taxonomy.get(source.source_type, taxonomy.get("unknown", {}))
    return int(defaults.get("authority_default", 1))


def _default_relevance(source: SourceCandidate) -> int:
    if source.relevance_rationale:
        return 4
    if source.recommended_uses:
        return 3
    return 2


def _default_coverage(source: SourceCandidate) -> int:
    return min(5, max(1, len(source.recommended_uses) + 2))


def score_source(
    source: SourceCandidate,
    *,
    relevance_score: int | None = None,
    coverage_score: int | None = None,
    as_of: date | None = None,
) -> SourceScore:
    config = _scoring_config()
    weights = config["weights"]
    bias_adjustments = config["bias_adjustments"]
    minimums = config["minimums"]

    authority = _default_authority(source)
    relevance = relevance_score or _default_relevance(source)
    recency = recency_score(source.publication_date, as_of=as_of)
    coverage = coverage_score or _default_coverage(source)
    bias_adjustment = float(bias_adjustments.get(source.bias_risk, 0))

    final_score = (
        authority * float(weights["authority"])
        + relevance * float(weights["relevance"])
        + recency * float(weights["recency"])
        + coverage * float(weights["coverage"])
        + bias_adjustment * float(weights["bias_adjustment"])
    )
    final_score = round(final_score, 2)
    include = final_score >= float(minimums["include_by_default_final_score"])

    return SourceScore(
        source_id=source.id,
        authority_score=authority,
        relevance_score=relevance,
        recency_score=recency,
        coverage_score=coverage,
        bias_risk=source.bias_risk,
        final_score=final_score,
        include=include,
        rationale=(
            f"authority={authority}, relevance={relevance}, recency={recency}, "
            f"coverage={coverage}, bias_risk={source.bias_risk}"
        ),
    )


def build_source_map(
    sources: list[SourceCandidate],
    *,
    required_source_types: list[str] | None = None,
    as_of: date | None = None,
    mock: bool = True,
) -> SourceMap:
    scores = sorted(
        [score_source(source, as_of=as_of) for source in sources],
        key=lambda score: score.final_score,
        reverse=True,
    )

    required = _dedupe_preserving_order(
        [canonical_source_need(source_type) for source_type in required_source_types or []]
    )
    present_types = {source.source_type for source in sources}
    gaps = [
        f"Missing source type: {source_type}"
        for source_type in required
        if source_type not in present_types
    ]

    return SourceMap(
        sources=sources,
        scores=scores,
        gaps=gaps,
        notes=_source_map_note(mock=mock),
    )
