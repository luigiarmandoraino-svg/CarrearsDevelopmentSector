from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .base import Parser
from ..fetcher import fetch_json
from ..models import Job
from ..utils import clean_text, parse_date


class ReliefWebParser(Parser):
    """ReliefWeb jobs API parser.

    The API is very useful as a supplemental source. Because ReliefWeb includes
    NGOs too, the main app filters organizations against the non-NGO catalogue
    when STRICT_ORG_CATALOG is enabled.
    """

    API_URL = "https://api.reliefweb.int/v1/jobs"

    async def collect(self, target_date: date) -> list[Job]:
        tz = ZoneInfo(self.timezone)
        start = datetime.combine(target_date, time.min, tzinfo=tz).isoformat()
        end = datetime.combine(target_date, time.max, tzinfo=tz).isoformat()
        params = {
            "appname": "telegram-job-bot",
            "profile": "full",
            "slim": "1",
            "limit": "100",
            "filter[field]": "date.created",
            "filter[value][from]": start,
            "filter[value][to]": end,
            "sort[]": "date.created:desc",
        }
        data = await fetch_json(self.API_URL, params=params)
        jobs: list[Job] = []
        for item in data.get("data", []):
            fields = item.get("fields", {})
            source = fields.get("source") or []
            countries = fields.get("country") or []
            city = clean_text(fields.get("city") or "")
            country = clean_text(", ".join([c.get("name", "") for c in countries if isinstance(c, dict)]))
            org = clean_text(source[0].get("name", "")) if source and isinstance(source[0], dict) else self.source.organization
            title = clean_text(fields.get("title", ""))
            body = clean_text(fields.get("body", ""))
            deadline = None
            if fields.get("date") and isinstance(fields["date"], dict):
                closing = fields["date"].get("closing")
                deadline = parse_date(closing, self.timezone) if closing else None
            jobs.append(Job(
                source_id=self.source.id,
                source_organization=self.source.organization,
                source_name=org,
                title=title,
                link=fields.get("url") or item.get("href") or self.source.url,
                location=clean_text(", ".join([x for x in [city, country] if x])),
                country=country,
                city=city,
                posted_date=target_date,
                deadline=deadline,
                detail_text=body[:12000],
                requirements_summary="See vacancy page / ReliefWeb detail",
                requirement_sources="ReliefWeb API fields; vacancy page for complete requirements",
            ))
        return jobs
