"""Dokumenty ISIR: stažení PDF, textová vrstva, OCR, PDF portfolia (vedlejší dokumenty)."""
from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .client import HTTP, IsirHttp
from .config import CONFIG, Config


@dataclass
class DocMeta:
    dokument_id: str
    soubor: str
    velikost_b: int
    stran: int
    ma_textovou_vrstvu: bool
    text_zdroj: str  # "text_layer" | "ocr" | "mixed" | "none"
    ocr_stran: int = 0
    prilohy: list[dict[str, Any]] = field(default_factory=list)  # PDF portfolio
    staženo: str = ""
    chyba: str | None = None


# ------------------------------------------------------------------------------------------
# Cesty v cache
# ------------------------------------------------------------------------------------------
def _pdf_path(doc_id: str, cfg: Config) -> Path:
    return cfg.cache_dir / "pdf" / f"{doc_id}.pdf"


def _txt_path(doc_id: str, cfg: Config) -> Path:
    return cfg.cache_dir / "text" / f"{doc_id}.txt"


def _meta_path(doc_id: str, cfg: Config) -> Path:
    return cfg.cache_dir / "meta" / f"{doc_id}.json"


def _attach_dir(doc_id: str, cfg: Config) -> Path:
    return cfg.cache_dir / "pdf" / f"{doc_id}_prilohy"


# ------------------------------------------------------------------------------------------
# Stažení
# ------------------------------------------------------------------------------------------
def stahnout(doc_id: str, http: IsirHttp = HTTP, force: bool = False) -> Path:
    doc_id = str(int(doc_id))  # validace – jen číslo
    cfg = http.cfg
    cfg.ensure_dirs()
    path = _pdf_path(doc_id, cfg)
    if path.exists() and path.stat().st_size > 0 and not force:
        return path
    url = f"{cfg.base_url}/isir/doc/dokument.PDF?id={doc_id}"
    r = http.get(url)
    ct = r.headers.get("content-type", "")
    if "pdf" not in ct.lower() and not r.content.startswith(b"%PDF"):
        raise RuntimeError(
            f"ISIR nevrátil PDF pro dokument {doc_id} (Content-Type: {ct}). "
            "Dokument nemusí být zveřejněn nebo byl odstraněn."
        )
    tmp = path.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    return path


# ------------------------------------------------------------------------------------------
# Textová vrstva + OCR
# ------------------------------------------------------------------------------------------
def _text_layer_pages(pdf_path: Path) -> list[str]:
    reader = PdfReader(str(pdf_path))
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    return pages


def _extract_attachments(pdf_path: Path, doc_id: str, cfg: Config) -> list[dict[str, Any]]:
    """PDF portfolio (vedlejší dokument): vybalí vložené soubory."""
    out: list[dict[str, Any]] = []
    try:
        reader = PdfReader(str(pdf_path))
        attachments = reader.attachments  # dict name -> list[bytes]
    except Exception:
        return out
    if not attachments:
        return out
    d = _attach_dir(doc_id, cfg)
    d.mkdir(parents=True, exist_ok=True)
    for name, blobs in attachments.items():
        for i, blob in enumerate(blobs):
            safe = re.sub(r"[^\w.\-]+", "_", name)[:120] or f"priloha_{i}"
            if len(blobs) > 1:
                safe = f"{i}_{safe}"
            p = d / safe
            p.write_bytes(blob)
            out.append({"nazev": name, "soubor": str(p), "velikost_b": len(blob),
                        "je_pdf": blob[:4] == b"%PDF"})
    return out


def _ocr_available(cfg: Config) -> bool:
    import pytesseract

    if cfg.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd
    return shutil.which(pytesseract.pytesseract.tesseract_cmd) is not None or Path(
        pytesseract.pytesseract.tesseract_cmd
    ).exists()


def _ocr_pages(pdf_path: Path, page_indexes: list[int], cfg: Config) -> dict[int, str]:
    """OCR vybraných stránek (0-based). Rendrování přes pypdfium2, OCR přes Tesseract."""
    import pypdfium2 as pdfium
    import pytesseract

    if cfg.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd
    result: dict[int, str] = {}
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        scale = cfg.ocr_dpi / 72.0
        for idx in page_indexes:
            page = pdf[idx]
            bitmap = page.render(scale=scale, grayscale=True)
            img = bitmap.to_pil()
            try:
                txt = pytesseract.image_to_string(img, lang=cfg.ocr_lang, config="--psm 6")
            except pytesseract.TesseractError:
                # chybí jazykový balíček → zkus výchozí
                txt = pytesseract.image_to_string(img, config="--psm 6")
            result[idx] = txt
            page.close()
    finally:
        pdf.close()
    return result


def _is_scanned(text: str, cfg: Config) -> bool:
    return len(re.sub(r"\s+", "", text)) < cfg.ocr_min_chars_per_page


def ziskat_text(doc_id: str, ocr: str = "auto", http: IsirHttp = HTTP, force: bool = False) -> tuple[str, DocMeta]:
    """
    Vrátí (text, metadata). ocr: 'auto' (OCR jen stránek bez textové vrstvy), 'force' (OCR všech
    stránek), 'never' (jen textová vrstva). Výsledek se ukládá do cache.
    """
    cfg = http.cfg
    doc_id = str(int(doc_id))
    txt_path, meta_path = _txt_path(doc_id, cfg), _meta_path(doc_id, cfg)
    if txt_path.exists() and meta_path.exists() and not force:
        meta = DocMeta(**json.loads(meta_path.read_text("utf-8")))
        # cache je použitelná, pokud nevyžadujeme OCR, které ještě neproběhlo
        if ocr == "never" or meta.text_zdroj in ("ocr", "mixed") or (ocr == "auto" and meta.text_zdroj == "text_layer"):
            return txt_path.read_text("utf-8"), meta

    pdf_path = stahnout(doc_id, http)
    pages = _text_layer_pages(pdf_path)
    n = len(pages)
    scanned = [i for i, t in enumerate(pages) if _is_scanned(t, cfg)]
    ma_text = len(scanned) < n

    ocr_done = 0
    zdroj = "text_layer" if ma_text else "none"
    to_ocr: list[int] = []
    if ocr == "force":
        to_ocr = list(range(n))
    elif ocr == "auto":
        to_ocr = scanned
    chyba = None
    if to_ocr:
        if not _ocr_available(cfg):
            chyba = ("Tesseract OCR není nainstalován nebo nenalezen (nastavte TESSERACT_CMD). "
                     f"{len(to_ocr)} stran bez textové vrstvy zůstalo nepřečteno.")
        else:
            to_ocr = to_ocr[: cfg.max_ocr_pages]
            try:
                ocr_texts = _ocr_pages(pdf_path, to_ocr, cfg)
                for i, t in ocr_texts.items():
                    pages[i] = t
                ocr_done = len(ocr_texts)
                zdroj = "ocr" if ocr_done == n else "mixed"
            except Exception as e:  # pragma: no cover
                chyba = f"OCR selhalo: {e}"

    prilohy = _extract_attachments(pdf_path, doc_id, cfg)
    # Text příloh (pouze PDF) připojíme na konec
    extra_parts: list[str] = []
    for pr in prilohy:
        if pr["je_pdf"]:
            try:
                sub_pages = _text_layer_pages(Path(pr["soubor"]))
                sub_scanned = [i for i, t in enumerate(sub_pages) if _is_scanned(t, cfg)]
                if sub_scanned and ocr != "never" and _ocr_available(cfg):
                    for i, t in _ocr_pages(Path(pr["soubor"]), sub_scanned[: cfg.max_ocr_pages], cfg).items():
                        sub_pages[i] = t
                        ocr_done += 1
                extra_parts.append(f"\n\n===== PŘÍLOHA: {pr['nazev']} =====\n" + _join_pages(sub_pages))
            except Exception as e:
                extra_parts.append(f"\n\n===== PŘÍLOHA: {pr['nazev']} (nečitelná: {e}) =====\n")

    text = _join_pages(pages) + "".join(extra_parts)
    meta = DocMeta(
        dokument_id=doc_id,
        soubor=str(pdf_path),
        velikost_b=pdf_path.stat().st_size,
        stran=n,
        ma_textovou_vrstvu=ma_text,
        text_zdroj=zdroj,
        ocr_stran=ocr_done,
        prilohy=prilohy,
        staženo=time.strftime("%Y-%m-%d %H:%M:%S"),
        chyba=chyba,
    )
    txt_path.write_text(text, "utf-8")
    meta_path.write_text(json.dumps(asdict(meta), ensure_ascii=False, indent=1), "utf-8")
    return text, meta


def _join_pages(pages: list[str]) -> str:
    return "\n".join(f"----- strana {i + 1} -----\n{_clean(t)}" for i, t in enumerate(pages))


def _clean(t: str) -> str:
    t = t.replace("\x0c", "")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def strany_textu(text: str, od: int | None, do: int | None) -> str:
    """Vrátí jen rozsah stran (1-based, včetně) z textu se značkami '----- strana N -----'."""
    if not od and not do:
        return text
    parts = re.split(r"(?=----- strana \d+ -----)", text)
    out = []
    for p in parts:
        m = re.match(r"----- strana (\d+) -----", p)
        if not m:
            if p.startswith("\n\n===== PŘÍLOHA"):
                out.append(p)
            continue
        n = int(m.group(1))
        if (od is None or n >= od) and (do is None or n <= do):
            out.append(p)
    return "".join(out)


def meta_z_cache(doc_id: str, cfg: Config = CONFIG) -> DocMeta | None:
    p = _meta_path(str(int(doc_id)), cfg)
    if p.exists():
        return DocMeta(**json.loads(p.read_text("utf-8")))
    return None
