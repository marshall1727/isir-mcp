"""Omezovač požadavků: minimální rozestup, limit za minutu a denní limit (perzistentní)."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from datetime import date
from pathlib import Path


class DailyLimitExceeded(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, min_interval_s: float, per_minute: int, daily: int, state_file: Path):
        self.min_interval_s = min_interval_s
        self.per_minute = per_minute
        self.daily = daily
        self.state_file = state_file
        self._lock = threading.Lock()
        self._last = 0.0
        self._minute: deque[float] = deque()
        self._day, self._count = self._load()

    # -- perzistence denního počítadla -------------------------------------------------
    def _load(self) -> tuple[str, int]:
        try:
            data = json.loads(self.state_file.read_text("utf-8"))
            if data.get("day") == date.today().isoformat():
                return data["day"], int(data.get("count", 0))
        except Exception:
            pass
        return date.today().isoformat(), 0

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps({"day": self._day, "count": self._count}), "utf-8"
            )
        except Exception:
            pass

    # -- veřejné rozhraní ----------------------------------------------------------------
    def stats(self) -> dict:
        with self._lock:
            self._rollover()
            return {
                "den": self._day,
                "pozadavku_dnes": self._count,
                "denni_limit": self.daily,
                "zbyva_dnes": max(0, self.daily - self._count),
                "limit_za_minutu": self.per_minute,
                "min_rozestup_s": self.min_interval_s,
            }

    def _rollover(self) -> None:
        today = date.today().isoformat()
        if today != self._day:
            self._day, self._count = today, 0
            self._save()

    def acquire(self) -> None:
        """Blokuje, dokud není možné odeslat další požadavek. Vyhodí DailyLimitExceeded."""
        with self._lock:
            self._rollover()
            if self._count >= self.daily:
                raise DailyLimitExceeded(
                    f"Denní limit {self.daily} požadavků na ISIR byl vyčerpán "
                    f"({self._count} dnes). Pokračujte zítra nebo zvyšte ISIR_DAILY_LIMIT "
                    f"(absolutní strop dle Podmínek provozu je 3000/den)."
                )
            now = time.monotonic()
            # limit za minutu (klouzavé okno 60 s)
            while self._minute and now - self._minute[0] > 60:
                self._minute.popleft()
            wait = 0.0
            if len(self._minute) >= self.per_minute:
                wait = max(wait, 60 - (now - self._minute[0]) + 0.05)
            wait = max(wait, self.min_interval_s - (now - self._last))
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._last = now
            self._minute.append(now)
            self._count += 1
            self._save()
