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
    # deterministic findings whose rule maps to one of the 12 locked
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
