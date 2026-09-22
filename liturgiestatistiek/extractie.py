"""Leest een liturgie-PDF en levert alleen de rijen en velden op die de
verwerking nodig heeft. Dit is de enige laag die de volledige PDF ziet;
alles wat hier niet expliciet wordt doorgelaten (namen van voorganger,
koster, lezers, doopouders) verlaat deze module niet.

De PDF is een Word-sjabloon met tweekoloms tabellen. Opstellers zetten
soms geneste tabellen of extra kolomlijnen in de inhoudscel, waardoor de
celdetectie van pdfplumber versnippert. Daarom worden rijen hier afgeleid
uit de horizontale lijnen die de volle tabelbreedte overspannen, en wordt
de tekst per rij gesplitst op de eerste kolomgrens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

ALGEMEEN_VELDEN = {
    "datum_tekst": "Datum",
    "bijzonderheden": "Bijzonderheden",
    "begeleiding": "Type muziek begeleiding",
}

KOP_ORDE = "ORDE VAN DIENST"
LIJN_MARGE = 3.0


@dataclass
class Rij:
    """Een rij uit de tabel ORDE VAN DIENST."""

    label: str
    inhoud: str
    pagina: int


@dataclass
class Liturgie:
    """Het naamloze deel van een liturgie."""

    bestand: str
    datum_tekst: str = ""
    bijzonderheden: str = ""
    begeleiding: str = ""
    rijen: list[Rij] = field(default_factory=list)


def lees_liturgie(pad: Path) -> Liturgie:
    liturgie = Liturgie(bestand=pad.name)
    orde_gestart = False

    with pdfplumber.open(pad) as pdf:
        for nummer, page in enumerate(pdf.pages, start=1):
            woorden = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            kop_top = _kop_positie(woorden, KOP_ORDE)

            for tabel in sorted(page.find_tables(), key=lambda t: t.bbox[1]):
                if kop_top is not None and tabel.bbox[1] > kop_top:
                    orde_gestart = True
                for label, inhoud in _rijen_van_tabel(page, tabel, woorden):
                    if orde_gestart:
                        liturgie.rijen.append(Rij(label=label, inhoud=inhoud, pagina=nummer))
                    else:
                        _neem_algemeen_veld(liturgie, label, inhoud)
            if kop_top is not None:
                orde_gestart = True

    return liturgie


def _rijen_van_tabel(page, tabel, woorden) -> list[tuple[str, str]]:
    x0, top, x1, bottom = tabel.bbox
    scheiding = _kolomgrens(tabel)
    if scheiding is None:
        return []

    grenzen = _samengevoegd(
        e["top"]
        for e in page.horizontal_edges
        if e["x0"] <= x0 + LIJN_MARGE and e["x1"] >= scheiding - LIJN_MARGE and top - LIJN_MARGE <= e["top"] <= bottom + LIJN_MARGE
    )
    if len(grenzen) < 2:
        grenzen = [top, bottom]

    in_tabel = [w for w in woorden if x0 - LIJN_MARGE <= w["x0"] and w["x1"] <= x1 + LIJN_MARGE]
    rijen = []
    for boven, onder in zip(grenzen, grenzen[1:]):
        in_rij = [w for w in in_tabel if boven <= (w["top"] + w["bottom"]) / 2 < onder]
        label = _tekst(w for w in in_rij if w["x0"] < scheiding)
        inhoud = _tekst(w for w in in_rij if w["x0"] >= scheiding)
        rijen.append((label, inhoud))
    return rijen


def _samengevoegd(posities) -> list[float]:
    """Sorteert posities en voegt waarden samen die minder dan een lijnmarge uit elkaar liggen."""
    resultaat: list[float] = []
    for p in sorted(posities):
        if not resultaat or p - resultaat[-1] > LIJN_MARGE:
            resultaat.append(p)
    return resultaat


def _kolomgrens(tabel) -> float | None:
    """De x-positie van de eerste kolomgrens: de tweede unieke linkerrand van alle cellen."""
    randen = sorted({round(c[0], 1) for c in tabel.cells})
    return randen[1] if len(randen) >= 2 else None


def _tekst(woorden) -> str:
    gesorteerd = sorted(woorden, key=lambda w: (round(w["top"]), w["x0"]))
    return " ".join(w["text"] for w in gesorteerd).strip()


def _kop_positie(woorden, kop: str) -> float | None:
    """Verticale positie van een sectiekop op de pagina, of None."""
    doel = kop.split()
    for i in range(len(woorden) - len(doel) + 1):
        if [w["text"].upper() for w in woorden[i : i + len(doel)]] == doel:
            return woorden[i]["top"]
    return None


def _neem_algemeen_veld(liturgie: Liturgie, label: str, inhoud: str) -> None:
    for attribuut, veldnaam in ALGEMEEN_VELDEN.items():
        if label.strip().lower() == veldnaam.lower():
            setattr(liturgie, attribuut, inhoud.strip())
