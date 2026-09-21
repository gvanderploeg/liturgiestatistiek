"""Tests op de publicatiestap: dataset.json en CSV uit data/."""

import csv
import json
from pathlib import Path

import pytest

from liturgiestatistiek.publicatie import publiceer

PROJECT = Path(__file__).resolve().parents[1]
DIENSTEN = sorted((PROJECT / "data" / "diensten").glob("*.yaml"))

pytestmark = pytest.mark.skipif(not DIENSTEN, reason="geen dienst-bestanden in data/diensten/")


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    doel = tmp_path_factory.mktemp("site") / "data"
    ds = publiceer(PROJECT / "data", doel)
    return ds, doel


def test_dataset_bevat_alle_diensten(dataset):
    ds, doel = dataset
    assert len(ds["diensten"]) == len(DIENSTEN)
    assert ds["eerste_dienst"] == DIENSTEN[0].stem
    assert ds["laatste_dienst"] == DIENSTEN[-1].stem
    geladen = json.loads((doel / "dataset.json").read_text(encoding="utf-8"))
    assert geladen["diensten"] == ds["diensten"]


def test_dataset_is_compact_en_naamloos(dataset):
    ds, _ = dataset
    for d in ds["diensten"]:
        assert set(d) == {"datum", "begeleiding", "kenmerken", "liederen"}
        for v in d["liederen"]:
            assert set(v) <= {"lied", "moment", "ruw"}
            assert ("ruw" in v) == (v["lied"] is None), "ruwe tekst gaat alleen mee als het lied niet herkend is"
            if v["lied"]:
                assert v["lied"] in ds["liederen"], f"{v['lied']} ontbreekt in de liederenlijst"


def test_liederenlijst_bevat_alleen_relevante_liederen(dataset):
    ds, _ = dataset
    gebruikt = {v["lied"] for d in ds["diensten"] for v in d["liederen"] if v["lied"]}
    for lied_id, lied in ds["liederen"].items():
        assert lied_id in gebruikt or lied.get("categorieen") or lied.get("status"), f"{lied_id} is nooit gezongen en heeft geen categorie"
        assert lied["titel"]
    assert len(ds["liederen"]) < 400, "de hele Opwekkingsbundel hoort niet in de dataset"


def test_bundels_hebben_afkorting(dataset):
    ds, _ = dataset
    assert ds["bundels"]["opw"] == {"naam": "Opwekking", "afkorting": "Opw"}
    assert ds["bundels"]["sela"]["afkorting"] == "Sela"


def test_csv_heeft_een_regel_per_vermelding(dataset):
    ds, doel = dataset
    with (doel / "liedvermeldingen.csv").open(encoding="utf-8", newline="") as f:
        rijen = list(csv.DictReader(f))
    assert len(rijen) == sum(len(d["liederen"]) for d in ds["diensten"])
    eerste = rijen[0]
    assert eerste["datum"] == ds["diensten"][0]["datum"]
    assert set(eerste) >= {"datum", "begeleiding", "kenmerken", "lied_id", "titel", "bundel", "nummer", "moment"}
