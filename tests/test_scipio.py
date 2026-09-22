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


def test_voorbeeldconfig_is_yaml():
    assert yaml.safe_load(VOORBEELD_CONFIG)["module"] == "5f0f325c00aa224c7bc5fd93"
