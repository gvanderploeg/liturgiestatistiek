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
            assert set(v) <= {"lied", "moment"}, "geen ruwe tekst in de dataset"
            if v["lied"]:
                assert v["lied"] in ds["liederen"], f"{v['lied']} ontbreekt in de liederenlijst"


def test_liederenlijst_bevat_alleen_relevante_liederen(dataset):
    ds, _ = dataset
    gebruikt = {v["lied"] for d in ds["diensten"] for v in d["liederen"] if v["lied"]}
    for lied_id, lied in ds["liederen"].items():
        assert lied_id in gebruikt or lied.get("categorieen") or lied.get("status"), f"{lied_id} is nooit gezongen en heeft geen categorie"
        assert lied["titel"]
    from liturgiestatistiek.catalogus import Catalogus

    assert len(ds["liederen"]) < len(Catalogus.laad(PROJECT / "data").liederen) / 2, "de hele catalogus hoort niet in de dataset"


def test_bundels_hebben_afkorting(dataset):
    ds, _ = dataset
    assert ds["bundels"]["opw"] == {"naam": "Opwekking", "afkorting": "Opw"}
    assert ds["bundels"]["sela"]["afkorting"] == "Sela"


def test_site_versie(dataset, tmp_path):
    from liturgiestatistiek.publicatie import SITE_BESTANDEN, site_versie

    ds, doel = dataset
    assert ds["versie"] == site_versie(doel.parent)
    assert len(site_versie(PROJECT / "site")) == 12
    for naam in SITE_BESTANDEN:
        (tmp_path / naam).write_text(naam, encoding="utf-8")
    eerste = site_versie(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "dataset.json").write_text("{}", encoding="utf-8")
    assert site_versie(tmp_path) == eerste, "nieuwe data alleen geeft geen nieuwe versie"
    (tmp_path / "app.js").write_text("gewijzigd", encoding="utf-8")
    assert site_versie(tmp_path) != eerste


def test_logo_wordt_bijgesneden_en_transparant(tmp_path):
    from PIL import Image

    from liturgiestatistiek.publicatie import FAVICON_BESTAND, LOGO_BESTAND, LOGO_HOOGTE, maak_logo

    bron = tmp_path / "logo.png"
    beeld = Image.new("RGB", (600, 400), (255, 255, 255))
    beeld.paste((11, 45, 99), (200, 100, 400, 300))
    beeld.save(bron)

    doel = tmp_path / "data"
    assert maak_logo(bron, doel)
    logo = Image.open(doel / LOGO_BESTAND)
    assert logo.mode == "RGBA" and logo.height == LOGO_HOOGTE
    assert logo.width < LOGO_HOOGTE * 1.3, "witruimte rondom is weggesneden"
    assert logo.getpixel((0, 0))[3] == 0, "wit is transparant"
    midden = logo.getpixel((logo.width // 2, logo.height // 2))
    assert midden[3] == 255 and midden[:3] == (11, 45, 99), "volle kleur blijft volledig dekkend en onveranderd"
    assert Image.open(doel / FAVICON_BESTAND).size == (64, 64)
    assert not maak_logo(tmp_path / "bestaat-niet.png", doel)


def test_csv_heeft_een_regel_per_vermelding(dataset):
    ds, doel = dataset
    with (doel / "liedvermeldingen.csv").open(encoding="utf-8", newline="") as f:
        rijen = list(csv.DictReader(f))
    assert len(rijen) == sum(len(d["liederen"]) for d in ds["diensten"])
    eerste = rijen[0]
    assert eerste["datum"] == ds["diensten"][0]["datum"]
    assert set(eerste) >= {"datum", "begeleiding", "kenmerken", "lied_id", "titel", "bundel", "nummer", "moment"}
