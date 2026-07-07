from __future__ import annotations

import re
from datetime import date
from typing import Tuple

from .europe import is_europe_location
from .models import Job


NATIONAL_PATTERNS = [
    r"\bnational\b", r"\blocal\b", r"\bno[- ]?[abcd]\b", r"\bnoa\b", r"\bnob\b", r"\bnoc\b",
    r"\bg[- ]?[1-7]\b", r"\bgs[- ]?[1-7]\b", r"\bgeneral service\b", r"\bservice contract\b",
    r"\bsb[- ]?[1-5]\b", r"\blica[- ]?[1-9]\b", r"\bipsa[- ]?[1-9]\b", r"\bunops lica\b"
]
INTERNATIONAL_PATTERNS = [
    r"\binternational\b", r"\bp[- ]?[1-5]\b", r"\bd[- ]?[12]\b", r"\bip[- ]?[1-5]\b", r"\bics[- ]?\d+\b",
    r"\bprofessional\b", r"\bconsultant\b", r"\broster\b"
]


def classify_job(job: Job) -> str:
    text = " ".join([job.title, job.grade, job.job_type, job.detail_text[:5000]]).lower()
    if any(re.search(p, text, re.I) for p in NATIONAL_PATTERNS):
        if "international consultant" in text or "international position" in text:
            return "International"
        return "National/Local"
    if any(re.search(p, text, re.I) for p in INTERNATIONAL_PATTERNS):
        return "International"
    return "Unknown / likely international"


def should_keep(job: Job, target_date: date, strict_posted_date: bool = True) -> Tuple[bool, str]:
    if strict_posted_date:
        if not job.posted_date:
            return False, "Skipped: no reliable posted/publication date found"
        if job.posted_date != target_date:
            return False, f"Skipped: posted date {job.posted_date} is not target date {target_date}"

    classification = classify_job(job)
    job.job_type = classification
    if classification == "National/Local" and not is_europe_location(job.location, job.country):
        return False, "Skipped: national/local position outside Europe"
    return True, "Included"
