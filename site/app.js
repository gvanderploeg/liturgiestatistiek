/* Liturgiestatistiek Westerkerk: leest data/dataset.json en beantwoordt alle
   vragen in de browser. Opbouw: gegevens en filters, vragenlaag (pure
   functies op de lijst liedvermeldingen), weergaven per route. */

(function () {
  "use strict";

  const MAANDNAMEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  const DAGNAMEN = ["zo", "ma", "di", "wo", "do", "vr", "za"];
  const MOMENTNAMEN = { aanvang: "aanvang", kindmoment: "kindmoment", luisterlied: "luisterlied", zegenlied: "zegenlied" };
  const KENMERKNAMEN = {
    doop: "doop", avondmaal: "avondmaal", belijdenis: "belijdenis", bevestiging: "bevestiging",
    pinksteren: "Pinksteren", pasen: "Pasen", "goede-vrijdag": "Goede Vrijdag", kerst: "Kerst",
    advent: "Advent", startzondag: "startzondag", dankdag: "dankdag", biddag: "biddag",
  };

  const STANDAARD = {
    recentWeken: 4,
    tweedeKort: 3,
    tweedeLang: 12,
    vaakMaanden: 12,
    vaakMinimaal: 4,
    vergetenMinimaal: 3,
    vergetenMaanden: 12,
  };

  let data = null;
  let vermeldingen = [];
  const filters = { categorie: "", begeleiding: "", bundel: "", zoek: "" };
  const instellingen = laadInstellingen();

  /* ---------- hulpfuncties ---------- */

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function datum(iso) {
    const [j, m, d] = iso.split("-").map(Number);
    return new Date(j, m - 1, d);
  }

  function kort(d) {
    return `${d.getDate()} ${MAANDNAMEN[d.getMonth()]}`;
  }

  function metDag(d) {
    return `${DAGNAMEN[d.getDay()]} ${d.getDate()} ${MAANDNAMEN[d.getMonth()]} ${d.getFullYear()}`;
  }

  function lang(d) {
    return `${d.getDate()} ${["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"][d.getMonth()]} ${d.getFullYear()}`;
  }

  function wekenTerug(n) {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - 7 * n);
    return d;
  }

  function maandenTerug(n) {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setMonth(d.getMonth() - n);
    return d;
  }

  function laadInstellingen() {
    try {
      return Object.assign({}, STANDAARD, JSON.parse(localStorage.getItem("liturgiestatistiek.instellingen") || "{}"));
    } catch (e) {
      return Object.assign({}, STANDAARD);
    }
  }

  function bewaarInstellingen() {
    try {
      localStorage.setItem("liturgiestatistiek.instellingen", JSON.stringify(instellingen));
    } catch (e) {
      /* opslag niet beschikbaar; instellingen gelden dan alleen voor deze pagina */
    }
  }

  /* ---------- gegevens ---------- */

  function lied(id) {
    return data.liederen[id] || { titel: id };
  }

  function bronLabel(id) {
    const l = lied(id);
    const delen = [];
    if (l.artiest && Object.values(data.bundels).some((b) => b.naam === l.artiest)) delen.push(l.artiest);
    if (l.referenties && l.referenties.length) {
      const r = l.referenties[0];
      const b = data.bundels[r.bundel];
      delen.push(`${b ? b.afkorting : r.bundel} ${r.nummer}`);
    } else if (l.artiest && !delen.length) {
      delen.push(l.artiest);
    }
    return delen.join(" · ");
  }

  function bundelsVan(id) {
    const l = lied(id);
    const codes = new Set((l.referenties || []).map((r) => r.bundel));
    for (const code in data.bundels) {
      if (l.artiest && data.bundels[code].naam === l.artiest) codes.add(code);
    }
    return codes;
  }

  function bouwVermeldingen() {
    vermeldingen = [];
    for (const dienst of data.diensten) {
      const d = datum(dienst.datum);
      dienst.liederen.forEach((v, i) => {
        vermeldingen.push({ datum: d, iso: dienst.datum, dienst, lied: v.lied, moment: v.moment || null, ruw: v.ruw || null, volgnummer: i + 1 });
      });
    }
  }

  function gefilterd() {
    return vermeldingen.filter((v) => {
      if (filters.begeleiding && v.dienst.begeleiding !== filters.begeleiding) return false;
      if (!v.lied) return !filters.categorie && !filters.bundel;
      if (filters.categorie && !(lied(v.lied).categorieen || []).includes(filters.categorie)) return false;
      if (filters.bundel && !bundelsVan(v.lied).has(filters.bundel)) return false;
      return true;
    });
  }

  /* ---------- vragenlaag ---------- */

  function telPerLied(lijst) {
    const tel = new Map();
    for (const v of lijst) {
      if (!v.lied) continue;
      const t = tel.get(v.lied) || { aantal: 0, laatst: null, eerst: null, datums: [] };
      t.aantal += 1;
      t.datums.push(v.datum);
      if (!t.laatst || v.datum > t.laatst) t.laatst = v.datum;
      if (!t.eerst || v.datum < t.eerst) t.eerst = v.datum;
      tel.set(v.lied, t);
    }
    return tel;
  }

  function vanaf(lijst, grens) {
    return lijst.filter((v) => v.datum >= grens);
  }

  function tussen(lijst, van, tot) {
    return lijst.filter((v) => v.datum >= van && v.datum < tot);
  }

  function recent(lijst, weken) {
    const grens = wekenTerug(weken);
    const diensten = new Map();
    for (const v of vanaf(lijst, grens)) {
      if (!diensten.has(v.iso)) diensten.set(v.iso, { dienst: v.dienst, datum: v.datum, liederen: [] });
      diensten.get(v.iso).liederen.push(v);
    }
    return [...diensten.values()].sort((a, b) => b.datum - a.datum);
  }

  function tijdVoorTweedeKeer(lijst, kortMaanden, langMaanden) {
    const grensKort = maandenTerug(kortMaanden);
    const grensLang = maandenTerug(kortMaanden + langMaanden);
    const inKort = telPerLied(vanaf(lijst, grensKort));
    const inLang = telPerLied(tussen(lijst, grensLang, grensKort));
    const uit = [];
    for (const [id, t] of inKort) {
      if (t.aantal === 1 && !inLang.has(id)) uit.push({ lied: id, datum: t.laatst });
    }
    return uit.sort((a, b) => a.datum - b.datum);
  }

  function vaakGezongen(lijst, maanden, minimaal) {
    const tel = telPerLied(vanaf(lijst, maandenTerug(maanden)));
    return [...tel.entries()].filter(([, t]) => t.aantal >= minimaal).map(([id, t]) => ({ lied: id, aantal: t.aantal, laatst: t.laatst })).sort((a, b) => b.aantal - a.aantal || b.laatst - a.laatst);
  }

  function vergetenBekenden(lijst, minimaalOoit, maanden) {
    const grens = maandenTerug(maanden);
    const ooit = telPerLied(lijst);
    const recentTel = telPerLied(vanaf(lijst, grens));
    return [...ooit.entries()].filter(([id, t]) => t.aantal >= minimaalOoit && !recentTel.has(id)).map(([id, t]) => ({ lied: id, aantal: t.aantal, laatst: t.laatst })).sort((a, b) => b.aantal - a.aantal || a.laatst - b.laatst);
  }

  /* ---------- weergave: bouwstenen ---------- */

  function liedLink(id, klasse) {
    return `<a href="#/lied/${encodeURIComponent(id)}" class="${klasse || ""}">${esc(lied(id).titel)}</a>`;
  }

  function dienstLink(dienst) {
    const d = datum(dienst.datum);
    return `<a href="#/diensten/${dienst.datum}">${esc(metDag(d))}</a>`;
  }

  function dienstOmschrijving(dienst) {
    const delen = [dienst.begeleiding === "geen" ? "geen begeleiding" : dienst.begeleiding];
    for (const k of dienst.kenmerken) delen.push(KENMERKNAMEN[k] || k);
    return delen.join(" · ");
  }

  function keuze(naam, waarden, huidig, suffix) {
    const opties = waarden.map((w) => `<option value="${w}"${w === huidig ? " selected" : ""}>${w}</option>`).join("");
    return `<select data-instelling="${naam}">${opties}</select>${suffix ? " " + suffix : ""}`;
  }

  function aantalTekst(n) {
    return n === 1 ? "1e keer" : `${n}x`;
  }

  /* ---------- weergave: dashboard ---------- */

  function filterBalk() {
    const categorieen = [...new Set(Object.values(data.liederen).flatMap((l) => l.categorieen || []))].sort();
    const begeleidingen = [...new Set(data.diensten.map((d) => d.begeleiding))].sort();
    const bundelsInGebruik = new Set();
    for (const v of vermeldingen) if (v.lied) for (const c of bundelsVan(v.lied)) bundelsInGebruik.add(c);
    const bundels = [...bundelsInGebruik].sort((a, b) => data.bundels[a].naam.localeCompare(data.bundels[b].naam));
    const opt = (lijst, huidig, alles, naam) => `<option value=""${!huidig ? " selected" : ""}>${alles}</option>` + lijst.map((w) => `<option value="${esc(w)}"${w === huidig ? " selected" : ""}>${esc(naam ? naam(w) : w)}</option>`).join("");
    return `<div class="filters">
      <span class="label">Filter alle blokken:</span>
      <select data-filter="categorie"${categorieen.length ? "" : " disabled title='Nog geen liederen met een categorie'"}>${opt(categorieen, filters.categorie, "alle categorieën")}</select>
      <select data-filter="begeleiding">${opt(begeleidingen, filters.begeleiding, "band en orgel", (w) => (w === "geen" ? "geen begeleiding" : w))}</select>
      <select data-filter="bundel">${opt(bundels, filters.bundel, "alle bundels", (w) => data.bundels[w].naam)}</select>
      <span class="zoek"><input type="search" data-zoek placeholder="Zoek een lied…" value="${esc(filters.zoek)}" aria-label="Zoek een lied"></span>
    </div>`;
  }

  function zoekResultaten() {
    const q = filters.zoek.trim().toLowerCase();
    if (q.length < 2) return "";
    const ooit = telPerLied(vermeldingen);
    const treffers = Object.entries(data.liederen).filter(([id, l]) => l.titel.toLowerCase().includes(q) || bronLabel(id).toLowerCase().includes(q) || (l.artiest || "").toLowerCase().includes(q)).slice(0, 25);
    if (!treffers.length) return `<div class="blok"><p class="stil">Geen lied gevonden voor "${esc(filters.zoek)}".</p></div>`;
    const rijen = treffers.map(([id]) => {
      const t = ooit.get(id);
      return `<tr><td>${liedLink(id)}</td><td class="bron">${esc(bronLabel(id))}</td><td class="r stil">${t ? `${t.aantal}x, laatst ${kort(t.laatst)}` : "nooit gezongen"}</td></tr>`;
    }).join("");
    return `<div class="blok" style="margin-bottom:14px"><div class="blok-kop"><h2>Zoekresultaat</h2><span class="criterium">${treffers.length} liederen</span></div><table>${rijen}</table></div>`;
  }

  function blokRecent(lijst) {
    const ooit = telPerLied(vermeldingen);
    const diensten = recent(lijst, instellingen.recentWeken);
    let inhoud;
    if (!diensten.length) {
      inhoud = `<div class="leeg">Geen diensten in de afgelopen ${instellingen.recentWeken} weken. Laatste dienst: ${esc(lang(datum(data.laatste_dienst)))}.</div>`;
    } else {
      const rijen = [];
      for (const d of diensten) {
        rijen.push(`<tr class="tussenkop"><td colspan="3">${dienstLink(d.dienst)} · ${esc(dienstOmschrijving(d.dienst))}</td></tr>`);
        for (const v of d.liederen) {
          if (!v.lied) {
            rijen.push(`<tr><td class="stil">nog niet herkend lied</td><td class="bron"></td><td></td></tr>`);
            continue;
          }
          const t = ooit.get(v.lied);
          rijen.push(`<tr><td>${liedLink(v.lied)}</td><td class="bron">${esc(bronLabel(v.lied))}${v.moment ? ` · ${MOMENTNAMEN[v.moment]}` : ""}</td><td class="r stil">${aantalTekst(t.aantal)}</td></tr>`);
        }
      }
      inhoud = `<table>${rijen.join("")}</table><a class="meer" href="#/diensten">alle diensten…</a>`;
    }
    return `<div class="blok"><div class="blok-kop"><h2>Recent gezongen</h2><span class="criterium">afgelopen ${keuze("recentWeken", [2, 3, 4, 6, 8, 13], instellingen.recentWeken, "weken")}</span></div>${inhoud}</div>`;
  }

  function blokTweedeKeer(lijst) {
    const items = tijdVoorTweedeKeer(lijst, instellingen.tweedeKort, instellingen.tweedeLang);
    const criterium = `1x in ${keuze("tweedeKort", [1, 2, 3, 4, 6], instellingen.tweedeKort, "mnd")}, 0x in ${keuze("tweedeLang", [6, 12, 18, 24], instellingen.tweedeLang, "mnd ervoor")}`;
    let inhoud;
    if (!items.length) inhoud = `<div class="leeg">Geen liederen die aan dit criterium voldoen.</div>`;
    else inhoud = `<table>${items.slice(0, 12).map((i) => `<tr><td>${liedLink(i.lied)}</td><td class="bron">${esc(bronLabel(i.lied))}</td><td class="r stil">${kort(i.datum)}</td></tr>`).join("")}</table>` + (items.length > 12 ? `<span class="meer stil">en nog ${items.length - 12} liederen</span>` : "");
    return `<div class="blok"><div class="blok-kop"><h2>Tijd voor een tweede keer</h2><span class="criterium">${criterium}</span></div>${inhoud}</div>`;
  }

  function blokVaak(lijst) {
    const items = vaakGezongen(lijst, instellingen.vaakMaanden, instellingen.vaakMinimaal);
    const criterium = `minstens ${keuze("vaakMinimaal", [2, 3, 4, 5, 6, 8, 10], instellingen.vaakMinimaal, "x")} in ${keuze("vaakMaanden", [3, 6, 12, 24], instellingen.vaakMaanden, "mnd")}`;
    let inhoud;
    if (!items.length) inhoud = `<div class="leeg">Geen lied is zo vaak gezongen in deze periode.</div>`;
    else {
      const max = items[0].aantal;
      inhoud = `<table>${items.slice(0, 12).map((i) => `<tr><td>${liedLink(i.lied)}</td><td class="bron">${esc(bronLabel(i.lied))}</td><td class="r"><span class="balk" style="width:${Math.round(60 * i.aantal / max)}px"></span>${i.aantal}</td></tr>`).join("")}</table>`;
    }
    return `<div class="blok"><div class="blok-kop"><h2>Vaak gezongen</h2><span class="criterium">${criterium}</span></div>${inhoud}</div>`;
  }

  function blokVergeten(lijst) {
    const items = vergetenBekenden(lijst, instellingen.vergetenMinimaal, instellingen.vergetenMaanden);
    const criterium = `minstens ${keuze("vergetenMinimaal", [2, 3, 4, 5], instellingen.vergetenMinimaal, "x ooit")}, 0x in ${keuze("vergetenMaanden", [6, 9, 12, 18, 24], instellingen.vergetenMaanden, "mnd")}`;
    const eerste = datum(data.eerste_dienst);
    let inhoud;
    if (!items.length) {
      const toelichting = eerste > maandenTerug(instellingen.vergetenMaanden) ? ` De data begint ${esc(lang(eerste))}, dus dit blok wordt pas zinvol na ${instellingen.vergetenMaanden} maanden historie.` : "";
      inhoud = `<div class="leeg">Geen liederen die aan dit criterium voldoen.${toelichting}</div>`;
    } else inhoud = `<table>${items.slice(0, 12).map((i) => `<tr><td>${liedLink(i.lied)}</td><td class="bron">${esc(bronLabel(i.lied))}</td><td class="r stil">${i.aantal}x, laatst ${kort(i.laatst)} ${i.laatst.getFullYear()}</td></tr>`).join("")}</table>` + (items.length > 12 ? `<span class="meer stil">en nog ${items.length - 12} liederen</span>` : "");
    return `<div class="blok"><div class="blok-kop"><h2>Vergeten bekenden</h2><span class="criterium">${criterium}</span></div>${inhoud}</div>`;
  }

  function dashboard() {
    const lijst = gefilterd();
    return filterBalk() + zoekResultaten() + `<div class="rooster">${blokRecent(lijst)}<div class="kolom">${blokTweedeKeer(lijst)}${blokVaak(lijst)}${blokVergeten(lijst)}</div></div>`;
  }

  /* ---------- weergave: diensten ---------- */

  function dienstBlok(dienst, ooit) {
    const rijen = dienst.liederen.map((v) => {
      if (!v.lied) return `<tr><td class="moment"></td><td class="stil">nog niet herkend lied</td><td class="bron"></td><td></td></tr>`;
      const t = ooit.get(v.lied);
      return `<tr><td class="moment">${v.moment ? MOMENTNAMEN[v.moment] : ""}</td><td>${liedLink(v.lied)}</td><td class="bron">${esc(bronLabel(v.lied))}</td><td class="r stil">${aantalTekst(t.aantal)}</td></tr>`;
    }).join("");
    return `<section class="dienst" id="dienst-${dienst.datum}"><h2>${esc(metDag(datum(dienst.datum)))}</h2><div class="sub">${esc(dienstOmschrijving(dienst))}</div><table>${rijen}</table></section>`;
  }

  function diensten(geselecteerd) {
    const ooit = telPerLied(vermeldingen);
    let lijst = [...data.diensten].sort((a, b) => (a.datum < b.datum ? 1 : -1));
    if (geselecteerd) {
      const een = lijst.find((d) => d.datum === geselecteerd);
      if (een) return `<div class="pagina"><p><a href="#/diensten">Alle diensten</a></p>${dienstBlok(een, ooit)}</div>`;
    }
    return `<div class="pagina"><h1>Diensten</h1><p class="stil">${lijst.length} diensten, van ${esc(lang(datum(data.eerste_dienst)))} tot ${esc(lang(datum(data.laatste_dienst)))}. Het getal rechts is hoe vaak het lied in deze data voorkomt, inclusief deze dienst.</p>${lijst.map((d) => dienstBlok(d, ooit)).join("")}</div>`;
  }

  /* ---------- weergave: lied ---------- */

  function liedPagina(id) {
    const l = data.liederen[id];
    if (!l) return `<div class="pagina"><h1>Onbekend lied</h1><p><a href="#/">Terug naar het dashboard</a></p></div>`;
    const eigen = vermeldingen.filter((v) => v.lied === id).sort((a, b) => b.datum - a.datum);
    const bronnen = (l.referenties || []).map((r) => `${data.bundels[r.bundel] ? data.bundels[r.bundel].naam : r.bundel} ${r.nummer}`);
    if (l.artiest) bronnen.push(l.artiest);
    const tags = (l.categorieen || []).map((c) => `<span class="label-tag">${esc(c)}</span>`).join("");
    const rijen = eigen.map((v) => `<tr><td>${dienstLink(v.dienst)}</td><td class="bron">${esc(dienstOmschrijving(v.dienst))}</td><td class="bron">${v.moment ? MOMENTNAMEN[v.moment] : ""}</td></tr>`).join("");
    const zoek = encodeURIComponent(`${l.titel} ${l.artiest || (bronnen[0] || "")}`.trim());
    const links = [
      `<a href="https://kerkliedwiki.nl/index.php?search=${encodeURIComponent(l.titel)}" target="_blank" rel="noopener">Kerkliedwiki</a>`,
      `<a href="https://www.youtube.com/results?search_query=${zoek}" target="_blank" rel="noopener">YouTube</a>`,
      `<a href="https://open.spotify.com/search/${zoek}" target="_blank" rel="noopener">Spotify</a>`,
    ];
    return `<div class="pagina"><h1>${esc(l.titel)}</h1>
      <p class="stil">${esc(bronnen.join(" · "))}${tags ? " · " + tags : ""}${l.status && l.status !== "normaal" ? ` · <span class="label-tag">${esc(l.status)}</span>` : ""}</p>
      ${l.opmerking ? `<p>${esc(l.opmerking)}</p>` : ""}
      <p>${eigen.length ? `${eigen.length}x gezongen sinds ${esc(lang(datum(data.eerste_dienst)))}, laatst op ${esc(metDag(eigen[0].datum))}.` : `Nog niet gezongen sinds ${esc(lang(datum(data.eerste_dienst)))}.`}</p>
      ${tijdlijn(eigen)}
      ${eigen.length ? `<table>${rijen}</table>` : ""}
      <h2>Elders</h2><p>${links.join(" · ")}</p>
    </div>`;
  }

  function tijdlijn(eigen) {
    const eerste = datum(data.eerste_dienst);
    const nu = new Date();
    const maanden = [];
    const cursor = new Date(eerste.getFullYear(), eerste.getMonth(), 1);
    while (cursor <= nu && maanden.length < 60) {
      maanden.push({ jaar: cursor.getFullYear(), maand: cursor.getMonth(), aantal: 0 });
      cursor.setMonth(cursor.getMonth() + 1);
    }
    for (const v of eigen) {
      const m = maanden.find((x) => x.jaar === v.datum.getFullYear() && x.maand === v.datum.getMonth());
      if (m) m.aantal += 1;
    }
    const balken = maanden.map((m) => `<span class="${m.aantal ? "vol" : ""}" style="height:${m.aantal ? 12 + 14 * m.aantal : 5}px" title="${MAANDNAMEN[m.maand]} ${m.jaar}: ${m.aantal}x"></span>`).join("");
    const labels = maanden.map((m) => `<span>${m.maand === 0 || maanden.length <= 12 ? MAANDNAMEN[m.maand] + (m.maand === 0 ? " " + m.jaar : "") : ""}</span>`).join("");
    return `<div class="tijdlijn">${balken}</div><div class="maanden">${labels}</div>`;
  }

  /* ---------- weergave: over ---------- */

  function over() {
    const liederenGezongen = telPerLied(vermeldingen).size;
    return `<div class="pagina">
      <h1>Over deze gegevens</h1>
      <p>Deze site telt welke liederen in de erediensten van de Westerkerk gezongen zijn, als hulp bij het samenstellen van een liturgie. De gegevens komen uit de liturgieën zoals die voor elke dienst gepubliceerd worden. De site informeert; de mensen die de liturgie maken, kiezen.</p>
      <h2>Omvang</h2>
      <ul>
        <li>De data begint op ${esc(lang(datum(data.eerste_dienst)))} en loopt tot en met ${esc(lang(datum(data.laatste_dienst)))}.</li>
        <li>${data.diensten.length} diensten, ${vermeldingen.length} liedvermeldingen, ${liederenGezongen} verschillende liederen.</li>
        <li>Wat vóór de begindatum gezongen is, is niet meegeteld. "Voor het eerst" en "nooit" betekenen dus altijd: sinds ${esc(lang(datum(data.eerste_dienst)))}.</li>
        <li>Bijgewerkt op ${esc(lang(new Date(data.gegenereerd)))}.</li>
      </ul>
      <h2>De criteria</h2>
      <p>Elk blok op het dashboard toont zijn criterium in de kopregel en die is aan te passen. De standaardwaarden:</p>
      <ul>
        <li><strong>Recent gezongen</strong>: alle liederen uit de diensten van de afgelopen ${STANDAARD.recentWeken} weken, met per lied hoe vaak het in de hele dataset voorkomt.</li>
        <li><strong>Tijd voor een tweede keer</strong>: precies één keer gezongen in de afgelopen ${STANDAARD.tweedeKort} maanden en niet in de ${STANDAARD.tweedeLang} maanden daarvoor. Nieuwe liederen slijten in door herhaling.</li>
        <li><strong>Vaak gezongen</strong>: minstens ${STANDAARD.vaakMinimaal} keer in de afgelopen ${STANDAARD.vaakMaanden} maanden.</li>
        <li><strong>Vergeten bekenden</strong>: minstens ${STANDAARD.vergetenMinimaal} keer gezongen sinds het begin van de data, maar niet in de afgelopen ${STANDAARD.vergetenMaanden} maanden.</li>
      </ul>
      <p>Aangepaste criteria worden in je eigen browser bewaard. <button data-reset>Terug naar standaardwaarden</button></p>
      <h2>Zelf rekenen</h2>
      <p>Alle liedvermeldingen zijn te downloaden als <a href="data/liedvermeldingen.csv">CSV</a> (te openen in Excel of Google Sheets) en als <a href="data/dataset.json">JSON</a>.</p>
      <h2>Hoe het werkt</h2>
      <p>Een script leest uit elke liturgie-PDF alleen de liedregels en de kenmerken van de dienst (datum, begeleiding, bijzonderheden zoals doop of avondmaal). Namen van mensen worden niet opgeslagen. De liedregels worden herkend aan bundel en nummer of aan de titel; twijfelgevallen worden met de hand nagekeken. Hetzelfde lied in verschillende bundels wordt zoveel mogelijk als één lied geteld. Code en gegevens staan op <a href="https://github.com/gvanderploeg/liturgiestatistiek" target="_blank" rel="noopener">GitHub</a>.</p>
    </div>`;
  }

  /* ---------- routering en events ---------- */

  function route() {
    const hash = location.hash.replace(/^#\/?/, "");
    const [pad, ...rest] = hash.split("/");
    return { pad: pad || "dashboard", rest: rest.map(decodeURIComponent) };
  }

  function render() {
    const r = route();
    const el = document.getElementById("inhoud");
    let naam = r.pad;
    if (r.pad === "dashboard" || r.pad === "") el.innerHTML = dashboard();
    else if (r.pad === "diensten") el.innerHTML = diensten(r.rest[0]);
    else if (r.pad === "lied") { el.innerHTML = liedPagina(r.rest[0]); naam = "dashboard"; }
    else if (r.pad === "over") el.innerHTML = over();
    else el.innerHTML = dashboard();
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("actief", a.dataset.route === naam));
    if (r.pad !== "dashboard" && r.pad !== "") window.scrollTo(0, 0);
  }

  function koppelEvents() {
    const el = document.getElementById("inhoud");
    el.addEventListener("change", (e) => {
      const t = e.target;
      if (t.dataset.instelling) {
        instellingen[t.dataset.instelling] = Number(t.value);
        bewaarInstellingen();
        render();
      } else if (t.dataset.filter) {
        filters[t.dataset.filter] = t.value;
        render();
      }
    });
    let timer = null;
    el.addEventListener("input", (e) => {
      if (!("zoek" in e.target.dataset)) return;
      filters.zoek = e.target.value;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const positie = e.target.selectionStart;
        render();
        const veld = el.querySelector("[data-zoek]");
        if (veld) { veld.focus(); veld.setSelectionRange(positie, positie); }
      }, 200);
    });
    el.addEventListener("click", (e) => {
      if ("reset" in e.target.dataset) {
        Object.assign(instellingen, STANDAARD);
        bewaarInstellingen();
        render();
      }
    });
    window.addEventListener("hashchange", render);
  }

  function voettekst() {
    const eerste = lang(datum(data.eerste_dienst));
    const laatste = lang(datum(data.laatste_dienst));
    document.getElementById("voet").innerHTML = `De gegevens beginnen op ${esc(eerste)} en lopen tot en met de dienst van ${esc(laatste)}. Alles wat "voor het eerst" of "nooit" heet, is sinds die begindatum. <a href="#/over">Meer over deze gegevens</a>.`;
    document.getElementById("bijgewerkt").textContent = `t/m ${metDag(datum(data.laatste_dienst))}`;
  }

  fetch("data/dataset.json", { cache: "no-cache" })
    .then((r) => {
      if (!r.ok) throw new Error(`dataset niet gevonden (${r.status})`);
      return r.json();
    })
    .then((d) => {
      data = d;
      bouwVermeldingen();
      voettekst();
      koppelEvents();
      render();
    })
    .catch((fout) => {
      document.getElementById("inhoud").innerHTML = `<p class="stil">De gegevens konden niet geladen worden: ${esc(fout.message)}. Draai lokaal eerst <code>liturgiestatistiek publiceer</code>.</p>`;
    });
})();
