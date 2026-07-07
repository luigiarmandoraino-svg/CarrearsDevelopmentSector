from __future__ import annotations

from datetime import date
from urllib.parse import urljoin, urlparse
import re

from bs4 import BeautifulSoup

from .base import Parser
from ..extract import soup_text, extract_title, extract_common_fields, extract_requirements
from ..fetcher import fetch_url
from ..models import Job
from ..utils import clean_text

LIKELY_JOB = re.compile(r"(?i)(job|career|vacanc|opening|position|opportunit|requisition|apply|consultancy|internship|employment)")
BAD_EXT = re.compile(r"(?i)\.(pdf|docx?|xlsx?|pptx?|jpg|png|zip)$")


class GenericHtmlParser(Parser):
    def __init__(self, source, timezone="Africa/Kigali", use_playwright=False):
        super().__init__(source, timezone)
        self.use_playwright = use_playwright

    async def collect(self, target_date: date) -> list[Job]:
        html = await fetch_url(self.source.url, use_playwright=self.use_playwright)
        links = self._extract_job_links(html)
        jobs: list[Job] = []
        for title, href in links[: self.source.max_detail_pages_per_run]:
            try:
                detail_html = await fetch_url(href, use_playwright=self.use_playwright)
                text = soup_text(detail_html)
                job_title = extract_title(detail_html, fallback=title)
                common = extract_common_fields(text, self.timezone)
                reqs = extract_requirements(text)
                job = Job(
                    source_id=self.source.id,
                    source_organization=self.source.organization,
                    title=job_title or title,
                    link=href,
                    location=common.get("location") or "",
                    grade=common.get("grade") or "",
                    posted_date=common.get("posted_date"),
                    deadline=common.get("deadline"),
                    detail_text=text[:12000],
                    **reqs,
                )
                jobs.append(job)
            except Exception as exc:
                # Keep going. The run log in main captures source-level failures; detail-level
                # failures are attached to raw jobs only when a job could be built.
                continue
        return jobs

    def _extract_job_links(self, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html or "", "lxml")
        base_host = urlparse(self.source.url).netloc
        found: list[tuple[str, str]] = []
        seen = set()
        for a in soup.find_all("a", href=True):
            txt = clean_text(a.get_text(" "))
            href = urljoin(self.source.url, a["href"])
            if href in seen or BAD_EXT.search(href):
                continue
            if not txt or len(txt) < 4:
                continue
            combined = f"{txt} {href}"
            if not LIKELY_JOB.search(combined):
                continue
            # Avoid drifting to unrelated domains except known ATS subdomains.
            host = urlparse(href).netloc
            if base_host and host and base_host not in host and not any(x in host for x in ["workday", "oraclecloud", "successfactors", "taleo", "csod", "greenhouse", "lever", "career"]):
                continue
            found.append((txt[:220], href))
            seen.add(href)
        return found
