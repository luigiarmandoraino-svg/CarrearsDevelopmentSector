import csv
import hashlib
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
YESTERDAY = datetime.now(TIMEZONE).date() - timedelta(days=1)

EUROPE_KEYWORDS = [
    "albania", "andorra", "austria", "belgium", "bulgaria", "croatia",
    "cyprus", "czech", "denmark", "estonia", "finland", "france",
    "germany", "greece", "hungary", "iceland", "ireland", "italy",
    "latvia", "lithuania", "luxembourg", "malta", "netherlands",
    "norway", "poland", "portugal", "romania", "slovakia", "slovenia",
    "spain", "sweden", "switzerland", "ukraine", "united kingdom",
    "uk", "rome", "geneva", "vienna", "brussels", "paris", "madrid",
    "berlin", "london", "copenhagen", "helsinki", "stockholm", "oslo"
]


def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Missing Telegram secrets.")
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
        r"\bInternship\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)

    return "Not specified"


def extract_deadline(text):
    patterns = [
        r"(deadline|closing date|application deadline|closing):?\s*([A-Za-z0-9, /\.-]{6,40})",
        r"(apply by):?\s*([A-Za-z0-9, /\.-]{6,40})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean(match.group(2))

    return "Not specified"


def extract_years(text):
    match = re.search(
        r"(\d+)\+?\s+years?.{0,80}(experience|professional experience|work experience)",
        text,
        re.IGNORECASE,
    )

    if match:
        return clean(match.group(0))

    match = re.search(
        r"(minimum|at least).{0,40}(\d+).{0,30}years?",
        text,
        re.IGNORECASE,
    )

    if match:
        return clean(match.group(0))

    return "Not clearly specified"


def extract_languages(text):
    found = []

    for language in [
        "English", "French", "Spanish", "Arabic", "Russian",
        "Chinese", "Portuguese", "Italian"
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
        "p-1", "p-2", "p-3", "p-4", "p-5",
        "d-1", "d-2"
    ]):
        return "International"

    if any(x in combined for x in [
        "national consultant",
        "national officer",
        "locally recruited",
        "local position",
        "no-a", "no-b", "no-c", "no-d",
        "noa", "nob", "noc", "nod"
    ]):
        return "National"

    if any(x in combined for x in ["consultant", "consultancy"]):
        return "Consultancy"

    return "Unknown"


def is_in_europe(location):
    location = location.lower()
    return any(keyword in location for keyword in EUROPE_KEYWORDS)


def should_include(job_type, location):
    if job_type in ["International", "Consultancy", "Unknown"]:
        return True

    if job_type == "National" and is_in_europe(location):
        return True

    return False


def normalize_id(title, organization, location):
    raw = f"{title}|{organization}|{location}".lower()
    raw = re.sub(r"[^a-z0-9]+", "", raw)
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_possible_date(value):
    try:
        return dateparser.parse(value, fuzzy=True).date()
    except Exception:
        return None


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

        location = country or "Not specified"
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
            "officer", "specialist", "manager", "consultant", "intern"
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
            detail_text = clean(
                BeautifulSoup(detail.text, "html.parser").get_text(" ")
            )
        except Exception:
            detail_text = page_text

        posted_date = None
        posted_match = re.search(
            r"(posted|publication date|date posted):?\s*([A-Za-z0-9, /\.-]{6,40})",
            detail_text,
            re.IGNORECASE,
        )

        if posted_match:
            posted_date = parse_possible_date(posted_match.group(2))

        if posted_date != YESTERDAY:
            continue

        location = "Not specified"

        location_match = re.search(
            r"(location|duty station):?\s*([A-Za-z, /\.-]{3,80})",
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
            "posted": str(YESTERDAY),
            "deadline": extract_deadline(detail_text),
            "years": extract_years(detail_text),
            "languages": extract_languages(detail_text),
            "url": url,
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


def main():
    all_jobs = []
    unique = set()

    with open("sources.csv", newline="", encoding="utf-8") as file:
        sources = list(csv.DictReader(file))
    max_sources = int(os.environ.get("MAX_SOURCES", "0") or "0")

    if max_sources > 0:
        sources = sources[:max_sources]
        print(f"Development mode: checking only the first {max_sources} sources.")
    for source in sources:
        print(f"Checking {source['organization']}")

        try:
            if source["method"] == "reliefweb":
                jobs = collect_reliefweb(source)
            else:
                jobs = collect_html(source)

            for job in jobs:
                key = normalize_id(
                    job["title"],
                    job["organization"],
                    job["location"],
                )

                if key not in unique:
                    unique.add(key)
                    all_jobs.append(job)

        except Exception as error:
            print(f"Error in {source['organization']}: {error}")

    if not all_jobs:
        send_telegram(
            f"Daily Development Jobs – {YESTERDAY}\n\n"
            "No new eligible positions found, or the sources checked did not expose posted dates."
        )
        return

    send_telegram(
        f"Daily Development Jobs – {YESTERDAY}\n\n"
        f"Found {len(all_jobs)} new eligible position(s)."
    )

    for index, job in enumerate(all_jobs, start=1):
        send_telegram(format_job(index, job))


if __name__ == "__main__":
    main()
