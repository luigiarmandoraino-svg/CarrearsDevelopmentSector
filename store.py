from __future__ import annotations

import re
from typing import Iterable

from bs4 import BeautifulSoup

from .utils import clean_text, parse_date


FIELD_PATTERNS = {
    "location": [r"(?i)(?:duty station|location|job location|country)\s*[:\-]\s*([^\n|;]+)"],
    "grade": [r"(?i)(?:grade|level|job level)\s*[:\-]\s*([^\n|;]+)", r"\b(P-[1-5]|D-[12]|NO-[A-D]|G-[1-7]|GS-[1-7]|IPSA-\d+|LICA-\d+|ICS-\d+)\b"],
    "posted": [r"(?i)(?:posted|publication date|date posted|published|opening date)\s*[:\-]\s*([^\n|;]+)"],
    "deadline": [r"(?i)(?:deadline|closing date|application deadline|apply by|expires|valid until)\s*[:\-]\s*([^\n|;]+)"],
    "education": [r"(?is)(?:education|minimum education|academic qualifications)\s*[:\-]?\s*(.{0,450})(?:experience|languages|competencies|skills|$)"],
    "languages": [r"(?is)(?:languages?|language requirements?)\s*[:\-]?\s*(.{0,450})(?:competencies|skills|required|deadline|$)"],
    "experience": [r"(?is)(?:experience|required experience|work experience|professional experience)\s*[:\-]?\s*(.{0,700})(?:languages|education|competencies|skills|deadline|$)"],
}

YEARS_RE = re.compile(r"(?i)(?:minimum|at least|a minimum of|not less than|minimum of)?\s*(\d{1,2})\+?\s+(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+)?(?:professional\s+)?experience")


def soup_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return clean_text(soup.get_text("\n"))


def first_match(patterns: Iterable[str], text: str) -> str:
    for p in patterns:
        m = re.search(p, text or "", flags=re.I | re.S)
        if m:
            return clean_text(m.group(1))[:600]
    return ""


def extract_title(html: str, fallback: str = "") -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for selector in ["h1", "h2", "meta[property='og:title']", "title"]:
        el = soup.select_one(selector)
        if not el:
            continue
        value = el.get("content") if el.name == "meta" else el.get_text(" ")
        value = clean_text(value)
        if value:
            return value[:220]
    return clean_text(fallback)[:220]


def extract_requirements(text: str) -> dict:
    exp_section = first_match(FIELD_PATTERNS["experience"], text)
    lang_section = first_match(FIELD_PATTERNS["languages"], text)
    edu_section = first_match(FIELD_PATTERNS["education"], text)

    years = "Not clearly stated"
    m = YEARS_RE.search(exp_section or text)
    if m:
        years = f"Minimum {m.group(1)} years"
    elif exp_section:
        years = clean_text(exp_section)[:260]

    languages = clean_text(lang_section)[:320] if lang_section else "Not clearly stated"
    education = clean_text(edu_section)[:320] if edu_section else "Not clearly stated"

    summary_parts = []
    if years != "Not clearly stated":
        summary_parts.append(f"Experience: {years}.")
    if languages != "Not clearly stated":
        summary_parts.append(f"Languages: {languages}.")
    if education != "Not clearly stated":
        summary_parts.append(f"Education: {education}.")

    sources = []
    if exp_section:
        sources.append("Experience / required experience section")
    if lang_section:
        sources.append("Languages section")
    if edu_section:
        sources.append("Education / qualifications section")

    return {
        "years_experience": years,
        "languages": languages,
        "education": education,
        "requirements_summary": " ".join(summary_parts) if summary_parts else "Not clearly stated",
        "requirement_sources": "; ".join(sources) if sources else "Not clearly stated",
    }


def extract_common_fields(text: str, timezone: str = "Africa/Kigali") -> dict:
    posted_raw = first_match(FIELD_PATTERNS["posted"], text)
    deadline_raw = first_match(FIELD_PATTERNS["deadline"], text)
    return {
        "location": first_match(FIELD_PATTERNS["location"], text),
        "grade": first_match(FIELD_PATTERNS["grade"], text),
        "posted_date": parse_date(posted_raw, timezone) if posted_raw else None,
        "deadline": parse_date(deadline_raw, timezone) if deadline_raw else None,
    }
