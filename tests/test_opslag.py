from pathlib import Path

import pytest

from liturgiestatistiek.cli import main
from liturgiestatistiek.opslag import OngeldigeYaml, laad_wachtrij, lees_yaml


def test_ongeldige_yaml_geeft_regelnummer_en_tip(tmp_path: Path):
    pad = tmp_path / "wachtrij.yaml"
    pad.write_text("- dienst: '2024-12-25'\n  soort: lied\n  ruw: x\n  voorstel:\n    nieuw:\n      titel: Psalm 90: Gij zijt geweest\n", encoding="utf-8")
    with pytest.raises(OngeldigeYaml) as info:
        laad_wachtrij(pad)
    melding = str(info.value)
    assert "regel 6" in melding
    assert "aanhalingstekens" in melding


def test_lees_yaml_ontbrekend_bestand(tmp_path: Path):
    assert lees_yaml(tmp_path / "bestaat-niet.yaml") is None


def test_cli_meldt_ongeldige_yaml_netjes(tmp_path: Path, capsys):
    project = tmp_path
    (project / "data").mkdir()
    (project / "data" / "bundels.yaml").write_text("- code: opw\n  naam: Opwekking\n  aliassen: [opw]\n", encoding="utf-8")
    (project / "werk").mkdir()
    (project / "werk" / "wachtrij.yaml").write_text("- dienst: x\n  soort: lied\n  ruw: a: b\n", encoding="utf-8")
    assert main(["--project", str(project), "verwerk"]) == 1
    uit = capsys.readouterr()
    assert "geen geldige YAML" in uit.err
    assert "Traceback" not in uit.err
