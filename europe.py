from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Dict, Any


@dataclass
class Source:
    id: str
    organization: str
    acronym: str
    category: str
    url: str
    parser: str = "generic_html"
    enabled: bool = True
    priority: str = "Medium"
    platform: str = ""
    max_detail_pages_per_run: int = 25
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    source_id: str
    source_organization: str
    title: str
    link: str
    location: str = ""
    country: str = ""
    city: str = ""
    grade: str = ""
    job_type: str = "Unknown"
    posted_date: Optional[date] = None
    deadline: Optional[date] = None
    years_experience: str = "Not clearly stated"
    languages: str = "Not clearly stated"
    education: str = "Not clearly stated"
    requirements_summary: str = "Not clearly stated"
    requirement_sources: str = "Not clearly stated"
    detail_text: str = ""
    source_name: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def display_org(self) -> str:
        return self.source_name or self.source_organization
