from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict

Language = Literal["javascript", "python", "java", "cpp", "typescript"]
Severity = Literal["critical", "high", "medium", "low"]
Category = Literal[
    "security", "logic", "performance", "style", "best_practice",
    "correctness", "reliability", "database", "api_design", "architecture",
    "data_integrity", "privacy", "maintainability", "production_readiness",
]

# Base model with strict config for all request models
class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewRequest(StrictBaseModel):
    code: str = Field(..., min_length=1, max_length=7000)
    language: Language


class Issue(StrictBaseModel):
    line: int = Field(0, ge=0)
    severity: Severity = "low"
    category: Category = "best_practice"
    issue: str = Field("", max_length=5000)
    fix_suggestion: str = Field("No specific suggestion available", max_length=5000)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    needs_human_review: bool = False
    rule: str = Field("", max_length=200)
    evidence: str = Field("", max_length=5000)
    missing_control: str = Field("", max_length=5000)
    source: Literal["deterministic", "ai_quality"] | str = ""
    knowledge_standards: list[dict] = []


class ReviewResponse(StrictBaseModel):
    issues: list[Issue] = []
    summary: str = Field("", max_length=10000)
    deterministic_findings: list[Issue] = []
    ai_quality_review: list[Issue] = []
    knowledge_retrieval: dict = {}
    language_detection: dict = {}
    # Phase 1 closed-world gate output (services/security_rules.py): only
    # deterministic findings whose rule maps to one of the active V1
    # SEC-* families and carry a real file/line survive here. Additive --
    # existing `issues`/`ai_quality_review` fields are untouched so the
    # current UI doesn't break; later phases will switch primary UI to
    # consume this field exclusively.
    security_findings: list[dict] = []


class ExplainRequest(StrictBaseModel):
    issue: dict
    code_context: str = Field(..., min_length=1, max_length=10000)
    language: str = Field(..., min_length=1, max_length=50)


class FindingReasoning(StrictBaseModel):
    findingConfirmed: bool = True
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    reasoning: str = Field("AI reasoning unavailable", max_length=5000)
    impact: str = Field("", max_length=5000)
    recommendation: str = Field("", max_length=5000)
    suggestedFix: str = Field("", max_length=5000)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    citedStandards: list[dict] = []


class FindingReasonRequest(StrictBaseModel):
    finding_index: int = Field(-1, ge=-1)
    finding_id: str = Field("", max_length=200)


class GithubImportRequest(StrictBaseModel):
    repo_url: str = Field(..., min_length=1, max_length=300)
    session_id: str = Field(..., min_length=1, max_length=200)


class ChatRequest(StrictBaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class FindingTransform(StrictBaseModel):
    original_snippet: str = Field("", max_length=50000)
    proposed_fix: str = Field("", max_length=50000)
    explanation: str = Field("AI fix generation unavailable", max_length=10000)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    finding_id: str = Field("", max_length=200)
    rule_id: str = Field("", max_length=200)
    file: str = Field("", max_length=500)
    line: int = Field(0, ge=0)
    summary: str = Field("", max_length=2000)
    explanation_bullets: list[str] = Field(default_factory=list)
    original_code: str = Field("", max_length=50000)
    fixed_code: str = Field("", max_length=50000)
    diff: str = Field("", max_length=50000)
    can_apply: bool = False
    apply_failure_reason: str = Field("", max_length=2000)
    target_file: str = Field("", max_length=500)
    document_type: Literal["paste", "project"] | str = ""
    start_line: int = Field(0, ge=0)
    end_line: int = Field(0, ge=0)
    target_start: int = Field(0, ge=0)
    target_end: int = Field(0, ge=0)
    source_hash: str = Field("", max_length=64)
    validation: dict[str, bool] = Field(default_factory=dict)


class HackerLensEvidence(StrictBaseModel):
    file: str = Field("", max_length=500)
    line: int | None = Field(None, ge=0)
    function: str = Field("", max_length=200)
    route: str = Field("", max_length=500)


class HackerLensObservation(StrictBaseModel):
    title: str = Field("", max_length=500)
    risk: Severity = "low"
    reason: str = Field("", max_length=5000)
    evidence: list[HackerLensEvidence] = []
    potential_impact: str = Field("", max_length=5000)
    hardening_action: str = Field("", max_length=5000)
    # True only once every evidence entry's file was cross-checked against
    # the project's real files server-side -- never trust the model's own
    # claim that a reference is real.
    verified: bool = False


class HackerLensTopTarget(StrictBaseModel):
    rank: int = Field(0, ge=0)
    title: str = Field("", max_length=500)
    reason: str = Field("", max_length=5000)
    evidence: list[HackerLensEvidence] = []


class HackerLensRiskPath(StrictBaseModel):
    label: str = Field("", max_length=500)
    steps: list[str] = Field(default_factory=list)
    evidence: list[HackerLensEvidence] = []


class HackerLensReport(StrictBaseModel):
    summary: str = Field("Hacker Mode analysis is currently unavailable.", max_length=10000)
    attack_surface_score: float = Field(0.0, ge=0.0, le=10.0)
    # Derived server-side from attack_surface_score by fixed thresholds, never
    # taken as-is from the model -- "do not let the model output an arbitrary
    # score/label without reasoning" from the spec.
    attack_surface_label: Severity = "low"
    score_reasoning: str = Field("", max_length=5000)
    top_targets: list[HackerLensTopTarget] = []
    attack_surfaces: list[str] = []
    risk_paths: list[HackerLensRiskPath] = []
    adversarial_observations: list[HackerLensObservation] = []
    hacker_hypotheses: list[HackerLensObservation] = []
    hardening_priorities: list[str] = []
    files_analyzed: list[str] = []
    error: str = Field("", max_length=5000)


BrutalAuditCategory = Literal[
    "security",
    "architecture",
    "reliability",
    "maintainability",
    "code_quality",
    "production_readiness",
]


class BrutalAuditEvidence(StrictBaseModel):
    file: str = Field("", max_length=500)
    line: int | None = Field(None, ge=0)
    function: str = Field("", max_length=200)
    route: str = Field("", max_length=500)


class BrutalAuditCriticism(StrictBaseModel):
    title: str = Field("", max_length=500)
    severity: Severity = "low"
    category: BrutalAuditCategory = "code_quality"
    reason: str = Field("", max_length=5000)
    evidence: list[BrutalAuditEvidence] = []
    impact: str = Field("", max_length=5000)
    improvement: str = Field("", max_length=5000)
    verified: bool = False


class BrutalAuditCategoryAnalysis(StrictBaseModel):
    category: BrutalAuditCategory = "code_quality"
    score: float = Field(0.0, ge=0.0, le=10.0)
    reasoning: str = Field("", max_length=5000)
    evidence: list[BrutalAuditEvidence] = []


class BrutalAuditAreaScore(StrictBaseModel):
    category: BrutalAuditCategory = "code_quality"
    score: float = Field(0.0, ge=0.0, le=10.0)


class BrutalAuditSnapshot(StrictBaseModel):
    files_analyzed: int = Field(0, ge=0)
    source_files_analyzed: int = Field(0, ge=0)
    api_entry_points: int = Field(0, ge=0)
    functions_classes: int = Field(0, ge=0)
    database_interaction_areas: int = Field(0, ge=0)
    external_integrations: int = Field(0, ge=0)
    privileged_operations: int = Field(0, ge=0)
    authentication_components: int = Field(0, ge=0)
    filesystem_usage: int = Field(0, ge=0)
    large_files: int = Field(0, ge=0)
    large_functions: int = Field(0, ge=0)
    frameworks: list[str] = []
    languages: list[str] = []
    dependencies: list[str] = []


class BrutalAuditReport(StrictBaseModel):
    summary: str = Field("Brutal Audit is currently unavailable.", max_length=10000)
    category_scores: dict[BrutalAuditCategory, float] = {}
    category_analysis: list[BrutalAuditCategoryAnalysis] = []
    code_review_rejections: list[BrutalAuditCriticism] = []
    strongest_areas: list[str] = []
    weakest_areas: list[BrutalAuditAreaScore] = []
    production_blockers: list[str] = []
    top_improvements: list[str] = []
    repository_snapshot: BrutalAuditSnapshot = Field(default_factory=BrutalAuditSnapshot)
    overall_score: float = Field(0.0, ge=0.0, le=10.0)
    verdict: Literal[
        "NOT READY",
        "NEEDS MAJOR WORK",
        "PROMISING BUT NOT PRODUCTION READY",
        "READY WITH HARDENING",
        "PRODUCTION READY",
    ] = "NOT READY"
    files_analyzed: list[str] = []
    error: str = Field("", max_length=5000)


class PasteFixRequest(StrictBaseModel):
    code: str = Field(..., min_length=1, max_length=7000)
    language: Language
    issue: dict


class ApplyProjectFixRequest(StrictBaseModel):
    finding_index: int = Field(-1, ge=-1)
    finding_id: str = Field("", max_length=200)


class DownloadProjectRequest(StrictBaseModel):
    filename: str | None = Field(None, max_length=200)


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., min_length=1, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=512)


class ResendVerificationRequest(BaseModel):
    pass


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=512)
    password: str = Field(..., min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=1, max_length=200)


class ChangeEmailRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_email: str = Field(..., min_length=3, max_length=254)


class UserOut(StrictBaseModel):
    id: str
    email: str = Field(..., max_length=254)
    email_verified: bool = False
    role: str = Field("user", max_length=50)
    status: str = Field("active", max_length=50)
    created_at: str = ""
    updated_at: str = ""
