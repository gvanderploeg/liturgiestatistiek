"""Ontleedt de tekst van liturgierijen: welke rijen zijn liederen, welke
bundelverwijzingen en titelfragmenten staan erin, op welk moment in de
dienst, en wat zeggen datum en bijzonderheden.

De ontleding is bewust ruim: bundelverwijzingen worden precies herkend,
de rest van de tekst wordt grof opgeknipt in fragmenten die de koppeling
tolerant vergelijkt met de catalogus. Wat misgaat vangt de wachtrij op,
en een besluit daar wordt een alias die het de volgende keer goed doet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .catalogus import Catalogus
from .modellen import Referentie
from .tekst import eenvoudig, normaliseer

LIED_LABEL = re.compile(r"lied\b|^zingen\b", re.IGNORECASE)
MEERDERE_LABEL = re.compile(r"\d+\s*(en|&|,)\s*\d+", re.IGNORECASE)
LIEDWOORDEN = re.compile(r"lied\b|\bzingen\b|\bgezongen\b", re.IGNORECASE)

RUIS_PREFIX = re.compile(r"^(zingen|zingend|zang|beginnen met)\s*(\([^)]*\))?\s*:?\s*", re.IGNORECASE)
KINDLIED_PREFIX = re.compile(r"^(kindlied|kinderlied)\s*\d*\s*[-:]\s*", re.IGNORECASE)
URL = re.compile(r"\(\s*https?://[^)]*\)?|https?://\S+", re.IGNORECASE)
HINTWOORDEN = {
    "luisterlied": re.compile(r"\bluisterlied\b", re.IGNORECASE),
    "refrein": re.compile(r"\brefrein\b", re.IGNORECASE),
}
GETALLEN = re.compile(r"\d+([.,:/]\s*\d+)*")
VULWOORDEN = re.compile(r"\b(vers|verzen|couplet|coupletten|allen|vrouwen|mannen|solo|samenzang|gemeente|koor|band|t/m|o\.a\.|ook in|tweetalig|origineel|facultatief)\b", re.IGNORECASE)
SCHEIDERS = re.compile(r"\s+[-–:/]\s+|\s*[-–:]\s+|\s+[-–]\s*|\.{2,}|[()\[\]\"“”;]")
RANDWOORDEN = re.compile(r"^(van|door|met|en|of)\b\s*|\b(van|door|met|en|of)\s*$", re.IGNORECASE)
PLACEHOLDER = " █ "

NUMMER = r"(\d{1,4}[a-z]?)(?![0-9])"
NA_ALIAS = r"[\s.,:_-]*(?:lied|psalm|ps\.?|nr\.?)?[\s.,:_-]*"
PSALMNUMMER = re.compile(r"\b(?:psalm|ps\.?)\s*(\d{1,3})\b", re.IGNORECASE)


@dataclass
class Ontleding:
    referenties: list[Referentie] = field(default_factory=list)
    titels: list[str] = field(default_factory=list)
    bundels: list[str] = field(default_factory=list)
    hints: set[str] = field(default_factory=set)


def is_liedrij(label: str, inhoud: str) -> bool:
    return bool(inhoud.strip()) and bool(LIED_LABEL.search(label))


def is_kandidaatrij(inhoud: str, catalogus: Catalogus) -> bool:
    """Een rij zonder liedlabel die toch naar een lied lijkt te verwijzen."""
    if not inhoud.strip():
        return False
    ontl = ontleed(inhoud, catalogus)
    return bool(ontl.referenties) or bool(ontl.bundels) or bool(LIEDWOORDEN.search(inhoud))


def bepaal_moment(label: str, inhoud: str, vorig_label: str, eerste: bool) -> str | None:
    l, i, v = eenvoudig(label), eenvoudig(inhoud), eenvoudig(vorig_label)
    if "luisterlied" in l or "luisterlied" in i:
        return "luisterlied"
    if "kind" in l or i.startswith("kindlied") or i.startswith("kinderlied") or v.startswith("kindmoment"):
        return "kindmoment"
    if "zegen" in l or "uitloop" in l or v.startswith("zegen"):
        return "zegenlied"
    if "votum" in l or eerste:
        return "aanvang"
    return None


def ontleed(inhoud: str, catalogus: Catalogus) -> Ontleding:
    ontl = Ontleding()
    tekst = eenvoudig_behoud_hoofdletters(inhoud)
    tekst = URL.sub(" ", tekst)
    tekst = RUIS_PREFIX.sub("", tekst)
    if KINDLIED_PREFIX.match(tekst):
        ontl.hints.add("kindmoment")
        tekst = KINDLIED_PREFIX.sub("", tekst)
    for hint, patroon in HINTWOORDEN.items():
        if patroon.search(tekst):
            ontl.hints.add(hint)
            tekst = patroon.sub(" ", tekst)

    tekst = _vind_referenties(tekst, catalogus, ontl)
    tekst = GETALLEN.sub(" ", tekst)
    tekst = VULWOORDEN.sub(" ", tekst)

    for deel in SCHEIDERS.split(tekst):
        deel = _schoon(deel)
        if len(re.sub(r"[^a-z]", "", deel.lower())) >= 2:
            ontl.titels.append(deel)
    return ontl


def eenvoudig_behoud_hoofdletters(tekst: str) -> str:
    vertaling = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": "-"})
    return " ".join((tekst or "").translate(vertaling).split())


_patronen_cache: dict[int, list[tuple[str, str, re.Pattern]]] = {}


def _alias_patronen(catalogus: Catalogus) -> list[tuple[str, str, re.Pattern]]:
    patronen = _patronen_cache.get(id(catalogus))
    if patronen is None:
        patronen = []
        for bundel in catalogus.bundels.values():
            for alias in bundel.aliassen:
                patronen.append((bundel.code, alias, re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z])(?:" + NA_ALIAS + NUMMER + ")?", re.IGNORECASE)))
        patronen.sort(key=lambda p: -len(p[1]))
        _patronen_cache[id(catalogus)] = patronen
    return patronen


def _vind_referenties(tekst: str, catalogus: Catalogus, ontl: Ontleding) -> str:
    gevonden: list[tuple[int, str, str | None]] = []
    for code, _alias, patroon in _alias_patronen(catalogus):
        while True:
            m = patroon.search(tekst)
            if not m:
                break
            gevonden.append((m.start(), code, m.group(1)))
            tekst = tekst[: m.start()] + PLACEHOLDER + tekst[m.end():]

    for pos, code in [(pos, code) for pos, code, nr in gevonden if nr is None]:
        if catalogus.bundels[code].psalmen:
            m = PSALMNUMMER.search(tekst)
            if m:
                gevonden.append((pos, code, m.group(1)))
                tekst = tekst[: m.start()] + PLACEHOLDER + tekst[m.end():]

    for _pos, code, nr in sorted(gevonden, key=lambda g: g[0]):
        if nr is not None:
            ontl.referenties.append(Referentie(code, nr.lower()))
        elif code not in ontl.bundels:
            ontl.bundels.append(code)
    return tekst


def _schoon(deel: str) -> str:
    """Haalt leestekens en losse voegwoorden aan de randen weg, tot er niets meer verandert."""
    deel = deel.replace("█", " ")
    vorige = None
    while deel != vorige:
        vorige = deel
        deel = re.sub(r"^[\s'\".,;:!?*-]+|[\s'\".,;:!?*-]+$", "", deel)
        deel = RANDWOORDEN.sub("", deel).strip()
    return " ".join(deel.split())


MAANDEN = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}
DATUM_TEKST = re.compile(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})")
DATUM_BESTAND = re.compile(r"(20\d{2})(\d{2})(\d{2})")


def bepaal_datum(datum_tekst: str, bestandsnaam: str) -> tuple[date | None, date | None]:
    """(datum uit het document, datum uit de bestandsnaam); elk kan None zijn."""
    uit_document = _datum_uit_tekst(datum_tekst)
    m = DATUM_BESTAND.search(bestandsnaam)
    uit_bestand = date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else _datum_uit_tekst(bestandsnaam)
    return uit_document, uit_bestand


def _datum_uit_tekst(tekst: str) -> date | None:
    m = DATUM_TEKST.search(eenvoudig(tekst))
    if not m or m.group(2) not in MAANDEN:
        return None
    try:
        return date(int(m.group(3)), MAANDEN[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


STOPWOORDEN = {"en", "van", "de", "het", "een", "met", "dienst", "zondag", "heilig", "e", "1e", "2e", "3e", "in", "op", "voor", "na"}


def herken_kenmerken(bijzonderheden: str, kenmerken: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """(herkende kenmerkcodes, onverklaarde woorden)."""
    tekst = normaliseer(bijzonderheden)
    if tekst in ("", "-", "geen", "nvt", "n v t"):
        return [], []
    codes = []
    for code, trefwoorden in kenmerken.items():
        for woord in sorted(trefwoorden, key=len, reverse=True):
            genorm = normaliseer(woord)
            if re.search(r"\b" + re.escape(genorm) + r"\b", tekst):
                if code not in codes:
                    codes.append(code)
                tekst = re.sub(r"\b" + re.escape(genorm) + r"\b", " ", tekst)
    rest = [w for w in tekst.split() if w not in STOPWOORDEN and not w.isdigit() and len(w) > 1]
    return codes, rest


BEGELEIDINGSVORMEN = ["band", "orgel", "piano", "gitaar", "cantorij", "koor", "hobo", "viool", "fluit", "cello", "trompet", "youtube", "beamer"]


def normaliseer_begeleiding(tekst: str) -> str:
    """Alleen herkende begeleidingsvormen blijven over, in vaste volgorde. Namen van
    musici die opstellers hier soms bij zetten verdwijnen zo uit de publieke data."""
    if (tekst or "").strip() in ("-", "geen"):
        return "geen"
    t = normaliseer(tekst)
    if not t:
        return "onbekend"
    woorden = set(t.split())
    gevonden = [vorm for vorm in BEGELEIDINGSVORMEN if vorm in woorden]
    return " ".join(gevonden) if gevonden else "overig"
