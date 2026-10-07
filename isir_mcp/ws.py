"""Webové služby ISIR: ISIR_CUZK_WS2 (lustrace) a ISIR_PUBLIC_WS (tok událostí)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

from lxml import etree

from .client import HTTP, IsirHttp

NS_CUZK = "http://isirws.cca.cz/types/"
NS_PUBLIC = "http://isirpublicws.cca.cz/types/"

# Spisová značka ve tvaru "KSOS 37 INS 1000/2024", "MSPH 94 INS 12345 / 2023", "INS 1000/2024"
SPIS_RE = re.compile(
    r"^\s*(?:(?P<soud>[A-Z]{4,6})\s+)?(?:(?P<senat>\d{1,3})\s+)?(?P<druh>INS|ICM|INC)\s+"
    r"(?P<bc>\d{1,6})\s*/\s*(?P<rok>\d{4})\s*$",
    re.IGNORECASE,
)


def parse_spisova_znacka(sz: str) -> dict[str, Any]:
    m = SPIS_RE.match(sz)
    if not m:
        raise ValueError(
            f"Nerozpoznaná spisová značka: {sz!r}. Očekávám např. 'KSOS 37 INS 1000/2024' "
            f"nebo 'INS 1000/2024'."
        )
    return {
        "soud": (m.group("soud") or "").upper() or None,
        "senat": int(m.group("senat")) if m.group("senat") else None,
        "druh": m.group("druh").upper(),
        "bc": int(m.group("bc")),
        "rok": int(m.group("rok")),
    }


def _strip_ns(root: etree._Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _parse_xml(text: str) -> etree._Element:
    root = etree.fromstring(text.encode("utf-8"))
    _strip_ns(root)
    fault = root.find(".//Fault")
    if fault is not None:
        raise RuntimeError("SOAP chyba ISIR: " + (fault.findtext("faultstring") or "neznámá"))
    return root


def _el_to_dict(el: etree._Element) -> dict[str, Any]:
    return {child.tag: (child.text or "").strip() for child in el}


# ------------------------------------------------------------------------------------------
# ISIR_CUZK_WS2 – lustrace
# ------------------------------------------------------------------------------------------
@dataclass
class LustraceParams:
    ic: str | None = None
    rc: str | None = None
    nazev_osoby: str | None = None
    jmeno: str | None = None
    datum_narozeni: str | None = None  # YYYY-MM-DD
    spisova_znacka: str | None = None
    jen_aktualni: bool = False
    presna_shoda_jmen: bool = False
    bez_diakritiky: bool = False
    max_vysledku: int = 20


def lustrace(p: LustraceParams, http: IsirHttp = HTTP) -> dict[str, Any]:
    parts: list[str] = []

    def add(tag: str, val: Any) -> None:
        if val is None or val == "":
            return
        parts.append(f"<{tag}>{escape(str(val))}</{tag}>")

    # Pořadí elementů musí odpovídat XSD (sequence).
    add("ic", (p.ic or "").replace(" ", "") or None)
    add("rc", (p.rc or "").replace("/", "").replace(" ", "") or None)
    if p.spisova_znacka:
        sz = parse_spisova_znacka(p.spisova_znacka)
        add("druhVec", sz["druh"])
        add("bcVec", sz["bc"])
        add("rocnik", sz["rok"])
    add("nazevOsoby", p.nazev_osoby)
    add("jmeno", p.jmeno)
    add("datumNarozeni", p.datum_narozeni)
    add("maxPocetVysledku", p.max_vysledku)
    add("filtrAktualniRizeni", "T" if p.jen_aktualni else None)
    add("vyhledatPresnouShoduJmen", "T" if p.presna_shoda_jmen else None)
    add("vyhledatBezDiakritiky", "T" if p.bez_diakritiky else None)

    body = f"<typ:getIsirWsCuzkDataRequest>{''.join(parts)}</typ:getIsirWsCuzkDataRequest>"
    root = _parse_xml(http.soap(http.cfg.ws_cuzk_url, body, NS_CUZK))

    results = []
    for d in root.iter("data"):
        row = _el_to_dict(d)
        row["spisovaZnacka"] = (
            f"{row.get('cisloSenatu','')} {row.get('druhVec','')} {row.get('bcVec','')}/{row.get('rocnik','')}".strip()
        )
        m = re.search(r"id=([0-9A-F]+)", row.get("urlDetailRizeni", ""), re.I)
        row["detailId"] = m.group(1) if m else None
        results.append(row)

    stav_el = root.find(".//stav")
    stav = _el_to_dict(stav_el) if stav_el is not None else {}
    return {"vysledky": results, "stav": stav}


# ------------------------------------------------------------------------------------------
# ISIR_PUBLIC_WS – tok událostí
# ------------------------------------------------------------------------------------------
def posledni_id_udalosti(http: IsirHttp = HTTP) -> int:
    body = "<typ:getIsirWsPublicPosledniIdDataRequest/>"
    root = _parse_xml(http.soap(http.cfg.ws_public_url, body, NS_PUBLIC))
    txt = root.findtext(".//cisloPosledniId")
    if not txt:
        raise RuntimeError("ISIR WS nevrátila poslední ID události.")
    return int(txt)


def udalosti_od_id(id_podnetu: int, http: IsirHttp = HTTP) -> dict[str, Any]:
    """Vrátí dávku událostí s ID > id_podnetu (velikost dávky určuje server)."""
    body = (
        f"<typ:getIsirWsPublicIdDataRequest><idPodnetu>{int(id_podnetu)}</idPodnetu>"
        "</typ:getIsirWsPublicIdDataRequest>"
    )
    root = _parse_xml(http.soap(http.cfg.ws_public_url, body, NS_PUBLIC))
    rows = []
    for d in root.iter("data"):
        row = _el_to_dict(d)
        pozn = row.pop("poznamka", "")
        if pozn:
            row["poznamka"] = _parse_poznamka(pozn)
        m = re.search(r"id=(\d+)", row.get("dokumentUrl", ""))
        row["dokumentId"] = m.group(1) if m else None
        rows.append(row)
    status_el = root.find(".//status")
    return {"udalosti": rows, "status": _el_to_dict(status_el) if status_el is not None else {}}


def _parse_poznamka(pozn: str) -> Any:
    """Poznámka je vnořený XML dokument (escapovaný). Převedeme na slovník."""
    try:
        txt = html.unescape(pozn) if "&lt;" in pozn else pozn
        el = etree.fromstring(txt.encode("utf-8"))
        _strip_ns(el)
        return _xml_to_obj(el)
    except Exception:
        return pozn


def _xml_to_obj(el: etree._Element) -> Any:
    children = list(el)
    if not children:
        return (el.text or "").strip()
    out: dict[str, Any] = {}
    for ch in children:
        val = _xml_to_obj(ch)
        if ch.tag in out:
            if not isinstance(out[ch.tag], list):
                out[ch.tag] = [out[ch.tag]]
            out[ch.tag].append(val)
        else:
            out[ch.tag] = val
    return out
