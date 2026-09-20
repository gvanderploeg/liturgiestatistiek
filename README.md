# Liturgiestatistiek Westerkerk

Liedstatistiek uit de liturgieen van de Westerkerk, als hulpmiddel bij de liedkeuze. Het functioneel ontwerp staat in [docs/functioneel-ontwerp.md](docs/functioneel-ontwerp.md).

## Opzet

```
archief/            liturgie-PDF's (lokaal, niet in Git: bevatten namen)
werk/wachtrij.yaml  twijfelgevallen voor de beheerder (lokaal, niet in Git)
data/
  bundels.yaml      liedbundels en hun schrijfwijzen
  artiesten.yaml    artiesten en hun schrijfwijzen
  kenmerken.yaml    dienstkenmerken en de trefwoorden waarmee ze herkend worden
  catalogus/        liederen, een YAML-bestand per bron; overig.yaml groeit via de wachtrij
  aliassen.yaml     besluiten van de beheerder over liedregels en Bijzonderheden
  aanvullingen.yaml liederen die de beheerder aan een dienst toevoegt
  diensten/         een YAML-bestand per dienst: de publieke uitkomst
liturgiestatistiek/ de verwerking (Python)
tests/
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

## Wekelijkse routine van de beheerder

Zet de nieuwe liturgie-PDF in `archief/` en draai:

```bash
.venv/bin/liturgiestatistiek verwerk
```

De uitvoer meldt hoeveel liederen herkend zijn en hoeveel twijfelgevallen in `werk/wachtrij.yaml` staan. Open dat bestand en vul per item een besluit in:

- `lied: <id>` koppelt de regel aan een bestaand lied uit `data/catalogus/`.
- `accepteer: true` neemt het voorstel over: een nieuw lied (pas eventueel eerst `id`, `titel` en `artiest` aan) of de voorgestelde kenmerken.
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

## Catalogus onderhouden

Elk lied in `data/catalogus/*.yaml` heeft een `id`, `titel`, en optioneel `referenties` (bundel en nummer), `artiest`, `eerste_regel`, `aliassen` (andere titels), `categorieen`, `taal`, `status` (`blacklist` of `favoriet`) en `opmerking`. Staat hetzelfde lied twee keer in de catalogus (bijvoorbeeld als Sela-lied en als Opwekkingsnummer), voeg dan de referenties en aliassen samen onder een id en verwijder de ander; de verwerking meldt aliassen die naar een verdwenen id wijzen.

Wordt een lied via zijn titel herkend terwijl de liturgie er een bundelnummer bij noemt, dan leert de verwerking die verwijzing zelf bij. Voor psalmberijmingen gebeurt dat niet, omdat dezelfde psalm in verschillende berijmingen verschillende liederen zijn.

## Tests

```bash
.venv/bin/pytest
```

De tests op de hele verwerking gebruiken de PDF's in `archief/` en worden overgeslagen als die map leeg is. Een van die tests controleert dat geen woord uit de persoonsvelden van de PDF's in `data/` terechtkomt.
