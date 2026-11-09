/* Liturgiestatistiek Westerkerk: leest data/dataset.json en beantwoordt alle
   vragen in de browser. Opbouw: gegevens en filters, vragenlaag (pure
   functies op de lijst liedvermeldingen), weergaven per route. */

(function () {
  "use strict";

  const MAANDNAMEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  const DAGNAMEN = ["zo", "ma", "di", "wo", "do", "vr", "za"];
  const MOMENTNAMEN = { aanvang: "aanvang", kindmoment: "kindmoment", luisterlied: "luisterlied", geloofsbelijdenis: "geloofsbelijdenis", zegenlied: "zegenlied" };
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
  let filtersOpen = false;
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

  function bundelBijNaam(naam) {
    for (const code in data.bundels) if (data.bundels[code].naam === naam) return code;
    return null;
  }

  function bronLabel(id) {
    /* Korte bron voor in lijsten: afkortingen, en een bron zonder nummer (zoals Sela)
       alleen als er geen nummer uit diezelfde bundel bij staat. */
    const l = lied(id);
    const refs = l.referenties || [];
    const delen = [];
    if (l.artiest) {
      const code = bundelBijNaam(l.artiest);
      if (!code) delen.push(l.artiest);
      else if (!refs.some((r) => r.bundel === code)) delen.push(data.bundels[code].afkorting);
    }
    if (refs.length) {
      const b = data.bundels[refs[0].bundel];
      delen.push(`${b ? b.afkorting : refs[0].bundel} ${refs[0].nummer}`);
    }
    return delen.join(" · ");
  }

  let bundelsOpNaamlengte = null;

  function kortTitel(titel) {
    /* Een titel die met een volle bundelnaam begint ("De Nieuwe Psalmberijming 146") krijgt de afkorting. */
    if (!bundelsOpNaamlengte) bundelsOpNaamlengte = Object.values(data.bundels).filter((b) => b.afkorting && b.afkorting !== b.naam).sort((a, b) => b.naam.length - a.naam.length);
    for (const b of bundelsOpNaamlengte) {
      if (titel.toLowerCase().startsWith(b.naam.toLowerCase() + " ")) return b.afkorting + titel.slice(b.naam.length);
    }
    return titel;
  }

  function gelijkeTekst(a, b) {
    return a.toLowerCase().replace(/\s+/g, " ").trim() === b.toLowerCase().replace(/\s+/g, " ").trim();
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

  function liedLink(id) {
    const titel = lied(id).titel;
    return `<a href="#/lied/${encodeURIComponent(id)}" title="${esc(titel)}">${esc(kortTitel(titel))}</a>`;
  }

  function liedCellen(id, moment) {
    /* Titel en bron als twee cellen van een lijsttabel. De bron blijft leeg als die
       gelijk is aan de (verkorte) titel; het moment verdwijnt op smalle schermen. */
    let bron = bronLabel(id);
    if (bron && gelijkeTekst(bron, kortTitel(lied(id).titel))) bron = "";
    if (!bron) {
      const extra = moment ? `<span class="alleen-breed bron"> · ${MOMENTNAMEN[moment]}</span>` : "";
      return `<td colspan="2">${liedLink(id)}${extra}</td>`;
    }
    const extra = moment ? `<span class="alleen-breed"> · ${MOMENTNAMEN[moment]}</span>` : "";
    return `<td>${liedLink(id)}</td><td class="bron" title="${esc(bron)}">${esc(bron)}${extra}</td>`;
  }

  function lijstTabel(kolommen, rijen, klasse) {
    /* Tabel met vaste kolombreedtes: elke regel blijft een regel, wat niet past wordt afgekapt. */
    const cols = kolommen.map((k) => `<col class="k-${k}">`).join("");
    return `<table class="lijst${klasse ? " " + klasse : ""}"><colgroup>${cols}</colgroup>${rijen.join("")}</table>`;
  }

  function maandJaar(d) {
    return `${MAANDNAMEN[d.getMonth()]} ${d.getFullYear()}`;
  }

  function kortMetJaar(d) {
    return `${d.getDate()} ${MAANDNAMEN[d.getMonth()]} ${d.getFullYear()}`;
  }

  function dienstLink(dienst) {
    const d = datum(dienst.datum);
    return `<a href="#/diensten/${dienst.datum}">${esc(metDag(d))}</a>`;
  }

  const KENMERKFAMILIE = {
    doop: "sacrament", avondmaal: "sacrament", belijdenis: "sacrament", bevestiging: "sacrament",
    advent: "feest", kerst: "feest", pasen: "feest", pinksteren: "feest", "goede-vrijdag": "feest",
  };

  function kenmerkLabel(k) {
    return `<span class="label label-${KENMERKFAMILIE[k] || "overig"}">${esc(KENMERKNAMEN[k] || k)}</span>`;
  }

  function isGepland(dienst) {
    const vandaag = new Date();
    vandaag.setHours(0, 0, 0, 0);
    return datum(dienst.datum) > vandaag;
  }

  function dienstOmschrijving(dienst) {
    const beg = dienst.begeleiding === "geen" ? "geen begeleiding" : dienst.begeleiding;
    const gepland = isGepland(dienst) ? ` <span class="label label-gepland" title="Deze dienst moet nog plaatsvinden; de liturgie kan nog veranderen">gepland</span>` : "";
    return esc(beg) + gepland + dienst.kenmerken.map((k) => " " + kenmerkLabel(k)).join("");
  }

  function telKlasse(n) {
    return n === 0 ? "tel-0" : n === 1 ? "tel-1" : n <= 3 ? "tel-2" : n <= 6 ? "tel-3" : "tel-4";
  }

  function telBadge(n, uitleg) {
    const tekst = n === 0 ? "nooit" : `${n}x`;
    const titel = uitleg || (n === 1 ? "voor het eerst gezongen sinds het begin van de data" : `${n}x gezongen sinds het begin van de data`);
    return `<span class="tel ${telKlasse(n)}" title="${esc(titel)}">${tekst}</span>`;
  }

  function keuze(naam, waarden, huidig, suffix, soort) {
    /* Keuzelijst voor een criterium. Op het dashboard (soort "instelling") wordt de keuze
       in de browser bewaard; op de liederenpagina (soort "param") staat die in de link. */
    const opties = waarden.map((w) => `<option value="${w}"${w === huidig ? " selected" : ""}>${w}</option>`).join("");
    return `<select data-${soort || "instelling"}="${naam}">${opties}</select>${suffix ? " " + suffix : ""}`;
  }

  /* De vragen die de liederenpagina kan beantwoorden. 'params' koppelt de parameters
     in de link aan de instellingen die het dashboard voor hetzelfde blok gebruikt. */
  const VRAGEN = {
    alle: { titel: "Alle gezongen liederen", sort: "laatst", richting: "af", params: {} },
    tweede: { titel: "Tijd voor een tweede keer", sort: "laatst", richting: "op", params: { kort: "tweedeKort", lang: "tweedeLang" } },
    vaak: { titel: "Vaak gezongen", sort: "aantal", richting: "af", params: { min: "vaakMinimaal", mnd: "vaakMaanden" } },
    vergeten: { titel: "Vergeten bekenden", sort: "aantal", richting: "af", params: { min: "vergetenMinimaal", mnd: "vergetenMaanden" } },
  };

  const FILTERPARAMS = { categorie: "categorie", begeleiding: "begeleiding", bundel: "bundel", zoek: "q" };

  function lijstUrl(vraag, zoek) {
    /* Link naar de volledige lijst voor een vraag, met de criteria en filters van dit moment. */
    const p = new URLSearchParams({ vraag });
    for (const [param, instelling] of Object.entries(VRAGEN[vraag].params)) p.set(param, instellingen[instelling]);
    for (const f of ["categorie", "begeleiding", "bundel"]) if (filters[f]) p.set(FILTERPARAMS[f], filters[f]);
    if (zoek) p.set("q", zoek);
    return "#/liederen?" + p.toString();
  }

  function urlMet(params, wijzigingen) {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(wijzigingen)) {
      if (v === "" || v == null) p.delete(k);
      else p.set(k, v);
    }
    return "#/liederen?" + p.toString();
  }

  function meerLink(vraag, aantal) {
    return `<a class="meer" href="${lijstUrl(vraag)}">${aantal === 1 ? "als lijst" : `alle ${aantal} liederen`}</a>`;
  }

  /* ---------- weergave: dashboard ---------- */

  function filterBalk(label) {
    const categorieen = [...new Set(Object.values(data.liederen).flatMap((l) => l.categorieen || []))].sort();
    const begeleidingen = [...new Set(data.diensten.map((d) => d.begeleiding))].sort();
    const bundelsInGebruik = new Set();
    for (const v of vermeldingen) if (v.lied) for (const c of bundelsVan(v.lied)) bundelsInGebruik.add(c);
    const bundels = [...bundelsInGebruik].sort((a, b) => data.bundels[a].naam.localeCompare(data.bundels[b].naam));
    const opt = (lijst, huidig, alles, naam) => `<option value=""${!huidig ? " selected" : ""}>${alles}</option>` + lijst.map((w) => `<option value="${esc(w)}"${w === huidig ? " selected" : ""}>${esc(naam ? naam(w) : w)}</option>`).join("");
    const actief = [filters.categorie, filters.begeleiding, filters.bundel].filter(Boolean).length;
    return `<div class="filters${filtersOpen ? " open" : ""}">
      <button type="button" class="filterknop" data-filterknop aria-expanded="${filtersOpen}">Filters${actief ? ` (${actief})` : ""}</button>
      <span class="filterkeuze">
        <span class="label">${label || "Filter alle blokken:"}</span>
        <select data-filter="categorie"${categorieen.length ? "" : " disabled title='Nog geen liederen met een categorie'"}>${opt(categorieen, filters.categorie, "alle categorieën")}</select>
        <select data-filter="begeleiding">${opt(begeleidingen, filters.begeleiding, "band en orgel", (w) => (w === "geen" ? "geen begeleiding" : w))}</select>
        <select data-filter="bundel">${opt(bundels, filters.bundel, "alle bundels", (w) => data.bundels[w].naam)}</select>
      </span>
      <span class="zoek"><input type="search" data-zoek placeholder="Zoek een lied…" value="${esc(filters.zoek)}" aria-label="Zoek een lied"></span>
    </div>`;
  }

  function zoekResultaten() {
    const q = filters.zoek.trim().toLowerCase();
    if (q.length < 2) return "";
    const ooit = telPerLied(vermeldingen);
    const alleTreffers = Object.entries(data.liederen).filter(([id, l]) => past(id, q) || (l.artiest || "").toLowerCase().includes(q));
    const treffers = alleTreffers.slice(0, 25);
    if (!treffers.length) return `<div class="blok"><p class="stil">Geen lied gevonden voor "${esc(filters.zoek)}".</p></div>`;
    const rijen = treffers.map(([id]) => {
      const t = ooit.get(id);
      return `<tr>${liedCellen(id)}<td class="r stil">${t ? `${t.aantal}x · ${maandJaar(t.laatst)}` : "nooit"}</td></tr>`;
    });
    const meer = alleTreffers.length > treffers.length ? `<a class="meer" href="${lijstUrl("alle", filters.zoek)}">alle gezongen liederen met "${esc(filters.zoek)}"</a>` : "";
    return `<div class="blok" style="margin-bottom:14px"><div class="blok-kop"><h2>Zoekresultaat</h2><span class="criterium">${alleTreffers.length} liederen</span></div>${lijstTabel(["titel", "bron", "laatst"], rijen)}${meer}</div>`;
  }

  function past(id, q) {
    const l = lied(id);
    return l.titel.toLowerCase().includes(q) || kortTitel(l.titel).toLowerCase().includes(q) || bronLabel(id).toLowerCase().includes(q);
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
        rijen.push(`<tr class="tussenkop"><td colspan="3">${dienstLink(d.dienst)} · ${dienstOmschrijving(d.dienst)}</td></tr>`);
        for (const v of d.liederen) {
          if (!v.lied) {
            rijen.push(`<tr><td class="stil">nog niet herkend lied</td><td class="bron"></td><td></td></tr>`);
            continue;
          }
          const t = ooit.get(v.lied);
          rijen.push(`<tr>${liedCellen(v.lied, v.moment)}<td class="r">${telBadge(t.aantal)}</td></tr>`);
        }
      }
      inhoud = lijstTabel(["titel", "bronmoment", "tel"], rijen) + `<a class="meer" href="#/diensten">alle diensten…</a>`;
    }
    return `<div class="blok"><div class="blok-kop"><h2>Recent gezongen</h2><span class="criterium">afgelopen ${keuze("recentWeken", [2, 3, 4, 6, 8, 13], instellingen.recentWeken, "weken")}</span></div>${inhoud}</div>`;
  }

  function blokTweedeKeer(lijst) {
    const items = tijdVoorTweedeKeer(lijst, instellingen.tweedeKort, instellingen.tweedeLang);
    const criterium = `1x in ${keuze("tweedeKort", [1, 2, 3, 4, 6], instellingen.tweedeKort, "mnd")}, 0x in ${keuze("tweedeLang", [6, 12, 18, 24], instellingen.tweedeLang, "mnd ervoor")}`;
    let inhoud;
    if (!items.length) inhoud = `<div class="leeg">Geen liederen die aan dit criterium voldoen.</div>`;
    else inhoud = lijstTabel(["titel", "bron", "datum"], items.slice(0, 12).map((i) => `<tr>${liedCellen(i.lied)}<td class="r stil">${kort(i.datum)}</td></tr>`)) + meerLink("tweede", items.length);
    return `<div class="blok"><div class="blok-kop"><h2>Tijd voor een tweede keer</h2><span class="criterium">${criterium}</span></div>${inhoud}</div>`;
  }

  function blokVaak(lijst) {
    const items = vaakGezongen(lijst, instellingen.vaakMaanden, instellingen.vaakMinimaal);
    const criterium = `minstens ${keuze("vaakMinimaal", [2, 3, 4, 5, 6, 8, 10], instellingen.vaakMinimaal, "x")} in ${keuze("vaakMaanden", [3, 6, 12, 24], instellingen.vaakMaanden, "mnd")}`;
    let inhoud;
    if (!items.length) inhoud = `<div class="leeg">Geen lied is zo vaak gezongen in deze periode.</div>`;
    else {
      const max = items[0].aantal;
      inhoud = lijstTabel(["titel", "bron", "balk"], items.slice(0, 12).map((i) => `<tr>${liedCellen(i.lied)}<td class="r"><span class="balk" style="width:${Math.round(45 * i.aantal / max)}px"></span>${i.aantal}</td></tr>`)) + meerLink("vaak", items.length);
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
    } else inhoud = lijstTabel(["titel", "bron", "laatst"], items.slice(0, 12).map((i) => `<tr>${liedCellen(i.lied)}<td class="r stil" title="laatst gezongen ${esc(lang(i.laatst))}">${i.aantal}x · ${maandJaar(i.laatst)}</td></tr>`)) + meerLink("vergeten", items.length);
    return `<div class="blok"><div class="blok-kop"><h2>Vergeten bekenden</h2><span class="criterium">${criterium}</span></div>${inhoud}</div>`;
  }

  function dashboard() {
    const lijst = gefilterd();
    return filterBalk() + zoekResultaten() + `<div class="rooster">${blokRecent(lijst)}<div class="kolom">${blokTweedeKeer(lijst)}${blokVaak(lijst)}${blokVergeten(lijst)}</div></div>`;
  }

  /* ---------- weergave: liederen (volledige lijsten) ---------- */

  const KOLOMMEN = {
    titel: { kop: "titel", standaard: "op", sleutel: (r) => kortTitel(lied(r.lied).titel).toLowerCase() },
    bron: { kop: "bron", standaard: "op", sleutel: (r) => bronLabel(r.lied).toLowerCase() },
    aantal: { kop: "aantal", standaard: "af", sleutel: (r) => r.aantal },
    eerst: { kop: "eerste keer", standaard: "af", sleutel: (r) => r.eerst.getTime() },
    laatst: { kop: "laatst", standaard: "af", sleutel: (r) => r.laatst.getTime() },
  };

  function liederenPagina(params) {
    /* Een volledige, sorteerbare lijst voor een van de vragen. Alles wat de lijst bepaalt
       (vraag, criterium, filters, zoekterm, sortering) staat in de link, zodat die te delen is. */
    const vraag = VRAGEN[params.get("vraag")] ? params.get("vraag") : "alle";
    const def = VRAGEN[vraag];
    for (const [filter, param] of Object.entries(FILTERPARAMS)) filters[filter] = params.get(param) || "";
    const waarde = (param) => {
      const v = Number(params.get(param));
      return Number.isFinite(v) && v > 0 ? v : instellingen[def.params[param]];
    };

    const lijst = gefilterd();
    const ooit = telPerLied(lijst);
    const metStats = (id, aantal) => ({ lied: id, aantal: aantal == null ? ooit.get(id).aantal : aantal, eerst: ooit.get(id).eerst, laatst: ooit.get(id).laatst });
    let rijen;
    let criterium = "";
    let aantalUitleg = null;
    if (vraag === "tweede") {
      const k = waarde("kort"), l = waarde("lang");
      rijen = tijdVoorTweedeKeer(lijst, k, l).map((i) => metStats(i.lied));
      criterium = `1x in ${keuze("kort", [1, 2, 3, 4, 6], k, "mnd", "param")}, 0x in ${keuze("lang", [6, 12, 18, 24], l, "mnd ervoor", "param")}`;
    } else if (vraag === "vaak") {
      const min = waarde("min"), mnd = waarde("mnd");
      rijen = vaakGezongen(lijst, mnd, min).map((i) => metStats(i.lied, i.aantal));
      criterium = `minstens ${keuze("min", [2, 3, 4, 5, 6, 8, 10], min, "x", "param")} in ${keuze("mnd", [3, 6, 12, 24], mnd, "mnd", "param")}`;
      aantalUitleg = `in de afgelopen ${mnd} maanden`;
    } else if (vraag === "vergeten") {
      const min = waarde("min"), mnd = waarde("mnd");
      rijen = vergetenBekenden(lijst, min, mnd).map((i) => metStats(i.lied));
      criterium = `minstens ${keuze("min", [2, 3, 4, 5], min, "x ooit", "param")}, 0x in ${keuze("mnd", [6, 9, 12, 18, 24], mnd, "mnd", "param")}`;
    } else {
      rijen = [...ooit.keys()].map((id) => metStats(id));
    }

    const q = filters.zoek.trim().toLowerCase();
    if (q) rijen = rijen.filter((r) => past(r.lied, q));

    const gevraagd = params.get("sort");
    const sort = KOLOMMEN[gevraagd] ? gevraagd : def.sort;
    const richting = ["op", "af"].includes(params.get("richting")) ? params.get("richting") : KOLOMMEN[gevraagd] ? KOLOMMEN[sort].standaard : def.richting;
    const sleutel = KOLOMMEN[sort].sleutel;
    const titelSleutel = KOLOMMEN.titel.sleutel;
    rijen.sort((a, b) => {
      const x = sleutel(a), y = sleutel(b);
      const verschil = typeof x === "string" ? x.localeCompare(y, "nl") : x - y;
      return (richting === "op" ? verschil : -verschil) || titelSleutel(a).localeCompare(titelSleutel(b), "nl");
    });

    const kop = (k) => {
      const actief = k === sort;
      const nieuw = actief ? (richting === "op" ? "af" : "op") : KOLOMMEN[k].standaard;
      const tekst = k === "aantal" && aantalUitleg ? `in ${waarde("mnd")} mnd` : KOLOMMEN[k].kop;
      const klassen = ["sorteer", k === "eerst" ? "kol-eerst" : "", k === "bron" ? "kol-bron" : "", k === "aantal" || k === "eerst" || k === "laatst" ? "r" : "", actief ? `gesorteerd ${richting}` : ""].filter(Boolean).join(" ");
      return `<th class="${klassen}"><a href="${urlMet(params, { sort: k, richting: nieuw })}">${tekst}</a></th>`;
    };
    const regels = rijen.map((r) => `<tr>${liedCellen(r.lied)}<td class="r">${telBadge(r.aantal, aantalUitleg ? `${r.aantal}x ${aantalUitleg}` : null)}</td><td class="r stil datumcel kol-eerst">${kortMetJaar(r.eerst)}</td><td class="r stil datumcel">${kortMetJaar(r.laatst)}</td></tr>`);
    const vraagKeuze = `<select data-vraag aria-label="Welke lijst">${Object.entries(VRAGEN).map(([k, v]) => `<option value="${k}"${k === vraag ? " selected" : ""}>${v.titel}</option>`).join("")}</select>`;
    const tabel = rijen.length
      ? `<table class="lijst banden volledig"><colgroup><col class="k-titel"><col class="k-bron"><col class="k-tel"><col class="k-eerst"><col class="k-datumjaar"></colgroup><thead><tr>${["titel", "bron", "aantal", "eerst", "laatst"].map(kop).join("")}</tr></thead><tbody>${regels.join("")}</tbody></table>`
      : `<div class="leeg">Geen liederen die hieraan voldoen.</div>`;
    return `<div class="pagina">
      <div class="lijstkop"><h1>${vraagKeuze}</h1>${criterium ? `<span class="criterium">${criterium}</span>` : ""}</div>
      ${filterBalk("Filter:")}
      <p class="stil">${rijen.length} ${rijen.length === 1 ? "lied" : "liederen"}${q ? ` met "${esc(filters.zoek)}"` : ""}. Klik op een kolomkop om te sorteren; deze link bevat de lijst zoals je hem nu ziet.</p>
      ${tabel}
    </div>`;
  }

  function zetParam(wijzigingen) {
    history.replaceState(null, "", urlMet(route().params, wijzigingen));
    render();
  }

  /* ---------- weergave: diensten ---------- */

  function dienstBlok(dienst, ooit) {
    const rijen = dienst.liederen.map((v) => {
      if (!v.lied) return `<tr><td class="moment"></td><td class="stil">nog niet herkend lied</td><td class="bron"></td><td></td></tr>`;
      const t = ooit.get(v.lied);
      return `<tr><td class="moment">${v.moment ? MOMENTNAMEN[v.moment] : ""}</td>${liedCellen(v.lied)}<td class="r">${telBadge(t.aantal)}</td></tr>`;
    });
    return `<section class="dienst" id="dienst-${dienst.datum}"><h2>${esc(metDag(datum(dienst.datum)))}</h2><div class="sub">${dienstOmschrijving(dienst)}</div>${lijstTabel(["moment", "titel", "bron", "tel"], rijen, "banden")}</section>`;
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
    const rijen = eigen.map((v) => `<tr><td>${dienstLink(v.dienst)}</td><td class="bron">${dienstOmschrijving(v.dienst)}</td><td class="bron">${v.moment ? MOMENTNAMEN[v.moment] : ""}</td></tr>`).join("");
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
      ${eigen.length ? `<table class="banden">${rijen}</table>` : ""}
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
      <p>Elk blok linkt naar de volledige lijst op de pagina Liederen. Daar is de lijst te sorteren, en de link bevat vraag, criterium, filters en sortering. Stuur je die door, dan ziet de ander precies dezelfde lijst, los van diens eigen bewaarde criteria.</p>
      <h2>Kleuren</h2>
      <p>Het getal achter een lied is hoe vaak het sinds het begin van de data gezongen is, inclusief de dienst waar je naar kijkt. De tint loopt op met het aantal; oranje betekent dat het lied in die dienst voor het eerst gezongen werd:</p>
      <p>${[1, 2, 5, 9].map(telBadge).join(" ")} ${telBadge(0)}</p>
      <p>Dienstkenmerken in twee families: ${["doop", "avondmaal", "belijdenis", "bevestiging"].map(kenmerkLabel).join(" ")} en ${["advent", "kerst", "pasen", "pinksteren", "goede-vrijdag"].map(kenmerkLabel).join(" ")}; de overige ${["startzondag", "dankdag", "biddag"].map(kenmerkLabel).join(" ")} zijn neutraal.</p>
      <h2>Zelf rekenen</h2>
      <p>Alle liedvermeldingen zijn te downloaden als <a href="data/liedvermeldingen.csv">CSV</a> (te openen in Excel of Google Sheets) en als <a href="data/dataset.json">JSON</a>.</p>
      <h2>Hoe het werkt</h2>
      <p>Een script leest uit elke liturgie-PDF alleen de liedregels en de kenmerken van de dienst (datum, begeleiding, bijzonderheden zoals doop of avondmaal). Namen van mensen worden niet opgeslagen. De liedregels worden herkend aan bundel en nummer of aan de titel; twijfelgevallen worden met de hand nagekeken. Hetzelfde lied in verschillende bundels wordt zoveel mogelijk als één lied geteld. Code en gegevens staan op <a href="https://github.com/gvanderploeg/liturgiestatistiek" target="_blank" rel="noopener">GitHub</a>.</p>
    </div>`;
  }

  /* ---------- routering en events ---------- */

  function route() {
    const hash = location.hash.replace(/^#\/?/, "");
    const [padDeel, query] = hash.split("?");
    const [pad, ...rest] = padDeel.split("/");
    return { pad: pad || "dashboard", rest: rest.map(decodeURIComponent), params: new URLSearchParams(query || "") };
  }

  let vorigePagina = null;

  function render() {
    const r = route();
    const el = document.getElementById("inhoud");
    let naam = r.pad;
    if (r.pad === "dashboard" || r.pad === "") el.innerHTML = dashboard();
    else if (r.pad === "diensten") el.innerHTML = diensten(r.rest[0]);
    else if (r.pad === "liederen") el.innerHTML = liederenPagina(r.params);
    else if (r.pad === "lied") { el.innerHTML = liedPagina(r.rest[0]); naam = "liederen"; }
    else if (r.pad === "over") el.innerHTML = over();
    else el.innerHTML = dashboard();
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("actief", a.dataset.route === naam));
    const pagina = r.pad + "/" + r.rest.join("/");
    if (pagina !== vorigePagina && r.pad !== "dashboard" && r.pad !== "") window.scrollTo(0, 0);
    vorigePagina = pagina;
  }

  function koppelEvents() {
    const el = document.getElementById("inhoud");
    const opLiederen = () => route().pad === "liederen";
    el.addEventListener("change", (e) => {
      const t = e.target;
      if (t.dataset.instelling) {
        instellingen[t.dataset.instelling] = Number(t.value);
        bewaarInstellingen();
        render();
      } else if (t.dataset.param) {
        zetParam({ [t.dataset.param]: t.value });
      } else if ("vraag" in t.dataset) {
        const p = new URLSearchParams(lijstUrl(t.value, filters.zoek).split("?")[1]);
        history.replaceState(null, "", "#/liederen?" + p.toString());
        render();
      } else if (t.dataset.filter) {
        if (opLiederen()) zetParam({ [FILTERPARAMS[t.dataset.filter]]: t.value });
        else {
          filters[t.dataset.filter] = t.value;
          render();
        }
      }
    });
    let timer = null;
    el.addEventListener("input", (e) => {
      if (!("zoek" in e.target.dataset)) return;
      const tekst = e.target.value;
      filters.zoek = tekst;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const positie = e.target.selectionStart;
        if (opLiederen()) zetParam({ q: tekst });
        else render();
        const veld = el.querySelector("[data-zoek]");
        if (veld) { veld.focus(); veld.setSelectionRange(positie, positie); }
      }, 200);
    });
    el.addEventListener("click", (e) => {
      if ("reset" in e.target.dataset) {
        Object.assign(instellingen, STANDAARD);
        bewaarInstellingen();
        render();
      } else if ("filterknop" in e.target.dataset) {
        filtersOpen = !filtersOpen;
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
