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


class QAReview(StrictModel):
    ready_to_publish: bool
    issues: list[QAIssue]
    summary: str | None = None


class Report(StrictModel):
    title: str
    markdown: str
    source_ids: list[str]
    status: str = "draft"


class RunMetadata(StrictModel):
    run_id: str
    created_at: str
    request: str
    status: str
    mode: str = "standard"
    lens: str = "general"
    mock: bool = True
