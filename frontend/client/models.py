from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class InterviewRecord:
    id: int
    company_name: str
    position_name: str
    base_location: str
    current_status: str
    interview_time: str | None = None
    job_url: str | None = None
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InterviewRecord":
        return cls(**data)


@dataclass(slots=True)
class JobRecommendation:
    id: str
    company_name: str
    position_name: str
    base_location: str
    match_score: int
    match_reasons: list[str] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)
    jd_summary: str = ""
    job_description: str = ""
    job_url: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobRecommendation":
        return cls(**data)
