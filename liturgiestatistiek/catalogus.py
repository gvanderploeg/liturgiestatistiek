"""De catalogus van liederen, bundels en artiesten, gelezen uit data/."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .modellen import Lied, Referentie
from .tekst import normaliseer, slug

CATALOGUS_MAP = "catalogus"
OVERIG_BESTAND = "overig.yaml"


@dataclass
class Bundel:
    code: str
    naam: str
    aliassen: list[str]
    psalmen: bool = False


@dataclass
class Artiest:
    naam: str
    aliassen: list[str]


@dataclass
class Catalogus:
    datamap: Path
    bundels: dict[str, Bundel] = field(default_factory=dict)
    artiesten: dict[str, Artiest] = field(default_factory=dict)
    liederen: dict[str, Lied] = field(default_factory=dict)
    bestand_van_lied: dict[str, str] = field(default_factory=dict)
    _per_referentie: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    @classmethod
    def laad(cls, datamap: Path) -> "Catalogus":
        cat = cls(datamap=datamap)
        for b in _lees_lijst(datamap / "bundels.yaml"):
            cat.bundels[b["code"]] = Bundel(b["code"], b["naam"], [a.lower() for a in b["aliassen"]], bool(b.get("psalmen")))
        for a in _lees_lijst(datamap / "artiesten.yaml"):
            cat.artiesten[a["naam"]] = Artiest(a["naam"], [x.lower() for x in a["aliassen"]])
        map_ = datamap / CATALOGUS_MAP
        map_.mkdir(parents=True, exist_ok=True)
        for bestand in sorted(map_.glob("*.yaml")):
            for d in _lees_lijst(bestand):
                lied = Lied.from_dict(d)
                if lied.id in cat.liederen:
                    raise ValueError(f"dubbel lied-id {lied.id} in {bestand.name} en {cat.bestand_van_lied[lied.id]}")
                cat._voeg_toe(lied, bestand.name)
        return cat

    def _voeg_toe(self, lied: Lied, bestand: str) -> None:
        self.liederen[lied.id] = lied
        self.bestand_van_lied[lied.id] = bestand
        for r in lied.referenties:
            self._per_referentie.setdefault((r.bundel, r.nummer.lower()), []).append(lied.id)

    def voeg_lied_toe(self, lied: Lied, bestand: str = OVERIG_BESTAND) -> None:
        if lied.id in self.liederen:
            raise ValueError(f"lied-id {lied.id} bestaat al")
        self._voeg_toe(lied, bestand)

    def voeg_referentie_toe(self, lied_id: str, ref: Referentie) -> bool:
        """Koppelt een bundelverwijzing aan een bestaand lied; False als de verwijzing al bezet is."""
        if self.op_referentie(ref):
            return False
        self.liederen[lied_id].referenties.append(ref)
        self._per_referentie.setdefault((ref.bundel, ref.nummer.lower()), []).append(lied_id)
        return True

    def op_referentie(self, ref: Referentie) -> list[Lied]:
        return [self.liederen[i] for i in self._per_referentie.get((ref.bundel, ref.nummer.lower()), [])]

    def vrij_id(self, basis: str) -> str:
        kandidaat = slug(basis) or "lied"
        n = 2
        while kandidaat in self.liederen:
            kandidaat = f"{slug(basis)}-{n}"
            n += 1
        return kandidaat

    def bundel_van_alias(self, alias: str) -> Bundel | None:
        alias = alias.lower()
        for b in self.bundels.values():
            if alias in b.aliassen:
                return b
        return None

    def artiest_van_alias(self, tekst: str) -> str | None:
        genorm = normaliseer(tekst)
        for a in self.artiesten.values():
            if genorm in (normaliseer(x) for x in a.aliassen):
                return a.naam
        return None

    def zoektermen(self) -> list[tuple[str, str]]:
        """(genormaliseerde tekst, lied-id) voor titel, eerste regel en aliassen van elk lied."""
        termen = []
        for lied in self.liederen.values():
            for t in [lied.titel, lied.eerste_regel, *lied.aliassen]:
                if t:
                    termen.append((normaliseer(t), lied.id))
        return termen

    def schrijf(self) -> None:
        per_bestand: dict[str, list[Lied]] = {}
        for lied_id, bestand in self.bestand_van_lied.items():
            per_bestand.setdefault(bestand, []).append(self.liederen[lied_id])
        map_ = self.datamap / CATALOGUS_MAP
        for bestand, liederen in per_bestand.items():
            liederen.sort(key=_sorteersleutel)
            _schrijf_lijst(map_ / bestand, [l.as_dict() for l in liederen])


def _sorteersleutel(lied: Lied):
    if lied.referenties:
        r = lied.referenties[0]
        cijfers = "".join(c for c in r.nummer if c.isdigit())
        return (0, r.bundel, int(cijfers) if cijfers else 0, r.nummer)
    return (1, lied.artiest or "", lied.titel.lower())


def _lees_lijst(pad: Path) -> list[dict]:
    if not pad.exists():
        return []
    with pad.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _schrijf_lijst(pad: Path, items: list[dict]) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    with pad.open("w", encoding="utf-8") as f:
        yaml.safe_dump(items, f, allow_unicode=True, sort_keys=False, width=120)
