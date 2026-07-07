from __future__ import annotations

from datetime import date

import feedparser

from .base import Parser
from ..fetcher import fetch_url
from ..models import Job
from ..utils import clean_text, parse_date


class RssParser(Parser):
    async def collect(self, target_date: date) -> list[Job]:
        content = await fetch_url(self.source.url)
        feed = feedparser.parse(content)
        jobs: list[Job] = []
        for entry in feed.entries:
            published = parse_date(getattr(entry, "published", None) or getattr(entry, "updated", None), self.timezone)
            summary = clean_text(getattr(entry, "summary", ""))
            jobs.append(Job(
                source_id=self.source.id,
                source_organization=self.source.organization,
                title=clean_text(getattr(entry, "title", "")),
                link=getattr(entry, "link", self.source.url),
                posted_date=published,
                detail_text=summary,
                requirements_summary="See vacancy page",
                requirement_sources="RSS entry; open vacancy page for full requirements",
            ))
        return jobs
