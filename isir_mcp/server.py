"""MCP server pro insolvenční rejstřík ISIR (isir.justice.cz)."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from typing import Any

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from . import detail as D
from . import documents as DOC
from . import ws as WS
from .client import HTTP
from .ratelimit import DailyLimitExceeded

mcp = FastMCP(
    "isir",
    instructions=(
        "Insolvenční rejstřík ČR (ISIR). Postup: 1) isir_lustrace pro nalezení řízení (IČO, RČ, jméno, "
        "spisová značka) → 2) isir_detail_rizeni pro hlavičku a počty událostí v oddílech A/B/C/D/P → "
        "3) isir_udalosti pro seznam událostí a ID dokumentů v oddílu → 4) isir_text_dokumentu pro plný "
        "text (textová vrstva + OCR skenů). isir_hledat_v_dokumentech prohledá plné texty všech dokumentů "
        "řízení. Server dodržuje Podmínky provozu ISIR (max 40 požadavků/min, 2500/den); hromadné "
        "operace mohou trvat déle. Dokumenty a texty se ukládají do lokální cache (cesta je ve výstupu), "
        "lze s nimi dále pracovat jako se soubory."
    ),
)


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def _err(e: Exception) -> str:
    if isinstance(e, DailyLimitExceeded):
        return _j({"chyba": str(e), "limity": HTTP.limiter.stats()})
    return _j({"chyba": f"{type(e).__name__}: {e}"})


# ------------------------------------------------------------------------------------------
@mcp.tool()
def isir_lustrace(
    ico: str | None = None,
    rc: str | None = None,
    nazev_osoby: str | None = None,
    jmeno: str | None = None,
    datum_narozeni: str | None = None,
    spisova_znacka: str | None = None,
    jen_aktualni: bool = False,
    presna_shoda_jmen: bool = False,
    bez_diakritiky: bool = False,
    max_vysledku: int = 20,
) -> str:
    """Lustrace v ISIR (webová služba ISIR_CUZK_WS2). Zadejte JEDNU z kombinací:
    - ico (8 číslic) nebo rc (rodné číslo, s lomítkem i bez),
    - spisova_znacka ('KSOS 37 INS 1000/2024' nebo jen 'INS 1000/2024'),
    - nazev_osoby (příjmení / název firmy) + volitelně jmeno a datum_narozeni (YYYY-MM-DD).
    Vrací seznam řízení: spisová značka, soud, dlužník, stav (druhStavKonkursu), data úpadku a
    detailId pro další nástroje. jen_aktualni=True vynechá skončená řízení."""
    try:
        res = WS.lustrace(WS.LustraceParams(
            ic=ico, rc=rc, nazev_osoby=nazev_osoby, jmeno=jmeno, datum_narozeni=datum_narozeni,
            spisova_znacka=spisova_znacka, jen_aktualni=jen_aktualni,
            presna_shoda_jmen=presna_shoda_jmen, bez_diakritiky=bez_diakritiky,
            max_vysledku=max(1, min(max_vysledku, 200)),
        ))
        for v in res["vysledky"]:
            v["stav_popis"] = STAVY.get(v.get("druhStavKonkursu", ""), v.get("druhStavKonkursu"))
        return _j(res)
    except Exception as e:
        return _err(e)


STAVY = {
    "NEVYRIZENA": "Před rozhodnutím o úpadku",
    "MORATORIUM": "Moratorium",
    "ÚPADEK": "V úpadku",
    "KONKURS": "Prohlášený konkurs",
    "ODDLUŽENÍ": "Povoleno oddlužení",
    "REORGANIZ": "Povolena reorganizace",
    "VYRIZENA": "Vyřízená věc",
    "PRAVOMOCNA": "Pravomocná věc",
    "ODSKRTNUTA": "Odškrtnutá – skončená věc",
    "ZRUŠENO VS": "Zrušeno vrchním soudem",
    "K-PO ZRUŠ.": "Prohlášený konkurs po zrušení VS",
    "OBZIVLA": "Obživlá věc",
    "NEVYR-POST": "Postoupená věc",
    "MYLNÝ ZÁP.": "Mylný zápis do rejstříku",
}


@mcp.tool()
def isir_detail_rizeni(rizeni: str, obnovit: bool = False) -> str:
    """Hlavička insolvenčního řízení: dlužník, stav, spisová značka, soud, insolvenční správce,
    lhůty, datum poslední události a počty událostí v oddílech A (do úpadku), B (po úpadku),
    C (incidenční spory), D (ostatní), P (přihlášky).
    `rizeni` = spisová značka, detailId (32 hex znaků) nebo URL detailu. obnovit=True obejde cache (1 h)."""
    try:
        return _j(D.detail_rizeni(rizeni, HTTP, use_cache=not obnovit))
    except Exception as e:
        return _err(e)


@mcp.tool()
def isir_udalosti(rizeni: str, oddil: str = "B", poslednich: int = 0, obnovit: bool = False,
                  hledat: str | None = None) -> str:
    """Seznam událostí (záznamů) jednoho oddílu řízení včetně ID dokumentů.
    oddil: A/B/C/D/P. Každá událost má označení (např. B-7, P12-3), datum, popis (může být více
    úkonů), hlavní dokument a vedlejší dokument (PDF portfolio s přílohami), datum právní moci.
    poslednich=N vrátí jen N nejnovějších. hledat=text filtruje podle popisu (bez ohledu na velikost
    písmen, bez diakritiky netřeba řešit – porovnává se po normalizaci)."""
    try:
        sec = D.udalosti_oddilu(rizeni, oddil, HTTP, use_cache=not obnovit)
        if hledat:
            q = _fold(hledat)
            sec["udalosti"] = [e for e in sec["udalosti"] if q in _fold(" ".join(e["popis"]))]
        if poslednich and poslednich > 0:
            sec["udalosti"] = sec["udalosti"][-poslednich:]
        sec["pocet_vraceno"] = len(sec["udalosti"])
        return _j(sec)
    except Exception as e:
        return _err(e)


@mcp.tool()
def isir_dokumenty(rizeni: str, oddily: str = "A,B,C,D,P", obnovit: bool = False) -> str:
    """Plochý seznam všech dokumentů řízení (ID, role hlavní/vedlejší, velikost, událost, oddíl,
    datum, popis). Vhodné jako podklad pro hromadné stažení/OCR. oddily: čárkou oddělené."""
    try:
        odd = [o.strip().upper() for o in oddily.split(",") if o.strip()]
        docs = D.dokumenty_rizeni(rizeni, odd, HTTP, use_cache=not obnovit)
        return _j({"pocet": len(docs), "celkem_kb": sum(d.get("velikost_kb") or 0 for d in docs),
                   "dokumenty": docs})
    except Exception as e:
        return _err(e)


@mcp.tool()
def isir_stahnout_dokument(dokument_id: str, znovu: bool = False) -> str:
    """Stáhne PDF dokumentu z ISIR do lokální cache a vrátí cestu k souboru, počet stran a
    informaci, zda má textovou vrstvu. Text nevrací – použijte isir_text_dokumentu."""
    try:
        path = DOC.stahnout(dokument_id, HTTP, force=znovu)
        pages = DOC._text_layer_pages(path)
        scanned = sum(1 for t in pages if DOC._is_scanned(t, HTTP.cfg))
        return _j({
            "dokument_id": str(int(dokument_id)),
            "soubor": str(path),
            "velikost_b": path.stat().st_size,
            "stran": len(pages),
            "stran_bez_textove_vrstvy": scanned,
            "doporuceni": "isir_text_dokumentu(ocr='auto')" if scanned else "isir_text_dokumentu(ocr='never')",
        })
    except Exception as e:
        return _err(e)


@mcp.tool()
def isir_text_dokumentu(dokument_id: str, ocr: str = "auto", strana_od: int | None = None,
                        strana_do: int | None = None, max_znaku: int = 60000,
                        offset: int = 0, znovu: bool = False) -> str:
    """Plný text dokumentu ISIR. Stáhne PDF (je-li třeba), vezme textovou vrstvu a stránky bez ní
    přečte OCR (Tesseract, čeština). U vedlejších dokumentů (PDF portfolio) vybalí přílohy a připojí
    i jejich text. Výstup je členěn značkami '----- strana N -----'.
    ocr: 'auto' (výchozí) | 'force' (OCR všech stran, např. při špatné textové vrstvě) | 'never'.
    Dlouhé texty: použijte strana_od/strana_do nebo offset (znaky) + max_znaku pro stránkování.
    Vrací JSON s metadaty (soubor, stran, zdroj textu, OCR stran, přílohy) a polem 'text'."""
    try:
        if ocr not in ("auto", "force", "never"):
            return _j({"chyba": "ocr musí být auto | force | never"})
        text, meta = DOC.ziskat_text(dokument_id, ocr, HTTP, force=znovu)
        part = DOC.strany_textu(text, strana_od, strana_do)
        total = len(part)
        chunk = part[offset: offset + max_znaku]
        out = asdict(meta)
        out.update({
            "textovy_soubor": str(DOC._txt_path(meta.dokument_id, HTTP.cfg)),
            "znaku_celkem": total,
            "offset": offset,
            "vraceno_znaku": len(chunk),
            "dalsi_offset": offset + len(chunk) if offset + len(chunk) < total else None,
            "text": chunk,
        })
        return _j(out)
    except Exception as e:
        return _err(e)


@mcp.tool()
def isir_hledat_v_dokumentech(rizeni: str, dotaz: str, oddily: str = "A,B,C,D,P",
                              max_dokumentu: int = 40, ocr: str = "auto", kontext_znaku: int = 300,
                              regex: bool = False) -> str:
    """Fulltextové hledání napříč dokumenty řízení. Stáhne (a podle potřeby OCR) až max_dokumentu
    dokumentů z vybraných oddílů (od nejnovějších) a vrátí nálezy s kontextem. Hledání je necitlivé na
    velikost písmen a diakritiku; regex=True použije regulární výraz (bez skládání diakritiky).
    POZOR: každý dosud nestažený dokument = 1 požadavek na ISIR a případné OCR (desítky sekund na
    dokument). Pro velká řízení zužte oddíly nebo max_dokumentu."""
    try:
        odd = [o.strip().upper() for o in oddily.split(",") if o.strip()]
        docs = D.dokumenty_rizeni(rizeni, odd, HTTP, use_cache=True)
        docs = list(reversed(docs))[: max(1, min(max_dokumentu, 300))]
        pattern = re.compile(dotaz, re.I) if regex else None
        q = _fold(dotaz)
        hits = []
        zpracovano = 0
        chyby = []
        for d in docs:
            try:
                text, meta = DOC.ziskat_text(d["dokument_id"], ocr, HTTP)
            except Exception as e:
                chyby.append({"dokument_id": d["dokument_id"], "chyba": str(e)})
                continue
            zpracovano += 1
            found = []
            if pattern:
                for m in pattern.finditer(text):
                    found.append((m.start(), m.end()))
            else:
                ft = _fold(text)
                start = 0
                while True:
                    i = ft.find(q, start)
                    if i < 0:
                        break
                    found.append((i, i + len(q)))
                    start = i + 1
            if found:
                ukazky = []
                for s, e in found[:10]:
                    a, b = max(0, s - kontext_znaku // 2), min(len(text), e + kontext_znaku // 2)
                    strana = text.rfind("----- strana ", 0, s)
                    sm = re.match(r"----- strana (\d+)", text[strana:strana + 30]) if strana >= 0 else None
                    ukazky.append({"strana": int(sm.group(1)) if sm else None,
                                   "kontext": re.sub(r"\s+", " ", text[a:b])})
                hits.append({**d, "pocet_nalezu": len(found), "text_zdroj": meta.text_zdroj,
                             "soubor": meta.soubor, "ukazky": ukazky})
        return _j({"dotaz": dotaz, "prohledano_dokumentu": zpracovano, "dokumentu_s_nalezem": len(hits),
                   "nalezy": hits, "chyby": chyby, "limity": HTTP.limiter.stats()})
    except Exception as e:
        return _err(e)


@mcp.tool()
def isir_tok_udalosti(od_id: int | None = None, davek: int = 1, jen_spisova_znacka: str | None = None) -> str:
    """Tok událostí celého rejstříku (webová služba ISIR_PUBLIC_WS, WS_1). Vrací dávky událostí
    s ID > od_id (bez od_id začne u posledního ID, tj. vrátí jen nejnovější). Každá událost: ID,
    datum, spisová značka (bez soudu), typ a popis, URL dokumentu a strukturovaná poznámka (dlužník,
    věřitel, přihláška, stav řízení...). Určeno pro sledování změn, ne pro cílené dotazy na jedno
    řízení (k tomu slouží isir_udalosti). jen_spisova_znacka filtruje výstup (tvar 'INS 1000/2024')."""
    try:
        if od_id is None:
            od_id = WS.posledni_id_udalosti(HTTP) - 1
        all_rows = []
        last = od_id
        for _ in range(max(1, min(davek, 20))):
            res = WS.udalosti_od_id(last, HTTP)
            rows = res["udalosti"]
            if not rows:
                break
            all_rows.extend(rows)
            last = max(int(r["id"]) for r in rows)
        if jen_spisova_znacka:
            sz = re.sub(r"\s*/\s*", "/", jen_spisova_znacka.strip().upper())
            all_rows = [r for r in all_rows if re.sub(r"\s*/\s*", "/", r.get("spisovaZnacka", "").upper()).endswith(sz)]
        return _j({"od_id": od_id, "posledni_id": last, "pocet": len(all_rows), "udalosti": all_rows})
    except Exception as e:
        return _err(e)


@mcp.tool()
def isir_stav_serveru() -> str:
    """Stav omezovače požadavků (kolik požadavků dnes, limity), adresář cache a dostupnost OCR."""
    cfg = HTTP.cfg
    try:
        ocr_ok = DOC._ocr_available(cfg)
    except Exception:
        ocr_ok = False
    pdfs = list((cfg.cache_dir / "pdf").glob("*.pdf")) if cfg.cache_dir.exists() else []
    return _j({
        "limity": HTTP.limiter.stats(),
        "cache_dir": str(cfg.cache_dir),
        "pdf_v_cache": len(pdfs),
        "pdf_cache_mb": round(sum(p.stat().st_size for p in pdfs) / 1e6, 1),
        "ocr_dostupne": ocr_ok,
        "ocr_jazyk": cfg.ocr_lang,
        "tesseract_cmd": cfg.tesseract_cmd or "(z PATH)",
    })


# ------------------------------------------------------------------------------------------
_FOLD_MAP = str.maketrans(
    "áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽäöüÄÖÜľĺŕôĽĹŔÔ",
    "acdeeinorstuuyzACDEEINORSTUUYZaouAOUllroLLRO",
)


def _fold(s: str) -> str:
    return s.translate(_FOLD_MAP).lower()


def main() -> None:
    HTTP.cfg.ensure_dirs()
    print(f"[isir-mcp] cache: {HTTP.cfg.cache_dir}", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
