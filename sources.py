from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import Job
from .utils import canonical_job_key


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    key TEXT PRIMARY KEY,
    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
    title TEXT,
    organization TEXT,
    location TEXT,
    deadline TEXT,
    link TEXT
);
CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    source_id TEXT,
    organization TEXT,
    status TEXT,
    message TEXT
);
"""


class Store:
    def __init__(self, db_path: str):
        self.path = Path(db_path)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def job_key(self, job: Job) -> str:
        return canonical_job_key(job.title, job.display_org, job.location, str(job.deadline or ""), job.link)

    def already_seen(self, job: Job) -> bool:
        key = self.job_key(job)
        row = self.conn.execute("SELECT 1 FROM seen_jobs WHERE key=?", (key,)).fetchone()
        return bool(row)

    def mark_seen(self, job: Job):
        key = self.job_key(job)
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_jobs(key,title,organization,location,deadline,link) VALUES(?,?,?,?,?,?)",
            (key, job.title, job.display_org, job.location, str(job.deadline or ""), job.link),
        )
        self.conn.commit()

    def log(self, source_id: str, organization: str, status: str, message: str):
        self.conn.execute(
            "INSERT INTO run_log(source_id, organization, status, message) VALUES(?,?,?,?)",
            (source_id, organization, status, message[:2000]),
        )
        self.conn.commit()
