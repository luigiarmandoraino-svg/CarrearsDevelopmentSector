from __future__ import annotations

import csv
from pathlib import Path

from .models import Source


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"true", "yes", "1", "y"}


def load_sources(path: str) -> list[Source]:
    out: list[Source] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            max_pages = row.get("Max_Detail_Pages_Per_Run") or row.get("max_detail_pages_per_run") or 25
            try:
                max_pages = int(max_pages)
            except Exception:
                max_pages = 25
            out.append(Source(
                id=str(row.get("ID") or row.get("id") or row.get("Organization") or ""),
                organization=row.get("Organization") or "",
                acronym=row.get("Acronym") or "",
                category=row.get("Category") or "",
                url=row.get("Career_Page_URL") or row.get("url") or "",
                parser=row.get("Parser") or "generic_html",
                enabled=_truthy(row.get("Enabled") or "true"),
                priority=row.get("Priority") or "Medium",
                platform=row.get("Platform_or_ATS") or "",
                max_detail_pages_per_run=max_pages,
                raw=row,
            ))
    return [s for s in out if s.url and s.enabled]


def organization_aliases(sources: list[Source]) -> set[str]:
    aliases: set[str] = set()
    for s in sources:
        for v in [s.organization, s.acronym]:
            v = (v or "").lower().strip()
            if v and len(v) > 2:
                aliases.add(v)
        # Common shorter form mappings can be added here as the bot learns.
    return aliases
