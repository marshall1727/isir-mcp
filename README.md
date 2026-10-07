# isir-mcp – MCP server pro insolvenční rejstřík (isir.justice.cz)

[![CI](https://github.com/marshall1727/isir-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/marshall1727/isir-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

> **English summary.** A local [Model Context Protocol](https://modelcontextprotocol.io) server
> (stdio) for the Czech public insolvency register **ISIR**. It looks up debtors and proceedings via
> the official SOAP web services of the Ministry of Justice, lists all events and documents of a
> case from the public case-detail page, downloads the PDFs, extracts their text and **OCRs scanned
> pages** (Tesseract, Czech), unpacks PDF portfolios and offers full-text search across a case.
> It enforces the register's published rate limits. Czech documentation follows.

Lokální MCP server pro Claude Desktop, Claude Code a další MCP klienty. Umožňuje asistentovi
pracovat s **úplným obsahem všech dokumentů** insolvenčního řízení – včetně skenů.

## Nástroje

| Nástroj | Zdroj v ISIR | Co dělá |
|---|---|---|
| `isir_lustrace` | webová služba ISIR_CUZK_WS2 | hledání řízení podle IČO, RČ, jména/názvu, data narození nebo spisové značky |
| `isir_detail_rizeni` | HTML detail řízení | hlavička: dlužník, stav, soud, správce, lhůty, počty událostí v oddílech A/B/C/D/P |
| `isir_udalosti` | HTML detail řízení (`page=all`) | všechny události oddílu s ID hlavního a vedlejšího dokumentu a právní mocí |
| `isir_dokumenty` | HTML detail řízení | plochý seznam všech dokumentů řízení |
| `isir_stahnout_dokument` | `/isir/doc/dokument.PDF?id=` | stáhne PDF do cache, zjistí textovou vrstvu |
| `isir_text_dokumentu` | PDF v cache | plný text: textová vrstva + **OCR** stran bez vrstvy; u PDF portfolií vybalí a přečte přílohy |
| `isir_hledat_v_dokumentech` | PDF v cache | fulltext napříč dokumenty řízení (bez ohledu na diakritiku, nebo regex) |
| `isir_tok_udalosti` | webová služba ISIR_PUBLIC_WS | tok událostí celého rejstříku (sledování změn) |
| `isir_stav_serveru` | – | využití limitů, cache, dostupnost OCR |

Server **nepoužívá** webový vyhledávací formulář ISIR (je chráněn CAPTCHA). Lustrace jde výhradně
přes oficiální webovou službu MSp určenou pro strojový přístup; detail řízení a dokumenty se čtou
z veřejných URL bez přihlášení.

## Limity a chování

[Podmínky provozu ISIR](https://isir.justice.cz/isir/common/stat.do?kodStranky=PROVOZPODMINKY)
povolují max. **50 požadavků/min a 3 000/den**. Server vynucuje výchozí **1 požadavek / 1,5 s
(40/min)** a **2 500/den**; denní počítadlo je uložené v cache a přežije restart. Při vyčerpání
vrátí nástroj chybu – limit nikdy nepřekročí.

Vše stažené (HTML detailů na 1 h, PDF, extrahovaný text, metadata) je v cache
`~/.isir-mcp/cache` (změna přes `ISIR_CACHE_DIR`). Cesty k souborům jsou ve výstupu nástrojů, takže
klient může s PDF/TXT dále pracovat jako s běžnými soubory.

> Cache obsahuje osobní údaje dlužníků z veřejného rejstříku. Zacházejte s ní jako s ostatními
> spisovými materiály (přístupová práva, výmaz po skončení věci).

## Instalace

### A) Claude Desktop – jedním kliknutím (.mcpb)

1. Stáhněte `isir-mcp-X.Y.Z.mcpb` z [Releases](https://github.com/marshall1727/isir-mcp/releases).
2. Otevřete soubor dvojklikem (nebo Claude Desktop → Settings → Extensions → Advanced settings → Install Extension…).
3. V nastavení rozšíření volitelně zadejte složku cache, cestu k Tesseractu, jazyky OCR, denní limit a kontakt.

Balíček používá runtime **uv** – Claude Desktop si sám stáhne Python i závislosti, nic dalšího
není potřeba. Pro OCR skenovaných dokumentů nainstalujte **Tesseract OCR** s českými daty (viz níže)
a cestu k `tesseract.exe` zadejte v nastavení rozšíření.

Sestavení balíčku ze zdrojů: `python scripts/build_mcpb.py` → `dist/isir-mcp-X.Y.Z.mcpb`
(použije oficiální CLI `@anthropic-ai/mcpb`, je-li k dispozici `npx`).

### B) Ručně (Claude Code, jiní MCP klienti, vývoj)

Požadavky: **Python 3.10+** a **Tesseract OCR** s českými daty.

- Windows: instalátor [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) → *Additional language data* → **Czech**.
  Výchozí cesta `C:\Program Files\Tesseract-OCR\tesseract.exe`.
- macOS: `brew install tesseract tesseract-lang`
- Debian/Ubuntu: `sudo apt install tesseract-ocr tesseract-ocr-ces`

```bash
git clone https://github.com/marshall1727/isir-mcp.git
cd isir-mcp
python -m venv .venv
# Windows: .\.venv\Scripts\pip install -e .    |  macOS/Linux: .venv/bin/pip install -e .
```

Na Windows lze místo toho spustit `install.ps1`, který vytvoří prostředí, nainstaluje balíček,
spustí offline testy a vygeneruje blok konfigurace pro Claude Desktop.

### Claude Desktop

`%APPDATA%\Claude\claude_desktop_config.json` (Windows) nebo
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "isir": {
      "command": "C:\\cesta\\k\\isir-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "isir_mcp.server"],
      "env": {
        "TESSERACT_CMD": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
        "ISIR_OCR_LANG": "ces+eng",
        "ISIR_CACHE_DIR": "C:\\cesta\\k\\isir-cache",
        "ISIR_CONTACT": "vas@email.cz"
      }
    }
  }
}
```

Po restartu ověřte: „Zavolej isir_stav_serveru“ → `ocr_dostupne: true`.

### Claude Code

```bash
claude mcp add isir -e TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe" -- <cesta>/.venv/Scripts/python.exe -m isir_mcp.server
```

### Ověření proti živému ISIR

```bash
.venv/bin/python tests/live_smoke.py     # ~6 požadavků: lustrace → detail → oddíl B → text dokumentu
```

## Proměnné prostředí

| Proměnná | Výchozí | Význam |
|---|---|---|
| `ISIR_CACHE_DIR` | `~/.isir-mcp/cache` | adresář cache |
| `ISIR_CONTACT` | – | kontakt do User-Agent (slušnost vůči provozovateli) |
| `ISIR_MIN_INTERVAL` | `1.5` | min. rozestup požadavků (s) |
| `ISIR_PER_MINUTE_LIMIT` | `40` | max. požadavků/min (strop ISIR: 50) |
| `ISIR_DAILY_LIMIT` | `2500` | max. požadavků/den (strop ISIR: 3000) |
| `ISIR_DETAIL_TTL` | `3600` | platnost cache detailu řízení (s) |
| `TESSERACT_CMD` | z PATH | cesta k tesseract.exe |
| `ISIR_OCR_LANG` | `ces+eng` | jazyky OCR |
| `ISIR_OCR_DPI` | `300` | rozlišení rendrování pro OCR |
| `ISIR_OCR_MIN_CHARS` | `40` | pod tolik znaků/stranu se strana považuje za sken |
| `ISIR_MAX_OCR_PAGES` | `300` | strop OCR stran na dokument |

## Typický postup v konverzaci

1. `isir_lustrace(ico="12345678")` → spisová značka + `detailId`
2. `isir_detail_rizeni("KSOS 25 INS 10525/2016")` → stav, správce, počty událostí
3. `isir_udalosti(rizeni=..., oddil="B", hledat="usnesení")` → ID dokumentů
4. `isir_text_dokumentu(dokument_id="58657721")` → plný text (OCR podle potřeby)
5. `isir_hledat_v_dokumentech(rizeni=..., dotaz="zajištěný věřitel", oddily="B,P", max_dokumentu=30)`

## Release

Hotové balíčky jsou v záložce [Releases](https://github.com/marshall1727/isir-mcp/releases):
`isir-mcp-X.Y.Z.mcpb` (rozšíření pro Claude Desktop), `isir_mcp-X.Y.Z-py3-none-any.whl`
(instalace `pip install <soubor>.whl`), sdist a zdrojový zip.
Release vytváří GitHub Actions automaticky po pushi tagu `vX.Y.Z`; verze tagu musí odpovídat
`version` v `pyproject.toml`. Lokálně to zařídí `publish.ps1`.

## Vývoj

```bash
pip install -e ".[dev]"
pytest            # offline testy parserů (fixture HTML)
ruff check .
```

Struktura: `ws.py` (SOAP služby), `detail.py` (parser detailu řízení), `documents.py` (PDF, OCR,
portfolia), `ratelimit.py`, `server.py` (MCP nástroje).

## Známá omezení

- Oddíl P velkých řízení (tisíce přihlášek) je jedna velká HTML stránka; načtení trvá, ale jde o
  1 požadavek. Fulltext přes stovky dokumentů respektuje limity – počítejte s minutami.
- Nová podoba rejstříku (eisir.justice.cz) byla v době vývoje v ověřovacím provozu bez dat;
  server používá stávající ISIR. Změní-li MSp HTML detailu, upravte `isir_mcp/detail.py`
  (testy ve `tests/` to odhalí).
- Kvalita OCR závisí na kvalitě skenu; `ocr="force"` pomůže u PDF s poškozenou textovou vrstvou.

## Právní poznámka

Insolvenční rejstřík je veřejně přístupný informační systém veřejné správy (§ 419 a násl.
insolvenčního zákona); každý má právo do něj nahlížet a pořizovat kopie a výpisy. Tento software
není produktem Ministerstva spravedlnosti. Uživatel odpovídá za dodržení Podmínek provozu ISIR
a za nakládání s osobními údaji získanými z rejstříku.

## Licence

MIT – viz [LICENSE](LICENSE).
