"""De verwerkingsstap.

De dienst-bestanden in data/diensten zijn de bron van waarheid. Een liturgie-PDF
is alleen nieuwe invoer: hij wordt verwerkt als er voor zijn datum nog geen dienst
is, of als de PDF sinds de vorige keer veranderd is (de vingerafdruk wijkt af).
Bestaande diensten worden verder niet overschreven en nooit verwijderd, zodat
handmatige correcties blijven staan en een leeg of onvolledig archief geen kwaad kan.

Besluiten uit de wachtrij worden vastgelegd als alias of catalogusregel (voor
toekomstige liturgieen) en tegelijk rechtstreeks in de betreffende dienst. Open
plekken in diensten worden bij elke run opnieuw bekeken tegen de aliassen en de
catalogus, zodat een nieuw besluit ook oudere diensten met dezelfde regel aanvult."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .catalogus import Catalogus
from .extractie import Liturgie, lees_liturgie_gecached
from .koppeling import DREMPEL_AUTOMATISCH, DREMPEL_ZEKER, Koppeling, Zoekindex, koppel
from .modellen import Dienst, Lied, Referentie, Vermelding, WachtrijItem
from .ontleding import (
    MEERDERE_LABEL,
    bepaal_datum,
    bepaal_moment,
    herken_kenmerken,
    is_kandidaatrij,
    is_liedrij,
    normaliseer_begeleiding,
    ontleed,
)
from .opslag import (
    AANVULLINGEN_BESTAND,
    ALIASSEN_BESTAND,
    DIENSTEN_MAP,
    KENMERKEN_BESTAND,
    WACHTRIJ_BESTAND,
    Aanvulling,
    Aliassen,
    laad_aanvullingen,
    laad_kenmerken,
    laad_wachtrij,
    lees_dienst,
    schrijf_aanvullingen,
    schrijf_dienst,
    schrijf_dienst_dict,
    schrijf_wachtrij,
)
from .tekst import normaliseer, sleutel


@dataclass
class Verslag:
    diensten: int = 0
    ongewijzigd: int = 0
    vingerafdruk_toegevoegd: int = 0
    vermeldingen: int = 0
    automatisch: int = 0
    handmatig: int = 0
    onbekend: int = 0
    wachtrij: int = 0
    besluiten_toegepast: int = 0
    open_ingevuld: int = 0
    referenties_geleerd: int = 0
    meldingen: list[str] = field(default_factory=list)

    def tekst(self) -> str:
        regels = [
            f"diensten verwerkt:      {self.diensten}",
            f"diensten ongewijzigd:   {self.ongewijzigd}",
            f"liedvermeldingen:       {self.vermeldingen}  (in de verwerkte diensten)",
            f"  automatisch herkend:  {self.automatisch}",
            f"  handmatig (alias):    {self.handmatig}",
            f"  onbekend:             {self.onbekend}",
            f"besluiten toegepast:    {self.besluiten_toegepast}",
            f"open plekken ingevuld:  {self.open_ingevuld}",
            f"referenties geleerd:    {self.referenties_geleerd}",
            f"wachtrij-items:         {self.wachtrij}",
        ]
        if self.vingerafdruk_toegevoegd:
            regels.append(f"eenmalig opnieuw opgebouwd (nog zonder vingerafdruk): {self.vingerafdruk_toegevoegd}")
        return "\n".join(regels + self.meldingen)


@dataclass
class Omgeving:
    project: Path

    @property
    def data(self) -> Path:
        return self.project / "data"

    @property
    def archief(self) -> Path:
        return self.project / "archief"

    @property
    def wachtrij(self) -> Path:
        return self.project / "werk" / WACHTRIJ_BESTAND

    @property
    def site_data(self) -> Path:
        return self.project / "site" / "data"

    @property
    def cache(self) -> Path:
        return self.project / "werk" / "cache"


def verwerk(omgeving: Omgeving, accepteer_referenties: bool = False, opnieuw: set[str] | None = None, alles_opnieuw: bool = False) -> Verslag:
    """Verwerkt nieuwe en gewijzigde liturgieen en past besluiten uit de wachtrij toe.
    Met 'opnieuw' (datums als JJJJ-MM-DD) of 'alles_opnieuw' worden bestaande diensten
    bewust opnieuw uit hun PDF opgebouwd; handmatige wijzigingen in die diensten gaan
    dan verloren, behalve wat via aliassen en aanvullingen is vastgelegd."""
    verslag = Verslag()
    opnieuw = opnieuw or set()
    diensten_map = omgeving.data / DIENSTEN_MAP
    catalogus = Catalogus.laad(omgeving.data)
    aliassen = Aliassen.laad(omgeving.data / ALIASSEN_BESTAND)
    aanvullingen = laad_aanvullingen(omgeving.data / AANVULLINGEN_BESTAND)
    kenmerken = laad_kenmerken(omgeving.data / KENMERKEN_BESTAND)

    oude_wachtrij = laad_wachtrij(omgeving.wachtrij)
    toegepast = _pas_besluiten_toe(oude_wachtrij, catalogus, aliassen, aanvullingen, diensten_map, accepteer_referenties, verslag)
    verslag.besluiten_toegepast = len(toegepast)
    if toegepast:
        catalogus.schrijf()
        aliassen.schrijf(omgeving.data / ALIASSEN_BESTAND)
        schrijf_aanvullingen(omgeving.data / AANVULLINGEN_BESTAND, aanvullingen)

    index = Zoekindex(catalogus)
    open_items = [i for i in oude_wachtrij if id(i) not in toegepast]
    open_items = _herbeoordeel(open_items, catalogus, aliassen, aanvullingen, index, diensten_map, verslag)

    nieuwe_wachtrij: list[WachtrijItem] = []
    verwerkt: set[str] = set()
    for dienst_id, liturgie, vingerafdruk in _liturgieen_per_datum(omgeving.archief, omgeving.cache, verslag):
        bestaand = lees_dienst(diensten_map, dienst_id)
        vorige = (bestaand or {}).get("vingerafdruk")
        bewust = alles_opnieuw or dienst_id in opnieuw
        if bestaand is not None and vorige == vingerafdruk and not bewust:
            verslag.ongewijzigd += 1
            continue
        dienst, items = verwerk_liturgie(liturgie, catalogus, aliassen, aanvullingen, kenmerken, index, verslag)
        if dienst is None:
            continue
        dienst.vingerafdruk = vingerafdruk
        schrijf_dienst(diensten_map, dienst)
        if bestaand is not None:
            if bewust:
                verslag.meldingen.append(f"OPNIEUW {dienst_id}: op verzoek opnieuw uit de PDF opgebouwd")
            elif vorige is None:
                verslag.vingerafdruk_toegevoegd += 1
            else:
                verslag.meldingen.append(f"OPNIEUW {dienst_id}: de liturgie is gewijzigd, dienst opnieuw verwerkt")
        verwerkt.add(dienst_id)
        nieuwe_wachtrij.extend(items)
        verslag.diensten += 1

    _behoud_bewerkingen(open_items, nieuwe_wachtrij)
    wachtrij = [i for i in open_items if i.dienst not in verwerkt] + nieuwe_wachtrij
    wachtrij.sort(key=lambda i: i.dienst)
    schrijf_wachtrij(omgeving.wachtrij, wachtrij)
    verslag.wachtrij = len(wachtrij)
    return verslag


def vingerafdruk_van(paden: list[Path]) -> str:
    """Vingerafdruk van de PDF('s) van een dienst: verandert als de inhoud verandert."""
    h = hashlib.sha256()
    for pad in sorted(paden):
        h.update(hashlib.sha256(pad.read_bytes()).digest())
    return h.hexdigest()[:16]


def _liturgieen_per_datum(archief: Path, cache: Path, verslag: Verslag) -> list[tuple[str, Liturgie, str]]:
    """Leest alle PDF's (met cache) en voegt liturgieën van dezelfde datum samen
    tot één, want er is één dienst per datum: de rijen worden achter elkaar
    gezet en de dubbele liederen vallen later weg. Geeft per datum de liturgie
    en de vingerafdruk van de bijbehorende PDF's."""
    per_datum: dict[str, Liturgie] = {}
    paden: dict[str, list[Path]] = {}
    for pad in sorted(archief.glob("*.pdf")):
        liturgie = lees_liturgie_gecached(pad, cache)
        uit_document, uit_bestand = bepaal_datum(liturgie.datum_tekst, liturgie.bestand)
        datum = uit_document or uit_bestand
        sleutel_datum = datum.isoformat() if datum else liturgie.bestand
        paden.setdefault(sleutel_datum, []).append(pad)
        eerder = per_datum.get(sleutel_datum)
        if eerder is None:
            per_datum[sleutel_datum] = liturgie
            continue
        verslag.meldingen.append(f"SAMENGEVOEGD {sleutel_datum}: {eerder.bestand.split(' + ')[-1]} en {liturgie.bestand}")
        eerder.bestand = f"{eerder.bestand} + {liturgie.bestand}"
        eerder.datum_tekst = eerder.datum_tekst or liturgie.datum_tekst
        eerder.bijzonderheden = ", ".join(b for b in (eerder.bijzonderheden, liturgie.bijzonderheden) if b and b != "-")
        eerder.begeleiding = eerder.begeleiding or liturgie.begeleiding
        eerder.rijen.extend(liturgie.rijen)
    return [(d, l, vingerafdruk_van(paden[d])) for d, l in per_datum.items()]


def verwerk_liturgie(liturgie: Liturgie, catalogus: Catalogus, aliassen: Aliassen, aanvullingen: list[Aanvulling], kenmerken: dict[str, list[str]], index: Zoekindex, verslag: Verslag) -> tuple[Dienst | None, list[WachtrijItem]]:
    uit_document, uit_bestand = bepaal_datum(liturgie.datum_tekst, liturgie.bestand)
    datum = uit_document or uit_bestand
    if datum is None:
        verslag.meldingen.append(f"OVERGESLAGEN {liturgie.bestand}: geen datum gevonden")
        return None, []
    if uit_document and uit_bestand and uit_document != uit_bestand:
        verslag.meldingen.append(f"LET OP {liturgie.bestand}: datum in document {uit_document} verschilt van bestandsnaam {uit_bestand}; document gebruikt")
    dienst_id = datum.isoformat()

    items: list[WachtrijItem] = []
    codes = _kenmerken_van_dienst(liturgie, kenmerken, aliassen, dienst_id, items)
    dienst = Dienst(datum=datum, begeleiding=normaliseer_begeleiding(liturgie.begeleiding), kenmerken=codes, bron=liturgie.bestand)

    vorig_label = ""
    eerste = True
    gezien: set[str] = set()
    for rij in liturgie.rijen:
        if is_liedrij(rij.label, rij.inhoud):
            ontl = ontleed(rij.inhoud, catalogus)
            k = koppel(rij.inhoud, ontl, catalogus, aliassen, index)
            moment = bepaal_moment(rij.label, rij.inhoud, vorig_label, eerste)
            eerste = False
            if k.genegeerd:
                vorig_label = rij.label
                continue
            if k.lied and k.lied in gezien:
                vorig_label = rij.label
                continue
            if k.lied:
                gezien.add(k.lied)
            plek = sleutel(dienst_id, rij.label, rij.inhoud) if k.herkenning == "onbekend" else None
            dienst.liederen.append(Vermelding(rij.inhoud, k.lied, k.herkenning, moment, plek))
            _tel(verslag, k.herkenning)
            if plek:
                items.append(_item_lied(dienst_id, rij.label, rij.inhoud, k, plek))
            elif MEERDERE_LABEL.search(rij.label):
                sl = sleutel(rij.label, rij.inhoud)
                if sl not in aliassen.negeer_rijen and not any(a.dienst == dienst_id and a.sleutel == sl for a in aanvullingen):
                    voorstel: dict = {"moment": moment}
                    tweede = _ander_lied(ontl, k.lied, index)
                    if tweede:
                        voorstel["lied"] = tweede
                    items.append(WachtrijItem(dienst_id, "kandidaat", rij.inhoud, "het label noemt meerdere liederen; het eerste is gekoppeld, voeg het tweede toe als aanvulling", label=rij.label, sleutel=sl, voorstel=voorstel))
            elif k.herkenning == "automatisch" and ontl.referenties and not k.titel_gebruikt:
                ander = _ander_lied(ontl, k.lied, index)
                if ander:
                    huidig = catalogus.liederen[k.lied]
                    items.append(WachtrijItem(dienst_id, "controle", rij.inhoud, f"gekoppeld aan {huidig.id} ({huidig.titel}) op grond van het nummer, maar de titel past beter bij {ander}; controleer het nummer", label=rij.label, kandidaten=k.kandidaten, voorstel={"lied": ander, "huidig": k.lied}))
        elif is_kandidaatrij(rij.inhoud, catalogus):
            sl = sleutel(rij.label, rij.inhoud)
            if sl in aliassen.negeer_rijen or any(a.dienst == dienst_id and a.sleutel == sl for a in aanvullingen):
                pass
            else:
                ontl = ontleed(rij.inhoud, catalogus)
                k = koppel(rij.inhoud, ontl, catalogus, aliassen, index)
                voorstel = {"moment": bepaal_moment(rij.label, rij.inhoud, vorig_label, False)}
                if k.lied:
                    voorstel["lied"] = k.lied
                elif k.voorstel:
                    voorstel.update(k.voorstel)
                items.append(WachtrijItem(dienst_id, "kandidaat", rij.inhoud, "geen liedrij, maar lijkt naar een lied te verwijzen", label=rij.label, sleutel=sl, kandidaten=k.kandidaten, voorstel=voorstel))
        vorig_label = rij.label

    if not dienst.liederen and not any(a.dienst == dienst_id for a in aanvullingen):
        verslag.meldingen.append(f"LEEG {dienst_id} ({liturgie.bestand}): geen liedregels gevonden; afwijkende opmaak? Vul zo nodig aan via aanvullingen.yaml")

    for a in aanvullingen:
        if a.dienst == dienst_id and a.lied not in gezien:
            if a.lied not in catalogus.liederen:
                verslag.meldingen.append(f"LET OP {dienst_id}: aanvulling verwijst naar onbekend lied {a.lied}")
                continue
            gezien.add(a.lied)
            dienst.liederen.append(Vermelding(a.ruw, a.lied, "handmatig", a.moment))
            _tel(verslag, "handmatig")

    return dienst, items


def _ander_lied(ontl, gekoppeld: str | None, index: Zoekindex) -> str | None:
    """Een ander catalogus-lied waarvan de titel vrijwel letterlijk in dezelfde cel staat,
    terwijl die titel niet ook bij het gekoppelde lied past."""
    for titel in ontl.titels:
        kandidaten = index.zoek(titel, None, limiet=3)
        if any(k.lied == gekoppeld and k.score >= DREMPEL_AUTOMATISCH for k in kandidaten):
            continue
        if kandidaten and kandidaten[0].score >= DREMPEL_ZEKER and kandidaten[0].lied != gekoppeld:
            return kandidaten[0].lied
    return None


def _kenmerken_van_dienst(liturgie: Liturgie, kenmerken: dict[str, list[str]], aliassen: Aliassen, dienst_id: str, items: list[WachtrijItem]) -> list[str]:
    sl = sleutel(liturgie.bijzonderheden)
    if sl in aliassen.bijzonderheden:
        return list(aliassen.bijzonderheden[sl])
    codes, rest = herken_kenmerken(liturgie.bijzonderheden, kenmerken)
    if rest:
        items.append(
            WachtrijItem(
                dienst_id,
                "bijzonderheden",
                liturgie.bijzonderheden,
                f"onverklaarde woorden in Bijzonderheden: {', '.join(rest)}",
                sleutel=sl,
                voorstel={"kenmerken": codes},
            )
        )
    return codes


def _item_lied(dienst_id: str, label: str, ruw: str, k: Koppeling, plek: str) -> WachtrijItem:
    return WachtrijItem(dienst_id, "lied", ruw, k.reden, label=label, sleutel=plek, kandidaten=k.kandidaten, voorstel=k.voorstel)


def _tel(verslag: Verslag, herkenning: str) -> None:
    verslag.vermeldingen += 1
    setattr(verslag, herkenning, getattr(verslag, herkenning) + 1)


def _pas_besluiten_toe(wachtrij: list[WachtrijItem], catalogus: Catalogus, aliassen: Aliassen, aanvullingen: list[Aanvulling], diensten_map: Path, accepteer_referenties: bool, verslag: Verslag) -> set[int]:
    """Past de besluiten uit de wachtrij toe; geeft de id's van de toegepaste items terug.
    Een besluit dat niet lukt blijft met zijn invulling in de wachtrij staan."""
    toegepast: set[int] = set()
    for item in wachtrij:
        if accepteer_referenties and not item.heeft_besluit and item.soort == "lied" and item.voorstel.get("bron") == "referentie" and "twijfel" not in item.voorstel:
            item.accepteer = True
        if not item.heeft_besluit:
            continue
        try:
            if item.soort == "bijzonderheden":
                _besluit_bijzonderheden(item, aliassen, diensten_map)
            elif item.soort == "kandidaat":
                _besluit_kandidaat(item, catalogus, aliassen, aanvullingen, diensten_map)
            elif item.soort == "controle":
                _besluit_controle(item, catalogus, aliassen, diensten_map)
            else:
                verslag.referenties_geleerd += _besluit_lied(item, catalogus, aliassen, diensten_map)
            toegepast.add(id(item))
        except ValueError as fout:
            verslag.meldingen.append(f"BESLUIT NIET TOEGEPAST ({item.dienst}, {item.ruw[:40]}): {fout}")
    return toegepast


def _herbeoordeel(items: list[WachtrijItem], catalogus: Catalogus, aliassen: Aliassen, aanvullingen: list[Aanvulling], index: Zoekindex, diensten_map: Path, verslag: Verslag) -> list[WachtrijItem]:
    """Bekijkt open wachtrij-items opnieuw tegen de huidige aliassen en catalogus. Wat nu
    wel herkend wordt, komt in de dienst te staan en verdwijnt uit de wachtrij. Zo krijgt
    een besluit over een regel ook effect op oudere diensten met dezelfde regel."""
    blijvend = []
    for item in items:
        if item.heeft_besluit:
            blijvend.append(item)
            continue
        if item.soort == "lied":
            k = koppel(item.ruw, ontleed(item.ruw, catalogus), catalogus, aliassen, index)
            if k.genegeerd:
                _verwijder_plek(diensten_map, item.dienst, item.sleutel)
                continue
            if k.lied:
                _vul_plek(diensten_map, item.dienst, item.sleutel, item.ruw, k.lied, k.herkenning)
                verslag.open_ingevuld += 1
                continue
        elif item.soort == "bijzonderheden":
            if item.sleutel in aliassen.bijzonderheden:
                _zet_kenmerken(diensten_map, item.dienst, aliassen.bijzonderheden[item.sleutel])
                continue
        elif item.soort == "kandidaat":
            if item.sleutel in aliassen.negeer_rijen or any(a.dienst == item.dienst and a.sleutel == item.sleutel for a in aanvullingen):
                continue
        elif item.soort == "controle":
            lied_id = aliassen.vermeldingen.get(normaliseer(item.ruw))
            if lied_id and lied_id in catalogus.liederen:
                _vervang_op_ruw(diensten_map, item.dienst, item.ruw, lied_id)
                continue
        blijvend.append(item)
    return blijvend


def _bewerk_dienst(map_: Path, dienst_id: str, bewerking) -> None:
    """Leest een dienst-bestand, past 'bewerking' toe op de inhoud en schrijft het terug
    als de bewerking True teruggeeft. Een ontbrekende dienst wordt overgeslagen."""
    inhoud = lees_dienst(map_, dienst_id)
    if inhoud is not None and bewerking(inhoud):
        schrijf_dienst_dict(map_, dienst_id, inhoud)


def _vul_plek(map_: Path, dienst_id: str, plek: str | None, ruw: str, lied_id: str, herkenning: str = "handmatig") -> None:
    """Vult de open plek van een niet-herkend lied. Staat het lied al elders in die
    dienst, dan vervalt de plek, want een lied telt een keer per dienst."""
    if not plek:
        return

    def bewerking(inhoud: dict) -> bool:
        liederen = inhoud.get("liederen") or []
        al_aanwezig = any(v.get("lied") == lied_id for v in liederen)
        nieuw, gewijzigd = [], False
        for v in liederen:
            if v.get("wachtrij") == plek and not v.get("lied"):
                gewijzigd = True
                if al_aanwezig:
                    continue
                v = Vermelding(ruw, lied_id, herkenning, v.get("moment")).as_dict()
                al_aanwezig = True
            nieuw.append(v)
        inhoud["liederen"] = nieuw
        return gewijzigd

    _bewerk_dienst(map_, dienst_id, bewerking)


def _verwijder_plek(map_: Path, dienst_id: str, plek: str | None) -> None:
    if not plek:
        return

    def bewerking(inhoud: dict) -> bool:
        voor = inhoud.get("liederen") or []
        inhoud["liederen"] = [v for v in voor if v.get("wachtrij") != plek]
        return len(inhoud["liederen"]) != len(voor)

    _bewerk_dienst(map_, dienst_id, bewerking)


def _voeg_lied_toe(map_: Path, dienst_id: str, ruw: str, lied_id: str, moment: str | None) -> None:
    def bewerking(inhoud: dict) -> bool:
        liederen = inhoud.setdefault("liederen", [])
        if any(v.get("lied") == lied_id for v in liederen):
            return False
        liederen.append(Vermelding(ruw, lied_id, "handmatig", moment).as_dict())
        return True

    _bewerk_dienst(map_, dienst_id, bewerking)


def _vervang_op_ruw(map_: Path, dienst_id: str, ruw: str, lied_id: str) -> None:
    def bewerking(inhoud: dict) -> bool:
        gewijzigd = False
        for i, v in enumerate(inhoud.get("liederen") or []):
            if v.get("ruw") == ruw and v.get("lied") != lied_id:
                inhoud["liederen"][i] = Vermelding(ruw, lied_id, "handmatig", v.get("moment")).as_dict()
                gewijzigd = True
        return gewijzigd

    _bewerk_dienst(map_, dienst_id, bewerking)


def _zet_kenmerken(map_: Path, dienst_id: str, codes: list[str]) -> None:
    def bewerking(inhoud: dict) -> bool:
        if inhoud.get("kenmerken") == list(codes):
            return False
        inhoud["kenmerken"] = list(codes)
        return True

    _bewerk_dienst(map_, dienst_id, bewerking)


def _besluit_bijzonderheden(item: WachtrijItem, aliassen: Aliassen, diensten_map: Path) -> None:
    if item.negeer:
        codes: list[str] = []
    elif item.kenmerken is not None:
        codes = list(item.kenmerken)
    else:
        codes = list(item.voorstel.get("kenmerken", []))
    aliassen.bijzonderheden[item.sleutel or sleutel(item.ruw)] = codes
    _zet_kenmerken(diensten_map, item.dienst, codes)


def _besluit_lied(item: WachtrijItem, catalogus: Catalogus, aliassen: Aliassen, diensten_map: Path) -> int:
    """Past een besluit op een liedregel toe; geeft terug hoeveel bundelverwijzingen
    de catalogus erbij leerde. Kiest de beheerder 'lied: X' voor een regel met een
    onbekend bundelnummer, dan krijgt X dat nummer als verwijzing."""
    norm = normaliseer(item.ruw)
    if item.negeer:
        aliassen.vermeldingen[norm] = "negeer"
        _verwijder_plek(diensten_map, item.dienst, item.sleutel)
        return 0
    lied_id = _lied_uit_besluit(item, catalogus)
    geleerd = 0
    if item.lied:
        refs = [Referentie(str(r["bundel"]), str(r["nummer"])) for r in (item.voorstel.get("nieuw") or {}).get("referenties", [])]
        geleerd = _leer_referenties(catalogus, lied_id, refs)
    if item.lied or item.voorstel.get("bron") != "referentie":
        aliassen.vermeldingen[norm] = lied_id
    _vul_plek(diensten_map, item.dienst, item.sleutel, item.ruw, lied_id)
    return geleerd


def _leer_referenties(catalogus: Catalogus, lied_id: str, referenties: list[Referentie]) -> int:
    """Voegt bundelverwijzingen toe aan een lied dat via zijn titel herkend is."""
    return sum(1 for r in referenties if catalogus.voeg_referentie_toe(lied_id, r))


def _besluit_controle(item: WachtrijItem, catalogus: Catalogus, aliassen: Aliassen, diensten_map: Path) -> None:
    """negeer bevestigt de huidige koppeling; lied of accepteer kiest het andere lied."""
    if item.negeer:
        lied_id = item.voorstel.get("huidig")
    elif item.lied:
        lied_id = item.lied
    else:
        lied_id = item.voorstel.get("lied")
    if not lied_id or lied_id not in catalogus.liederen:
        raise ValueError(f"lied {lied_id} bestaat niet in de catalogus")
    aliassen.vermeldingen[normaliseer(item.ruw)] = lied_id
    _vervang_op_ruw(diensten_map, item.dienst, item.ruw, lied_id)


def _besluit_kandidaat(item: WachtrijItem, catalogus: Catalogus, aliassen: Aliassen, aanvullingen: list[Aanvulling], diensten_map: Path) -> None:
    """Een aanvulling komt meteen in de dienst te staan, en wordt ook bewaard in
    aanvullingen.yaml zodat hij terugkomt als de dienst ooit opnieuw verwerkt wordt."""
    sl = item.sleutel or sleutel(item.label, item.ruw)
    if item.negeer:
        aliassen.negeer_rijen.append(sl)
        return
    if item.accepteer and "lied" in item.voorstel and "nieuw" not in item.voorstel:
        lied_id = item.voorstel["lied"]
        if lied_id not in catalogus.liederen:
            raise ValueError(f"voorgesteld lied {lied_id} bestaat niet")
    else:
        lied_id = _lied_uit_besluit(item, catalogus)
    aanvullingen.append(Aanvulling(item.dienst, sl, item.ruw, lied_id, item.voorstel.get("moment")))
    _voeg_lied_toe(diensten_map, item.dienst, item.ruw, lied_id, item.voorstel.get("moment"))


def _lied_uit_besluit(item: WachtrijItem, catalogus: Catalogus) -> str:
    if item.lied:
        if item.lied not in catalogus.liederen:
            raise ValueError(f"lied {item.lied} bestaat niet in de catalogus")
        return item.lied
    nieuw = item.voorstel.get("nieuw")
    if not (item.accepteer and nieuw):
        raise ValueError("geen lied en geen te accepteren voorstel")
    if not nieuw.get("titel"):
        raise ValueError("voorstel heeft geen titel")
    referenties = [Referentie(str(r["bundel"]), str(r["nummer"])) for r in nieuw.get("referenties", [])]
    for ref in referenties:
        bestaand = catalogus.op_referentie(ref)
        if len(bestaand) == 1:
            _leer_referenties(catalogus, bestaand[0].id, referenties)
            return bestaand[0].id
    lied_id = nieuw.get("id") or catalogus.vrij_id(nieuw["titel"])
    if lied_id in catalogus.liederen:
        lied_id = catalogus.vrij_id(lied_id)
    lied = Lied(
        id=lied_id,
        titel=nieuw["titel"],
        referenties=referenties,
        artiest=nieuw.get("artiest") or None,
        aliassen=[a for a in nieuw.get("aliassen", []) if normaliseer(a) != normaliseer(nieuw["titel"])],
        categorieen=list(nieuw.get("categorieen", [])),
    )
    catalogus.voeg_lied_toe(lied)
    return lied_id


def _behoud_bewerkingen(oud: list[WachtrijItem], nieuw: list[WachtrijItem]) -> None:
    """Neemt aangepaste voorstellen zonder besluit over in de nieuwe wachtrij."""
    per_sleutel = {(i.dienst, i.soort, normaliseer(i.ruw)): i for i in oud if not i.heeft_besluit}
    for item in nieuw:
        vorige = per_sleutel.get((item.dienst, item.soort, normaliseer(item.ruw)))
        if vorige and vorige.voorstel:
            item.voorstel = vorige.voorstel
