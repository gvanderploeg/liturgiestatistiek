"""Ontleedt de tekst van liturgierijen: welke rijen zijn liederen, welke
bundelverwijzingen, titels en artiesten staan erin, op welk moment in de
dienst, en wat zeggen datum en bijzonderheden."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .catalogus import Catalogus
from .modellen import Referentie
from .tekst import eenvoudig, normaliseer

LIED_LABEL = re.compile(r"lied\b", re.IGNORECASE)
MEERDERE_LABEL = re.compile(r"\d+\s*(en|&|,)\s*\d+", re.IGNORECASE)

RUIS_PREFIX = re.compile(r"^(zingen|zingend|zang|beginnen met)\s*(\([^)]*\))?\s*:?\s*", re.IGNORECASE)
KINDLIED_PREFIX = re.compile(r"^(kindlied|kinderlied)\s*\d*\s*[-:]\s*", re.IGNORECASE)
URL = re.compile(r"\(\s*https?://[^)]*\)?|https?://\S+", re.IGNORECASE)
HINTWOORDEN = {
    "luisterlied": re.compile(r"\bluisterlied\b", re.IGNORECASE),
    "refrein": re.compile(r"\brefrein\b", re.IGNORECASE),
    "tweetalig": re.compile(r"\btweetalig\b", re.IGNORECASE),
    "origineel": re.compile(r"\borigineel\b", re.IGNORECASE),
    "facultatief": re.compile(r"\bfacultatief\b", re.IGNORECASE),
}
OVERIGE_RUIS = [
    re.compile(r"\bmet tekst op powerpoint\b", re.IGNORECASE),
    re.compile(r"\buit de berijming van( het| de)?\b", re.IGNORECASE),
    re.compile(r"\bo\.a\.\s*", re.IGNORECASE),
    re.compile(r"\book in\b", re.IGNORECASE),
    re.compile(r"\b(vers|verzen|couplet|coupletten)\b[\s\d,.]*(\ben\b[\s\d,.]*)*", re.IGNORECASE),
    re.compile(r"\(\s*(allen|vrouwen|mannen)\s*\)", re.IGNORECASE),
    re.compile(r":\s*\d+(\s*,\s*\d+)*(\s*en\s*\d+)?"),
    re.compile(r"\b\d{1,3}(\s*[.,:]\s*\d{1,3})*\b(?!\s*[a-z])", re.IGNORECASE),
    re.compile(r"(?<=[a-z])\s*:\s*(?=[\d\s,.]+$)"),
]
SCHEIDERS = re.compile(r"\s+[-–:/]\s+|\s*[-–:]\s+|\s+[-–]\s*|\.{2,}|[()\[\]\"“”]|\s*[:;]\s+")
TRAILING_WOORDEN = re.compile(r"\b(van|door|met|en|of)\s*$", re.IGNORECASE)
PLACEHOLDER = " █ "

NUMMER = r"(\d{1,4}[a-z]?)(?![0-9])"
NA_ALIAS = r"[\s.,:_-]*(?:lied|psalm|ps\.?|nr\.?)?[\s.,:_-]*"
PSALMNUMMER = re.compile(r"\b(?:psalm|ps\.?)\s*(\d{1,3})\b", re.IGNORECASE)


@dataclass
class Ontleding:
    referenties: list[Referentie] = field(default_factory=list)
    titels: list[str] = field(default_factory=list)
    artiest: str | None = None
    hints: set[str] = field(default_factory=set)


def is_liedrij(label: str, inhoud: str) -> bool:
    return bool(inhoud.strip()) and bool(LIED_LABEL.search(label))


def is_kandidaatrij(inhoud: str, catalogus: Catalogus) -> bool:
    """Een rij zonder liedlabel die toch naar een lied lijkt te verwijzen."""
    if not inhoud.strip():
        return False
    ontl = ontleed(inhoud, catalogus)
    return bool(ontl.referenties) or ontl.artiest is not None or bool(re.search(r"\b(lied|zingen|gezongen)\b", inhoud, re.IGNORECASE))


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
    tekst = _vind_artiest(tekst, catalogus, ontl)

    for patroon in OVERIGE_RUIS:
        tekst = patroon.sub(" ", tekst)

    for deel in SCHEIDERS.split(tekst):
        deel = _schoon(deel)
        if len(re.sub(r"[^a-z]", "", deel.lower())) >= 2:
            ontl.titels.append(deel)
    return ontl


def eenvoudig_behoud_hoofdletters(tekst: str) -> str:
    vertaling = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": "-"})
    return " ".join((tekst or "").translate(vertaling).split())


def _alias_patronen(catalogus: Catalogus) -> list[tuple[str, str, re.Pattern]]:
    patronen = []
    for bundel in catalogus.bundels.values():
        for alias in bundel.aliassen:
            patronen.append((bundel.code, alias, re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z])(?:" + NA_ALIAS + NUMMER + ")?", re.IGNORECASE)))
    patronen.sort(key=lambda p: -len(p[1]))
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

    zonder_nummer = [(pos, code) for pos, code, nr in gevonden if nr is None]
    for pos, code in zonder_nummer:
        if catalogus.bundels[code].psalmen:
            m = PSALMNUMMER.search(tekst)
            if m:
                gevonden.append((pos, code, m.group(1)))
                tekst = tekst[: m.start()] + PLACEHOLDER + tekst[m.end():]

    for _pos, code, nr in sorted(gevonden, key=lambda g: g[0]):
        if nr is not None:
            ontl.referenties.append(Referentie(code, nr.lower()))
        elif not catalogus.bundels[code].psalmen:
            ontl.hints.add(f"bundel:{code}")
    return tekst


def _vind_artiest(tekst: str, catalogus: Catalogus, ontl: Ontleding) -> str:
    aliassen = sorted(
        ((alias, artiest.naam) for artiest in catalogus.artiesten.values() for alias in artiest.aliassen),
        key=lambda a: -len(a[0]),
    )
    for alias, naam in aliassen:
        patroon = re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", re.IGNORECASE)
        if patroon.search(tekst):
            if ontl.artiest is None:
                ontl.artiest = naam
            tekst = patroon.sub(PLACEHOLDER, tekst)
    return tekst


def _schoon(deel: str) -> str:
    deel = deel.replace("█", " ")
    deel = re.sub(r"^[\s'\".,;:!?*-]+|[\s'\".,;:!?*-]+$", "", deel)
    deel = TRAILING_WOORDEN.sub("", deel).strip()
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


def normaliseer_begeleiding(tekst: str) -> str:
    t = normaliseer(tekst)
    return t if t and t != "-" else "geen"
