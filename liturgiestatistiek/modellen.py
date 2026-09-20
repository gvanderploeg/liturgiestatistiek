"""Gegevensmodel: dienst, liedvermelding, lied en de wachtrij."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

MOMENTEN = ("aanvang", "kindmoment", "luisterlied", "zegenlied")
HERKENNINGEN = ("automatisch", "handmatig", "onbekend")


@dataclass
class Referentie:
    bundel: str
    nummer: str

    def as_dict(self) -> dict:
        return {"bundel": self.bundel, "nummer": self.nummer}


@dataclass
class Lied:
    id: str
    titel: str
    referenties: list[Referentie] = field(default_factory=list)
    artiest: str | None = None
    eerste_regel: str | None = None
    aliassen: list[str] = field(default_factory=list)
    categorieen: list[str] = field(default_factory=list)
    taal: str | None = None
    status: str = "normaal"
    opmerking: str | None = None

    def as_dict(self) -> dict:
        d: dict = {"id": self.id, "titel": self.titel}
        if self.referenties:
            d["referenties"] = [r.as_dict() for r in self.referenties]
        for veld in ("artiest", "eerste_regel", "taal", "opmerking"):
            waarde = getattr(self, veld)
            if waarde:
                d[veld] = waarde
        if self.aliassen:
            d["aliassen"] = list(self.aliassen)
        if self.categorieen:
            d["categorieen"] = list(self.categorieen)
        if self.status != "normaal":
            d["status"] = self.status
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Lied":
        return cls(
            id=d["id"],
            titel=d["titel"],
            referenties=[Referentie(str(r["bundel"]), str(r["nummer"])) for r in d.get("referenties", [])],
            artiest=d.get("artiest"),
            eerste_regel=d.get("eerste_regel"),
            aliassen=list(d.get("aliassen", [])),
            categorieen=list(d.get("categorieen", [])),
            taal=d.get("taal"),
            status=d.get("status", "normaal"),
            opmerking=d.get("opmerking"),
        )


@dataclass
class Vermelding:
    volgorde: int
    ruw: str
    lied: str | None
    herkenning: str
    moment: str | None = None

    def as_dict(self) -> dict:
        d: dict = {"volgorde": self.volgorde, "ruw": self.ruw}
        if self.moment:
            d["moment"] = self.moment
        d["lied"] = self.lied
        d["herkenning"] = self.herkenning
        return d


@dataclass
class Dienst:
    datum: date
    begeleiding: str
    kenmerken: list[str]
    bron: str
    liederen: list[Vermelding] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "datum": self.datum.isoformat(),
            "begeleiding": self.begeleiding,
            "kenmerken": list(self.kenmerken),
            "bron": self.bron,
            "liederen": [v.as_dict() for v in self.liederen],
        }


@dataclass
class Kandidaat:
    lied: str
    titel: str
    score: int

    def as_dict(self) -> dict:
        return {"lied": self.lied, "titel": self.titel, "score": self.score}


@dataclass
class WachtrijItem:
    """Een twijfelgeval voor de beheerder. De velden lied, accepteer, negeer en
    kenmerken zijn het besluit; de rest is context."""

    dienst: str
    soort: str
    ruw: str
    reden: str
    label: str = ""
    sleutel: str | None = None
    kandidaten: list[Kandidaat] = field(default_factory=list)
    voorstel: dict = field(default_factory=dict)
    lied: str | None = None
    accepteer: bool = False
    negeer: bool = False
    kenmerken: list[str] | None = None

    def as_dict(self) -> dict:
        d: dict = {"dienst": self.dienst, "soort": self.soort}
        if self.label:
            d["label"] = self.label
        d["ruw"] = self.ruw
        d["reden"] = self.reden
        if self.sleutel:
            d["sleutel"] = self.sleutel
        if self.kandidaten:
            d["kandidaten"] = [k.as_dict() for k in self.kandidaten]
        if self.voorstel:
            d["voorstel"] = self.voorstel
        if self.soort == "bijzonderheden":
            d["kenmerken"] = self.kenmerken
            d["accepteer"] = self.accepteer
            d["negeer"] = self.negeer
        else:
            d["lied"] = self.lied
            d["accepteer"] = self.accepteer
            d["negeer"] = self.negeer
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "WachtrijItem":
        return cls(
            dienst=str(d["dienst"]),
            soort=d["soort"],
            ruw=d.get("ruw", ""),
            reden=d.get("reden", ""),
            label=d.get("label", ""),
            sleutel=d.get("sleutel"),
            kandidaten=[Kandidaat(**k) for k in d.get("kandidaten", [])],
            voorstel=d.get("voorstel") or {},
            lied=d.get("lied"),
            accepteer=bool(d.get("accepteer", False)),
            negeer=bool(d.get("negeer", False)),
            kenmerken=d.get("kenmerken"),
        )

    @property
    def heeft_besluit(self) -> bool:
        if self.soort == "bijzonderheden":
            return self.negeer or self.accepteer or self.kenmerken is not None
        return self.negeer or self.accepteer or bool(self.lied)
