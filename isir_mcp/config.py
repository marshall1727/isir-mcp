"""Konfigurace MCP serveru ISIR (proměnné prostředí)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    """Prázdná hodnota (např. nevyplněné pole v UI Claude Desktop) = výchozí."""
    val = os.environ.get(name, "").strip()
    return val or default


@dataclass
class Config:
    # Adresy ISIR
    base_url: str = _env_str("ISIR_BASE_URL", "https://isir.justice.cz")
    ws_cuzk_url: str = _env_str(
        "ISIR_WS_CUZK_URL", "https://isir.justice.cz:8443/isir_cuzk_ws/IsirWsCuzkService"
    )
    ws_public_url: str = _env_str(
        "ISIR_WS_PUBLIC_URL", "https://isir.justice.cz:8443/isir_public_ws/IsirWsPublicService"
    )

    # Omezení provozu podle Podmínek provozu ISIR (max 50 požadavků/min, max 3000/den).
    # Výchozí hodnoty jsou záměrně pod limitem.
    min_interval_s: float = _env_float("ISIR_MIN_INTERVAL", 1.5)   # 1 požadavek za 1,5 s = 40/min
    per_minute_limit: int = _env_int("ISIR_PER_MINUTE_LIMIT", 40)
    daily_limit: int = _env_int("ISIR_DAILY_LIMIT", 2500)
    timeout_s: float = _env_float("ISIR_TIMEOUT", 90.0)

    # Cache (stažené PDF, extrahovaný text, HTML detailů)
    cache_dir: Path = field(
        default_factory=lambda: Path(
            _env_str("ISIR_CACHE_DIR", str(Path.home() / ".isir-mcp" / "cache"))
        ).expanduser()
    )
    detail_cache_ttl_s: int = _env_int("ISIR_DETAIL_TTL", 3600)  # detail řízení 1 h

    # OCR
    tesseract_cmd: str | None = _env_str("TESSERACT_CMD", "") or None
    ocr_lang: str = _env_str("ISIR_OCR_LANG", "ces+eng")
    ocr_dpi: int = _env_int("ISIR_OCR_DPI", 300)
    # Pokud má stránka méně znaků textové vrstvy než tato mez, považuje se za sken.
    ocr_min_chars_per_page: int = _env_int("ISIR_OCR_MIN_CHARS", 40)
    max_ocr_pages: int = _env_int("ISIR_MAX_OCR_PAGES", 300)

    # Slušnost vůči provozovateli: identifikujte se (ISIR_CONTACT = e-mail nebo web).
    user_agent: str = _env_str(
        "ISIR_USER_AGENT",
        "isir-mcp/0.1 (https://github.com/marshall1727/isir-mcp; "
        + _env_str("ISIR_CONTACT", "kontakt neuveden")
        + ")",
    )

    def ensure_dirs(self) -> None:
        for sub in ("pdf", "text", "html", "meta"):
            (self.cache_dir / sub).mkdir(parents=True, exist_ok=True)


CONFIG = Config()
