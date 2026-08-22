from pydantic import BaseModel, Field


class FindingAnalysis(BaseModel):
    confirmed: bool
    severity: str
    reason: str
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)