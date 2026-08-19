from typing import Literal, Optional

from pydantic import BaseModel, Field

Language = Literal["javascript", "python", "java", "cpp", "typescript"]
Severity = Literal["critical", "medium", "low"]
Category = Literal["security", "logic", "performance", "style", "best_practice"]


class ReviewRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=3000)
    language: Language


class Issue(BaseModel):
    line: int = 0
    severity: Severity = "low"
    category: Category = "best_practice"
    issue: str = ""
    fix_suggestion: str = "No specific suggestion available"
    confidence: float = 0.5
    needs_human_review: bool = False


class ReviewResponse(BaseModel):
    issues: list[Issue] = []
    summary: str = ""


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
    confidence: float = 0.0
    citedStandards: list[dict] = []


class FindingReasonRequest(BaseModel):
    finding_index: int
