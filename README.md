# Liturgiestatistiek Westerkerk

Liedstatistiek uit de liturgieen van de Westerkerk, als hulpmiddel bij de liedkeuze. Het functioneel ontwerp staat in [docs/functioneel-ontwerp.md](docs/functioneel-ontwerp.md).

## Opzet

```
archief/            liturgie-PDF's (lokaal, niet in Git: bevatten namen)
werk/wachtrij.yaml  twijfelgevallen voor de beheerder (lokaal, niet in Git)
data/
  bundels.yaml      liedbundels (en bronnen als Sela) met hun schrijfwijzen
  kenmerken.yaml    dienstkenmerken en de trefwoorden waarmee ze herkend worden
  catalogus/        liederen, een YAML-bestand per bundelcode (opw.yaml, nlb.yaml, ...);
                    liederen zonder bundelverwijzing staan in overig.yaml
  aliassen.yaml     besluiten van de beheerder over liedregels en Bijzonderheden
  aanvullingen.yaml liederen die de beheerder aan een dienst toevoegt
  diensten/         een YAML-bestand per dienst: de publieke uitkomst
site/               de website: index.html, app.js, stijl.css
site/data/          dataset.json en liedvermeldingen.csv, gegenereerd (niet in Git)
liturgiestatistiek/ de verwerking en publicatie (Python)
tests/
.github/workflows/  bouwt site/data en publiceert site/ naar GitHub Pages bij elke push
```

De dienst-bestanden worden bij elke verwerking opnieuw opgebouwd uit de PDF's plus de besluiten in `aliassen.yaml`, `aanvullingen.yaml` en de catalogus. Correcties horen dus in die bestanden, niet in `data/diensten/`.

## Installatie

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Eenmalig de catalogus vullen uit het stamgegevens-sheet:

```bash
.venv/bin/liturgiestatistiek importeer-catalogus import/Liturgiestatistiek.xlsx
```

## PDF's ophalen uit Scipio

De liturgieen staan als bijlage bij de kerkdiensten in de agenda van de Scipio web-app (web.scipio-app.nl). Het commando `haal-op` logt in met je eigen account, loopt de agenda van de module pagina voor pagina terug in de tijd, neemt alleen de events van de kerkdienst-pagina, en downloadt elke liturgie-PDF die nog niet in `archief/` staat. Van de eventgegevens wordt niets bewaard.

```bash
SCIPIO_EMAIL=jij@voorbeeld.nl SCIPIO_WACHTWOORD=geheim .venv/bin/liturgiestatistiek haal-op --log
```

De eerste keer schrijft het commando een voorbeeldconfiguratie naar `werk/scipio.yaml` (buiten Git) met de ids van community, module en kerkdienst-pagina en een naamfilter voor de bijlagen; controleer die en draai opnieuw. Standaard kijkt het commando `terugkijk_dagen` (90) terug en een week vooruit, want de liturgie staat er al dagen voor de dienst. Voor het eenmalig inladen van de historie geef je een begindatum mee:

```bash
SCIPIO_EMAIL=jij@voorbeeld.nl SCIPIO_WACHTWOORD=geheim .venv/bin/liturgiestatistiek haal-op --vanaf 2024-09-01 --log
```

Wat al in `archief/` staat wordt nooit opnieuw gedownload, dus een tweede run over dezelfde periode kost alleen de paginaverzoeken. Met `--log` zie je elk verzoek met status, duur en omvang, zonder token. Bij een serverfout wacht het commando vijf seconden en probeert het een keer opnieuw; tussen pagina's zit een halve seconde pauze.

Dit gebruikt de interne API van een web-app die de leverancier als "in ontwikkeling" aanmerkt. Werkt het ineens niet meer, dan is de handmatige route er nog: de PDF zelf in `archief/` zetten.

## Wekelijkse routine van de beheerder

Zet de nieuwe liturgie-PDF in `archief/`, of haal die op met `haal-op`, en draai:

```bash
.venv/bin/liturgiestatistiek verwerk
```

De uitvoer meldt hoeveel liederen herkend zijn en hoeveel twijfelgevallen in `werk/wachtrij.yaml` staan. Open dat bestand en vul per item een besluit in:

- `lied: <id>` koppelt de regel aan een bestaand lied uit `data/catalogus/`.
- `accepteer: true` neemt het voorstel over: een nieuw lied (pas eventueel eerst `id` en `titel` aan) of de voorgestelde kenmerken. Bij een lied zonder bundelnummer is de voorgestelde titel de hele regel inclusief artiest, in de volgorde van de liturgie ("Geen afstand - Eline Bakker"); de kale titel gaat mee als alias zodat een volgende vermelding zonder artiest ook herkend wordt.
- `negeer: true` markeert de regel als geen lied, of het Bijzonderheden-veld als zonder kenmerk.
- `kenmerken: [doop, avondmaal]` kiest bij soort `bijzonderheden` zelf de kenmerken.

Bij items van soort `kandidaat` (een rij zonder liedlabel die toch naar een lied verwijst) mag je `ruw` inkorten tot alleen de liedtekst; die tekst komt in de dienst. Items van soort `controle` melden dat een lied via zijn bundelnummer gekoppeld is terwijl de titel beter bij een ander lied past, meestal een typefout in het nummer: `negeer: true` bevestigt de huidige koppeling, `accepteer: true` kiest het andere lied. Draai daarna opnieuw `verwerk`: de besluiten landen in `aliassen.yaml`, `aanvullingen.yaml` en `data/catalogus/overig.yaml`, de diensten worden bijgewerkt en de wachtrij krimpt. Items zonder besluit blijven staan. Commit vervolgens `data/`.

Voorstellen die op een bundelverwijzing berusten (bijvoorbeeld "NLB 216" dat nog niet in de catalogus staat) zijn eenduidig en kun je in een keer overnemen:

```bash
.venv/bin/liturgiestatistiek verwerk --accepteer-referenties
```

Om te zien wat de extractie en ontleding van een PDF maken:

```bash
.venv/bin/liturgiestatistiek toon "archief/20260920 Eredienst Westerkerk.pdf"
```

## Website

De website leest `site/data/dataset.json` en doet alle tellingen in de browser. Lokaal bekijken:

```bash
.venv/bin/liturgiestatistiek publiceer
```

```bash
python3 -m http.server 8765 --directory site
```

Daarna staat de site op http://localhost:8765. Op GitHub bouwt de workflow in `.github/workflows/publiceer.yml` de dataset bij elke push naar `main` en zet `site/` op GitHub Pages. Eenmalig instellen: in de repository onder Settings, Pages, de bron op "GitHub Actions" zetten.

De dashboardblokken tonen hun criterium in de kopregel; wie de drempels aanpast, krijgt die in de eigen browser bewaard. De pagina "Over" legt de criteria uit en linkt naar de CSV. De voettekst noemt de begindatum van de gegevens, omdat "voor het eerst" en "nooit" altijd relatief zijn aan die datum.

## Catalogus onderhouden

Elk lied in `data/catalogus/*.yaml` heeft een `id`, `titel`, en optioneel `referenties` (bundel en nummer), `artiest` (alleen informatief), `eerste_regel`, `aliassen` (andere titels), `categorieen`, `taal`, `status` (`blacklist` of `favoriet`) en `opmerking`. Een lied hoort in het bestand van de bundel van zijn eerste verwijzing; de verwerking zet nieuwe liederen daar zelf neer. Verhuizen tussen bestanden is knippen en plakken, het id blijft gelijk.

De ontleding van liedregels is bewust ruim gehouden: bundel plus nummer wordt precies herkend, de rest van de regel wordt grof in fragmenten geknipt en tolerant met de catalogus vergeleken. Een enkele misser is acceptabel, want elk besluit in de wachtrij wordt een alias die het de volgende keer in een keer goed doet. Staat hetzelfde lied twee keer in de catalogus (bijvoorbeeld als Sela-lied en als Opwekkingsnummer), voeg dan de referenties en aliassen samen onder een id en verwijder de ander; de verwerking meldt aliassen die naar een verdwenen id wijzen.

Wordt een lied via zijn titel herkend terwijl de liturgie er een bundelnummer bij noemt, dan leert de verwerking die verwijzing zelf bij. Voor psalmberijmingen gebeurt dat niet, omdat dezelfde psalm in verschillende berijmingen verschillende liederen zijn.

## Tests

```bash
.venv/bin/pytest
```

De tests op de hele verwerking gebruiken de PDF's in `archief/` en worden overgeslagen als die map leeg is. Een van die tests controleert dat geen woord uit de persoonsvelden van de PDF's in `data/` terechtkomt.
