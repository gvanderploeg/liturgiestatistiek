"""Lezen en schrijven van de YAML-bestanden: diensten, aliassen,
aanvullingen, kenmerken en de wachtrij."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .modellen import Dienst, WachtrijItem

DIENSTEN_MAP = "diensten"
ALIASSEN_BESTAND = "aliassen.yaml"
AANVULLINGEN_BESTAND = "aanvullingen.yaml"
KENMERKEN_BESTAND = "kenmerken.yaml"
WACHTRIJ_BESTAND = "wachtrij.yaml"


@dataclass
class Aliassen:
    """Besluiten van de beheerder die bij elke verwerking opnieuw worden toegepast.

    vermeldingen: genormaliseerde liedregel -> lied-id, of "negeer".
    bijzonderheden: sleutel (hash) van de tekst in Bijzonderheden -> kenmerkcodes.
    negeer_rijen: sleutels van kandidaatrijen die geen lied zijn.
    """

    vermeldingen: dict[str, str] = field(default_factory=dict)
    bijzonderheden: dict[str, list[str]] = field(default_factory=dict)
    negeer_rijen: list[str] = field(default_factory=list)

    @classmethod
    def laad(cls, pad: Path) -> "Aliassen":
        d = _lees(pad) or {}
        return cls(
            vermeldingen=dict(d.get("vermeldingen") or {}),
            bijzonderheden={k: list(v) for k, v in (d.get("bijzonderheden") or {}).items()},
            negeer_rijen=list(d.get("negeer_rijen") or []),
        )

    def schrijf(self, pad: Path) -> None:
        _schrijf(
            pad,
            {
                "vermeldingen": dict(sorted(self.vermeldingen.items())),
                "bijzonderheden": dict(sorted(self.bijzonderheden.items())),
                "negeer_rijen": sorted(set(self.negeer_rijen)),
            },
        )


@dataclass
class Aanvulling:
    """Een lied dat de beheerder aan een dienst toevoegt omdat het niet op een liedrij stond."""

    dienst: str
    sleutel: str
    ruw: str
    lied: str
    moment: str | None = None

    def as_dict(self) -> dict:
        d = {"dienst": self.dienst, "sleutel": self.sleutel, "ruw": self.ruw, "lied": self.lied}
        if self.moment:
            d["moment"] = self.moment
        return d


def laad_aanvullingen(pad: Path) -> list[Aanvulling]:
    return [Aanvulling(str(d["dienst"]), d["sleutel"], d["ruw"], d["lied"], d.get("moment")) for d in (_lees(pad) or [])]


def schrijf_aanvullingen(pad: Path, items: list[Aanvulling]) -> None:
    _schrijf(pad, [a.as_dict() for a in sorted(items, key=lambda a: (a.dienst, a.sleutel))])


def laad_kenmerken(pad: Path) -> dict[str, list[str]]:
    return {k: list(v) for k, v in (_lees(pad) or {}).items()}


def schrijf_dienst(map_: Path, dienst: Dienst) -> Path:
    map_.mkdir(parents=True, exist_ok=True)
    pad = map_ / f"{dienst.datum.isoformat()}.yaml"
    _schrijf(pad, dienst.as_dict())
    return pad


def laad_wachtrij(pad: Path) -> list[WachtrijItem]:
    return [WachtrijItem.from_dict(d) for d in (_lees(pad) or [])]


def schrijf_wachtrij(pad: Path, items: list[WachtrijItem]) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    kop = (
        "# Wachtrij: twijfelgevallen uit de verwerking. Vul per item een besluit in en\n"
        "# draai daarna opnieuw 'liturgiestatistiek verwerk'.\n"
        "#   lied: <lied-id>       koppel aan een bestaand lied uit data/catalogus/\n"
        "#   accepteer: true       neem het voorstel over (nieuw lied of kenmerken)\n"
        "#   negeer: true          dit is geen lied (of: geen kenmerk)\n"
        "#   kenmerken: [..]       alleen bij soort bijzonderheden: kies zelf de kenmerken\n"
        "# Bij een voorstel voor een nieuw lied mag je id, titel en artiest eerst aanpassen.\n"
        "# Bij soort kandidaat mag je 'ruw' inkorten tot alleen de liedtekst; die tekst wordt opgeslagen.\n"
        "# Dit bestand blijft lokaal en kan namen bevatten.\n\n"
    )
    with pad.open("w", encoding="utf-8") as f:
        f.write(kop)
        yaml.safe_dump([i.as_dict() for i in items], f, allow_unicode=True, sort_keys=False, width=120)


class OngeldigeYaml(Exception):
    """Een YAML-bestand dat de beheerder bewerkt is niet meer leesbaar."""


def lees_yaml(pad: Path):
    """Leest een YAML-bestand; None als het niet bestaat, OngeldigeYaml met regelnummer als het niet parseert."""
    return _lees(pad)


def _lees(pad: Path):
    if not pad.exists():
        return None
    with pad.open(encoding="utf-8") as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as fout:
            plek = getattr(fout, "problem_mark", None)
            waar = f" op regel {plek.line + 1}" if plek else ""
            raise OngeldigeYaml(
                f"{pad} is geen geldige YAML{waar}: {getattr(fout, 'problem', fout)}. "
                "Tip: een waarde met een dubbele punt of een aanhalingsteken erin moet tussen dubbele aanhalingstekens, "
                'bijvoorbeeld titel: "Psalm 90: Gij zijt geweest"'
            ) from None


def _schrijf(pad: Path, inhoud) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    with pad.open("w", encoding="utf-8") as f:
        yaml.safe_dump(inhoud, f, allow_unicode=True, sort_keys=False, width=120)
