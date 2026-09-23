"""Commandoregel: importeer-catalogus, verwerk, toon."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from .catalogus import Catalogus
from .extractie import lees_liturgie
from .importeer import importeer_sheet
from .koppeling import Zoekindex, koppel
from .ontleding import bepaal_moment, is_kandidaatrij, is_liedrij, ontleed
from .opslag import ALIASSEN_BESTAND, Aliassen, OngeldigeYaml
from .publicatie import publiceer
from .scipio import CONFIG_BESTAND, VOORBEELD_CONFIG, ScipioConfig, ScipioFout, haal_op
from .verwerking import Omgeving, verwerk


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="liturgiestatistiek", description="Liedstatistiek uit de liturgieen van de Westerkerk")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="projectmap met data/ en archief/ (standaard: huidige map)")
    sub = parser.add_subparsers(dest="commando", required=True)

    p_import = sub.add_parser("importeer-catalogus", help="lees de catalogus-tabbladen uit het stamgegevens-sheet")
    p_import.add_argument("xlsx", type=Path)

    p_verwerk = sub.add_parser("verwerk", help="pas wachtrij-besluiten toe en verwerk alle PDF's in archief/")
    p_verwerk.add_argument("--accepteer-referenties", action="store_true", help="neem voorstellen over die op een bundelverwijzing berusten")

    p_toon = sub.add_parser("toon", help="laat zien wat de extractie en ontleding van een PDF maken")
    p_toon.add_argument("pdf", type=Path)
    p_toon.add_argument("--alles", action="store_true", help="toon ook rijen die geen lied zijn")

    sub.add_parser("publiceer", help="bouw site/data/dataset.json en de CSV uit data/")

    p_haal = sub.add_parser("haal-op", help="download nieuwe liturgie-PDF's uit de Scipio web-app naar archief/ (instellingen in werk/scipio.yaml, inlog via SCIPIO_EMAIL en SCIPIO_WACHTWOORD)")
    p_haal.add_argument("--log", action="store_true", help="toon elk verzoek met status, duur en omvang (zonder token)")
    p_haal.add_argument("--vanaf", type=date.fromisoformat, help="kijk terug tot deze datum (JJJJ-MM-DD) in plaats van de standaard terugkijkperiode; voor het inladen van historie")

    args = parser.parse_args(argv)
    omgeving = Omgeving(args.project)
    try:
        return _voer_uit(args, omgeving)
    except OngeldigeYaml as fout:
        print(fout, file=sys.stderr)
        return 1


def _voer_uit(args, omgeving: Omgeving) -> int:
    if args.commando == "haal-op":
        logging.basicConfig(level=logging.DEBUG if args.log else logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
        return _haal_op(omgeving, args.vanaf)

    if args.commando == "publiceer":
        dataset = publiceer(omgeving.data, omgeving.site_data)
        print(f"{len(dataset['diensten'])} diensten, {len(dataset['liederen'])} liederen -> {omgeving.site_data}")
        return 0

    if args.commando == "importeer-catalogus":
        catalogus = Catalogus.laad(omgeving.data)
        for bestand, aantal in importeer_sheet(args.xlsx, catalogus).items():
            print(f"{bestand}: {aantal} toegevoegd")
        return 0

    if args.commando == "verwerk":
        print(verwerk(omgeving, accepteer_referenties=args.accepteer_referenties).tekst())
        return 0

    if args.commando == "toon":
        return _toon(args.pdf, omgeving, args.alles)

    return 1


def _haal_op(omgeving: Omgeving, vanaf) -> int:
    configpad = omgeving.project / "werk" / CONFIG_BESTAND
    if not configpad.exists():
        configpad.parent.mkdir(parents=True, exist_ok=True)
        configpad.write_text(VOORBEELD_CONFIG, encoding="utf-8")
        print(f"Voorbeeldconfiguratie geschreven naar {configpad}. Controleer de ids en draai opnieuw.")
        return 1
    email, wachtwoord = os.environ.get("SCIPIO_EMAIL"), os.environ.get("SCIPIO_WACHTWOORD")
    if not email or not wachtwoord:
        print("Zet SCIPIO_EMAIL en SCIPIO_WACHTWOORD als omgevingsvariabelen.")
        return 1
    try:
        verslag = haal_op(ScipioConfig.laad(configpad), email, wachtwoord, omgeving.archief, vanaf)
    except ScipioFout as fout:
        print(f"Ophalen mislukt: {fout}")
        return 1
    print(verslag.tekst())
    return 1 if verslag.fouten else 0


def _toon(pdf: Path, omgeving: Omgeving, alles: bool) -> int:
    catalogus = Catalogus.laad(omgeving.data)
    aliassen = Aliassen.laad(omgeving.data / ALIASSEN_BESTAND)
    index = Zoekindex(catalogus)
    liturgie = lees_liturgie(pdf)
    print(f"bestand:        {liturgie.bestand}")
    print(f"datum:          {liturgie.datum_tekst}")
    print(f"bijzonderheden: {liturgie.bijzonderheden}")
    print(f"begeleiding:    {liturgie.begeleiding}")
    print()
    vorig = ""
    eerste = True
    for rij in liturgie.rijen:
        lied = is_liedrij(rij.label, rij.inhoud)
        kandidaat = not lied and is_kandidaatrij(rij.inhoud, catalogus)
        if lied or kandidaat or alles:
            soort = "LIED" if lied else ("KAND" if kandidaat else "    ")
            print(f"{soort} {rij.label[:30]:30} | {rij.inhoud}")
        if lied or kandidaat:
            ontl = ontleed(rij.inhoud, catalogus)
            k = koppel(rij.inhoud, ontl, catalogus, aliassen, index)
            moment = bepaal_moment(rij.label, rij.inhoud, vorig, eerste and lied)
            refs = ", ".join(f"{r.bundel} {r.nummer}" for r in ontl.referenties) or "-"
            print(f"       refs: {refs} | titels: {ontl.titels} | bundels: {ontl.bundels} | hints: {sorted(ontl.hints)} | moment: {moment}")
            print(f"       -> {k.herkenning}: {k.lied or ''} ({k.reden})" + (f" kandidaten: {[(c.lied, c.score) for c in k.kandidaten]}" if k.kandidaten else ""))
            if lied:
                eerste = False
        vorig = rij.label
    return 0


if __name__ == "__main__":
    sys.exit(main())
