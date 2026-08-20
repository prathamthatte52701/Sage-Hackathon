from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Severity = Literal["critical", "high", "medium", "low"]


class StandardRef(BaseModel):
    name: str
    reference: str


class KnowledgeRecord(BaseModel):
    rule_id: str
    title: str
    category: str
    subcategory: str = ""
    language: list[str] = Field(default_factory=lambda: ["any"])
    framework: list[str] = Field(default_factory=lambda: ["any"])
    severity: Severity = "medium"
    description: str
    why_it_matters: str
    bad_patterns: list[str] = Field(default_factory=list)
    good_patterns: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    detection_hints: list[str] = Field(default_factory=list)
    fix_strategy: str
    production_impact: str
    standards: list[StandardRef] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    content: str
    version: int = 1
    embedding: list[float] | None = None
    embedding_model: str | None = None
    content_hash: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("language", "framework")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized = sorted({v.strip().lower() for v in values if v.strip()})
        return normalized or ["any"]

    def normalized_content(self) -> str:
        sections = [
            self.title,
            self.category,
            self.subcategory,
            self.description,
            self.why_it_matters,
            "Bad patterns: " + "; ".join(self.bad_patterns),
            "Good patterns: " + "; ".join(self.good_patterns),
            "Exceptions: " + "; ".join(self.exceptions),
            "Detection hints: " + "; ".join(self.detection_hints),
            self.fix_strategy,
            self.production_impact,
            self.content,
        ]
        return "\n".join(part.strip() for part in sections if part and part.strip())

    def with_ingestion_metadata(self, embedding: list[float], embedding_model: str) -> dict:
        now = datetime.now(timezone.utc)
        content_hash = sha256(self.normalized_content().encode("utf-8")).hexdigest()
        doc = self.model_dump()
        doc.update(
            {
                "embedding": embedding,
                "embedding_model": embedding_model,
                "content_hash": content_hash,
                "updated_at": now,
                "created_at": self.created_at or now,
            }
        )
        return doc
