"""Koppelt een ontlede liedregel aan een lied uit de catalogus, of levert
een voorstel en kandidaten op voor de wachtrij."""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .catalogus import Catalogus
from .modellen import Kandidaat, Lied, Referentie
from .ontleding import Ontleding
from .opslag import Aliassen
from .tekst import normaliseer, slug

DREMPEL_AUTOMATISCH = 90
DREMPEL_ZEKER = 96
DREMPEL_KANDIDAAT = 60
NEGEER = "negeer"


@dataclass
class Koppeling:
    lied: str | None
    herkenning: str
    reden: str = ""
    kandidaten: list[Kandidaat] = field(default_factory=list)
    voorstel: dict = field(default_factory=dict)
    geleerde_referenties: list[Referentie] = field(default_factory=list)

    @property
    def genegeerd(self) -> bool:
        return self.herkenning == NEGEER


def titelscore(vraag: str, doel: str, **_: object) -> int:
    """Vergelijkt twee genormaliseerde titels. Een titel van minstens drie
    woorden die letterlijk in de andere voorkomt (titel tegenover eerste
    regel) scoort hoog; verder telt alleen de gesorteerde woordvergelijking,
    zodat korte catalogustitels niet overal 'in passen'."""
    score = int(fuzz.token_sort_ratio(vraag, doel))
    kort, lang = sorted((vraag, doel), key=len)
    if len(kort.split()) >= 3 and kort in lang:
        score = max(score, 95)
    return score


class Zoekindex:
    def __init__(self, catalogus: Catalogus):
        self.catalogus = catalogus
        termen = catalogus.zoektermen()
        self.teksten = [t for t, _ in termen]
        self.lied_ids = [i for _, i in termen]

    def zoek(self, titel: str, artiest: str | None, limiet: int = 5) -> list[Kandidaat]:
        if not self.teksten:
            return []
        vraag = normaliseer(titel)
        treffers = process.extract(vraag, self.teksten, scorer=titelscore, limit=limiet * 3, score_cutoff=DREMPEL_KANDIDAAT - 5)
        beste: dict[str, int] = {}
        for _tekst, score, index in treffers:
            lied_id = self.lied_ids[index]
            lied = self.catalogus.liederen[lied_id]
            score = int(score)
            if artiest and not (lied.artiest and normaliseer(lied.artiest) == normaliseer(artiest)):
                score -= 3
            if score > beste.get(lied_id, 0):
                beste[lied_id] = score
        gesorteerd = sorted(beste.items(), key=lambda kv: -kv[1])[:limiet]
        return [Kandidaat(lied_id, self.catalogus.liederen[lied_id].titel, score) for lied_id, score in gesorteerd if score >= DREMPEL_KANDIDAAT]


def koppel(ruw: str, ontl: Ontleding, catalogus: Catalogus, aliassen: Aliassen, index: Zoekindex) -> Koppeling:
    via_alias = aliassen.vermeldingen.get(normaliseer(ruw))
    if via_alias == NEGEER:
        return Koppeling(None, NEGEER, "door beheerder gemarkeerd als geen lied")
    if via_alias:
        if via_alias in catalogus.liederen:
            return Koppeling(via_alias, "handmatig", "alias van beheerder")
        return Koppeling(None, "onbekend", f"alias verwijst naar onbekend lied {via_alias}")

    if ontl.referenties:
        return _via_referenties(ontl, catalogus, index)
    if ontl.titels:
        return _via_titel(ontl, catalogus, index)
    return Koppeling(None, "onbekend", "geen bundelverwijzing en geen titel herkend", voorstel=_voorstel_nieuw(ontl, catalogus, ruw))


def _via_referenties(ontl: Ontleding, catalogus: Catalogus, index: Zoekindex) -> Koppeling:
    for ref in ontl.referenties:
        liederen = catalogus.op_referentie(ref)
        if len(liederen) == 1:
            return Koppeling(liederen[0].id, "automatisch", f"referentie {ref.bundel} {ref.nummer}")
        if len(liederen) > 1:
            kandidaten = [Kandidaat(l.id, l.titel, _titelscore(ontl, l)) for l in liederen]
            kandidaten.sort(key=lambda k: -k.score)
            if ontl.titels and kandidaten[0].score >= 70 and (len(kandidaten) == 1 or kandidaten[0].score - kandidaten[1].score >= 15):
                return Koppeling(kandidaten[0].lied, "automatisch", f"referentie {ref.bundel} {ref.nummer} met titel")
            return Koppeling(None, "onbekend", f"referentie {ref.bundel} {ref.nummer} past op meerdere liederen", kandidaten=kandidaten)

    kandidaten = _zoek_titels(ontl, index)
    psalmberijming = any(catalogus.bundels[r.bundel].psalmen for r in ontl.referenties)
    if not psalmberijming and kandidaten and kandidaten[0].score >= DREMPEL_ZEKER and (len(kandidaten) == 1 or kandidaten[0].score > kandidaten[1].score):
        lied = catalogus.liederen[kandidaten[0].lied]
        nieuw = [r for r in ontl.referenties if not any(b.bundel == r.bundel and b.nummer == r.nummer for b in lied.referenties)]
        return Koppeling(lied.id, "automatisch", f"titel is {lied.titel}; referentie toegevoegd aan catalogus", kandidaten=kandidaten[:3], geleerde_referenties=nieuw)
    return Koppeling(
        None,
        "onbekend",
        "referentie niet in de catalogus",
        kandidaten=kandidaten[:3],
        voorstel=_voorstel_nieuw(ontl, catalogus),
    )


def _zoek_titels(ontl: Ontleding, index: Zoekindex) -> list[Kandidaat]:
    alle: dict[str, Kandidaat] = {}
    for titel in ontl.titels:
        for k in index.zoek(titel, ontl.artiest):
            if k.lied not in alle or k.score > alle[k.lied].score:
                alle[k.lied] = k
    return sorted(alle.values(), key=lambda k: -k.score)


def _titelscore(ontl: Ontleding, lied: Lied) -> int:
    if not ontl.titels:
        return 0
    doelen = [normaliseer(t) for t in [lied.titel, lied.eerste_regel, *lied.aliassen] if t]
    return max(titelscore(normaliseer(titel), doel) for titel in ontl.titels for doel in doelen)


def _via_titel(ontl: Ontleding, catalogus: Catalogus, index: Zoekindex) -> Koppeling:
    kandidaten = _zoek_titels(ontl, index)
    if kandidaten and kandidaten[0].score >= DREMPEL_AUTOMATISCH and (len(kandidaten) == 1 or kandidaten[0].score > kandidaten[1].score):
        return Koppeling(kandidaten[0].lied, "automatisch", f"titel lijkt op {kandidaten[0].titel} ({kandidaten[0].score})", kandidaten=kandidaten[:3])
    return Koppeling(None, "onbekend", "geen lied met deze titel in de catalogus", kandidaten=kandidaten[:3], voorstel=_voorstel_nieuw(ontl, catalogus))


def _voorstel_nieuw(ontl: Ontleding, catalogus: Catalogus, ruw: str = "") -> dict:
    titel = max(ontl.titels, key=len) if ontl.titels else ""
    if ontl.referenties:
        ref = ontl.referenties[0]
        bundel = catalogus.bundels[ref.bundel]
        basis = f"{ref.bundel}-{ref.nummer}"
        if bundel.psalmen and titel:
            basis = f"{ref.bundel}-{ref.nummer}-{slug(' '.join(titel.split()[:5]))}"
        if not titel:
            titel = f"{bundel.naam} {ref.nummer}"
        bron = "referentie"
    else:
        basis = f"{ontl.artiest} {titel}" if ontl.artiest else (titel or ruw)
        bron = "titel"
    nieuw = {"id": catalogus.vrij_id(basis), "titel": titel, "artiest": ontl.artiest}
    if ontl.referenties:
        nieuw["referenties"] = [r.as_dict() for r in ontl.referenties]
    return {"bron": bron, "nieuw": nieuw}
