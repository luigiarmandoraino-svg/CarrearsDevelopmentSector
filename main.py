from __future__ import annotations

import os
from typing import Iterable

import httpx

from .models import Job
from .utils import html_escape


def format_job_message(job: Job, index: int | None = None) -> str:
    prefix = f"{index}. " if index else ""
    posted = job.posted_date.isoformat() if job.posted_date else "Not clearly stated"
    deadline = job.deadline.isoformat() if job.deadline else "Not clearly stated"
    grade = job.grade or "Not clearly stated"
    location = job.location or job.country or "Not clearly stated"

    return f"""<b>{html_escape(prefix + job.title)} – {html_escape(job.display_org)}</b>

<b>Location:</b> {html_escape(location)}
<b>Type:</b> {html_escape(job.job_type)}
<b>Grade:</b> {html_escape(grade)}
<b>Posted:</b> {html_escape(posted)}
<b>Deadline:</b> {html_escape(deadline)}
<b>Link:</b> {html_escape(job.link)}

<b>Requirements summary:</b>
• <b>Years of experience:</b> {html_escape(job.years_experience)}
• <b>Languages:</b> {html_escape(job.languages)}
• <b>Education:</b> {html_escape(job.education)}

<b>Requirement source:</b> {html_escape(job.requirement_sources)}"""


async def send_telegram_message(text: str, token: str, chat_id: str, parse_mode: str = "HTML") -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json={
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        })
        r.raise_for_status()


async def send_jobs(jobs: list[Job], dry_run: bool = False) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not dry_run and (not token or not chat_id):
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set unless DRY_RUN=true")

    if not jobs:
        message = "No new international positions or Europe-based national/local positions were found for yesterday."
        if dry_run:
            print(message)
        else:
            await send_telegram_message(message, token, chat_id)
        return

    header = f"Daily job alert: {len(jobs)} new position(s) posted yesterday."
    if dry_run:
        print(header)
    else:
        await send_telegram_message(header, token, chat_id)

    for i, job in enumerate(jobs, 1):
        msg = format_job_message(job, i)
        if dry_run:
            print("\n" + "=" * 80 + "\n" + msg)
        else:
            await send_telegram_message(msg, token, chat_id)
