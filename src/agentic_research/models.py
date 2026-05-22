from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TargetType = Literal["company", "industry", "market", "competitor_set", "person", "other"]
ResearchLens = Literal[
    "general",
    "sales",
    "investment",
    "interview",
    "strategy",
    "industry",
    "diligence",
]
ResearchDepth = Literal["brief", "standard", "deep_dive"]
BiasRisk = Literal["low", "medium", "high"]
ClaimType = Literal["fact", "inference", "opinion", "unknown"]
Confidence = Literal["high", "medium", "low"]
Severity = Literal["high", "medium", "low"]
SourceFetchStatus = Literal["fetched", "failed", "skipped", "fallback"]
SourceFetchFailureReason = Literal[
    "http_403",
    "timeout",
    "unsupported_content_type",
    "pdf_skipped",
    "no_readable_text",
    "bad_url",
    "bot_access_block",
    "http_error",
    "fetch_error",
    "pdf_extraction_failed",
]
FallbackContextType = Literal["search_snippet_only", "metadata_only"]
RunType = Literal["checkpoint", "full", "continue"]
IssueCategory = Literal[
    "unsupported_claim",
    "weak_source",
    "missing_recent_signal",
    "overconfident_inference",
    "source_gap",
    "stale_or_unclear_recency",
    "missing_user_context",
    "report_structure_issue",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchQuestion(StrictModel):
    id: str
    question: str
    rationale: str | None = None
    priority: int = Field(default=3, ge=1, le=5)


class ResearchCharter(StrictModel):
    target: str
    target_type: TargetType
    research_lens: ResearchLens
    depth: ResearchDepth
    deliverable: str
    key_questions: list[str]
    geography: str = "global"
    time_horizon: str = "current and recent developments"
    known_constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)


class ResearchPlan(StrictModel):
    research_questions: list[str]
    report_sections: list[str]
    required_source_types: list[str]
    checkpoint_questions: list[str]
    likely_specialists: list[str] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


class CheckpointAnswer(StrictModel):
    question: str
    answer: str


class UserFeedback(StrictModel):
    answered_checkpoint_questions: list[CheckpointAnswer] = Field(default_factory=list)
    approved_source_ids: list[str] = Field(default_factory=list)
    rejected_source_ids: list[str] = Field(default_factory=list)
    depth_override: ResearchDepth | None = None
    lens_override: ResearchLens | None = None
    user_notes: str | None = None
    priority_topics: list[str] = Field(default_factory=list)


class SourceCandidate(StrictModel):
    id: str
    title: str
    publisher: str
    url: str
    source_type: str
    bias_risk: BiasRisk
    relevance_rationale: str
    recommended_uses: list[str]
    publication_date: str | None = None
    notes: str | None = None


class SourceScore(StrictModel):
    source_id: str
    authority_score: float = Field(ge=1, le=5)
    relevance_score: float = Field(ge=1, le=5)
    recency_score: float = Field(ge=1, le=5)
    coverage_score: float = Field(ge=1, le=5)
    bias_risk: BiasRisk
    final_score: float
    include: bool = False
    rationale: str | None = None


class SourceMap(StrictModel):
    sources: list[SourceCandidate]
    scores: list[SourceScore]
    gaps: list[str]
    notes: str | None = None


class SourceDiscoveryResult(StrictModel):
    sources: list[SourceCandidate]
    gaps: list[str] = Field(default_factory=list)
    notes: str | None = None


class SourceChunk(StrictModel):
    source_id: str
    url: str
    chunk_id: str
    index: int
    text: str


class SourceContent(StrictModel):
    source_id: str
    url: str
    content_type: str | None = None
    title: str | None = None
    text: str
    excerpt: str | None = None
    chunks: list[SourceChunk] = Field(default_factory=list)


class SourceFetchResult(StrictModel):
    source_id: str
    url: str
    status: SourceFetchStatus
    content_type: str | None = None
    title: str | None = None
    excerpt: str | None = None
    error: str | None = None
    failure_reason: SourceFetchFailureReason | None = None
    text_char_count: int = 0
    chunk_count: int = 0
    fetched_url: str | None = None


class SourceFetchLog(StrictModel):
    results: list[SourceFetchResult] = Field(default_factory=list)


class SourceFallbackContext(StrictModel):
    source_id: str
    url: str
    title: str
    publisher: str
    snippet: str | None = None
    context_type: FallbackContextType
    evidence_strength: Literal["weak"] = "weak"
    caveats: list[str] = Field(default_factory=list)


class EvidenceClaim(StrictModel):
    id: str
    claim: str
    claim_type: ClaimType
    confidence: Confidence
    report_section: str
    source_id: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    source_type: str | None = None
    quote_or_excerpt: str | None = None


class EvidenceLedger(StrictModel):
    claims: list[EvidenceClaim] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)


class EvidenceExtractionResult(StrictModel):
    claims: list[EvidenceClaim]
    notes: str | None = None


class SpecialistAnalysis(StrictModel):
    specialist: str
    summary: str
    evidence_claims: list[EvidenceClaim] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class QAIssue(StrictModel):
    severity: Severity
    problem: str
    suggested_fix: str
    affected_section: str | None = None
    category: IssueCategory | None = None


class QAReview(StrictModel):
    ready_to_publish: bool
    issues: list[QAIssue]
    summary: str | None = None


class Report(StrictModel):
    title: str
    markdown: str
    source_ids: list[str]
    claim_ids: list[str] = Field(default_factory=list)
    status: str = "draft"


class RunMetadata(StrictModel):
    run_id: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    request: str
    status: str
    status_reason: str | None = None
    mode: str = "standard"
    lens: str = "general"
    mock: bool = True
    model: str | None = None
    run_type: RunType | None = None
