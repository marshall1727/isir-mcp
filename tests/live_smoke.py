r"""Živý test proti ISIR (vyžaduje internet, ~6 požadavků). Spuštění:
    .\.venv\Scripts\python tests\live_smoke.py
"""
from isir_mcp import detail as D
from isir_mcp import documents as DOC
from isir_mcp import ws as WS
from isir_mcp.client import HTTP

print("1) lustrace podle spisové značky INS 1000/2024")
res = WS.lustrace(WS.LustraceParams(spisova_znacka="INS 1000/2024", max_vysledku=5))
assert res["vysledky"], res
v = res["vysledky"][0]
print("   ->", v["spisovaZnacka"], v.get("nazevOrganizace"), v.get("druhStavKonkursu"), v["detailId"])

print("2) detail řízení")
det = D.detail_rizeni(v["detailId"])
print("   ->", det.get("dluznik"), "|", det.get("stav"), "|", det.get("spisova_znacka"))
print("   oddíly:", {k: o["celkem_udalosti"] for k, o in det["oddily"].items()})

print("3) události oddílu B")
sec = D.udalosti_oddilu(v["detailId"], "B")
assert sec["vse_nacteno"], sec["celkem"]
print(f"   -> {len(sec['udalosti'])} událostí; první: {sec['udalosti'][0]['oznaceni']} {sec['udalosti'][0]['popis']}")
doc = next((e["dokument"] for e in sec["udalosti"] if e.get("dokument") and e["dokument"].get("id")), None)
assert doc, "žádný dokument v oddílu B"

print(f"4) text dokumentu {doc['id']}")
text, meta = DOC.ziskat_text(doc["id"], "auto")
print("   ->", meta.stran, "stran, zdroj:", meta.text_zdroj, "OCR stran:", meta.ocr_stran, "chyba:", meta.chyba)
print("   ", text[:300].replace("\n", " "))

print("5) poslední ID toku událostí:", WS.posledni_id_udalosti())
print("limity:", HTTP.limiter.stats())
print("OK")
