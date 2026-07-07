from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from rapidfuzz import fuzz

from .filtering import should_keep, classify_job
from .models import Job, Source
from .parsers import GenericHtmlParser, ReliefWebParser, RssParser
from .sources import load_sources, organization_aliases
from .store import Store
from .telegram import send_jobs
from .utils import target_yesterday


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"true", "1", "yes", "y"}


def build_parser(source: Source, timezone: str, use_playwright_default: bool = False):
    parser = source.parser.lower()
    if parser == "reliefweb_api":
        return ReliefWebParser(source, timezone)
    if parser == "rss":
        return RssParser(source, timezone)
    if parser == "generic_playwright":
        return GenericHtmlParser(source, timezone, use_playwright=use_playwright_default)
    return GenericHtmlParser(source, timezone, use_playwright=use_playwright_default)


def same_org_allowed(job: Job, allowed: set[str]) -> bool:
    """For aggregator feeds, prevent NGOs from entering the no-NGO bot.

    This is intentionally fuzzy because ReliefWeb/UNJobs names often differ from
    the official catalogue, e.g. 'UN Children's Fund' vs 'UNICEF'.
    """
    org = (job.display_org or "").lower().strip()
    if not org:
        return False
    if org in allowed:
        return True
    for alias in allowed:
        if alias and (alias in org or org in alias):
            return True
        if len(alias) > 4 and fuzz.token_set_ratio(alias, org) >= 88:
            return True
    return False


def dedupe_jobs(jobs: list[Job], store: Store) -> list[Job]:
    by_key: dict[str, Job] = {}
    for job in jobs:
        key = store.job_key(job)
        current = by_key.get(key)
        if not current:
            by_key[key] = job
            continue
        # Keep the richer record when duplicate appears from multiple pages.
        richness = len(job.detail_text or "") + len(job.requirements_summary or "")
        current_richness = len(current.detail_text or "") + len(current.requirements_summary or "")
        if richness > current_richness:
            by_key[key] = job
    return list(by_key.values())


async def run(args: argparse.Namespace) -> int:
    load_dotenv(args.env_file)
    timezone = args.timezone or os.getenv("TZ", "Africa/Kigali")
    target_date = args.target_date or target_yesterday(timezone)
    source_csv = args.sources or os.getenv("SOURCE_CSV", "sources.csv")
    db_path = args.db or os.getenv("DB_PATH", "jobbot.sqlite")
    dry_run = args.dry_run or env_bool("DRY_RUN", False)
    strict_posted = args.strict_posted_date if args.strict_posted_date is not None else env_bool("STRICT_POSTED_DATE", True)
    use_playwright = args.use_playwright or env_bool("USE_PLAYWRIGHT", False)
    strict_org_catalog = args.strict_org_catalog or env_bool("STRICT_ORG_CATALOG", True)
    max_sources = int(os.getenv("MAX_SOURCES_PER_RUN", "0") or "0")

    sources = load_sources(source_csv)
    if max_sources > 0:
        sources = sources[:max_sources]
    allowed_orgs = organization_aliases(sources)
    store = Store(db_path)

    candidates: list[Job] = []
    for source in sources:
        try:
            parser = build_parser(source, timezone, use_playwright)
            jobs = await parser.collect(target_date)
            # Restrict aggregator output to known non-NGO organizations.
            if strict_org_catalog and source.parser == "reliefweb_api":
                jobs = [j for j in jobs if same_org_allowed(j, allowed_orgs)]
            kept = 0
            for job in jobs:
                keep, reason = should_keep(job, target_date, strict_posted)
                if keep:
                    job.job_type = classify_job(job)
                    candidates.append(job)
                    kept += 1
            store.log(source.id, source.organization, "OK", f"Collected {len(jobs)} job(s); kept {kept}")
        except Exception as exc:
            store.log(source.id, source.organization, "ERROR", repr(exc))
            print(f"ERROR {source.organization}: {exc}")

    unique = dedupe_jobs(candidates, store)
    new_jobs: list[Job] = []
    for job in unique:
        if not store.already_seen(job):
            new_jobs.append(job)
            store.mark_seen(job)

    new_jobs.sort(key=lambda j: (j.display_org, j.title))
    await send_jobs(new_jobs, dry_run=dry_run)
    print(f"Done. Target date: {target_date}. New jobs sent: {len(new_jobs)}")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily Telegram bot for UN/IFI/development job postings.")
    p.add_argument("--sources", default=None, help="CSV source catalogue path")
    p.add_argument("--db", default=None, help="SQLite database path")
    p.add_argument("--timezone", default=None, help="IANA timezone, e.g. Africa/Kigali")
    p.add_argument("--target-date", default=None, help="Override target date YYYY-MM-DD; default is yesterday in timezone")
    p.add_argument("--env-file", default=".env", help=".env file path")
    p.add_argument("--dry-run", action="store_true", help="Print messages instead of sending Telegram")
    p.add_argument("--use-playwright", action="store_true", help="Use Playwright rendering for generic pages")
    p.add_argument("--strict-org-catalog", action="store_true", help="Aggregator jobs must match the non-NGO source catalogue")
    p.add_argument("--strict-posted-date", dest="strict_posted_date", action="store_true", default=None, help="Require posted date to equal target date")
    p.add_argument("--allow-unknown-posted-date", dest="strict_posted_date", action="store_false", help="Include jobs with no detected posted date")
    return p.parse_args()


def main():
    args = parse_args()
    if isinstance(args.target_date, str) and args.target_date:
        from datetime import date
        args.target_date = date.fromisoformat(args.target_date)
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
