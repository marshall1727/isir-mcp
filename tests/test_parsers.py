from pathlib import Path

import pytest

from isir_mcp import detail as D
from isir_mcp import documents as DOC
from isir_mcp import ws as WS

FIX = Path(__file__).parent / "fixtures"
HTML = (FIX / "detail_sample.html").read_text("utf-8")


def test_spisova_znacka():
    sz = WS.parse_spisova_znacka("KSOS 37 INS 1000/2024")
    assert sz == {"soud": "KSOS", "senat": 37, "druh": "INS", "bc": 1000, "rok": 2024}
    sz = WS.parse_spisova_znacka("INS 1000 / 2024")
    assert sz["soud"] is None and sz["senat"] is None and sz["bc"] == 1000
    with pytest.raises(ValueError):
        WS.parse_spisova_znacka("1000/2024")


def test_hlavicka():
    h = D.parse_hlavicka(HTML)
    assert h["dluznik"] == "Josef Vzorek"
    assert h["stav"].startswith("Odškrtnutá")
    assert h["spisova_znacka"] == "KSOS 37 INS 1000/2024"
    assert h["soud"] == "Krajského soudu v Ostravě"
    assert h["insolvencni_spravce"].startswith("Mgr. Jan Správce")
    assert h["posledni_udalost"] == "12.03.2026 (B-23)"
    assert h["konec_lhuty_prihlasek"] == "06.05.2024"
    assert h["datum_skonceni"] == "30.01.2026"
    assert h["bydliste"].startswith("Vzorov")


def test_oddil_A():
    sec = D.parse_oddil(HTML, "A")
    assert sec["celkem"] == 2 and sec["stranek"] == 1
    ev = sec["udalosti"]
    assert len(ev) == 2
    assert ev[0]["oznaceni"] == "A-1"
    assert ev[0]["dokument"] == {"id": None, "poznamka": "není k dispozici"}
    assert ev[0]["typ_udalosti"] == ["I_6"]
    assert ev[1]["dokument"]["id"] == "57086078"
    assert ev[1]["dokument"]["velikost_kb"] == 237
    assert ev[1]["vedlejsi_dokument"] is None


def test_oddil_B_vice_polozek_a_strankovani():
    sec = D.parse_oddil(HTML, "B")
    assert sec["celkem"] == 508 and sec["zobrazeno"] == [1, 150] and sec["stranek"] == 4
    ev = sec["udalosti"][0]
    assert ev["oznaceni"] == "B-7"
    assert len(ev["popis"]) == 2
    assert ev["typ_udalosti"] == ["I_1038", "I_1065"]
    assert ev["dokument"]["id"] == "58657721"
    assert ev["vedlejsi_dokument"]["id"] == "58668510"
    assert ev["pravni_moc"] == ["24.06.2024", "10.07.2024"]


def test_oddil_P():
    sec = D.parse_oddil(HTML, "P")
    ev = sec["udalosti"][0]
    assert ev["oznaceni"] == "P1-1" and ev["prihlaska"] == "P1"
    assert ev["platni_veritele"] == ["Okresní soud v Karviné"]
    assert ev["vedlejsi_dokument"]["id"] == "57623563"


def test_oddil_chybi():
    sec = D.parse_oddil(HTML, "C")
    assert sec["udalosti"] == [] and sec["celkem"] is None


def test_strany_textu():
    text = "----- strana 1 -----\nA\n----- strana 2 -----\nB\n----- strana 3 -----\nC"
    assert DOC.strany_textu(text, 2, 2).strip() == "----- strana 2 -----\nB"
    assert DOC.strany_textu(text, 2, None).count("strana") == 2
    assert DOC.strany_textu(text, None, None) == text


def test_lustrace_request_xml(monkeypatch):
    sent = {}

    class FakeHttp:
        class cfg:
            ws_cuzk_url = "x"

        def soap(self, url, body, ns):
            sent["body"] = body
            return (
                "<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'><soap:Body>"
                "<ns2:getIsirWsCuzkDataResponse xmlns:ns2='http://isirws.cca.cz/types/'>"
                "<data><ic>26863154</ic><cisloSenatu>25</cisloSenatu><druhVec>INS</druhVec><bcVec>10525</bcVec>"
                "<rocnik>2016</rocnik><nazevOrganizace>Krajský soud v Ostravě</nazevOrganizace>"
                "<nazevOsoby>Firma a.s.</nazevOsoby><druhStavKonkursu>REORGANIZ</druhStavKonkursu>"
                "<urlDetailRizeni>https://isir.justice.cz/isir/ueu/evidence_upadcu_detail.do?id=3BD92F3EAA724B37ACCEDD86B31BE055</urlDetailRizeni>"
                "</data><stav><pocetVysledku>1</pocetVysledku><relevanceVysledku>2</relevanceVysledku></stav>"
                "</ns2:getIsirWsCuzkDataResponse></soap:Body></soap:Envelope>"
            )

    res = WS.lustrace(WS.LustraceParams(spisova_znacka="KSOS 25 INS 10525/2016", jen_aktualni=True), FakeHttp())
    assert "<druhVec>INS</druhVec><bcVec>10525</bcVec><rocnik>2016</rocnik>" in sent["body"]
    assert "<filtrAktualniRizeni>T</filtrAktualniRizeni>" in sent["body"]
    assert "typ:" not in sent["body"].split(">", 1)[1].split("</typ:")[0]  # vnitřní elementy bez prefixu
    v = res["vysledky"][0]
    assert v["detailId"] == "3BD92F3EAA724B37ACCEDD86B31BE055"
    assert v["spisovaZnacka"] == "25 INS 10525/2016"
    assert res["stav"]["pocetVysledku"] == "1"


def test_soap_fault():
    class FakeHttp:
        class cfg:
            ws_cuzk_url = "x"

        def soap(self, url, body, ns):
            return ("<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'><soap:Body>"
                    "<soap:Fault><faultcode>soap:Client</faultcode><faultstring>Data nejsou validní</faultstring>"
                    "</soap:Fault></soap:Body></soap:Envelope>")

    with pytest.raises(RuntimeError, match="Data nejsou validní"):
        WS.lustrace(WS.LustraceParams(ic="1"), FakeHttp())


def test_poznamka_parse():
    pozn = ("&lt;?xml version=\"1.0\"?>&lt;ns2:udalost xmlns:ns2=\"http://www.cca.cz/isir/poznamka\">"
            "&lt;idOsobyPuvodce>KSZPCPM&lt;/idOsobyPuvodce>&lt;osoba>&lt;nazevOsoby>Simfina a.s.&lt;/nazevOsoby>"
            "&lt;ic>24823546&lt;/ic>&lt;/osoba>&lt;/ns2:udalost>")
    obj = WS._parse_poznamka(pozn)
    assert obj["idOsobyPuvodce"] == "KSZPCPM"
    assert obj["osoba"]["ic"] == "24823546"
