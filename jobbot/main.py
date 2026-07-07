"""
Daily jobs bot — sends NEW positions from international organizations to Telegram.

It reads jobs from public, keyless job platforms (no login, no API key):
  - Workday        (e.g. the Global Fund)
  - Greenhouse
  - Lever
  - SmartRecruiters
  - RSS/Atom feeds

How "new" is decided:
  Each source returns all currently-open jobs. The bot remembers what it has
  seen before (seen_jobs.json). A job is "new" if its id was not seen in a
  previous run. The FIRST time it runs it just records everything as a baseline
  (so you don't get flooded), then from the next day on you only get new ones.

Which organizations are checked is controlled by sources.json — see that file.

Environment variables (set as GitHub Secrets):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import html
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

try:
    import pytz
    TIMEZONE = pytz.timezone("Africa/Kigali")
    TODAY = datetime.now(TIMEZONE).date()
except Exception:  # pytz optional; fall back to UTC
    TODAY = datetime.utcnow().date()

YESTERDAY = TODAY - timedelta(days=1)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SEEN_JOBS_FILE = "seen_jobs.json"
SOURCES_FILE = os.path.join(os.path.dirname(__file__), "sources.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (jobs-bot)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe(text):
    return html.escape(str(text if text is not None else ""), quote=False)


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("No Telegram credentials set. Message would have been:\n", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for start in range(0, len(message), 3800):
        chunk = message[start:start + 3800]
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        r.raise_for_status()
        time.sleep(0.5)


def load_seen():
    if not os.path.exists(SEEN_JOBS_FILE):
        return {}, True
    try:
        with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f), False
    except Exception:
        return {}, True


def save_seen(seen):
    with open(SEEN_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Collectors — one per platform. Each returns a list of job dicts:
#   {id, title, organization, location, url}
# and raises an exception if the source can't be read (so it gets reported).
# ---------------------------------------------------------------------------

def collect_workday(src):
    tenant = src["tenant"]
    dc = src.get("datacenter", "wd1")
    site = src["site"]
    base = f"https://{tenant}.{dc}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"

    jobs, offset = [], 0
    while True:
        body = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""}
        r = requests.post(api, headers=HEADERS, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for p in postings:
            path = p.get("externalPath", "")
            jobs.append({
                "id": path or p.get("bulletFields", [""])[0],
                "title": p.get("title", "Untitled"),
                "organization": src["name"],
                "location": p.get("locationsText", "Not specified"),
                "url": f"{base}/{site}{path}",
            })
        offset += len(postings)
        if offset >= data.get("total", offset):
            break
    return jobs


def collect_greenhouse(src):
    token = src["token"]
    api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    r = requests.get(api, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    r.raise_for_status()
    jobs = []
    for p in r.json().get("jobs", []):
        loc = (p.get("location") or {}).get("name", "Not specified")
        jobs.append({
            "id": str(p.get("id")),
            "title": p.get("title", "Untitled"),
            "organization": src["name"],
            "location": loc,
            "url": p.get("absolute_url", ""),
        })
    return jobs


def collect_lever(src):
    company = src["company"]
    api = f"https://api.lever.co/v0/postings/{company}?mode=json"
    r = requests.get(api, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    r.raise_for_status()
    jobs = []
    for p in r.json():
        cats = p.get("categories", {}) or {}
        jobs.append({
            "id": str(p.get("id")),
            "title": p.get("text", "Untitled"),
            "organization": src["name"],
            "location": cats.get("location", "Not specified"),
            "url": p.get("hostedUrl", ""),
        })
    return jobs


def collect_smartrecruiters(src):
    company = src["company"]
    api = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
    jobs, offset = [], 0
    while True:
        r = requests.get(
            api,
            params={"limit": 100, "offset": offset},
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        content = data.get("content", [])
        if not content:
            break
        for p in content:
            loc = p.get("location", {}) or {}
            city = loc.get("city", "")
            country = loc.get("country", "")
            location = ", ".join(x for x in (city, country) if x) or "Not specified"
            pid = p.get("id")
            jobs.append({
                "id": str(pid),
                "title": p.get("name", "Untitled"),
                "organization": src["name"],
                "location": location,
                "url": f"https://jobs.smartrecruiters.com/{company}/{pid}",
            })
        offset += len(content)
        if offset >= data.get("totalFound", offset):
            break
    return jobs


def collect_rss(src):
    r = requests.get(src["url"], headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    jobs = []
    # RSS 2.0 <item> ...
    for item in root.iter("item"):
        title = item.findtext("title", "Untitled")
        link = item.findtext("link", "")
        guid = item.findtext("guid") or link
        jobs.append({
            "id": guid,
            "title": title,
            "organization": src["name"],
            "location": "See announcement",
            "url": link,
        })
    # Atom <entry> ...
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{ns}entry"):
        title = entry.findtext(f"{ns}title", "Untitled")
        link_el = entry.find(f"{ns}link")
        link = link_el.get("href") if link_el is not None else ""
        guid = entry.findtext(f"{ns}id") or link
        jobs.append({
            "id": guid,
            "title": title,
            "organization": src["name"],
            "location": "See announcement",
            "url": link,
        })
    return jobs


COLLECTORS = {
    "workday": collect_workday,
    "greenhouse": collect_greenhouse,
    "lever": collect_lever,
    "smartrecruiters": collect_smartrecruiters,
    "rss": collect_rss,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def format_job(index, job):
    return (
        f"<b>{index}. {safe(job['title'])}</b>\n"
        f"Organization: {safe(job['organization'])}\n"
        f"Location: {safe(job['location'])}\n"
        f"Link: {safe(job['url'])}"
    )


def main():
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        sources = [s for s in json.load(f).get("sources", []) if s.get("enabled", True)]

    seen, is_first_run = load_seen()

    new_jobs = []
    ok_sources, failed_sources = [], []
    total_found = 0

    for src in sources:
        collector = COLLECTORS.get(src.get("type"))
        if not collector:
            failed_sources.append((src.get("name", "?"), f"unknown type '{src.get('type')}'"))
            continue
        try:
            jobs = collector(src)
            ok_sources.append((src["name"], len(jobs)))
            total_found += len(jobs)
            for job in jobs:
                key = f"{src['name']}:{job['id']}"
                if key not in seen:
                    if not is_first_run:
                        new_jobs.append(job)
                    seen[key] = {"title": job["title"], "first_seen": str(TODAY)}
                else:
                    seen[key]["last_seen"] = str(TODAY)
        except Exception as e:
            msg = str(e)
            failed_sources.append((src["name"], msg[:100]))
            print(f"FAILED {src['name']}: {e}")

    save_seen(seen)

    # Build the morning summary.
    lines = [f"<b>Daily Jobs — {TODAY}</b>"]
    if is_first_run:
        lines.append("First run: recorded a baseline of currently-open jobs. "
                     "From tomorrow you'll only get NEW ones.")
    lines.append(f"Sources working: {len(ok_sources)} | failed: {len(failed_sources)}")
    lines.append(f"Total open positions seen: {total_found}")
    lines.append(f"New to report: {0 if is_first_run else len(new_jobs)}")
    if ok_sources:
        lines.append("\n<b>Working sources:</b>")
        lines += [f"• {safe(n)}: {c} open" for n, c in ok_sources]
    if failed_sources:
        lines.append("\n<b>Sources that failed (need fixing):</b>")
        lines += [f"• {safe(n)}: {safe(err)}" for n, err in failed_sources]
    send_telegram("\n".join(lines))

    if is_first_run or not new_jobs:
        if not is_first_run:
            send_telegram("No new positions today.")
        return

    buffer = ""
    for index, job in enumerate(new_jobs, start=1):
        block = format_job(index, job) + "\n\n"
        if len(buffer) + len(block) > 3500:
            send_telegram(buffer.strip())
            buffer = ""
        buffer += block
    if buffer.strip():
        send_telegram(buffer.strip())


if __name__ == "__main__":
    main()
