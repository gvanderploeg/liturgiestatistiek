from datetime import date
from pathlib import Path

import pytest

from liturgiestatistiek.catalogus import Catalogus
from liturgiestatistiek.ontleding import (
    bepaal_datum,
    bepaal_moment,
    herken_kenmerken,
    is_kandidaatrij,
    is_liedrij,
    normaliseer_begeleiding,
    ontleed,
)

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalogus():
    return Catalogus.laad(PROJECT / "data")


def refs(ontl):
    return [(r.bundel, r.nummer) for r in ontl.referenties]


@pytest.mark.parametrize(
    "inhoud, verwacht_refs, verwacht_titel",
    [
        ("Opwekking 815 (Vul dit huis met glorie)", [("opw", "815")], "Vul dit huis met glorie"),
        ("Witter dan sneeuw (Opw 811)", [("opw", "811")], "Witter dan sneeuw"),
        ("Opwekking 623 -Laat het huis gevuld zijn..", [("opw", "623")], "Laat het huis gevuld zijn"),
        ("Opw. 220/JdH197 Volle verzeek’ring Jezus is mijn", [("opw", "220"), ("jdh", "197")], "Volle verzeek'ring Jezus is mijn"),
        ("LB 870:1, 3, 4, 8 Heilige God, geprezen zij", [("nlb", "870")], "Heilige God, geprezen zij"),
        ("Liedboek_2013 lied 912 vers 1, 2, 4 en 6. Neem mijn leven, laat het Heer", [("nlb", "912")], "Neem mijn leven, laat het Heer"),
        ("NLB 413 vers 1,2 en 3 Grote God, wij loven U", [("nlb", "413")], "Grote God, wij loven U"),
        ("LB 51b create in me", [("nlb", "51b")], "create in me"),
        ("Psalm 24:1 DNP De aarde is met al wat leeft", [("dnp", "24")], "De aarde is met al wat leeft"),
        ("DNP psalm 133 vers 1 en 2 ‘Wat is het goed’", [("dnp", "133")], "Wat is het goed"),
        ("De Nieuwe Psalmberijming, psalm 25: 2, 4, 8", [("dnp", "25")], None),
        ("Psalm 119:40 uit de berijming van het GKV Kerkboek 2017*", [("gkb", "119")], None),
        ("Psalm 103, The Psalm Project", [("tpp", "103")], None),
        ("Loof de Heer zijn ziel (Psalm Project 103)", [("tpp", "103")], "Loof de Heer zijn ziel"),
        ("The psalm project, gebed om hulp, psalm 86.", [("tpp", "86")], "gebed om hulp"),
        ("E&R2, 423 (Heer, U bent mijn leven)", [("er2", "423")], "Heer, U bent mijn leven"),
        ("E&R liedbundel 2, 439: 4 coupletten (Wij blijven geloven dat onder miljoenen)", [("er2", "439")], "Wij blijven geloven dat onder miljoenen"),
        ("OK4kids 74 (Een wijs man bouwde zijn huis)", [("opwkids", "74")], "Een wijs man bouwde zijn huis"),
        ("Opwekking kids 233 (God heeft een plan met je leven)", [("opwkids", "233")], "God heeft een plan met je leven"),
        ("Ar126 Ashwa lilbaraka (Verlangen naar de zegen)", [("ar", "126")], "Ashwa lilbaraka"),
        ("Doop (sela, Hemelhoog 502))", [("hh", "502")], "Doop"),
        ("Opwekking 797 (Sela – Breng ons samen)", [("opw", "797")], "Breng ons samen"),
        ("Meer dan een wonder – Kinga Ban", [], "Meer dan een wonder"),
        ("Sela: Breng ons samen", [], "Breng ons samen"),
        ("Geen afstand- Eline Bakker", [], "Geen afstand"),
        ("Holy forever van Chris Tomlin – met tekst op Powerpoint", [], "Holy forever"),
        ("zingen (als amen) Vervuld van uw zegen (NLB 425)", [("nlb", "425")], "Vervuld van uw zegen"),
        ("zingen: Ga met God en Hij zal met je zijn (NLB)", [], "Ga met God en Hij zal met je zijn"),
        ("Opwekking 797 (U roept ons samen) (https://nederlandzingt.eo.nl/lied/breng-ons-samen-1)", [("opw", "797")], "U roept ons samen"),
        ("Run to the father", [], "Run to the father"),
    ],
)
def test_ontleed(catalogus, inhoud, verwacht_refs, verwacht_titel):
    ontl = ontleed(inhoud, catalogus)
    assert refs(ontl) == verwacht_refs
    if verwacht_titel is not None:
        assert any(t.lower().startswith(verwacht_titel.lower()) for t in ontl.titels), ontl.titels
    assert not any(t.lower() in ("nlb", "sela", "dnp") for t in ontl.titels)


def test_bundel_zonder_nummer_wordt_voorkeur(catalogus):
    assert ontleed("Sela: Breng ons samen", catalogus).bundels == ["sela"]
    assert ontleed("zingen: Ga met God (NLB)", catalogus).bundels == ["nlb"]
    assert ontleed("Opwekking 815", catalogus).bundels == []


def test_ontleed_hints(catalogus):
    assert "luisterlied" in ontleed("Flowers (Luisterlied)", catalogus).hints
    assert "refrein" in ontleed("Opwekking 849 - refrein", catalogus).hints
    assert "kindmoment" in ontleed("Kindlied - We are one", catalogus).hints


@pytest.mark.parametrize(
    "label, inhoud, verwacht",
    [
        ("Lied 1", "Opwekking 815", True),
        ("Lied 4 (dooplied)", "Doop", True),
        ("Zegen > Lied 7", "Vervuld van uw zegen", True),
        ("Geloofsbelijdenis = Lied 5", "We believe", True),
        ("Collecten Collectelied", "Burn the Ships", True),
        ("Lied 6", "", False),
        ("Kindmoment", "Iemand met kinderlied", False),
        ("Votum en groet (gesproken, gezongen of Sela/Psalm 121/…)", "Voorganger", False),
        ("Geloofsbelijdenis gezongen", "Opwekking 575", False),
    ],
)
def test_is_liedrij(label, inhoud, verwacht):
    assert is_liedrij(label, inhoud) is verwacht


@pytest.mark.parametrize(
    "inhoud, verwacht",
    [
        ("Opwekking 575 Jezus alleen", True),
        ('beginnen met "Votum en groet" van Sela', True),
        ("Iemand met kinderlied ??", True),
        ("Voorganger", False),
        ("1&2 en 5&6", False),
        ("", False),
    ],
)
def test_is_kandidaatrij(catalogus, inhoud, verwacht):
    assert is_kandidaatrij(inhoud, catalogus) is verwacht


@pytest.mark.parametrize(
    "label, inhoud, vorig, eerste, verwacht",
    [
        ("Lied 1", "Opwekking 815", "Welkom", True, "aanvang"),
        ("Votum en groet = Lied 1", "Onze hulp", "Welkom", True, "aanvang"),
        ("Lied 1 (votum)", "Opwekking 847", "Welkom", True, "aanvang"),
        ("Lied 3 (kinderlied)", "Opwekking kids 233", "Leefregel", False, "kindmoment"),
        ("Lied 4 - kinderlied", "OK4kids 74", "Gebed", False, "kindmoment"),
        ("Lied 2", "Ik wens jou", "Kindmoment", False, "kindmoment"),
        ("Lied 3", "Kindlied - We are one", "Gebed", False, "kindmoment"),
        ("Zegen > Lied 7", "Vervuld van uw zegen", "Kinderen komen terug", False, "zegenlied"),
        ("Lied 7 - uitlooplied", "Jesus be the name", "Zegen", False, "zegenlied"),
        ("Lied 9", "Opwekking 849 - refrein", "Zegen", False, "zegenlied"),
        ("Inleiding op de Zegen > Lied 6", "Opwekking 710", "Gebed", False, "zegenlied"),
        ("Lied 7 (Luisterlied door de band)", "No longer slaves", "Zegen", False, "luisterlied"),
        ("Lied 2", "Flowers (Luisterlied)", "Bijbellezing", False, "luisterlied"),
        ("Lied 4 (dooplied)", "Doop", "Doop", False, None),
        ("Lied 3", "Meer dan een wonder", "Preek", False, None),
    ],
)
def test_bepaal_moment(label, inhoud, vorig, eerste, verwacht):
    assert bepaal_moment(label, inhoud, vorig, eerste) == verwacht


def test_bepaal_datum():
    assert bepaal_datum("zondag 31 mei 2026", "20260531 Eredienst Westerkerk.pdf") == (date(2026, 5, 31), date(2026, 5, 31))
    assert bepaal_datum("21 juni 2026", "x.pdf") == (date(2026, 6, 21), None)
    assert bepaal_datum("", "Eredienst Westerkerk 24 mei 2026 -.pdf") == (None, date(2026, 5, 24))


def test_herken_kenmerken():
    cfg = {"doop": ["doop", "doopzondag"], "bevestiging": ["bevestiging"], "belijdenis": ["belijdenis", "belijdenisdienst"]}
    assert herken_kenmerken("Doopzondag", cfg) == (["doop"], [])
    assert herken_kenmerken("1e Belijdenisdienst", cfg) == (["belijdenis"], [])
    assert herken_kenmerken("-", cfg) == ([], [])
    codes, rest = herken_kenmerken("Doop Jan Jansen en Piet Pietersen, bevestiging diakenen", cfg)
    assert codes == ["doop", "bevestiging"]
    assert "jansen" in rest and "diakenen" in rest


def test_normaliseer_begeleiding():
    assert normaliseer_begeleiding("Band") == "band"
    assert normaliseer_begeleiding("Orgel/Piano") == "orgel piano"
    assert normaliseer_begeleiding("-") == "geen"
    assert normaliseer_begeleiding("") == "geen"
