"""De verwerkingsstap: besluiten uit de wachtrij toepassen, alle PDF's in het
archief verwerken tot dienst-bestanden, en een nieuwe wachtrij schrijven."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .catalogus import Catalogus
from .extractie import Liturgie, lees_liturgie
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
    schrijf_aanvullingen,
    schrijf_dienst,
    schrijf_wachtrij,
)
from .tekst import normaliseer, sleutel


@dataclass
class Verslag:
    diensten: int = 0
    vermeldingen: int = 0
    automatisch: int = 0
    handmatig: int = 0
    onbekend: int = 0
    wachtrij: int = 0
    besluiten_toegepast: int = 0
    referenties_geleerd: int = 0
    meldingen: list[str] = field(default_factory=list)

    def tekst(self) -> str:
        regels = [
            f"diensten verwerkt:      {self.diensten}",
            f"liedvermeldingen:       {self.vermeldingen}",
            f"  automatisch herkend:  {self.automatisch}",
            f"  handmatig (alias):    {self.handmatig}",
            f"  onbekend:             {self.onbekend}",
            f"besluiten toegepast:    {self.besluiten_toegepast}",
            f"referenties geleerd:    {self.referenties_geleerd}",
            f"wachtrij-items:         {self.wachtrij}",
        ]
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


def verwerk(omgeving: Omgeving, accepteer_referenties: bool = False) -> Verslag:
    verslag = Verslag()
    catalogus = Catalogus.laad(omgeving.data)
    aliassen = Aliassen.laad(omgeving.data / ALIASSEN_BESTAND)
    aanvullingen = laad_aanvullingen(omgeving.data / AANVULLINGEN_BESTAND)
    kenmerken = laad_kenmerken(omgeving.data / KENMERKEN_BESTAND)

    oude_wachtrij = laad_wachtrij(omgeving.wachtrij)
    verslag.besluiten_toegepast = _pas_besluiten_toe(oude_wachtrij, catalogus, aliassen, aanvullingen, accepteer_referenties, verslag)
    if verslag.besluiten_toegepast:
        catalogus.schrijf()
        aliassen.schrijf(omgeving.data / ALIASSEN_BESTAND)
        schrijf_aanvullingen(omgeving.data / AANVULLINGEN_BESTAND, aanvullingen)

    index = Zoekindex(catalogus)
    nieuwe_wachtrij: list[WachtrijItem] = []
    geleerd_voor = verslag.referenties_geleerd
    for pad in sorted(omgeving.archief.glob("*.pdf")):
        liturgie = lees_liturgie(pad)
        dienst, items = verwerk_liturgie(liturgie, catalogus, aliassen, aanvullingen, kenmerken, index, verslag)
        if dienst is None:
            continue
        schrijf_dienst(omgeving.data / DIENSTEN_MAP, dienst)
        nieuwe_wachtrij.extend(items)
        verslag.diensten += 1
    if verslag.referenties_geleerd > geleerd_voor:
        catalogus.schrijf()

    _behoud_bewerkingen(oude_wachtrij, nieuwe_wachtrij)
    schrijf_wachtrij(omgeving.wachtrij, nieuwe_wachtrij)
    verslag.wachtrij = len(nieuwe_wachtrij)
    return verslag


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
                verslag.referenties_geleerd += _leer_referenties(catalogus, k.lied, k.geleerde_referenties)
            dienst.liederen.append(Vermelding(rij.inhoud, k.lied, k.herkenning, moment))
            _tel(verslag, k.herkenning)
            if k.herkenning == "onbekend":
                items.append(_item_lied(dienst_id, rij.label, rij.inhoud, k))
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


def _item_lied(dienst_id: str, label: str, ruw: str, k: Koppeling) -> WachtrijItem:
    return WachtrijItem(dienst_id, "lied", ruw, k.reden, label=label, kandidaten=k.kandidaten, voorstel=k.voorstel)


def _tel(verslag: Verslag, herkenning: str) -> None:
    verslag.vermeldingen += 1
    setattr(verslag, herkenning, getattr(verslag, herkenning) + 1)


def _pas_besluiten_toe(wachtrij: list[WachtrijItem], catalogus: Catalogus, aliassen: Aliassen, aanvullingen: list[Aanvulling], accepteer_referenties: bool, verslag: Verslag) -> int:
    aantal = 0
    for item in wachtrij:
        if accepteer_referenties and not item.heeft_besluit and item.soort == "lied" and item.voorstel.get("bron") == "referentie":
            item.accepteer = True
        if not item.heeft_besluit:
            continue
        try:
            if item.soort == "bijzonderheden":
                _besluit_bijzonderheden(item, aliassen)
            elif item.soort == "kandidaat":
                _besluit_kandidaat(item, catalogus, aliassen, aanvullingen)
            elif item.soort == "controle":
                _besluit_controle(item, catalogus, aliassen)
            else:
                _besluit_lied(item, catalogus, aliassen)
            aantal += 1
        except ValueError as fout:
            verslag.meldingen.append(f"BESLUIT NIET TOEGEPAST ({item.dienst}, {item.ruw[:40]}): {fout}")
    return aantal


def _besluit_bijzonderheden(item: WachtrijItem, aliassen: Aliassen) -> None:
    if item.negeer:
        codes: list[str] = []
    elif item.kenmerken is not None:
        codes = list(item.kenmerken)
    else:
        codes = list(item.voorstel.get("kenmerken", []))
    aliassen.bijzonderheden[item.sleutel or sleutel(item.ruw)] = codes


def _besluit_lied(item: WachtrijItem, catalogus: Catalogus, aliassen: Aliassen) -> None:
    norm = normaliseer(item.ruw)
    if item.negeer:
        aliassen.vermeldingen[norm] = "negeer"
        return
    lied_id = _lied_uit_besluit(item, catalogus)
    if item.lied:
        refs = [Referentie(str(r["bundel"]), str(r["nummer"])) for r in (item.voorstel.get("nieuw") or {}).get("referenties", [])]
        _leer_referenties(catalogus, lied_id, refs)
    if item.lied or item.voorstel.get("bron") != "referentie":
        aliassen.vermeldingen[norm] = lied_id


def _leer_referenties(catalogus: Catalogus, lied_id: str, referenties: list[Referentie]) -> int:
    """Voegt bundelverwijzingen toe aan een lied dat via zijn titel herkend is."""
    return sum(1 for r in referenties if catalogus.voeg_referentie_toe(lied_id, r))


def _besluit_controle(item: WachtrijItem, catalogus: Catalogus, aliassen: Aliassen) -> None:
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


def _besluit_kandidaat(item: WachtrijItem, catalogus: Catalogus, aliassen: Aliassen, aanvullingen: list[Aanvulling]) -> None:
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
        aliassen=list(nieuw.get("aliassen", [])),
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
