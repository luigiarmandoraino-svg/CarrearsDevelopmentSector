import csv
import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

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

SEND_ALL_AVAILABLE = os.environ.get("SEND_ALL_AVAILABLE", "false").lower() == "true"

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
    "stockholm", "oslo", "the hague", "amsterdam", "lisbon", "dublin",
    "prague", "warsaw", "budapest", "turin", "brindisi", "florence",
    "milan", "trieste"
]

ITALY_KEYWORDS = [
    "italy", "rome", "roma", "turin", "torino", "brindisi", "florence",
    "firenze", "milan", "milano", "trieste", "bologna", "venice", "venezia"
]

UN_ORGANIZATIONS = {
    "un careers", "un secretariat", "undp", "unicef", "unhcr", "wfp",
    "unfpa", "un women", "unops", "unv", "fao", "ifad", "ilo", "who",
    "unesco", "unido", "icao", "imo", "itu", "upu", "wipo", "wmo",
    "iaea", "iom", "ctbto", "opcw", "unaids", "unep", "un-habitat",
    "ohchr", "ocha", "unodc", "unctad", "itc", "undrr", "unrwa",
    "unssc", "unu", "unitar", "unicc", "unidir", "unrisd", "un tourism",
    "uncdf"
}

JOB_TITLE_KEYWORDS = [
    "officer", "specialist", "manager", "analyst", "assistant",
    "associate", "advisor", "adviser", "expert", "consultant",
    "coordinator", "director", "intern", "internship", "engineer",
    "economist", "programme", "program", "project", "portfolio",
    "investment", "operations", "procurement", "finance", "financial",
    "monitoring", "evaluation", "partnership", "grant", "risk",
    "climate", "agriculture", "agricultural", "rural", "development",
    "policy", "technical", "head", "lead", "chief", "representative",
    "administrator", "administrative", "legal", "hr", "human resources",
    "communication", "data", "digital", "it ", "information technology"
]

REJECT_TITLE_KEYWORDS = [
    "program expenses", "programme expenses", "expenses", "expense",
    "annual report", "financial report", "publication", "publications",
    "press release", "news", "story", "stories", "event", "events",
    "donate", "donation", "procurement notice", "tender", "bid",
    "request for proposal", "rfp", "request for quotation", "rfq",
    "vendor", "supplier", "login", "register", "registration",
    "candidate profile", "create profile", "talent community",
    "job alert", "job alerts", "search jobs", "job search",
    "all jobs", "open vacancies", "vacancies", "careers",
    "career opportunities", "current opportunities", "current vacancies",
    "work with us", "employment", "about us", "contact", "privacy",
    "terms", "sitemap", "subscribe", "newsletter", "linkedin",
    "facebook", "twitter", "instagram", "youtube", "home", "back to",
    "learn more", "read more", "view all", "more information",
    "salary scales", "benefits", "staff categories", "recruitment process"
]

GENERIC_URL_ENDINGS = [
    "/careers", "/careers/", "/career", "/career/", "/jobs", "/jobs/",
    "/vacancies", "/vacancies/", "/employment", "/employment/",
    "/job-openings", "/job-openings/", "/listing", "/listing/",
    "/current-vacancies", "/current-vacancies/", "/current-opportunities",
    "/current-opportunities/", "/work-with-us", "/work-with-us/"
]


def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def safe(text):
    """Escape text for Telegram HTML mode."""
    return html.escape(str(text or ""), quote=False)


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


def is_un_source(source):
    org = clean(source.get("organization", "")).lower()
    category = clean(source.get("category", "")).lower()
    return org in UN_ORGANIZATIONS or category.startswith("un") or "un " in category or "un/" in category


def is_in_europe(location):
    location = (location or "").lower()
    return any(keyword in location for keyword in EUROPE_KEYWORDS)


def is_in_italy(location):
    location = (location or "").lower()
    return any(keyword in location for keyword in ITALY_KEYWORDS)


def looks_like_generic_url(url, source_url=None):
    if not url:
        return True

    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    full = url.rstrip("/").lower()

    if source_url and full == source_url.rstrip("/").lower():
        return True

    for ending in GENERIC_URL_ENDINGS:
        if path == ending.rstrip("/"):
            return True

    return False


def is_rejected_title(title):
    title_l = clean(title).lower()

    if not title_l:
        return True

    if len(title_l) < 5:
        return True

    if any(word in title_l for word in REJECT_TITLE_KEYWORDS):
        return True

    # Reject very long navigation/menu items.
    if len(title_l) > 180:
        return True

    return False


def title_has_job_signal(title):
    title_l = f" {clean(title).lower()} "

    if re.search(r"\b(P-[1-7]|D-[1-2]|NO-[A-D]|NOA|NOB|NOC|NOD|G-[1-7]|GS-[1-7]|IPSA-[0-9]+|ICS-[0-9]+)\b", title, re.IGNORECASE):
        return True

    return any(keyword in title_l for keyword in JOB_TITLE_KEYWORDS)


def link_candidate_is_valid(title, href, source_url):
    if is_rejected_title(title):
        return False

    absolute = urljoin(source_url, href or "")
    if looks_like_generic_url(absolute, source_url):
        return False

    title_l = clean(title).lower()
    href_l = (href or "").lower()

    if title_has_job_signal(title):
        return True

    # URL-specific signals are allowed only when title is not generic.
    if any(x in href_l for x in ["job", "careersection", "requisition", "vacancy", "position", "opening", "jobs/"]):
        return True

    return False


def page_is_probably_job_detail(title, detail_text, url):
    """
    Stronger validation to avoid sending pages such as UNICEF/UNFPA programme
    expense pages, generic career pages, reports, or navigation links.
    """
    title = clean(title)
    detail_text = clean(detail_text)
    combined = f"{title} {detail_text}".lower()

    if is_rejected_title(title):
        return False

    if "program expenses" in combined or "programme expenses" in combined:
        return False

    if looks_like_generic_url(url):
        return False

    if not title_has_job_signal(title):
        return False

    # A real vacancy page should normally contain at least two of these signals.
    signals = 0

    if re.search(r"\b(deadline|closing date|application deadline|apply by|closing)\b", combined, re.IGNORECASE):
        signals += 1

    if re.search(r"\b(location|duty station|job location)\b", combined, re.IGNORECASE):
        signals += 1

    if re.search(r"\b(grade|level|contract type|appointment type|position type|post level|job level|contract level)\b", combined, re.IGNORECASE):
        signals += 1

    if re.search(r"\b(experience|professional experience|work experience|education|degree|languages|required qualifications|minimum requirements)\b", combined, re.IGNORECASE):
        signals += 1

    if re.search(r"\b(apply|application|candidate|requisition|vacancy)\b", combined, re.IGNORECASE):
        signals += 1

    return signals >= 2


def extract_grade(title, text):
    """
    Conservative grade extraction.

    First check the job title because it is specific to the vacancy.
    Then check labelled grade/level fields in the vacancy text.
    Do not guess from random grade mentions in a long career page.
    """
    title = clean(title)
    text = clean(text)

    grade_pattern = r"\b(P-[1-7]|D-[1-2]|NO-[A-D]|NOA|NOB|NOC|NOD|G-[1-7]|GS-[1-7]|IPSA-[0-9]+|ICS-[0-9]+)\b"

    title_match = re.search(grade_pattern, title, re.IGNORECASE)
    if title_match:
        return title_match.group(1).upper()

    labelled_patterns = [
        r"(?:grade|level|post level|job level|position level|contract level)\s*:?\s*(P-[1-7]|D-[1-2]|NO-[A-D]|NOA|NOB|NOC|NOD|G-[1-7]|GS-[1-7]|IPSA-[0-9]+|ICS-[0-9]+)",
        r"(?:grade|level|post level|job level|position level|contract level)\s*:?\s*([A-Z]{1,4}-?[0-9]{1,2})",
    ]

    for pattern in labelled_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    contract = extract_contract_type(title, text)
    if contract == "Internship":
        return "Internship"
    if contract == "Consultancy":
        return "Consultancy"

    return "Not clearly specified"


def extract_contract_type(title, text):
    """
    Contract/type extraction must be conservative.

    Priority:
    1. Job title signals.
    2. Labelled fields such as Contract type / Appointment type.
    3. Clear UN grade family.
    """
    title_l = clean(title).lower()
    text_l = clean(text).lower()

    if re.search(r"\b(internship|intern)\b", title_l):
        return "Internship"

    if re.search(r"\b(consultancy|consultant)\b", title_l):
        return "Consultancy"

    labelled_patterns = [
        r"(?:contract type|appointment type|position type|job type|category)\s*:?\s*([A-Za-z \-/]{3,60})",
        r"(?:staff category)\s*:?\s*([A-Za-z \-/]{3,60})",
    ]

    for pattern in labelled_patterns:
        match = re.search(pattern, text_l, re.IGNORECASE)
        if not match:
            continue

        value = clean(match.group(1)).lower()

        if "consult" in value:
            return "Consultancy"

        if "intern" in value:
            return "Internship"

        if "national" in value:
            return "National"

        if "international" in value or "professional" in value:
            return "International"

        if "general service" in value or value.startswith("g-") or value.startswith("gs-"):
            return "General Service"

    combined_specific = f"{title_l} {text_l[:3000]}"

    if re.search(r"\b(P-[1-7]|D-[1-2])\b", title, re.IGNORECASE):
        return "International"

    if re.search(r"\b(NO-[A-D]|NOA|NOB|NOC|NOD)\b", title, re.IGNORECASE):
        return "National"

    if re.search(r"\b(G-[1-7]|GS-[1-7])\b", title, re.IGNORECASE):
        return "General Service"

    if "internationally recruited" in combined_specific:
        return "International"

    if "locally recruited" in combined_specific or "local recruitment" in combined_specific:
        return "National"

    return "Unknown"


def extract_deadline(text):
    text = clean(text)

    patterns = [
        r"(?:deadline|closing date|application deadline|closing)\s*:?\s*([A-Za-z0-9, /\.-]{6,50})",
        r"(?:apply by)\s*:?\s*([A-Za-z0-9, /\.-]{6,50})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean(match.group(1))

    return "Not specified"


def extract_years(text):
    """
    Conservative experience extraction.

    It only searches sentences that explicitly mention experience and returns a
    short requirement-like phrase. If unclear, it returns 'Not clearly specified'
    rather than guessing.
    """
    text = clean(text)

    sentences = re.split(r"(?<=[.!?])\s+", text)
    experience_sentences = [
        sentence for sentence in sentences
        if re.search(
            r"\b(experience|professional experience|work experience|relevant experience)\b",
            sentence,
            re.IGNORECASE,
        )
    ]

    candidates = []

    for sentence in experience_sentences:
        patterns = [
            r"(?:minimum|at least|required).{0,60}?(\d+)\+?\s+years?.{0,120}",
            r"(\d+)\+?\s+years?.{0,120}?(?:experience|professional experience|work experience|relevant experience)",
        ]

        for pattern in patterns:
            match = re.search(pattern, sentence, re.IGNORECASE)
            if match:
                candidate = clean(match.group(0))
                if len(candidate) <= 220:
                    candidates.append(candidate)

    if candidates:
        candidates = sorted(set(candidates), key=len)
        return candidates[0]

    return "Not clearly specified"


def extract_languages(text):
    text = clean(text)
    found = []

    for language in [
        "English", "French", "Spanish", "Arabic", "Russian",
        "Chinese", "Portuguese", "Italian", "German"
    ]:
        if re.search(rf"\b{language}\b", text, re.IGNORECASE):
            found.append(language)

    if found:
        return ", ".join(sorted(set(found)))

    return "Not clearly specified"


def should_include(job_type, location, grade, source):
    """
    Filtering requested by user:
    - Post international positions globally.
    - Post national/local positions only in Europe.
    - Remove UN G/GS positions except if the duty station is in Italy.
    - Keep consultancies globally.
    - Keep unknown only if not clearly excluded, because many pages do not expose type.
    """
    grade_l = clean(grade).lower()

    if is_un_source(source) and re.search(r"\b(g-[1-7]|gs-[1-7])\b", grade_l, re.IGNORECASE):
        return is_in_italy(location)

    if job_type == "General Service":
        if is_un_source(source):
            return is_in_italy(location)
        return is_in_europe(location)

    if job_type in ["International", "Consultancy", "Internship", "Unknown"]:
        return True

    if job_type == "National" and is_in_europe(location):
        return True

    return False


def normalize_id(title, organization, location, url=None):
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
        "limit": 1000 if SEND_ALL_AVAILABLE else 100,
        "sort[]": "date:desc",
    }

    if not SEND_ALL_AVAILABLE:
        params.update({
            "filter[field]": "date.created",
            "filter[value][from]": f"{YESTERDAY}T00:00:00+00:00",
            "filter[value][to]": f"{YESTERDAY}T23:59:59+00:00",
        })

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

        if is_rejected_title(title) or not title_has_job_signal(title):
            continue

        job_type = extract_contract_type(title, text)
        grade = extract_grade(title, text)

        if not should_include(job_type, location, grade, source):
            continue

        jobs.append({
            "title": title,
            "organization": organization,
            "location": location,
            "type": job_type,
            "grade": grade,
            "posted": "Available now" if SEND_ALL_AVAILABLE else str(YESTERDAY),
            "deadline": extract_deadline(text),
            "years": extract_years(text),
            "languages": extract_languages(text),
            "url": url,
            "date_status": "day_zero" if SEND_ALL_AVAILABLE else "posted_date",
            "newness_method": "Day-zero full list" if SEND_ALL_AVAILABLE else "Posted yesterday",
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

        if not link_candidate_is_valid(title, href, source["url"]):
            continue

        links.append((title, urljoin(source["url"], href)))

    seen = set()

    for title, url in links[:40]:
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

        if not page_is_probably_job_detail(title, detail_text, url):
            continue

        posted_date = None
        posted_match = re.search(
            r"(?:posted|publication date|date posted|posting date|published|published on)\s*:?\s*([A-Za-z0-9, /\.-]{6,50})",
            detail_text,
            re.IGNORECASE,
        )

        if posted_match:
            posted_date = parse_possible_date(posted_match.group(1))

        # If a posted date exists, keep only jobs posted yesterday unless Day Zero is enabled.
        # If no posted date exists, keep it for seen_jobs tracking.
        if posted_date and posted_date != YESTERDAY and not SEND_ALL_AVAILABLE:
            continue

        location = "Not specified"

        location_match = re.search(
            r"(?:location|duty station|duty stations|job location)\s*:?\s*([A-Za-z, /\.-]{3,100})",
            detail_text,
            re.IGNORECASE,
        )

        if location_match:
            location = clean(location_match.group(1))

        job_type = extract_contract_type(title, detail_text)
        grade = extract_grade(title, detail_text)

        if not should_include(job_type, location, grade, source):
            continue

        jobs.append({
            "title": title,
            "organization": source["organization"],
            "location": location,
            "type": job_type,
            "grade": grade,
            "posted": "Available now" if SEND_ALL_AVAILABLE else (str(posted_date) if posted_date else "Not exposed by source"),
            "deadline": extract_deadline(detail_text),
            "years": extract_years(detail_text),
            "languages": extract_languages(detail_text),
            "url": url,
            "date_status": "day_zero" if SEND_ALL_AVAILABLE else ("posted_date" if posted_date else "first_seen_tracking"),
            "newness_method": "Day-zero full list" if SEND_ALL_AVAILABLE else ("Posted yesterday" if posted_date else "First seen by bot"),
        })

    return jobs


def format_job(index, job):
    return f"""<b>{index}. {safe(job['title'])} – {safe(job['organization'])}</b>

Location: {safe(job['location'])}
Type: {safe(job['type'])}
Grade: {safe(job['grade'])}
Posted: {safe(job['posted'])}
Newness method: {safe(job.get('newness_method', 'Not specified'))}
Deadline: {safe(job['deadline'])}
Link: {safe(job['url'])}

<b>Requirements summary:</b>
• Years of experience: {safe(job['years'])}
• Languages: {safe(job['languages'])}
• Note: grade, type and experience are shown only when clearly supported by the vacancy title or labelled vacancy text.

<b>Requirement source:</b>
Extracted from the specific job announcement page where available.
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
    run_mode,
):
    failed_text = "None"

    if failed_sources:
        failed_text = "\n".join([f"• {safe(name)}: {safe(error)}" for name, error in failed_sources[:10]])

        if len(failed_sources) > 10:
            failed_text += f"\n• Plus {len(failed_sources) - 10} more failed source(s)."

    return f"""<b>Daily Development Jobs – {YESTERDAY}</b>

<b>Summary:</b>
Run mode: {safe(run_mode)}
Sources checked: {sources_checked}
Sources successful: {sources_successful}
Sources failed: {sources_failed}
Jobs collected before deduplication: {jobs_collected}
Duplicates removed: {duplicates_removed}
Already-seen jobs skipped: {already_seen_skipped}
Baseline jobs saved without posting date: {baseline_without_dates}
Jobs sent: {jobs_sent}

<b>Quality controls:</b>
• Generic career pages, reports, programme expense pages and navigation links are filtered out.
• UN G/GS posts are excluded unless the duty station is in Italy.
• Type, grade and experience are not guessed from unrelated page text.

<b>How new jobs are detected:</b>
• If the source shows a posted date: only jobs posted yesterday are sent.
• If the source does not show a posted date: only jobs not seen in previous bot runs are sent.
• In Day Zero mode: all currently visible eligible positions are sent once and saved as seen.

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

    run_mode = "DAY ZERO / SEND ALL AVAILABLE POSITIONS" if SEND_ALL_AVAILABLE else "Daily update"

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

                if SEND_ALL_AVAILABLE:
                    unique.add(key)
                    all_jobs.append(job)
                    continue

                # First normal run after adding seen_jobs.json:
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
        run_mode=run_mode,
    )

    send_telegram(summary_message)

    if not all_jobs:
        send_telegram("No eligible positions found in this run.")
        return

    for index, job in enumerate(all_jobs, start=1):
        send_telegram(format_job(index, job))


if __name__ == "__main__":
    main()
