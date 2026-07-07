from __future__ import annotations

import hashlib
import html
import re
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import dateparser


_SPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return _SPACE.sub(" ", value.replace("\xa0", " ")).strip()


def html_escape(value: str | None) -> str:
    return html.escape(value or "", quote=False)


def normalize_key(value: str | None) -> str:
    value = clean_text(value or "").lower()
    return _NON_ALNUM.sub(" ", value).strip()


def parse_date(value: str | None, timezone: str = "Africa/Kigali") -> Optional[date]:
    value = clean_text(value or "")
    if not value:
        return None
    # Remove common labels but keep the date content.
    value = re.sub(r"(?i)^(posted|date posted|publication date|published|closing date|deadline|expires|apply by|valid until)[:\-\s]+", "", value).strip()
    settings = {
        "TIMEZONE": timezone,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DAY_OF_MONTH": "first",
        "DATE_ORDER": "DMY",
    }
    dt = dateparser.parse(value, settings=settings)
    if not dt:
        return None
    return dt.date()


def target_yesterday(timezone: str = "Africa/Kigali") -> date:
    now = datetime.now(ZoneInfo(timezone)).date()
    return now - timedelta(days=1)


def canonical_job_key(title: str, org: str, location: str = "", deadline: str = "", link: str = "") -> str:
    """Stable duplicate key across sources.

    We intentionally do not rely only on URL because the same vacancy can appear on
    ReliefWeb, UNJobs, the organization's portal, and the ATS with different URLs.
    """
    base = "|".join([
        normalize_key(title),
        normalize_key(org),
        normalize_key(location),
        normalize_key(str(deadline or "")),
    ])
    if len(normalize_key(title)) < 8:
        base += "|" + normalize_key(link)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
