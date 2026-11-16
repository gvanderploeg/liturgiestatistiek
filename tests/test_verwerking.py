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
from liturgiestatistiek.tekst import normaliseer
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
        shutil.copy2(pdf, project / "archief" / pdf.name)
    cache = PROJECT / "werk" / "cache"
    if cache.exists():
        shutil.copytree(cache, project / "werk" / "cache")
    return Omgeving(project)


@pytest.fixture(scope="module")
def eerste_run(omgeving):
    return verwerk(omgeving)


def _datums_in_archief() -> set[str]:
    from liturgiestatistiek.ontleding import bepaal_datum

    datums = set()
    for pdf in PDFS:
        liturgie = lees_liturgie(pdf)
        doc, bestand = bepaal_datum(liturgie.datum_tekst, liturgie.bestand)
        datums.add((doc or bestand).isoformat())
    return datums


def test_elke_datum_wordt_een_dienst(omgeving, eerste_run):
    """Een dienst per datum; twee PDF's op dezelfde dag worden samengevoegd."""
    diensten = sorted((omgeving.data / "diensten").glob("*.yaml"))
    datums = _datums_in_archief()
    assert {p.stem for p in diensten} == datums
    assert eerste_run.diensten == len(datums)
    assert len(PDFS) - len(datums) == sum(1 for m in eerste_run.meldingen if m.startswith("SAMENGEVOEGD"))
    leeg_gemeld = {m.split()[1] for m in eerste_run.meldingen if m.startswith("LEEG ")}
    for pad in diensten:
        d = yaml.safe_load(pad.open(encoding="utf-8"))
        assert set(d) == {"datum", "begeleiding", "kenmerken", "bron", "vingerafdruk", "liederen"}
        assert d["liederen"] or pad.stem in leeg_gemeld, f"{pad.name} heeft geen liederen en is niet gemeld"
        for v in d["liederen"]:
            assert set(v) <= {"ruw", "moment", "lied", "herkenning", "wachtrij"}
            assert ("wachtrij" in v) == (v["lied"] is None), "alleen een open plek verwijst naar de wachtrij"
            assert v["herkenning"] in ("automatisch", "handmatig", "onbekend")
            assert (v["lied"] is None) == (v["herkenning"] == "onbekend")
            assert ("ruw" in v) == (v["lied"] is not None), "ruwe tekst alleen bij een herkend lied"
    assert len(leeg_gemeld) <= 3, leeg_gemeld


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
    kenmerken = yaml.safe_load((PROJECT / "data" / "kenmerken.yaml").open(encoding="utf-8"))
    for woorden in kenmerken.values():
        publiek |= {w.lower() for tekst in woorden for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", tekst)}
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
    doop = k("Doop (sela, Hemelhoog 502))")
    if doop.lied is None:
        assert doop.kandidaten[0].lied == "sela-doop"
        assert "twijfel" in doop.voorstel, "onbekend nummer met een sterk gelijkende titel wordt niet stilzwijgend samengevoegd"
        assert doop.voorstel["nieuw"]["id"] == "hh-502"
    else:
        assert doop.lied == "sela-doop", "alleen via een al bekende verwijzing"
    onbekend_nummer = k("Opwekking kids 999 (Hoe machtig is uw naam)")
    assert onbekend_nummer.herkenning == "onbekend"
    assert onbekend_nummer.voorstel["bron"] == "referentie"
    assert "twijfel" in onbekend_nummer.voorstel
    assert onbekend_nummer.kandidaten[0].lied == "sela-hoe-machtig-is-uw-naam"
    assert k("Loof de Heer zijn ziel (Psalm Project 103)").lied == "tpp-103-loof-de-heer-mijn-ziel"
    onbekend = k("Een lied dat echt niet bestaat")
    assert onbekend.herkenning == "onbekend"
    assert onbekend.voorstel["nieuw"]["titel"] == "Een lied dat echt niet bestaat"
    assert "aliassen" not in onbekend.voorstel["nieuw"]
    met_artiest = k("Geen afstand- Eline Bakker").voorstel["nieuw"]
    assert met_artiest["titel"] == "Geen afstand - Eline Bakker"
    assert met_artiest["id"] == "geen-afstand-eline-bakker"
    assert met_artiest["aliassen"] == ["Geen afstand"]
    assert k("Charity Gayle: I speak Jesus").voorstel["nieuw"]["titel"] == "Charity Gayle - I speak Jesus"
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
    assert len(controles) <= max(3, len(PDFS) // 5), [i.ruw for i in controles]


def lees(omgeving, dienst_id):
    return yaml.safe_load((omgeving.data / "diensten" / f"{dienst_id}.yaml").open(encoding="utf-8"))


def schrijf(omgeving, dienst_id, inhoud):
    with (omgeving.data / "diensten" / f"{dienst_id}.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(inhoud, f, allow_unicode=True, sort_keys=False)


def open_plekken(omgeving) -> int:
    return sum(1 for p in (omgeving.data / "diensten").glob("*.yaml") for v in yaml.safe_load(p.open(encoding="utf-8"))["liederen"] if v["lied"] is None)


def test_tweede_run_laat_diensten_ongemoeid(omgeving, eerste_run):
    voor = {p.name: p.read_bytes() for p in (omgeving.data / "diensten").glob("*.yaml")}
    verslag = verwerk(omgeving)
    assert verslag.diensten == 0
    assert verslag.ongewijzigd == len(voor)
    assert {p.name: p.read_bytes() for p in (omgeving.data / "diensten").glob("*.yaml")} == voor
    assert verslag.wachtrij == eerste_run.wachtrij, "open items blijven in de wachtrij staan"


def test_dienst_zonder_pdf_blijft_staan(omgeving, eerste_run):
    los = omgeving.data / "diensten" / "1999-01-03.yaml"
    los.write_text("datum: '1999-01-03'\nbegeleiding: band\nkenmerken: []\nbron: handmatig\nliederen: []\n", encoding="utf-8")
    verwerk(omgeving)
    assert los.exists()
    los.unlink()


def test_leeg_archief_raakt_diensten_niet_aan(tmp_path):
    data = tmp_path / "data"
    (data / "diensten").mkdir(parents=True)
    for naam in ("bundels.yaml", "kenmerken.yaml"):
        shutil.copy(PROJECT / "data" / naam, data / naam)
    bestaand = data / "diensten" / "2024-01-07.yaml"
    bestaand.write_text("datum: '2024-01-07'\nliederen: []\n", encoding="utf-8")
    (tmp_path / "archief").mkdir()
    verwerk(Omgeving(tmp_path))
    assert bestaand.exists()


def test_handmatige_correctie_blijft_staan(omgeving, eerste_run):
    dienst_id = sorted(p.stem for p in (omgeving.data / "diensten").glob("*.yaml"))[5]
    inhoud = lees(omgeving, dienst_id)
    inhoud["begeleiding"] = "cantorij"
    schrijf(omgeving, dienst_id, inhoud)
    verwerk(omgeving)
    assert lees(omgeving, dienst_id)["begeleiding"] == "cantorij"


def test_gewijzigde_pdf_wordt_opnieuw_verwerkt(omgeving, eerste_run):
    dienst_id = sorted(p.stem for p in (omgeving.data / "diensten").glob("*.yaml"))[6]
    origineel = lees(omgeving, dienst_id)
    inhoud = dict(origineel, vingerafdruk="0000000000000000", begeleiding="cantorij")
    schrijf(omgeving, dienst_id, inhoud)
    verslag = verwerk(omgeving)
    assert f"OPNIEUW {dienst_id}: de liturgie is gewijzigd, dienst opnieuw verwerkt" in verslag.meldingen
    assert verslag.diensten == 1
    assert lees(omgeving, dienst_id) == origineel


def test_opnieuw_op_verzoek(omgeving, eerste_run):
    dienst_id = sorted(p.stem for p in (omgeving.data / "diensten").glob("*.yaml"))[7]
    verslag = verwerk(omgeving, opnieuw={dienst_id})
    assert verslag.diensten == 1
    assert f"OPNIEUW {dienst_id}: op verzoek opnieuw uit de PDF opgebouwd" in verslag.meldingen


def test_alias_vult_open_plekken_in_oude_diensten(omgeving, eerste_run):
    items = [i for i in laad_wachtrij(omgeving.wachtrij) if i.soort == "lied" and not i.heeft_besluit]
    item = items[0]
    lied_id = next(iter(Catalogus.laad(omgeving.data).liederen))
    aliassen = Aliassen.laad(omgeving.data / "aliassen.yaml")
    aliassen.vermeldingen[normaliseer(item.ruw)] = lied_id
    aliassen.schrijf(omgeving.data / "aliassen.yaml")

    verslag = verwerk(omgeving)
    assert verslag.open_ingevuld >= 1
    assert verslag.diensten == 0, "geen dienst opnieuw uit zijn PDF opgebouwd"
    liederen = lees(omgeving, item.dienst)["liederen"]
    assert not any(v.get("wachtrij") == item.sleutel for v in liederen)
    assert any(v["lied"] == lied_id for v in liederen)
    assert not any(i.dienst == item.dienst and i.sleutel == item.sleutel for i in laad_wachtrij(omgeving.wachtrij))


def test_wachtrij_besluiten_worden_toegepast(omgeving, eerste_run):
    items = laad_wachtrij(omgeving.wachtrij)
    nieuw = next(i for i in items if i.soort == "lied" and i.voorstel.get("bron") == "titel")
    nieuw.accepteer = True
    negeer = next(i for i in items if i.soort == "lied" and i is not nieuw)
    negeer.negeer = True
    bijz = next(i for i in items if i.soort == "bijzonderheden")
    bijz.kenmerken = ["startzondag"]
    schrijf_wachtrij(omgeving.wachtrij, items)
    open_voor = open_plekken(omgeving)

    verslag = verwerk(omgeving, accepteer_referenties=True)
    assert verslag.besluiten_toegepast >= 3
    assert open_plekken(omgeving) < open_voor

    catalogus = Catalogus.laad(omgeving.data)
    assert nieuw.voorstel["nieuw"]["id"] in catalogus.liederen
    aliassen = Aliassen.laad(omgeving.data / "aliassen.yaml")
    assert any(v == "negeer" for v in aliassen.vermeldingen.values())
    assert aliassen.bijzonderheden[bijz.sleutel] == ["startzondag"]

    dienst = yaml.safe_load((omgeving.data / "diensten" / f"{bijz.dienst}.yaml").open(encoding="utf-8"))
    assert dienst["kenmerken"] == ["startzondag"]
    dienst = yaml.safe_load((omgeving.data / "diensten" / f"{nieuw.dienst}.yaml").open(encoding="utf-8"))
    assert any(v.get("ruw") == nieuw.ruw and v["herkenning"] == "handmatig" for v in dienst["liederen"])
    assert all(v.get("wachtrij") != negeer.sleutel for v in lees(omgeving, negeer.dienst)["liederen"])

    resterend = laad_wachtrij(omgeving.wachtrij)
    assert not any(i.ruw == nieuw.ruw and i.dienst == nieuw.dienst for i in resterend)
    assert not any(i.soort == "lied" and i.voorstel.get("bron") == "referentie" and "twijfel" not in i.voorstel for i in resterend)
