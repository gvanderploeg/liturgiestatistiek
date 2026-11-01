import re
from datetime import date
from pathlib import Path

import yaml

from liturgiestatistiek.scipio import VOORBEELD_CONFIG, ScipioConfig, begindatum, bestands_url, liturgie_bijlagen, veilige_bestandsnaam


def test_voorbeeldconfig_is_geldig(tmp_path: Path):
    pad = tmp_path / "scipio.yaml"
    pad.write_text(VOORBEELD_CONFIG, encoding="utf-8")
    config = ScipioConfig.laad(pad)
    assert config.community == "5f0ef48000aa224c7bc483ee"
    assert config.pagina == "5f0f325c00aa224c7bc5fd94"
    assert config.terugkijk_dagen == 90
    assert config.per_pagina == 10
    assert re.compile(config.bestandsfilter, re.IGNORECASE).search("20260920 Eredienst Westerkerk.pdf")


def test_config_met_alleen_ids(tmp_path: Path):
    pad = tmp_path / "scipio.yaml"
    pad.write_text("community: c\nmodule: m\npagina: p\n", encoding="utf-8")
    config = ScipioConfig.laad(pad)
    assert config.terugkijk_dagen == 90
    assert config.bestandsfilter == r"eredienst.*\.pdf$"


def test_bestands_url_zet_token_in_query():
    url = bestands_url("abc def", "c1", "f1")
    assert url == "https://web.scipio-app.nl/api/v2/me/communities/c1/files/f1?Authorization=bearer%20abc%20def"


def test_liturgie_bijlagen_filtert_op_naam():
    patroon = re.compile(r"eredienst.*\.pdf$", re.IGNORECASE)
    event = {
        "files": [
            {"_id": "a", "title": "20260920 Eredienst Westerkerk.pdf", "extension": "pdf"},
            {"_id": "b", "title": "Collecterooster.pdf", "extension": "pdf"},
            {"_id": "c", "title": "Eredienst Westerkerk 24 mei 2026 -.pdf", "extension": "pdf"},
        ]
    }
    assert [f["_id"] for f in liturgie_bijlagen(event, patroon)] == ["a", "c"]
    assert liturgie_bijlagen({}, patroon) == []


def test_begindatum():
    assert begindatum({"beginDate": "2024-04-28T08:00:00.000Z"}) == date(2024, 4, 28)
    assert begindatum({}) is None
    assert begindatum({"beginDate": "onzin"}) is None


def test_veilige_bestandsnaam():
    assert veilige_bestandsnaam("20260920 Eredienst Westerkerk.pdf") == "20260920 Eredienst Westerkerk.pdf"
    assert veilige_bestandsnaam("Eredienst Westerkerk 24 mei 2026 -.pdf") == "Eredienst Westerkerk 24 mei 2026 -.pdf"
    assert "/" not in veilige_bestandsnaam("../../etc/passwd.pdf")
    assert veilige_bestandsnaam("") == "bestand.pdf"


def test_lidmaatschap_uit_memberships_available(monkeypatch):
    import json

    from liturgiestatistiek import scipio

    antwoord = [
        {
            "community": {"_id": "andere", "name": "Andere gemeente"},
            "memberships": [{"appendedMembership": {"_id": "niet-deze"}}],
        },
        {
            "community": {"_id": "5f0ef48000aa224c7bc483ee", "name": "Westerkerk"},
            "memberships": [{"emailAddress": "x", "isUser": True, "appendedMembership": {"_id": "5f0ef51200aa224c7bc48989", "firstName": "G"}}],
        },
    ]
    monkeypatch.setattr(scipio, "_verzoek", lambda *a, **k: json.dumps(antwoord).encode())
    config = ScipioConfig("5f0ef48000aa224c7bc483ee", "m", "p")
    assert scipio.lidmaatschap("token", config) == "5f0ef51200aa224c7bc48989"
    assert scipio.lidmaatschap("token", ScipioConfig("c", "m", "p", lidmaatschap="handmatig")) == "handmatig"


def test_zoek_herhaling_op_id_of_datum():
    from liturgiestatistiek.scipio import is_reeks, zoek_herhaling

    lijst = [
        {"_id": "a", "beginDate": "2025-04-06T08:00:00.000Z", "files": []},
        {"_id": "b", "beginDate": "2025-04-13T08:00:00.000Z", "files": [{"_id": "f", "title": "20250413 Eredienst Westerkerk.pdf"}]},
    ]
    assert zoek_herhaling(lijst, {"_id": "b"})["files"][0]["_id"] == "f"
    assert zoek_herhaling(lijst, {"_id": "x", "beginDate": "2025-04-13T08:00:00.000Z"})["_id"] == "b"
    assert zoek_herhaling(lijst, {"_id": "x", "beginDate": "2025-05-01T08:00:00.000Z"}) is None
    assert is_reeks({"repeat": {"type": "WEEKLY"}})
    assert not is_reeks({"repeat": {"type": "NO_REPEAT"}})
    assert not is_reeks({})


def test_vooruit_dagen_in_config(tmp_path: Path):
    pad = tmp_path / "scipio.yaml"
    pad.write_text(VOORBEELD_CONFIG, encoding="utf-8")
    assert ScipioConfig.laad(pad).vooruit_dagen == 4
    pad.write_text("community: c\nmodule: m\npagina: p\nvooruit_dagen: 0\n", encoding="utf-8")
    assert ScipioConfig.laad(pad).vooruit_dagen == 0


def test_is_bijgewerkt(tmp_path: Path):
    import os

    from liturgiestatistiek.scipio import is_bijgewerkt

    doel = tmp_path / "x.pdf"
    assert not is_bijgewerkt({"modified": "2026-10-30T12:00:00.000Z"}, doel), "geen bestand: niet opnieuw maar gewoon nieuw"
    doel.write_bytes(b"%PDF")
    os.utime(doel, (1793000000, 1793000000))
    assert is_bijgewerkt({"modified": "2026-11-01T12:00:00.000Z"}, doel)
    assert not is_bijgewerkt({"modified": "2026-10-01T12:00:00.000Z"}, doel)
    assert not is_bijgewerkt({}, doel)


def test_haal_op_kijkt_terug_en_vooruit(tmp_path: Path, monkeypatch):
    """Zonder server: login, lidmaatschap, de agenda-aanroepen en het downloaden zijn vervangen."""
    from datetime import datetime, timedelta, timezone

    from liturgiestatistiek import scipio

    vandaag = datetime.now(timezone.utc).date()

    def ev(i, dagen, titel=None, pagina="kerk", modified="2020-01-01T00:00:00.000Z"):
        d = vandaag + timedelta(days=dagen)
        files = [{"_id": f"f{i}", "title": titel or f"{d:%Y%m%d} Eredienst Westerkerk.pdf"}]
        return {"_id": f"e{i}", "page_id": pagina, "beginDate": f"{d}T08:00:00.000Z", "modified": modified, "files": files, "repeat": {"type": "NO_REPEAT"}}

    terug = [ev(1, -7), ev(2, -14, pagina="andere"), ev(3, -400)]
    vooruit = [ev(4, 0), ev(5, 3), ev(6, 10)]
    aanroepen = []
    monkeypatch.setattr(scipio, "login", lambda e, w: "token")
    monkeypatch.setattr(scipio, "lidmaatschap", lambda t, c: "lid")
    monkeypatch.setattr(scipio, "events_pagina", lambda t, m, c, skip, tot: aanroepen.append(("terug", tot.date())) or terug)
    monkeypatch.setattr(scipio, "komende_events_pagina", lambda t, m, c, skip, van: aanroepen.append(("vooruit", van.date())) or vooruit)
    def nep_download(t, c, b, doel):
        doel.parent.mkdir(parents=True, exist_ok=True)
        doel.write_bytes(b"%PDF")

    monkeypatch.setattr(scipio, "download", nep_download)
    monkeypatch.setattr(scipio.time, "sleep", lambda s: None)

    archief = tmp_path / "archief"
    config = ScipioConfig("c", "m", "kerk")
    verslag = scipio.haal_op(config, "e", "w", archief)

    assert aanroepen == [("terug", vandaag), ("vooruit", vandaag)]
    namen = sorted(verslag.gedownload)
    assert namen == sorted(f"{vandaag + timedelta(days=d):%Y%m%d} Eredienst Westerkerk.pdf" for d in (-7, 0, 3))
    assert verslag.kerkdiensten == 4, "de andere pagina telt niet, de dienst over tien dagen valt buiten het venster"

    vooruit[0]["modified"] = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    verslag = scipio.haal_op(config, "e", "w", archief)
    assert verslag.gedownload == []
    assert verslag.bijgewerkt == [f"{vandaag:%Y%m%d} Eredienst Westerkerk.pdf"]
    assert verslag.al_aanwezig == 2


def test_voorbeeldconfig_is_yaml():
    assert yaml.safe_load(VOORBEELD_CONFIG)["module"] == "5f0f325c00aa224c7bc5fd93"
