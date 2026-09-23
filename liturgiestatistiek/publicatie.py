"""Bouwt uit de YAML in data/ de bestanden die de website inleest:
site/data/dataset.json met alle diensten en liederen, en site/data/liedvermeldingen.csv
voor wie zelf wil rekenen. Alle telling gebeurt in de browser; hier wordt alleen
verzameld en compact weggeschreven."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .catalogus import Catalogus
from .opslag import DIENSTEN_MAP

DATASET_BESTAND = "dataset.json"
CSV_BESTAND = "liedvermeldingen.csv"

log = logging.getLogger("liturgiestatistiek.publicatie")


def bouw_dataset(datamap: Path) -> dict:
    catalogus = Catalogus.laad(datamap)
    diensten = []
    for pad in sorted((datamap / DIENSTEN_MAP).glob("*.yaml")):
        with pad.open(encoding="utf-8") as f:
            d = yaml.safe_load(f)
        liederen = []
        for v in d["liederen"]:
            item: dict = {"lied": v["lied"]}
            if v.get("moment"):
                item["moment"] = v["moment"]
            liederen.append(item)
        diensten.append(
            {
                "datum": str(d["datum"]),
                "begeleiding": d.get("begeleiding") or "geen",
                "kenmerken": list(d.get("kenmerken") or []),
                "liederen": liederen,
            }
        )

    gebruikt = {v["lied"] for d in diensten for v in d["liederen"] if v["lied"]}
    liederen_uit = {}
    for lied_id in sorted(gebruikt - set(catalogus.liederen)):
        log.warning("dienst verwijst naar lied %s dat niet in de catalogus staat; draai 'verwerk' om de diensten bij te werken", lied_id)
        liederen_uit[lied_id] = {"titel": lied_id, "ontbreekt": True}
    for lied_id, lied in sorted(catalogus.liederen.items()):
        if lied_id not in gebruikt and not lied.categorieen and lied.status == "normaal":
            continue
        record: dict = {"titel": lied.titel}
        if lied.referenties:
            record["referenties"] = [r.as_dict() for r in lied.referenties]
        if lied.artiest:
            record["artiest"] = lied.artiest
        if lied.categorieen:
            record["categorieen"] = list(lied.categorieen)
        if lied.status != "normaal":
            record["status"] = lied.status
        if lied.opmerking:
            record["opmerking"] = lied.opmerking
        liederen_uit[lied_id] = record

    bundels = {code: {"naam": b.naam, "afkorting": b.afkorting} for code, b in catalogus.bundels.items()}
    return {
        "gegenereerd": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "eerste_dienst": diensten[0]["datum"] if diensten else None,
        "laatste_dienst": diensten[-1]["datum"] if diensten else None,
        "bundels": bundels,
        "liederen": liederen_uit,
        "diensten": diensten,
    }


def schrijf_csv(dataset: dict, pad: Path) -> None:
    pad.parent.mkdir(parents=True, exist_ok=True)
    with pad.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["datum", "begeleiding", "kenmerken", "volgnummer", "lied_id", "titel", "bundel", "nummer", "artiest", "moment", "categorieen"])
        for d in dataset["diensten"]:
            for i, v in enumerate(d["liederen"], start=1):
                lied = dataset["liederen"].get(v["lied"]) if v["lied"] else None
                ref = (lied or {}).get("referenties", [{}])[0] if lied else {}
                w.writerow(
                    [
                        d["datum"],
                        d["begeleiding"],
                        " ".join(d["kenmerken"]),
                        i,
                        v["lied"] or "",
                        lied["titel"] if lied else v.get("ruw", ""),
                        ref.get("bundel", ""),
                        ref.get("nummer", ""),
                        (lied or {}).get("artiest", ""),
                        v.get("moment", ""),
                        " ".join((lied or {}).get("categorieen", [])),
                    ]
                )


def publiceer(datamap: Path, doelmap: Path) -> dict:
    dataset = bouw_dataset(datamap)
    doelmap.mkdir(parents=True, exist_ok=True)
    with (doelmap / DATASET_BESTAND).open("w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, separators=(",", ":"))
    schrijf_csv(dataset, doelmap / CSV_BESTAND)
    return dataset
