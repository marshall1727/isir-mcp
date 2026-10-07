"""Detail insolvenčního řízení (HTML stránka evidence_upadcu_detail.do) – stažení a parsování."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from bs4 import BeautifulSoup, Tag

from .client import HTTP, IsirHttp
from .ws import LustraceParams, lustrace

ODDILY = ("A", "B", "C", "D", "P")
ODDIL_NAZVY = {
    "A": "Řízení do úpadku",
    "B": "Řízení po úpadku",
    "C": "Incidenční spory",
    "D": "Ostatní",
    "P": "Přihlášky",
}
DETAIL_ID_RE = re.compile(r"^[0-9A-F]{32}$", re.I)
DOC_ID_RE = re.compile(r"dokument\.PDF\?id=(\d+)", re.I)


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


# ------------------------------------------------------------------------------------------
# Získání detail ID
# ------------------------------------------------------------------------------------------
def resolve_detail_id(identifikator: str, http: IsirHttp = HTTP) -> tuple[str, dict[str, Any] | None]:
    """Přijme detail ID, URL detailu nebo spisovou značku. Vrátí (detail_id, záznam lustrace|None)."""
    s = identifikator.strip()
    m = re.search(r"id=([0-9A-F]{32})", s, re.I)
    if m:
        return m.group(1).upper(), None
    if DETAIL_ID_RE.match(s):
        return s.upper(), None
    res = lustrace(LustraceParams(spisova_znacka=s, max_vysledku=10), http)
    vys = res["vysledky"]
    if not vys:
        raise LookupError(f"Spisová značka {s!r} nebyla v ISIR nalezena ({res['stav']}).")
    # Při zadaném soudu/senátu zúžíme
    from .ws import parse_spisova_znacka

    sz = parse_spisova_znacka(s)
    if sz["senat"] is not None:
        filt = [v for v in vys if str(v.get("cisloSenatu")) == str(sz["senat"])]
        if filt:
            vys = filt
    if len(vys) > 1:
        # více dlužníků v jednom řízení sdílí stejný detail – vezmi první, ale uveď to
        ids = {v.get("detailId") for v in vys}
        if len(ids) > 1:
            raise LookupError(
                "Spisová značka odpovídá více řízením: "
                + "; ".join(f"{v['spisovaZnacka']} ({v.get('nazevOrganizace')})" for v in vys)
                + ". Upřesněte soud/senát nebo použijte detailId."
            )
    v = vys[0]
    if not v.get("detailId"):
        raise LookupError("ISIR nevrátil URL detailu řízení.")
    return v["detailId"], v


# ------------------------------------------------------------------------------------------
# Stažení HTML (s cache)
# ------------------------------------------------------------------------------------------
def fetch_detail_html(detail_id: str, oddil: str | None = None, strana: str | int = "all",
                      http: IsirHttp = HTTP, use_cache: bool = True) -> str:
    cfg = http.cfg
    key = f"{detail_id}_{oddil or 'main'}_{strana}"
    cache_file = cfg.cache_dir / "html" / f"{key}.html"
    if use_cache and cache_file.exists() and time.time() - cache_file.stat().st_mtime < cfg.detail_cache_ttl_s:
        return cache_file.read_text("utf-8")
    url = f"{cfg.base_url}/isir/ueu/evidence_upadcu_detail.do?id={detail_id}"
    if oddil:
        oddil = oddil.upper()
        pages = "&".join(f"page{o}=1" for o in ODDILY if o != oddil)
        url += f"&actSheet={oddil}&{pages}&page{oddil}={strana}"
    html = http.get(url).text
    cache_file.write_text(html, "utf-8")
    return html


# ------------------------------------------------------------------------------------------
# Parsování
# ------------------------------------------------------------------------------------------
def parse_hlavicka(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, Any] = {}
    table = soup.find("table", class_="evidenceUpadcuDetail")
    if table is None:
        if "Chyba" in soup.get_text():
            raise LookupError("ISIR vrátil chybovou stránku – detail řízení neexistuje nebo je nedostupný.")
        raise LookupError("Nepodařilo se najít tabulku detailu řízení.")
    nadpisy = table.find_all("h2", class_="evidenceUpadcuDetailNadpis")
    if len(nadpisy) >= 2:
        out["dluznik"] = _norm(nadpisy[1].get_text())

    for tr in table.find_all("tr", recursive=False) or table.find_all("tr"):
        cells = [_norm(td.get_text(" ")) for td in tr.find_all("td", recursive=False)]
        if not cells:
            continue
        label = cells[0] if len(cells) >= 2 else ""
        # řádky typu [prázdná/odkaz, popisek, hodnota]
        if len(cells) == 3 and cells[1]:
            label, value = cells[1], cells[2]
        elif len(cells) >= 2:
            value = cells[-1]
        else:
            continue
        key = _klic(label)
        if key:
            out[key] = value
    # Spisová značka: "KSOS 37 INS 1000 / 2024 vedená u Krajského soudu v Ostravě"
    sz = out.get("spisova_znacka", "")
    m = re.match(r"(.*?)\s*vedená u\s*(.*)", sz)
    if m:
        out["spisova_znacka"] = re.sub(r"\s*/\s*", "/", _norm(m.group(1)))
        out["soud"] = _norm(m.group(2))
    return out


def _klic(label: str) -> str | None:
    label = label.rstrip(":").strip().lower()
    mapping = {
        "aktuální stav": "stav",
        "spisová značka": "spisova_znacka",
        "jméno/název": "jmeno_nazev",
        "ič": "ic",
        "rodné číslo / datum nar.": "rc_datum_narozeni",
        "bydliště": "bydliste",
        "sídlo": "sidlo",
        "insolvenční správce": "insolvencni_spravce",
        "- kancelář": "spravce_kancelar",
        "datum poslední zveřejněné události": "posledni_udalost",
        "konec lhůty pro přihlášení pohledávek": "konec_lhuty_prihlasek",
        "datum skončení insolvenčního řízení": "datum_skonceni",
        "mezinárodní příslušnost soudu": "mezinarodni_prislusnost",
    }
    for k, v in mapping.items():
        if label.startswith(k):
            return v
    return None


def parse_oddil(html: str, oddil: str) -> dict[str, Any]:
    """Vrátí události oddílu z aktuálně načtené stránky (včetně informace o stránkování)."""
    oddil = oddil.upper()
    soup = BeautifulSoup(html, "lxml")
    div = soup.find("div", id=f"zalozka{oddil}")
    result: dict[str, Any] = {"oddil": oddil, "nazev": ODDIL_NAZVY.get(oddil), "udalosti": [],
                              "zobrazeno": None, "celkem": None, "stranek": None}
    if div is None:
        return result
    table = div.find("table", class_="evidenceUpadcuDetailTable")
    if table is None:
        return result

    headers = [_norm(th.get_text()) for th in table.find_all("th")]
    # Sloupce: [poř., datum, čas (colspan 2 = jeden th), popis, ID události (hidden), dokument,
    #           vedlejší dokument, datum PM, (platní věřitelé u P), senátní značka]
    rows = table.find_all("tr")[1:]
    for tr in rows:
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 6:
            continue
        ev = _parse_radek(tds, oddil, headers)
        if ev:
            result["udalosti"].append(ev)

    # Stránkování: "Zobrazené záznamy: 1-150 z 508"
    nxt = table.find_next_sibling("div")
    if nxt is not None:
        txt = _norm(nxt.get_text(" "))
        m = re.search(r"Zobrazené záznamy:\s*(\d+)\s*-\s*(\d+)\s*z\s*(\d+)", txt)
        if m:
            result["zobrazeno"] = [int(m.group(1)), int(m.group(2))]
            result["celkem"] = int(m.group(3))
        pages = [int(a.get_text()) for a in nxt.find_all("a") if a.get_text().strip().isdigit()]
        result["stranek"] = max(pages) if pages else 1
    result["vse_nacteno"] = result["celkem"] is None or len(result["udalosti"]) >= result["celkem"]
    return result


def _parse_radek(tds: list[Tag], oddil: str, headers: list[str]) -> dict[str, Any] | None:
    def lines(td: Tag) -> list[str]:
        # jednotlivé <span> oddělené <br> = více položek v jedné události
        items = [_norm(s.get_text(" ")) for s in td.find_all("span")]
        items = [i for i in items if i]
        if not items:
            t = _norm(td.get_text(" "))
            items = [t] if t else []
        return items

    poradi = _norm(tds[0].get_text(" "))  # "7." nebo "P1 - 1."
    datum = _norm(tds[1].get_text())
    cas = _norm(tds[2].get_text())
    popisy = lines(tds[3])
    # ID události je ve skrytém sloupci (td s class hidden), následuje dokument, vedlejší dokument, PM
    idx = 4
    typy_udalosti: list[str] = []
    if idx < len(tds) and "hidden" in (tds[idx].get("class") or []):
        typy_udalosti = lines(tds[idx])
        idx += 1
    hlavni = _dokument(tds[idx]) if idx < len(tds) else None
    vedlejsi = _dokument(tds[idx + 1]) if idx + 1 < len(tds) else None
    pravni_moc = lines(tds[idx + 2]) if idx + 2 < len(tds) else []
    pravni_moc = [p for p in pravni_moc if re.match(r"\d{2}\.\d{2}\.\d{4}", p)]
    rest = [lines(td) for td in tds[idx + 3:]]

    oznaceni = poradi
    prihlaska = None
    m = re.match(r"(P\d+)\s*-\s*(\d+)\.?", poradi)
    if m:
        prihlaska, cislo = m.group(1), int(m.group(2))
        oznaceni = f"{prihlaska}-{cislo}"
    else:
        m2 = re.match(r"(\d+)\.?", poradi)
        if m2:
            oznaceni = f"{oddil}-{m2.group(1)}"

    ev: dict[str, Any] = {
        "oznaceni": oznaceni,            # např. B-7 nebo P1-1
        "oddil": oddil,
        "datum_zverejneni": datum,
        "cas_zverejneni": cas,
        "popis": popisy,
        "typ_udalosti": typy_udalosti,
        "dokument": hlavni,
        "vedlejsi_dokument": vedlejsi,
        "pravni_moc": pravni_moc,
    }
    if prihlaska:
        ev["prihlaska"] = prihlaska
    if oddil == "P" and rest:
        ev["platni_veritele"] = [x for x in rest[0] if x]
        if len(rest) > 1:
            ev["senatni_znacka_vs_ns"] = [x for x in rest[1] if x]
    elif rest:
        ev["senatni_znacka_vs_ns"] = [x for x in rest[0] if x]
    if not datum and not popisy and not hlavni:
        return None
    return ev


def _dokument(td: Tag) -> dict[str, Any] | None:
    a = td.find("a", href=DOC_ID_RE)
    if a is None:
        txt = _norm(td.get_text())
        return {"id": None, "poznamka": txt} if txt and txt != "" else None
    m = DOC_ID_RE.search(a["href"])
    size = re.search(r"\((\d+)\s*kB\)", _norm(a.get_text()))
    return {
        "id": m.group(1) if m else None,
        "velikost_kb": int(size.group(1)) if size else None,
        "url": f"https://isir.justice.cz/isir/doc/dokument.PDF?id={m.group(1)}" if m else None,
    }


# ------------------------------------------------------------------------------------------
# Vysoká úroveň
# ------------------------------------------------------------------------------------------
def detail_rizeni(identifikator: str, http: IsirHttp = HTTP, use_cache: bool = True) -> dict[str, Any]:
    detail_id, lustr = resolve_detail_id(identifikator, http)
    html = fetch_detail_html(detail_id, None, "all", http, use_cache)
    hl = parse_hlavicka(html)
    oddily = {}
    for o in ODDILY:
        sec = parse_oddil(html, o)
        oddily[o] = {
            "nazev": sec["nazev"],
            "celkem_udalosti": sec["celkem"] if sec["celkem"] is not None else len(sec["udalosti"]),
            "stranek": sec["stranek"],
        }
    out = {
        "detail_id": detail_id,
        "url": f"{http.cfg.base_url}/isir/ueu/evidence_upadcu_detail.do?id={detail_id}",
        **hl,
        "oddily": oddily,
    }
    if lustr:
        out["lustrace"] = lustr
    return out


def udalosti_oddilu(identifikator: str, oddil: str, http: IsirHttp = HTTP,
                    use_cache: bool = True, max_udalosti: int | None = None) -> dict[str, Any]:
    """Vrátí všechny události oddílu (načte stránku s page{oddil}=all)."""
    oddil = oddil.upper()
    if oddil not in ODDILY:
        raise ValueError(f"Neznámý oddíl {oddil!r}; povoleno: {', '.join(ODDILY)}")
    detail_id, _ = resolve_detail_id(identifikator, http)
    html = fetch_detail_html(detail_id, oddil, "all", http, use_cache)
    sec = parse_oddil(html, oddil)
    if sec["celkem"] is not None and len(sec["udalosti"]) < sec["celkem"]:
        # 'all' nebylo respektováno – projdi stránky
        stranek = sec["stranek"] or 1
        for p in range(2, stranek + 1):
            html_p = fetch_detail_html(detail_id, oddil, p, http, use_cache)
            sec["udalosti"].extend(parse_oddil(html_p, oddil)["udalosti"])
    sec["detail_id"] = detail_id
    if max_udalosti:
        sec["udalosti"] = sec["udalosti"][-max_udalosti:]
    return sec


def dokumenty_rizeni(identifikator: str, oddily: list[str] | None = None, http: IsirHttp = HTTP,
                     use_cache: bool = True) -> list[dict[str, Any]]:
    """Plochý seznam všech dokumentů (hlavních i vedlejších) napříč oddíly."""
    docs: list[dict[str, Any]] = []
    for o in oddily or ODDILY:
        sec = udalosti_oddilu(identifikator, o, http, use_cache)
        for ev in sec["udalosti"]:
            for role, d in (("hlavni", ev.get("dokument")), ("vedlejsi", ev.get("vedlejsi_dokument"))):
                if d and d.get("id"):
                    docs.append({
                        "dokument_id": d["id"],
                        "role": role,
                        "velikost_kb": d.get("velikost_kb"),
                        "udalost": ev["oznaceni"],
                        "oddil": o,
                        "datum": ev["datum_zverejneni"],
                        "popis": " | ".join(ev["popis"]),
                    })
    return docs


def to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
