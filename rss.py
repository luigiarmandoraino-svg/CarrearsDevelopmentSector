from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable, List

from ..models import Job, Source


class Parser(ABC):
    def __init__(self, source: Source, timezone: str = "Africa/Kigali"):
        self.source = source
        self.timezone = timezone

    @abstractmethod
    async def collect(self, target_date: date) -> list[Job]:
        raise NotImplementedError
