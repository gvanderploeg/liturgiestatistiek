"""De zoekfunctie gebruikt een voorselectie om snel te zijn. Deze test vergelijkt haar
met de volledige doorloop van de hele catalogus, voor echte titels en liturgieregels."""

import random
from pathlib import Path

import pytest
from rapidfuzz import process

from liturgiestatistiek.catalogus import Catalogus
from liturgiestatistiek.koppeling import DREMPEL_KANDIDAAT, Kandidaat, Zoekindex, titelscore
from liturgiestatistiek.tekst import normaliseer

PROJECT = Path(__file__).resolve().parents[1]


def volledig_zoeken(index: Zoekindex, titel: str, voorkeur, limiet: int) -> list[Kandidaat]:
    """De zoekfunctie zoals die was voor de voorselectie: titelscore tegen elke term."""
    vraag = normaliseer(titel)
    treffers = process.extract(vraag, index.teksten, scorer=titelscore, limit=limiet * 3, score_cutoff=DREMPEL_KANDIDAAT - 5)
    beste: dict[str, int] = {}
    for _tekst, score, i in treffers:
        lied_id = index.lied_ids[i]
        score = int(score)
        if voorkeur and not index._uit_bundel(index.catalogus.liederen[lied_id], voorkeur):
            score -= 2
        if score > beste.get(lied_id, 0):
            beste[lied_id] = score
    gesorteerd = sorted(beste.items(), key=lambda kv: -kv[1])[:limiet]
    return [Kandidaat(l, index.catalogus.liederen[l].titel, s) for l, s in gesorteerd if s >= DREMPEL_KANDIDAAT]


def vragen(catalogus: Catalogus) -> list[str]:
    rnd = random.Random(7)
    liederen = list(catalogus.liederen.values())
    titels = [l.titel for l in rnd.sample(liederen, min(120, len(liederen)))]
    regels = [
        "Heer, wijs mij uw weg",
        "Ik wens jou",
        "Vul dit huis met glorie",
        "De aarde is met al wat leeft",
        "Wij blijven geloven dat onder miljoenen",
        "Once in royal David's city",
        "Gods zegen voor jou",
        "Groot is uw trouw o Heer",
        "Heilig heilig heilig",
        "Jezus overwinnaar",
        "U nodigt mij aan tafel",
        "Hier in uw heiligdom",
        "Spreek o Heer door uw heilig woord",
        "Lam van God dat de zonde der wereld draagt",
        "Psalm",
        "Heer",
    ]
    verminkt = [t[: max(4, len(t) * 2 // 3)] for t in titels[:30]]
    return titels + regels + verminkt


@pytest.fixture(scope="module")
def index():
    return Zoekindex(Catalogus.laad(PROJECT / "data"))


def test_voorselectie_geeft_dezelfde_kandidaten(index):
    verschillen = []
    for vraag in vragen(index.catalogus):
        for voorkeur, limiet in (((), 5), (("sela",), 5), (None, 3), (None, 1)):
            snel = index.zoek(vraag, voorkeur, limiet)
            traag = volledig_zoeken(index, vraag, voorkeur, limiet)
            if [(k.lied, k.score) for k in snel] != [(k.lied, k.score) for k in traag]:
                verschillen.append((vraag, voorkeur, limiet, snel, traag))
    assert not verschillen, verschillen[:3]


def test_geheugen_geeft_een_kopie(index):
    eerste = index.zoek("Heer, wijs mij uw weg")
    eerste.clear()
    assert index.zoek("Heer, wijs mij uw weg"), "het onthouden resultaat mag niet via een eerdere uitkomst leeglopen"
