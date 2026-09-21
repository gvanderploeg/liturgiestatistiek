"""Tests op de hele verwerking, met een tijdelijke kopie van data/ en de
PDF's uit archief/. Zonder PDF's worden deze tests overgeslagen."""

import re
import shutil
from pathlib import Path

import pdfplumber
import pytest
import yaml

from liturgiestatistiek.catalogus import Catalogus
from liturgiestatistiek.extractie import ALGEMEEN_VELDEN, lees_liturgie
from liturgiestatistiek.koppeling import Zoekindex, koppel
from liturgiestatistiek.ontleding import is_liedrij, ontleed
from liturgiestatistiek.opslag import Aliassen, laad_wachtrij, schrijf_wachtrij
from liturgiestatistiek.verwerking import Omgeving, verwerk

PROJECT = Path(__file__).resolve().parents[1]
PDFS = sorted((PROJECT / "archief").glob("*.pdf"))

pytestmark = pytest.mark.skipif(not PDFS, reason="geen liturgie-PDF's in archief/")


@pytest.fixture(scope="module")
def omgeving(tmp_path_factory):
    project = tmp_path_factory.mktemp("project")
    data = project / "data"
    data.mkdir()
    for naam in ("bundels.yaml", "kenmerken.yaml"):
        shutil.copy(PROJECT / "data" / naam, data / naam)
    (data / "catalogus").mkdir()
    for naam in ("opw.yaml", "sela.yaml", "tpp.yaml", "svg.yaml"):
        shutil.copy(PROJECT / "data" / "catalogus" / naam, data / "catalogus" / naam)
    (project / "archief").mkdir()
    for pdf in PDFS:
        shutil.copy(pdf, project / "archief" / pdf.name)
    return Omgeving(project)


@pytest.fixture(scope="module")
def eerste_run(omgeving):
    return verwerk(omgeving)


def test_elke_pdf_wordt_een_dienst(omgeving, eerste_run):
    diensten = sorted((omgeving.data / "diensten").glob("*.yaml"))
    assert len(diensten) == len(PDFS)
    assert eerste_run.diensten == len(PDFS)
    for pad in diensten:
        d = yaml.safe_load(pad.open(encoding="utf-8"))
        assert set(d) == {"datum", "begeleiding", "kenmerken", "bron", "liederen"}
        assert d["liederen"], f"{pad.name} heeft geen liederen"
        for v in d["liederen"]:
            assert set(v) <= {"ruw", "moment", "lied", "herkenning"}
            assert v["herkenning"] in ("automatisch", "handmatig", "onbekend")
            assert (v["lied"] is None) == (v["herkenning"] == "onbekend")


def test_meeste_liederen_worden_herkend(eerste_run):
    assert eerste_run.vermeldingen >= 100
    assert eerste_run.automatisch / eerste_run.vermeldingen >= 0.5


def _persoonsnamen() -> set[str]:
    """Woorden uit de ALGEMEEN-tabel die geen deel zijn van de toegestane velden."""
    toegestaan = {v.lower() for v in ALGEMEEN_VELDEN.values()}
    namen: set[str] = set()
    for pdf in PDFS:
        with pdfplumber.open(pdf) as doc:
            tabel = doc.pages[0].extract_tables()[0]
        for rij in tabel:
            label = (rij[0] or "").strip().lower()
            waarde = " ".join((c or "") for c in rij[1:])
            if label in toegestaan or not waarde.strip():
                continue
            for woord in re.findall(r"[A-Za-zÀ-ÿ]{4,}", waarde):
                if woord[0].isupper():
                    namen.add(woord.lower())
    publiek: set[str] = set()
    for pdf in PDFS:
        liturgie = lees_liturgie(pdf)
        for rij in liturgie.rijen:
            if is_liedrij(rij.label, rij.inhoud):
                publiek |= {w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", rij.inhoud)}
    for pad in (PROJECT / "data" / "catalogus").glob("*.yaml"):
        if pad.name != "overig.yaml":
            for lied in yaml.safe_load(pad.open(encoding="utf-8")) or []:
                for tekst in (lied["titel"], lied.get("eerste_regel") or "", *lied.get("aliassen", [])):
                    publiek |= {w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", tekst)}
    return namen - publiek - {"voorganger", "band", "team", "gastvrij"}


def _naamzinnen() -> set[str]:
    """Volledige waarden uit de persoonsvelden, gesplitst op voegwoorden."""
    toegestaan = {v.lower() for v in ALGEMEEN_VELDEN.values()}
    zinnen: set[str] = set()
    for pdf in PDFS:
        with pdfplumber.open(pdf) as doc:
            tabel = doc.pages[0].extract_tables()[0]
        for rij in tabel:
            label = (rij[0] or "").strip().lower()
            waarde = " ".join((c or "") for c in rij[1:])
            if label in toegestaan:
                continue
            for deel in re.split(r"\s+en\s+|&|,|/", waarde):
                deel = " ".join(deel.split()).lower()
                if len(deel.split()) >= 2:
                    zinnen.add(deel)
    return zinnen


def test_geen_persoonsnamen_in_publieke_data(omgeving, eerste_run):
    namen = _persoonsnamen()
    assert len(namen) > 20, "de controle vond nauwelijks namen; klopt de tabelherkenning nog?"
    zinnen = _naamzinnen()
    afgeleid = [*(omgeving.data / "diensten").glob("*.yaml"), *(omgeving.data / "catalogus").glob("*.yaml"), omgeving.data / "aliassen.yaml", omgeving.data / "aanvullingen.yaml"]
    for pad in (p for p in afgeleid if p.exists()):
        tekst = pad.read_text(encoding="utf-8").lower()
        woorden = set(re.findall(r"[a-zà-ÿ]{4,}", tekst))
        gelekt = namen & woorden
        assert not gelekt, f"{pad.relative_to(omgeving.project)} bevat woorden uit de persoonsvelden: {sorted(gelekt)}"
        platte_tekst = " ".join(tekst.split())
        gelekte_zinnen = [z for z in zinnen if z in platte_tekst]
        assert not gelekte_zinnen, f"{pad.relative_to(omgeving.project)} bevat een naam uit de persoonsvelden: {gelekte_zinnen}"


def test_bijzonderheden_met_namen_komen_alleen_in_de_wachtrij(omgeving, eerste_run):
    items = laad_wachtrij(omgeving.wachtrij)
    bijz = [i for i in items if i.soort == "bijzonderheden"]
    assert bijz, "verwacht minstens een onverklaard Bijzonderheden-veld in de voorbeelddata"
    for item in bijz:
        assert item.sleutel and len(item.sleutel) == 12
        assert item.voorstel.get("kenmerken") is not None


def test_koppeling_op_voorbeelden(omgeving, eerste_run):
    catalogus = Catalogus.laad(omgeving.data)
    aliassen = Aliassen.laad(omgeving.data / "aliassen.yaml")
    index = Zoekindex(catalogus)

    def k(ruw):
        return koppel(ruw, ontleed(ruw, catalogus), catalogus, aliassen, index)

    assert k("Opwekking 815 (Vul dit huis met glorie)").lied == "opw-815"
    assert k("Jezus Overwinnaar").lied == "opw-832"
    assert k("Ik zal er zijn - Sela").lied == "sela-ik-zal-er-zijn"
    assert k("Doop (sela, Hemelhoog 502))").lied == "sela-doop"
    assert k("Loof de Heer zijn ziel (Psalm Project 103)").lied == "tpp-103-loof-de-heer-mijn-ziel"
    onbekend = k("Een lied dat echt niet bestaat")
    assert onbekend.herkenning == "onbekend"
    assert onbekend.voorstel["nieuw"]["titel"] == "Een lied dat echt niet bestaat"
    psalm = k("God zegent ons (PvN 67)")
    assert psalm.herkenning == "onbekend", "een psalmberijming wordt niet op titel aan een ander lied gehangen"


def test_titelscore():
    from liturgiestatistiek.koppeling import titelscore

    assert titelscore("vervuld van uw zegen", "vervuld van uw zegen ga uw weg") >= 95
    assert titelscore("spreek o heer door uw heilig woord", "spreek o heer") >= 95
    assert titelscore("spreek o heer door uw heilig woord", "heilig heilig heilig heer") < 80
    assert titelscore("doop", "de doop van jezus") < 60
    assert titelscore("ik wens jou", "ik wens jou") == 100


def test_typefout_in_nummer_wordt_gemeld(omgeving, eerste_run):
    """De liturgie van 13 september noemt Opwekking 286 met de titel van Opwekking 268."""
    items = laad_wachtrij(omgeving.wachtrij)
    controles = [i for i in items if i.soort == "controle"]
    assert any(i.dienst == "2026-09-13" and i.voorstel == {"lied": "opw-268", "huidig": "opw-286"} for i in controles)
    assert len(controles) <= 3, [i.ruw for i in controles]


def test_wachtrij_besluiten_worden_toegepast(omgeving, eerste_run):
    items = laad_wachtrij(omgeving.wachtrij)
    nieuw = next(i for i in items if i.soort == "lied" and i.voorstel.get("bron") == "titel")
    nieuw.accepteer = True
    negeer = next(i for i in items if i.soort == "lied" and i is not nieuw)
    negeer.negeer = True
    bijz = next(i for i in items if i.soort == "bijzonderheden")
    bijz.kenmerken = ["startzondag"]
    schrijf_wachtrij(omgeving.wachtrij, items)

    verslag = verwerk(omgeving, accepteer_referenties=True)
    assert verslag.besluiten_toegepast >= 3
    assert verslag.onbekend < eerste_run.onbekend

    catalogus = Catalogus.laad(omgeving.data)
    assert nieuw.voorstel["nieuw"]["id"] in catalogus.liederen
    aliassen = Aliassen.laad(omgeving.data / "aliassen.yaml")
    assert any(v == "negeer" for v in aliassen.vermeldingen.values())
    assert aliassen.bijzonderheden[bijz.sleutel] == ["startzondag"]

    dienst = yaml.safe_load((omgeving.data / "diensten" / f"{bijz.dienst}.yaml").open(encoding="utf-8"))
    assert dienst["kenmerken"] == ["startzondag"]
    dienst = yaml.safe_load((omgeving.data / "diensten" / f"{nieuw.dienst}.yaml").open(encoding="utf-8"))
    assert any(v["ruw"] == nieuw.ruw and v["herkenning"] == "handmatig" for v in dienst["liederen"])
    assert all(v["ruw"] != negeer.ruw for v in yaml.safe_load((omgeving.data / "diensten" / f"{negeer.dienst}.yaml").open(encoding="utf-8"))["liederen"])

    resterend = laad_wachtrij(omgeving.wachtrij)
    assert not any(i.ruw == nieuw.ruw and i.dienst == nieuw.dienst for i in resterend)
    assert not any(i.soort == "lied" and i.voorstel.get("bron") == "referentie" for i in resterend)
