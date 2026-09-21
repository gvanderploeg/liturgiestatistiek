"""Koppelt een ontlede liedregel aan een lied uit de catalogus, of levert
een voorstel en kandidaten op voor de wachtrij.

Bundelverwijzingen zijn een harde sleutel. Titels worden tolerant
vergeleken: woordvolgorde en leestekens tellen niet, en een titel die
letterlijk in een langere eerste regel voorkomt telt als gelijk. Een
enkele misser is acceptabel; de wachtrij en de aliassen vangen die op."""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .catalogus import Catalogus
from .modellen import Kandidaat, Lied, Referentie
from .ontleding import Ontleding
from .opslag import Aliassen
from .tekst import normaliseer, slug

DREMPEL_AUTOMATISCH = 88
DREMPEL_ZEKER = 95
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
    titel_gebruikt: bool = False

    @property
    def genegeerd(self) -> bool:
        return self.herkenning == NEGEER


def titelscore(vraag: str, doel: str, **_: object) -> int:
    """Vergelijkt twee genormaliseerde titels."""
    score = int(fuzz.token_sort_ratio(vraag, doel))
    kort, lang = sorted((vraag, doel), key=len)
    woorden_kort = set(kort.split())
    if len(woorden_kort) >= 3 and kort in lang:
        score = max(score, 95)
    elif len(woorden_kort) >= 3 and woorden_kort <= set(lang.split()):
        score = max(score, 90)
    return score


class Zoekindex:
    def __init__(self, catalogus: Catalogus):
        self.catalogus = catalogus
        termen = catalogus.zoektermen()
        self.teksten = [t for t, _ in termen]
        self.lied_ids = [i for _, i in termen]

    def zoek(self, titel: str, voorkeur: list[str] = (), limiet: int = 5) -> list[Kandidaat]:
        """Kandidaten voor een titelfragment. Noemt de regel een bundel zonder
        nummer (voorkeur, bundelcodes), dan krijgen liederen buiten die bundel een
        klein streepje tegen; zo wint bij gelijke titel de Sela-versie van de Opwekking-versie."""
        if not self.teksten:
            return []
        vraag = normaliseer(titel)
        treffers = process.extract(vraag, self.teksten, scorer=titelscore, limit=limiet * 3, score_cutoff=DREMPEL_KANDIDAAT - 5)
        beste: dict[str, int] = {}
        for _tekst, score, index in treffers:
            lied_id = self.lied_ids[index]
            score = int(score)
            if voorkeur and not self._uit_bundel(self.catalogus.liederen[lied_id], voorkeur):
                score -= 2
            if score > beste.get(lied_id, 0):
                beste[lied_id] = score
        gesorteerd = sorted(beste.items(), key=lambda kv: -kv[1])[:limiet]
        return [Kandidaat(lied_id, self.catalogus.liederen[lied_id].titel, score) for lied_id, score in gesorteerd if score >= DREMPEL_KANDIDAAT]

    def _uit_bundel(self, lied: Lied, codes: list[str]) -> bool:
        namen = {normaliseer(self.catalogus.bundels[c].naam) for c in codes if c in self.catalogus.bundels}
        if lied.artiest and normaliseer(lied.artiest) in namen:
            return True
        return any(r.bundel in codes for r in lied.referenties)


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
            kandidaten = sorted((Kandidaat(l.id, l.titel, _titelscore(ontl, l)) for l in liederen), key=lambda k: -k.score)
            if ontl.titels and kandidaten[0].score >= 70 and (len(kandidaten) == 1 or kandidaten[0].score - kandidaten[1].score >= 15):
                return Koppeling(kandidaten[0].lied, "automatisch", f"referentie {ref.bundel} {ref.nummer} met titel", titel_gebruikt=True)
            return Koppeling(None, "onbekend", f"referentie {ref.bundel} {ref.nummer} past op meerdere liederen", kandidaten=kandidaten)

    kandidaten = _zoek_titels(ontl, index)
    psalmberijming = any(catalogus.bundels[r.bundel].psalmen for r in ontl.referenties)
    if not psalmberijming and _duidelijke_winnaar(kandidaten, DREMPEL_ZEKER):
        lied = catalogus.liederen[kandidaten[0].lied]
        nieuw = [r for r in ontl.referenties if not any(b.bundel == r.bundel and b.nummer == r.nummer for b in lied.referenties)]
        return Koppeling(lied.id, "automatisch", f"titel is {lied.titel}; referentie toegevoegd aan catalogus", kandidaten=kandidaten[:3], geleerde_referenties=nieuw, titel_gebruikt=True)
    return Koppeling(None, "onbekend", "referentie niet in de catalogus", kandidaten=kandidaten[:3], voorstel=_voorstel_nieuw(ontl, catalogus))


def _via_titel(ontl: Ontleding, catalogus: Catalogus, index: Zoekindex) -> Koppeling:
    kandidaten = _zoek_titels(ontl, index)
    if _duidelijke_winnaar(kandidaten, DREMPEL_AUTOMATISCH):
        return Koppeling(kandidaten[0].lied, "automatisch", f"titel lijkt op {kandidaten[0].titel} ({kandidaten[0].score})", kandidaten=kandidaten[:3])
    return Koppeling(None, "onbekend", "geen lied met deze titel in de catalogus", kandidaten=kandidaten[:3], voorstel=_voorstel_nieuw(ontl, catalogus))


def _duidelijke_winnaar(kandidaten: list[Kandidaat], drempel: int) -> bool:
    return bool(kandidaten) and kandidaten[0].score >= drempel and (len(kandidaten) == 1 or kandidaten[0].score > kandidaten[1].score)


def _zoek_titels(ontl: Ontleding, index: Zoekindex) -> list[Kandidaat]:
    alle: dict[str, Kandidaat] = {}
    for titel in ontl.titels:
        for k in index.zoek(titel, ontl.bundels):
            if k.lied not in alle or k.score > alle[k.lied].score:
                alle[k.lied] = k
    return sorted(alle.values(), key=lambda k: -k.score)


def _titelscore(ontl: Ontleding, lied: Lied) -> int:
    if not ontl.titels:
        return 0
    doelen = [normaliseer(t) for t in [lied.titel, lied.eerste_regel, *lied.aliassen] if t]
    return max(titelscore(normaliseer(titel), doel) for titel in ontl.titels for doel in doelen)


def _voorstel_nieuw(ontl: Ontleding, catalogus: Catalogus, ruw: str = "") -> dict:
    """Voorstel voor een nieuw catalogus-lied.

    Met bundelverwijzing is het langste fragment de titel (de rest is meestal
    couplet- of bronvermelding). Zonder verwijzing wordt de hele opgeschoonde
    regel de titel, in de volgorde van de liturgie, zodat de artiest erin blijft
    ("Geen afstand - Eline Bakker"); het langste fragment gaat mee als alias."""
    langste = max(ontl.titels, key=len) if ontl.titels else ""
    aliassen: list[str] = []
    if ontl.referenties:
        ref = ontl.referenties[0]
        bundel = catalogus.bundels[ref.bundel]
        titel = langste
        basis = f"{ref.bundel}-{ref.nummer}"
        if bundel.psalmen and titel:
            basis = f"{ref.bundel}-{ref.nummer}-{slug(' '.join(titel.split()[:5]))}"
        if not titel:
            titel = f"{bundel.naam} {ref.nummer}"
        bron = "referentie"
    else:
        titel = " - ".join(ontl.titels) if ontl.titels else ruw
        if langste and langste != titel:
            aliassen.append(langste)
        basis = titel
        bron = "titel"
    nieuw: dict = {"id": catalogus.vrij_id(basis), "titel": titel}
    if aliassen:
        nieuw["aliassen"] = aliassen
    if ontl.bundels:
        nieuw["artiest"] = catalogus.bundels[ontl.bundels[0]].naam
    if ontl.referenties:
        nieuw["referenties"] = [r.as_dict() for r in ontl.referenties]
    return {"bron": bron, "nieuw": nieuw}
