"""Haalt liturgie-PDF's op uit de Scipio web-app (web.scipio-app.nl).

Dit gebruikt de interne API van de web-app, niet de officiele Socie-API
(die kent geen agenda of bestanden). De web-app is door de leverancier als
"in ontwikkeling" gemarkeerd; verwacht dat dit af en toe reparatie vraagt.

Stappen: inloggen met e-mail en wachtwoord (token van 15 minuten), de
agenda-events van de module pagina voor pagina ophalen (nieuwste eerst),
alleen de events van de kerkdienst-pagina nemen, en van elk event met een
liturgie-PDF het bestand downloaden naar archief/. Alleen de PDF wordt
bewaard; de eventgegevens (die namen bevatten) worden niet opgeslagen.

Met logging op DEBUG worden alle verzoeken gemeld, zonder token.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

API = "https://web.scipio-app.nl/api"
CONFIG_BESTAND = "scipio.yaml"
WACHT_TUSSEN_PAGINAS = 5.0
WACHT_NA_DOWNLOAD = 1.0
WACHT_NA_SERVERFOUT = 10.0
MAX_PAGINAS = 200

log = logging.getLogger("liturgiestatistiek.scipio")

KOPPEN = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "nl-NL,nl;q=0.9",
    "Platform": "Web",
    "AppVersion": "1000",
    "Language": "nl_nl",
    "Origin": "https://web.scipio-app.nl",
    "Referer": "https://web.scipio-app.nl/app/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
}


@dataclass
class ScipioConfig:
    community: str
    module: str
    pagina: str
    bestandsfilter: str = r"eredienst.*\.pdf$"
    terugkijk_dagen: int = 90
    per_pagina: int = 10
    lidmaatschap: str | None = None

    @classmethod
    def laad(cls, pad: Path) -> "ScipioConfig":
        with pad.open(encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        return cls(
            community=str(d["community"]),
            module=str(d["module"]),
            pagina=str(d["pagina"]),
            bestandsfilter=d.get("bestandsfilter", cls.bestandsfilter),
            terugkijk_dagen=int(d.get("terugkijk_dagen", cls.terugkijk_dagen)),
            per_pagina=int(d.get("per_pagina", cls.per_pagina)),
            lidmaatschap=str(d["lidmaatschap"]) if d.get("lidmaatschap") else None,
        )


VOORBEELD_CONFIG = """# Scipio-instellingen voor 'liturgiestatistiek haal-op'. Dit bestand blijft
# buiten Git (map werk/). De ids staan in de netwerkaanroepen van de web-app:
#   .../communities/<community>/modules/<module>/events?until=...
# en per event het veld page_id van de kerkdiensten (de agendapagina).
# E-mail en wachtwoord komen uit de omgevingsvariabelen SCIPIO_EMAIL en SCIPIO_WACHTWOORD.
community: 5f0ef48000aa224c7bc483ee
module: 5f0f325c00aa224c7bc5fd93
pagina: 5f0f325c00aa224c7bc5fd94
# Alleen bijlagen waarvan de naam hierop past (hoofdletterongevoelig) worden gedownload.
bestandsfilter: 'eredienst.*\\.pdf$'
# Standaard kijkt haal-op zoveel dagen terug: genoeg voor de wekelijkse routine.
# Voor het eenmalig inladen van de historie: haal-op --vanaf 2024-09-01
terugkijk_dagen: 90
# Aantal events per opgevraagde pagina (de web-app zelf gebruikt 10).
per_pagina: 10
# Het lidmaatschap-id wordt normaal zelf opgezocht. Lukt dat niet, zet hier de
# waarde van de header membership_id uit een verzoek in de browser.
# lidmaatschap: 5f0ef51200aa224c7bc48989
"""


class ScipioFout(Exception):
    pass


def _zonder_token(url: str) -> str:
    return url.split("?")[0]


def _verzoek(url: str, token: str | None = None, data: dict | None = None, pogingen: int = 2, membership: str | None = None) -> bytes:
    koppen = dict(KOPPEN)
    body = None
    if data is not None:
        koppen["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    if token:
        koppen["Authorization"] = f"bearer {token}"
    if membership:
        koppen["membership_id"] = membership
    methode = "POST" if data is not None else "GET"
    for poging in range(1, pogingen + 1):
        start = time.monotonic()
        req = urllib.request.Request(url, data=body, headers=koppen, method=methode)
        try:
            with urllib.request.urlopen(req, timeout=60) as antwoord:
                inhoud = antwoord.read()
                log.debug("%s %s -> %s, %d bytes, %.1fs", methode, _zonder_token(url), antwoord.status, len(inhoud), time.monotonic() - start)
                return inhoud
        except urllib.error.HTTPError as fout:
            kop = fout.read()[:300].decode("utf-8", "replace")
            log.debug("%s %s -> %s na %.1fs: %s", methode, _zonder_token(url), fout.code, time.monotonic() - start, kop.replace("\n", " ")[:120] or "(leeg antwoord)")
            if "Authorization=" not in url:
                log.debug("  query: %s", urllib.parse.urlsplit(url).query or "(geen)")
            log.debug("  antwoordheaders: %s", {k: v for k, v in fout.headers.items() if k.lower() not in ("set-cookie",)})
            if fout.code >= 500 and poging < pogingen:
                log.info("serverfout %s, na %.0f seconden nog een keer", fout.code, WACHT_NA_SERVERFOUT)
                time.sleep(WACHT_NA_SERVERFOUT)
                continue
            raise ScipioFout(f"{fout.code} bij {_zonder_token(url)}: {kop[:200]}") from None
        except urllib.error.URLError as fout:
            log.debug("%s %s -> geen verbinding: %s", methode, _zonder_token(url), fout.reason)
            raise ScipioFout(f"geen verbinding met {_zonder_token(url)}: {fout.reason}") from None
    raise ScipioFout(f"opgegeven na {pogingen} pogingen: {_zonder_token(url)}")


def login(email: str, wachtwoord: str) -> str:
    log.info("inloggen als %s", email)
    antwoord = json.loads(_verzoek(f"{API}/v2/auth/login", data={"email": email, "password": wachtwoord, "appType": "CHURCH", "totp": ""}))
    token = antwoord.get("accessToken")
    if not token:
        raise ScipioFout(f"inloggen gaf geen token: {antwoord}")
    log.debug("token geldig tot %s", antwoord.get("expires"))
    return token


def lidmaatschap(token: str, config: ScipioConfig) -> str:
    """Het lidmaatschap-id van de gebruiker in deze gemeente. De web-app stuurt
    dat als header membership_id mee bij elk verzoek binnen de gemeente."""
    if config.lidmaatschap:
        return config.lidmaatschap
    antwoord = json.loads(_verzoek(f"{API}/v2/me/memberships_available", token))
    for gemeente in antwoord if isinstance(antwoord, list) else []:
        if str((gemeente.get("community") or {}).get("_id")) != config.community:
            continue
        for lid in gemeente.get("memberships", []):
            lid_id = (lid.get("appendedMembership") or {}).get("_id") or lid.get("_id")
            if lid_id:
                log.debug("lidmaatschap %s voor gemeente %s", lid_id, config.community)
                return str(lid_id)
    log.debug("memberships_available gaf: %s", json.dumps(antwoord)[:500])
    raise ScipioFout(f"geen lidmaatschap gevonden voor gemeente {config.community}; zet 'lidmaatschap' in de configuratie (de header membership_id in de browser)")


def events_pagina(token: str, membership: str, config: ScipioConfig, skip: int, tot: datetime) -> list[dict]:
    params = urllib.parse.urlencode({"until": tot.strftime("%Y-%m-%dT00:00:00.000Z"), "sort": "beginDate:desc", "skip": skip, "limit": config.per_pagina}, safe=":")
    url = f"{API}/v2/app/communities/{config.community}/modules/{config.module}/events?{params}"
    inhoud = json.loads(_verzoek(url, token, membership=membership))
    if not isinstance(inhoud, list):
        raise ScipioFout(f"onverwacht antwoord op events: {str(inhoud)[:200]}")
    return inhoud


def herhalingen(token: str, membership: str, config: ScipioConfig, event_id: str) -> list[dict]:
    """Alle herhalingen van de reeks waar dit event toe behoort, elk met eigen bijlagen.
    De lijst op module-niveau laat bijlagen van herhalingen soms weg; hier staan ze wel."""
    url = f"{API}/v2/app/communities/{config.community}/modules/{config.module}/pages/{config.pagina}/events/{event_id}/recurrences"
    inhoud = json.loads(_verzoek(url, token, membership=membership))
    return inhoud if isinstance(inhoud, list) else []


def zoek_herhaling(lijst: list[dict], event: dict) -> dict | None:
    """De herhaling die bij dit event hoort: zelfde id, of anders zelfde begindatum."""
    for h in lijst:
        if h.get("_id") == event.get("_id"):
            return h
    datum = begindatum(event)
    for h in lijst:
        if datum and begindatum(h) == datum:
            return h
    return None


def is_reeks(event: dict) -> bool:
    return (event.get("repeat") or {}).get("type", "NO_REPEAT") != "NO_REPEAT"


def bestands_url(token: str, community: str, bestand_id: str) -> str:
    return f"{API}/v2/me/communities/{community}/files/{bestand_id}?Authorization=" + urllib.parse.quote(f"bearer {token}")


def download(token: str, community: str, bijlage: dict, doel: Path) -> None:
    url = bijlage.get("presignedUrl") or bestands_url(token, community, bijlage["_id"])
    log.debug("download %s via %s", bijlage.get("title"), "presignedUrl" if bijlage.get("presignedUrl") else "bestandseindpunt")
    inhoud = _verzoek(url)
    if not inhoud.startswith(b"%PDF"):
        raise ScipioFout(f"bestand {bijlage['_id']} is geen PDF (begint met {inhoud[:20]!r})")
    doel.parent.mkdir(parents=True, exist_ok=True)
    doel.write_bytes(inhoud)


def veilige_bestandsnaam(titel: str) -> str:
    naam = re.sub(r"[^\w .&()-]+", " ", titel, flags=re.UNICODE)
    return " ".join(naam.split()).strip() or "bestand.pdf"


def liturgie_bijlagen(event: dict, patroon: re.Pattern) -> list[dict]:
    return [f for f in event.get("files", []) if patroon.search(f.get("title", ""))]


def begindatum(event: dict) -> date | None:
    tekst = event.get("beginDate")
    if not tekst:
        return None
    try:
        return datetime.fromisoformat(tekst.replace("Z", "+00:00")).date()
    except ValueError:
        return None


@dataclass
class OphaalVerslag:
    paginas: int = 0
    events: int = 0
    kerkdiensten: int = 0
    bijlagen: int = 0
    reeksen: int = 0
    gedownload: list[str] = field(default_factory=list)
    al_aanwezig: int = 0
    zonder_bijlage: list[str] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)

    def tekst(self) -> str:
        regels = [
            f"pagina's opgevraagd:    {self.paginas}",
            f"reeksen nagevraagd:     {self.reeksen}",
            f"events bekeken:         {self.events}",
            f"  kerkdiensten:         {self.kerkdiensten}",
            f"  met liturgie-PDF:     {self.bijlagen}",
            f"  zonder liturgie-PDF:  {len(self.zonder_bijlage)}",
            f"al in archief:          {self.al_aanwezig}",
            f"gedownload:             {len(self.gedownload)}",
        ]
        regels += [f"  + {naam}" for naam in self.gedownload]
        regels += [f"  - {regel}" for regel in self.zonder_bijlage]
        regels += [f"FOUT {f}" for f in self.fouten]
        return "\n".join(regels)


def haal_op(config: ScipioConfig, email: str, wachtwoord: str, archief: Path, vanaf: date | None = None) -> OphaalVerslag:
    """Downloadt liturgie-PDF's van kerkdiensten vanaf 'vanaf' (standaard:
    terugkijk_dagen geleden) tot vandaag, zoals de web-app zelf de afgelopen
    agenda opvraagt. De dienst van vandaag komt bij de volgende run mee.
    Wat al in het archief staat wordt overgeslagen."""
    verslag = OphaalVerslag()
    token = login(email, wachtwoord)
    patroon = re.compile(config.bestandsfilter, re.IGNORECASE)
    nu = datetime.now(timezone.utc)
    if vanaf is None:
        vanaf = (nu - timedelta(days=config.terugkijk_dagen)).date()
    tot = nu
    membership = lidmaatschap(token, config)
    log.info("kerkdiensten van %s tot %s", vanaf, tot.date())
    reeksen: dict[str, list[dict]] = {}
    skip = 0
    while verslag.paginas < MAX_PAGINAS:
        events = events_pagina(token, membership, config, skip, tot)
        verslag.paginas += 1
        if not events:
            log.debug("lege pagina bij skip=%d, klaar", skip)
            break
        oudste = None
        for event in events:
            verslag.events += 1
            datum = begindatum(event)
            if datum and (oudste is None or datum < oudste):
                oudste = datum
            if event.get("page_id") != config.pagina:
                continue
            verslag.kerkdiensten += 1
            bijlagen = liturgie_bijlagen(event, patroon)
            if not bijlagen and is_reeks(event) and not (datum and datum < vanaf):
                reeks = (event.get("repeat") or {}).get("_id") or event.get("_id")
                if reeks not in reeksen:
                    try:
                        reeksen[reeks] = herhalingen(token, membership, config, event["_id"])
                        verslag.reeksen += 1
                        time.sleep(WACHT_NA_DOWNLOAD)
                    except ScipioFout as fout:
                        reeksen[reeks] = []
                        verslag.fouten.append(f"herhalingen van reeks bij {datum}: {fout}")
                herhaling = zoek_herhaling(reeksen[reeks], event)
                if herhaling:
                    bijlagen = liturgie_bijlagen(herhaling, patroon)
                    if bijlagen:
                        log.debug("kerkdienst %s: bijlage gevonden via de herhalingen van de reeks", datum)
            if not bijlagen:
                alle = [f.get("title", "?") for f in event.get("files", [])]
                log.info("kerkdienst %s (%s) zonder liturgie-PDF; bijlagen: %s", datum, event.get("name", "?"), ", ".join(alle) if alle else "geen")
                verslag.zonder_bijlage.append(f"{datum}: {', '.join(alle) if alle else 'geen bijlagen'}")
            for bijlage in bijlagen:
                verslag.bijlagen += 1
                doel = archief / veilige_bestandsnaam(bijlage["title"])
                if doel.exists():
                    verslag.al_aanwezig += 1
                    continue
                if datum and datum < vanaf:
                    continue
                try:
                    download(token, config.community, bijlage, doel)
                    verslag.gedownload.append(doel.name)
                    log.info("gedownload: %s (%s)", doel.name, datum)
                    time.sleep(WACHT_NA_DOWNLOAD)
                except ScipioFout as fout:
                    verslag.fouten.append(f"{bijlage['title']}: {fout}")
            

        log.debug("pagina %d: %d events, oudste %s", verslag.paginas, len(events), oudste)
        if oudste and oudste < vanaf:
            log.debug("oudste event %s ligt voor %s, klaar", oudste, vanaf)
            break
        if len(events) < config.per_pagina:
            break
        skip += len(events)
        time.sleep(WACHT_TUSSEN_PAGINAS)
    return verslag
