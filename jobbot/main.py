import csv
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import pytz
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TIMEZONE = pytz.timezone("Africa/Kigali")
TODAY = datetime.now(TIMEZONE).date()
YESTERDAY = TODAY - timedelta(days=1)

SEEN_JOBS_FILE = "seen_jobs.json"

EUROPE_KEYWORDS = [
    "albania", "andorra", "armenia", "austria", "belarus", "belgium",
    "bosnia", "bulgaria", "croatia", "cyprus", "czech", "denmark",
    "estonia", "finland", "france", "georgia", "germany", "greece",
    "hungary", "iceland", "ireland", "italy", "kosovo", "latvia",
    "liechtenstein", "lithuania", "luxembourg", "malta", "moldova",
    "monaco", "montenegro", "netherlands", "norway", "poland",
    "portugal", "romania", "san marino", "serbia", "slovakia",
    "slovenia", "spain", "sweden", "switzerland", "ukraine",
    "united kingdom", "uk", "rome", "geneva", "vienna", "brussels",
    "paris", "madrid", "berlin", "london", "copenhagen", "helsinki",
    "stockholm", "oslo", "luxembourg", "the hague", "amsterdam",
    "lisbon", "dublin", "prague", "warsaw", "budapest"
]


def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    response.raise_for_status()


def extract_grade(text):
    patterns = [
        r"\bP-[1-7]\b",
        r"\bD-[1-2]\b",
        r"\bNO-[A-D]\b",
        r"\bNOA\b|\bNOB\b|\bNOC\b|\bNOD\b",
        r"\bG-[1-7]\b",
        r"\bGS-[1-7]\b",
        r"\bIPSA-[0-9]+\b",
        r"\bICS-[0-9]+\b",
        r"\bConsultant\b",
        r"\bConsultancy\b",
        r"\bInternship\b",
        r"\bIntern\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return "Not specified"


def extract_deadline(text):
    patterns = [
        r"(deadline|closing date|application deadline|closing):?\s*([A-Za-z0-9, /\.-]{6,50})",
        r"(apply by):?\s*([A-Za-z0-9, /\.-]{6,50})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean(match.group(2))

    return "Not specified"


def extract_years(text):
    patterns = [
        r"(\d+)\+?\s+years?.{0,100}(experience|professional experience|work experience)",
        r"(minimum|at least).{0,50}(\d+).{0,40}years?",
        r"(\d+)\s+years?.{0,80}relevant experience",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean(match.group(0))

    return "Not clearly specified"


def extract_languages(text):
    found = []

    for language in [
        "English", "French", "Spanish", "Arabic", "Russian",
        "Chinese", "Portuguese", "Italian", "German"
    ]:
        if re.search(language, text, re.IGNORECASE):
            found.append(language)

    if found:
        return ", ".join(sorted(set(found)))

    return "Not clearly specified"


def classify_type(title, location, text):
    combined = f"{title} {location} {text}".lower()

    if any(x in combined for x in [
        "international professional",
        "international consultant",
        "internationally recruited",
        "international staff",
        "p-1", "p-2", "p-3", "p-4", "p-5", "p-6", "p-7",
        "d-1", "d-2"
    ]):
        return "International"

    if any(x in combined for x in [
        "national consultant",
        "national officer",
        "locally recruited",
        "local position",
        "local recruitment",
        "no-a", "no-b", "no-c", "no-d",
        "noa", "nob", "noc", "nod"
    ]):
        return "National"

    if any(x in combined for x in ["consultant", "consultancy"]):
        return "Consultancy"

    return "Unknown"


def is_in_europe(location):
    location = (location or "").lower()
    return any(keyword in location for keyword in EUROPE_KEYWORDS)


def should_include(job_type, location):
    # Main rule requested:
    # - keep international jobs globally
    # - keep national/local jobs only if located in Europe
    # - keep consultancies globally for now, because many sources do not label national/international clearly
    # - keep unknown jobs for now, but deduplication and date tracking will control repetition
    if job_type in ["International", "Consultancy", "Unknown"]:
        return True

    if job_type == "National" and is_in_europe(location):
        return True

    return False


def normalize_id(title, organization, location, url=None):
    # Use URL if available, because the same job title may appear in different countries/offices.
    # Still include title/org/location to deduplicate across pages that use slightly different URLs.
    raw = f"{title}|{organization}|{location}|{url or ''}".lower()
    raw = re.sub(r"[^a-z0-9]+", "", raw)
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_possible_date(value):
    if not value:
        return None

    try:
        return dateparser.parse(value, fuzzy=True).date()
    except Exception:
        return None


def load_seen_jobs():
    if not os.path.exists(SEEN_JOBS_FILE):
        return {}, True

    try:
        with open(SEEN_JOBS_FILE, "r", encoding="utf-8") as file:
            return json.load(file), False
    except Exception:
        return {}, True


def save_seen_jobs(seen_jobs):
    with open(SEEN_JOBS_FILE, "w", encoding="utf-8") as file:
        json.dump(seen_jobs, file, indent=2, ensure_ascii=False)


def remember_job(seen_jobs, key, job):
    if key not in seen_jobs:
        seen_jobs[key] = {
            "first_seen": str(TODAY),
            "last_seen": str(TODAY),
            "title": job.get("title"),
            "organization": job.get("organization"),
            "location": job.get("location"),
            "url": job.get("url"),
        }
    else:
        seen_jobs[key]["last_seen"] = str(TODAY)

    return seen_jobs


def collect_reliefweb(source):
    jobs = []

    params = {
        "appname": "telegram-job-bot",
        "profile": "list",
        "limit": 100,
        "sort[]": "date:desc",
        "filter[field]": "date.created",
        "filter[value][from]": f"{YESTERDAY}T00:00:00+00:00",
        "filter[value][to]": f"{YESTERDAY}T23:59:59+00:00",
    }

    response = requests.get(source["url"], params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    for item in data.get("data", []):
        fields = item.get("fields", {})

        title = fields.get("title", "Untitled")
        url = fields.get("url", "")
        organization = ", ".join(
            [x.get("name", "") for x in fields.get("source", [])]
        ) or "ReliefWeb"

        country = ", ".join(
            [x.get("name", "") for x in fields.get("country", [])]
        )

        city = fields.get("city", "")
        location = clean(f"{city}, {country}".strip(", ")) or "Not specified"
        text = clean(str(fields))

        job_type = classify_type(title, location, text)

        if not should_include(job_type, location):
            continue

        jobs.append({
            "title": title,
            "organization": organization,
            "location": location,
            "type": job_type,
            "grade": extract_grade(text),
            "posted": str(YESTERDAY),
            "deadline": extract_deadline(text),
            "years": extract_years(text),
            "languages": extract_languages(text),
            "url": url,
            "date_status": "posted_date",
        })

    return jobs


def collect_html(source):
    jobs = []

    try:
        response = requests.get(
            source["url"],
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
    except Exception as error:
        print(f"Could not access {source['organization']}: {error}")
        return jobs

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = clean(soup.get_text(" "))

    links = []

    for a in soup.find_all("a", href=True):
        title = clean(a.get_text(" ", strip=True))
        href = a.get("href")

        if not title or len(title) < 5:
            continue

        combined = f"{title} {href}".lower()

        if any(word in combined for word in [
            "vacancy", "career", "job", "position", "requisition",
            "officer", "specialist", "manager", "consultant", "intern",
            "expert", "advisor", "programme", "program", "project"
        ]):
            links.append((title, urljoin(source["url"], href)))

    seen = set()

    for title, url in links[:30]:
        if url in seen:
            continue

        seen.add(url)

        try:
            detail = requests.get(
                url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            detail.raise_for_status()
            detail_text = clean(
                BeautifulSoup(detail.text, "html.parser").get_text(" ")
            )
        except Exception:
            detail_text = page_text

        posted_date = None
        posted_match = re.search(
            r"(posted|publication date|date posted|posting date|published|published on):?\s*([A-Za-z0-9, /\.-]{6,50})",
            detail_text,
            re.IGNORECASE,
        )

        if posted_match:
            posted_date = parse_possible_date(posted_match.group(2))

        # New rule:
        # If a posted date exists, keep only jobs posted yesterday.
        # If no posted date exists, keep it for seen_jobs tracking.
        if posted_date and posted_date != YESTERDAY:
            continue

        location = "Not specified"

        location_match = re.search(
            r"(location|duty station|duty stations|job location):?\s*([A-Za-z, /\.-]{3,100})",
            detail_text,
            re.IGNORECASE,
        )

        if location_match:
            location = clean(location_match.group(2))

        job_type = classify_type(title, location, detail_text)

        if not should_include(job_type, location):
            continue

        jobs.append({
            "title": title,
            "organization": source["organization"],
            "location": location,
            "type": job_type,
            "grade": extract_grade(detail_text),
            "posted": str(posted_date) if posted_date else "Not exposed by source",
            "deadline": extract_deadline(detail_text),
            "years": extract_years(detail_text),
            "languages": extract_languages(detail_text),
            "url": url,
            "date_status": "posted_date" if posted_date else "first_seen_tracking",
        })

    return jobs


def format_job(index, job):
    return f"""<b>{index}. {job['title']} – {job['organization']}</b>

Location: {job['location']}
Type: {job['type']}
Grade: {job['grade']}
Posted: {job['posted']}
Deadline: {job['deadline']}
Link: {job['url']}

<b>Requirements summary:</b>
• Years of experience: {job['years']}
• Languages: {job['languages']}

<b>Requirement source:</b>
Extracted from the job announcement text where available.
"""


def format_summary(
    sources_checked,
    sources_successful,
    sources_failed,
    failed_sources,
    jobs_collected,
    duplicates_removed,
    already_seen_skipped,
    baseline_without_dates,
    jobs_sent,
):
    failed_text = "None"

    if failed_sources:
        failed_text = "\n".join([f"• {name}: {error}" for name, error in failed_sources[:10]])

        if len(failed_sources) > 10:
            failed_text += f"\n• Plus {len(failed_sources) - 10} more failed source(s)."

    return f"""<b>Daily Development Jobs – {YESTERDAY}</b>

<b>Summary:</b>
Sources checked: {sources_checked}
Sources successful: {sources_successful}
Sources failed: {sources_failed}
Jobs collected before deduplication: {jobs_collected}
Duplicates removed: {duplicates_removed}
Already-seen jobs skipped: {already_seen_skipped}
Baseline jobs saved without posting date: {baseline_without_dates}
Jobs sent: {jobs_sent}

<b>How new jobs are detected:</b>
• If the source shows a posted date: only jobs posted yesterday are sent.
• If the source does not show a posted date: only jobs not seen in previous bot runs are sent.

<b>Failed sources:</b>
{failed_text}
"""


def main():
    all_jobs = []
    unique = set()

    seen_jobs, is_first_seen_run = load_seen_jobs()

    sources_checked = 0
    sources_successful = 0
    sources_failed = 0
    failed_sources = []
    jobs_collected = 0
    duplicates_removed = 0
    already_seen_skipped = 0
    baseline_without_dates = 0

    with open("sources.csv", newline="", encoding="utf-8") as file:
        sources = list(csv.DictReader(file))

    max_sources = int(os.environ.get("MAX_SOURCES", "0") or "0")

    if max_sources > 0:
        sources = sources[:max_sources]
        print(f"Development mode: checking only the first {max_sources} sources.")

    for source in sources:
        source_name = source.get("organization", "Unknown source")
        sources_checked += 1

        print(f"Checking {source_name}")

        try:
            if source.get("method") == "reliefweb":
                jobs = collect_reliefweb(source)
            else:
                jobs = collect_html(source)

            sources_successful += 1
            jobs_collected += len(jobs)

            for job in jobs:
                key = normalize_id(
                    job["title"],
                    job["organization"],
                    job["location"],
                    job.get("url"),
                )

                job_has_no_posted_date = job.get("date_status") == "first_seen_tracking"
                already_seen = key in seen_jobs

                remember_job(seen_jobs, key, job)

                if key in unique:
                    duplicates_removed += 1
                    continue

                # First run after adding seen_jobs.json:
                # Do not send all old vacancies from sources without posted dates.
                # Save them as baseline instead.
                if job_has_no_posted_date and is_first_seen_run:
                    baseline_without_dates += 1
                    continue

                if already_seen:
                    already_seen_skipped += 1
                    continue

                unique.add(key)
                all_jobs.append(job)

        except Exception as error:
            sources_failed += 1
            error_text = str(error)

            if len(error_text) > 120:
                error_text = error_text[:120] + "..."

            failed_sources.append((source_name, error_text))
            print(f"Error in {source_name}: {error}")

    save_seen_jobs(seen_jobs)

    jobs_sent = len(all_jobs)

    summary_message = format_summary(
        sources_checked=sources_checked,
        sources_successful=sources_successful,
        sources_failed=sources_failed,
        failed_sources=failed_sources,
        jobs_collected=jobs_collected,
        duplicates_removed=duplicates_removed,
        already_seen_skipped=already_seen_skipped,
        baseline_without_dates=baseline_without_dates,
        jobs_sent=jobs_sent,
    )

    send_telegram(summary_message)

    if not all_jobs:
        send_telegram("No new eligible positions found today.")
        return

    for index, job in enumerate(all_jobs, start=1):
        send_telegram(format_job(index, job))


if __name__ == "__main__":
    main()

