from datetime import date

from agentic_research.models import SourceCandidate
from agentic_research.source_scoring import build_source_map, score_source


def test_score_source_uses_authority_recency_bias_and_coverage() -> None:
    source = SourceCandidate(
        id="src_1",
        title="NVIDIA FY2026 Form 10-K",
        publisher="SEC",
        url="https://example.com/nvidia-10k",
        source_type="corporate_filing",
        publication_date="2026-03-01",
        relevance_rationale="Direct company filing for investor preparation.",
        recommended_uses=["financial profile", "risk factors"],
        bias_risk="low",
    )

    score = score_source(source, relevance_score=5, coverage_score=4, as_of=date(2026, 5, 18))

    assert score.authority_score == 5
    assert score.recency_score == 5
    assert score.final_score == 4.4
    assert score.include is True


def test_build_source_map_sorts_scores_and_marks_gaps() -> None:
    strong_source = SourceCandidate(
        id="src_strong",
        title="Company annual report",
        publisher="SEC",
        url="https://example.com/annual-report",
        source_type="corporate_filing",
        bias_risk="low",
        publication_date="2026-01-15",
        relevance_rationale="Direct filing for the company.",
        recommended_uses=["business overview"],
    )
    weak_source = SourceCandidate(
        id="src_weak",
        title="Vendor blog post",
        publisher="Vendor",
        url="https://example.com/vendor-blog",
        source_type="whitepaper",
        bias_risk="high",
        publication_date=None,
        relevance_rationale="Context only.",
        recommended_uses=["context only"],
    )

    source_map = build_source_map(
        [weak_source, strong_source],
        required_source_types=["corporate_filing", "news"],
        as_of=date(2026, 5, 18),
    )

    assert [score.source_id for score in source_map.scores] == ["src_strong", "src_weak"]
    assert source_map.scores[0].include is True
    assert source_map.scores[1].include is False
    assert "Missing source type: news" in source_map.gaps
