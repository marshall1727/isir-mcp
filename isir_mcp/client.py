"""HTTP klient pro ISIR s omezovačem požadavků."""
from __future__ import annotations

import httpx

from .config import CONFIG, Config
from .ratelimit import RateLimiter


class IsirHttp:
    def __init__(self, config: Config = CONFIG):
        self.cfg = config
        self.cfg.ensure_dirs()
        self.limiter = RateLimiter(
            config.min_interval_s,
            config.per_minute_limit,
            config.daily_limit,
            config.cache_dir / "meta" / "ratelimit.json",
        )
        self._client = httpx.Client(
            timeout=config.timeout_s,
            follow_redirects=True,
            headers={"User-Agent": config.user_agent, "Accept-Language": "cs"},
        )

    def get(self, url: str, **kw) -> httpx.Response:
        self.limiter.acquire()
        r = self._client.get(url, **kw)
        r.raise_for_status()
        return r

    def soap(self, url: str, body_xml: str, types_ns: str) -> str:
        """Odešle SOAP 1.1 požadavek. `body_xml` je obsah <Body> s prefixem `typ:` pro kořenový element."""
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            f'xmlns:typ="{types_ns}"><soapenv:Header/><soapenv:Body>{body_xml}'
            "</soapenv:Body></soapenv:Envelope>"
        )
        self.limiter.acquire()
        r = self._client.post(
            url,
            content=envelope.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
        )
        # SOAP Fault přichází s HTTP 500 a popisem chyby v těle – nechceme ztratit text.
        if r.status_code >= 500 and b"Fault" in r.content:
            return r.text
        r.raise_for_status()
        return r.text

    def close(self) -> None:
        self._client.close()


HTTP = IsirHttp()
