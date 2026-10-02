from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "GenerationAttempt",
    "GenerationMode",
    "QualityIssue",
    "ScriptFact",
    "ScriptGenerationAudit",
    "ScriptGenerationResult",
    "ScriptPlan",
    "ScriptQualityReport",
    "StructuredFacts",
]

GenerationMode = Literal["rule", "llm", "llm_repaired", "validated_rule_fallback"]


class ScriptFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    section: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    required: bool = False
    numbers: list[str] = Field(default_factory=list, max_length=20)
    entities: list[str] = Field(default_factory=list, max_length=20)
    status_markers: list[str] = Field(default_factory=list, max_length=20)
    kind: Literal["context", "summary", "ai", "index", "sector", "strategy", "risk", "asset"] = "context"
    subject: str | None = Field(default=None, max_length=120)
    direction: Literal["up", "down", "flat", "mixed"] | None = None
    unit: Literal["point", "percent", "percentage_point", "currency", "other"] | None = None


class StructuredFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["ai_briefing", "finance", "finance_multi_asset"]
    facts: list[ScriptFact] = Field(min_length=1, max_length=60)

    @property
    def source_numbers(self) -> list[str]:
        return sorted({number for fact in self.facts for number in fact.numbers})

    @property
    def entities(self) -> list[str]:
        return list(dict.fromkeys(entity for fact in self.facts for entity in fact.entities))


class ScriptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mainline: str = Field(min_length=1, max_length=300)
    main_fact_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    opening: str = Field(min_length=1, max_length=300)
    sections: list[str] = Field(min_length=2, max_length=8)
    required_facts: list[str] = Field(min_length=1, max_length=30)
    risk_close: str | None = Field(default=None, max_length=400)


class QualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    severity: Literal["error", "warning"]
    evidence: str | None = Field(default=None, max_length=500)


class ScriptQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    character_count: int = Field(ge=0)
    issues: list[QualityIssue] = Field(default_factory=list)
    checked_at: str = Field(max_length=80)

    @property
    def errors(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]


class GenerationAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["plan", "draft", "repair", "fallback"]
    index: int = Field(ge=0)
    prompt_version: str = Field(min_length=1, max_length=120)
    output: str = Field(default="", max_length=8000)
    error: str | None = Field(default=None, max_length=2000)
    quality_report: ScriptQualityReport | None = None


class ScriptGenerationAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation_mode: GenerationMode
    prompt_version: str = Field(min_length=1, max_length=120)
    plan: ScriptPlan | None = None
    attempts: list[GenerationAttempt] = Field(default_factory=list, max_length=10)
    quality_report: ScriptQualityReport
    fallback_reason: str | None = Field(default=None, max_length=2000)


class ScriptGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: str = Field(min_length=1, max_length=8000)
    audit: ScriptGenerationAudit
