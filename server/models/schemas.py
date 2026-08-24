from typing import Literal, Optional

from pydantic import BaseModel, Field

Language = Literal["javascript", "python", "java", "cpp", "typescript"]
Severity = Literal["critical", "high", "medium", "low"]
Category = Literal[
    "security", "logic", "performance", "style", "best_practice",
    "correctness", "reliability", "database", "api_design", "architecture",
    "data_integrity", "privacy", "maintainability", "production_readiness",
]


class ReviewRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=7000)
    language: Language


class Issue(BaseModel):
    line: int = 0
    severity: Severity = "low"
    category: Category = "best_practice"
    issue: str = ""
    fix_suggestion: str = "No specific suggestion available"
    confidence: float = 0.5
    needs_human_review: bool = False
    rule: str = ""
    evidence: str = ""
    missing_control: str = ""
    source: Literal["deterministic", "ai_quality"] | str = ""
    knowledge_standards: list[dict] = []


class ReviewResponse(BaseModel):
    issues: list[Issue] = []
    summary: str = ""
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


class ExplainRequest(BaseModel):
    issue: dict
    code_context: str
    language: str


class FindingReasoning(BaseModel):
    findingConfirmed: bool = True
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    reasoning: str = "AI reasoning unavailable"
    impact: str = ""
    recommendation: str = ""
    suggestedFix: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    citedStandards: list[dict] = []


class FindingReasonRequest(BaseModel):
    finding_index: int = -1
    finding_id: str = ""


class GithubImportRequest(BaseModel):
    repo_url: str = Field(..., min_length=1, max_length=300)
    session_id: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


class FindingTransform(BaseModel):
    original_snippet: str = ""
    proposed_fix: str = ""
    explanation: str = "AI fix generation unavailable"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    finding_id: str = ""
    rule_id: str = ""
    file: str = ""
    line: int = 0
    summary: str = ""
    explanation_bullets: list[str] = []
    original_code: str = ""
    fixed_code: str = ""
    diff: str = ""
    can_apply: bool = False
    apply_failure_reason: str = ""
    target_file: str = ""
    document_type: Literal["paste", "project"] | str = ""
    start_line: int = 0
    end_line: int = 0
    target_start: int = 0
    target_end: int = 0
    source_hash: str = ""
    validation: dict[str, bool] = Field(default_factory=dict)


class HackerLensEvidence(BaseModel):
    file: str = ""
    line: int | None = None
    function: str = ""
    route: str = ""


class HackerLensObservation(BaseModel):
    title: str = ""
    risk: Severity = "low"
    reason: str = ""
    evidence: list[HackerLensEvidence] = []
    potential_impact: str = ""
    hardening_action: str = ""
    # True only once every evidence entry's file was cross-checked against
    # the project's real files server-side -- never trust the model's own
    # claim that a reference is real.
    verified: bool = False


class HackerLensTopTarget(BaseModel):
    rank: int = 0
    title: str = ""
    reason: str = ""
    evidence: list[HackerLensEvidence] = []


class HackerLensRiskPath(BaseModel):
    label: str = ""
    steps: list[str] = []
    evidence: list[HackerLensEvidence] = []


class HackerLensReport(BaseModel):
    summary: str = "Hacker Mode analysis is currently unavailable."
    attack_surface_score: float = Field(0.0, ge=0.0, le=10.0)
    # Derived server-side from attack_surface_score by fixed thresholds, never
    # taken as-is from the model -- "do not let the model output an arbitrary
    # score/label without reasoning" from the spec.
    attack_surface_label: Severity = "low"
    score_reasoning: str = ""
    top_targets: list[HackerLensTopTarget] = []
    attack_surfaces: list[str] = []
    risk_paths: list[HackerLensRiskPath] = []
    adversarial_observations: list[HackerLensObservation] = []
    hacker_hypotheses: list[HackerLensObservation] = []
    hardening_priorities: list[str] = []
    files_analyzed: list[str] = []
    error: str = ""


BrutalAuditCategory = Literal[
    "security",
    "architecture",
    "reliability",
    "maintainability",
    "code_quality",
    "production_readiness",
]


class BrutalAuditEvidence(BaseModel):
    file: str = ""
    line: int | None = None
    function: str = ""
    route: str = ""


class BrutalAuditCriticism(BaseModel):
    title: str = ""
    severity: Severity = "low"
    category: BrutalAuditCategory = "code_quality"
    reason: str = ""
    evidence: list[BrutalAuditEvidence] = []
    impact: str = ""
    improvement: str = ""
    verified: bool = False


class BrutalAuditCategoryAnalysis(BaseModel):
    category: BrutalAuditCategory = "code_quality"
    score: float = Field(0.0, ge=0.0, le=10.0)
    reasoning: str = ""
    evidence: list[BrutalAuditEvidence] = []


class BrutalAuditAreaScore(BaseModel):
    category: BrutalAuditCategory = "code_quality"
    score: float = Field(0.0, ge=0.0, le=10.0)


class BrutalAuditSnapshot(BaseModel):
    files_analyzed: int = 0
    source_files_analyzed: int = 0
    api_entry_points: int = 0
    functions_classes: int = 0
    database_interaction_areas: int = 0
    external_integrations: int = 0
    privileged_operations: int = 0
    authentication_components: int = 0
    filesystem_usage: int = 0
    large_files: int = 0
    large_functions: int = 0
    frameworks: list[str] = []
    languages: list[str] = []
    dependencies: list[str] = []


class BrutalAuditReport(BaseModel):
    summary: str = "Brutal Audit is currently unavailable."
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
    error: str = ""


class PasteFixRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=7000)
    language: Language
    issue: dict


class ApplyProjectFixRequest(BaseModel):
    finding_index: int = -1
    finding_id: str = ""


class DownloadProjectRequest(BaseModel):
    filename: str | None = None


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    created_at: str = ""
