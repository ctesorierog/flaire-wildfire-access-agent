// flAIre: a home over Tolosaldea's forest, then a map workspace whose homes relight with each answer.
// Talks to server.py: POST /api/chat streams NDJSON events (tool_start, tool_end, note, answer, done, error).
// tool_end may carry `selection` (the study sites a tool placed) and `attachment` (photo or report).

const SUGGESTIONS = [
  "¿Dónde pongo el primer retén y por qué?",
  "¿Qué aporta el tercer retén?",
  "Enséñame una foto de CAND-02",
  "¿Cuándo hay que activar los retenes?",
];
const VERDICT = {
  sirve: ["i-check", "Usable: real car park"],
  no_sirve: ["i-cross", "Not usable as it is"],
  dudoso: ["i-half", "Doubtful: private yard"],
  sin_revisar: ["i-dot", "Not checked on a photo yet"],
};
const CANDS = Array.from({ length: 10 }, (_, i) => `CAND-${String(i + 1).padStart(2, "0")}`);
const THRESHOLD = 12;
const COLOR = { inside: "#ece9e2", lit: "#f1c27d", out: "#e0775c", site: "#f1c27d", park: "#8fb3c9" };
const CREDIT = "Eusko Jaurlaritza / Gobierno Vasco · geoEuskadi ORTO_2025";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html !== undefined) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const icon = (id) => `<svg aria-hidden="true"><use href="#${id}"/></svg>`;
const fmt = (n) => n.toLocaleString("en-US");
// Site names from OSM sometimes already end in "(Town)"; don't print the town twice.
// English names for the generic OSM types ("Aparcamiento sin nombre" = an unnamed car park); proper names stay.
const GENERIC = { "Aparcamiento": "Car park", "Zona industrial": "Industrial area", "Polideportivo": "Sports centre", "Área de picnic": "Picnic area" };
const siteName = (name, town) => {
  let n = String(name);
  const suffix = ` (${town})`;
  if (n.endsWith(suffix)) n = n.slice(0, -suffix.length);
  const g = n.match(/^(.*) sin nombre$/);
  return g && GENERIC[g[1]] ? GENERIC[g[1]] : n;
};
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

let thread = newThread();
let count = 0;
let busy = false;

function newThread() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

// ---------------------------------------------------------------- views
// Three places, reached by clicking: home, map, chat. On a wide screen map and chat share one view;
// on a phone they are two tabs, each one screen tall. Nothing moves on scroll.
function go(view) {
  const work = view !== "home";
  document.body.classList.toggle("at-home", !work);
  document.body.classList.toggle("at-work", work);
  if (!work) { $("q-home").focus(); return; }
  $("work").dataset.pane = view;
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-pressed", String(t.dataset.go === view)));
  if (view === "map") $("tabs-new").hidden = true;
  requestAnimationFrame(() => { map.resize(); if (view === "chat" || !narrow()) $("q").focus(); });
}
const narrow = () => matchMedia("(max-width: 900px)").matches;

// ---------------------------------------------------------------- map
const map = {
  data: null, selection: [], prev: [], t: 1, box: null, ctx: null, hover: null,

  async load() {
    this.data = await (await fetch("map.json")).json();
    this.ready?.();
    this.ctx = $("dots").getContext("2d");
    this.resize();
    addEventListener("resize", () => this.resize());
    const c = $("dots");
    c.addEventListener("mousemove", (e) => this.onMove(e));
    c.addEventListener("click", (e) => { const s = this.siteAt(e); if (s && s.id.startsWith("CAND")) showSite(s.id); });
  },

  // The forest image is drawn with object-fit: contain; the dots must sit in the same box.
  resize() {
    if (!this.data) return;
    const c = $("dots"), r = c.getBoundingClientRect(), dpr = devicePixelRatio || 1;
    const { width: iw, height: ih } = this.data.meta.image;
    const s = Math.min(r.width / iw, r.height / ih);
    this.box = { x: (r.width - iw * s) / 2, y: (r.height - ih * s) / 2, w: iw * s, h: ih * s, scale: s };
    c.width = Math.round(r.width * dpr);
    c.height = Math.round(r.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  },

  // A home is inside when its nearest origin (a park or a chosen site) is within the threshold: the tools' rule.
  inside(h, sel) {
    let best = h[3] ?? Infinity;
    for (const id of sel) {
      const t = h[4 + CANDS.indexOf(id)];
      if (t != null && t < best) best = t;
    }
    return best <= THRESHOLD;
  },

  stats(sel) {
    let n = 0, alta = 0;
    for (const h of this.data.homes) if (this.inside(h, sel)) { n++; if (h[2] === "A") alta++; }
    return { n, alta };
  },

  set(sel) {
    const next = [...new Set(sel)].filter((s) => CANDS.includes(s)).sort();
    if (next.join() === this.selection.join()) return;
    this.prev = this.selection;
    this.selection = next;
    updateCounter(this.prev, next);
    if (narrow() && $("work").dataset.pane === "chat") $("tabs-new").hidden = false; // tell a phone user the map changed
    this.animate();
  },

  animate() {
    if (reduced) { this.t = 1; this.draw(); return; }
    const start = performance.now();
    const step = (now) => {
      this.t = Math.min(1, (now - start) / 300);
      this.draw();
      if (this.t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  },

  xy(p) { return [this.box.x + p.x * this.box.w, this.box.y + p.y * this.box.h]; },

  draw() {
    const { ctx, box, data } = this;
    if (!data || !box) return;
    const c = $("dots");
    ctx.clearRect(0, 0, c.width, c.height);
    const k = Math.max(0.8, Math.min(1.6, box.w / 900));
    const ease = 1 - Math.pow(1 - this.t, 3);
    const groups = { inside: [], lit: [], out: [] };
    for (const h of data.homes) {
      const today = this.inside(h, []);
      const now = this.inside(h, this.selection);
      const x = box.x + h[0] * box.w, y = box.y + h[1] * box.h;
      groups[today ? "inside" : now ? "lit" : "out"].push([x, y, h[2] === "A"]);
    }
    // A thin dark halo keeps the dots readable on the forest green, also when projected.
    const dots = (list, color, r) => {
      ctx.beginPath();
      for (const [x, y, alta] of list) { ctx.moveTo(x + r * (alta ? 1.25 : 1), y); ctx.arc(x, y, r * (alta ? 1.25 : 1), 0, Math.PI * 2); }
      ctx.strokeStyle = "rgba(10,12,14,.85)"; ctx.lineWidth = 1; ctx.stroke();
      ctx.fillStyle = color; ctx.fill();
    };
    dots(groups.inside, COLOR.inside, 1.5 * k);
    dots(groups.out, COLOR.out, 1.7 * k);
    if (groups.lit.length) {
      ctx.globalAlpha = ease;
      dots(groups.lit, COLOR.lit, 1.7 * k); // a short fade in place: nothing grows or moves
      ctx.globalAlpha = 1;
    }
    // Fire stations: small open diamonds.
    // Marks first, labels in a second pass, so no ring is ever painted over a label.
    ctx.font = `500 ${Math.round(11 * k)}px "IBM Plex Mono", monospace`;
    const labels = [];
    // The fire station: a filled blue-grey diamond, named, so it never reads as one more home.
    ctx.lineWidth = 2;
    for (const p of this.visibleParks()) {
      const [x, y] = this.xy(p), r = 9 * k;
      ctx.beginPath(); ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath();
      ctx.fillStyle = COLOR.park; ctx.fill(); ctx.strokeStyle = "#0e1013"; ctx.stroke();
      if (box.w > 520 || this.hover === p.id) labels.push([x + r + 4 * k, y, p.id === "GIP-ORIA" ? "Fire station · Tolosa" : p.name, COLOR.park]);
    }
    // Study sites: rings; the chosen ones filled and labelled.
    for (const s of data.sites) {
      const [x, y] = this.xy(s), on = this.selection.includes(s.id), r = (on ? 7 : 5.5) * k;
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      if (on) { ctx.fillStyle = COLOR.site; ctx.fill(); ctx.fillStyle = "#0e1013"; ctx.beginPath(); ctx.arc(x, y, r * 0.38, 0, Math.PI * 2); ctx.fill(); }
      ctx.strokeStyle = COLOR.site; ctx.lineWidth = (this.hover === s.id ? 2.4 : 1.6); ctx.stroke();
      if (on || this.hover === s.id) labels.unshift([x + r + 4 * k, y, `${s.id} · ${s.municipality}`, COLOR.site]);
    }
    for (const [x, y, text, color] of labels) this.label(x, y, text, color, k);
  },

  label(x, y, text, color, k) {
    const ctx = this.ctx, w = ctx.measureText(text).width + 12 * k;
    if (x + w > $("dots").clientWidth - 4) x -= w + 22 * k; // flip to the left at the right edge
    ctx.fillStyle = "rgba(14,16,19,.88)"; ctx.fillRect(x, y - 9 * k, w, 18 * k);
    ctx.fillStyle = color; ctx.fillText(text, x + 6 * k, y + 4 * k);
  },

  // Stations outside Tolosaldea still count for coverage; build_map.py marks the ones inside it (on_map).
  visibleParks() { return this.data.parks.filter((p) => p.on_map); },

  siteAt(e) {
    if (!this.data) return null;
    const r = $("dots").getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
    let best = null, bd = 16 * 16;
    for (const s of [...this.data.sites, ...this.visibleParks()]) {
      const [x, y] = this.xy(s), d = (x - mx) ** 2 + (y - my) ** 2;
      if (d < bd) { bd = d; best = s; }
    }
    return best;
  },

  onMove(e) {
    const s = this.siteAt(e), id = s ? s.id : null;
    $("dots").classList.toggle("over-site", !!s && s.id.startsWith("CAND"));
    if (id !== this.hover) { this.hover = id; this.draw(); }
  },
};

function countUp(node, from, to) {
  if (reduced || from === to) { node.textContent = fmt(to); return; }
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / 400), e = 1 - Math.pow(1 - t, 3);
    node.textContent = fmt(Math.round(from + (to - from) * e));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function updateCounter(prev, sel) {
  const before = map.stats(prev), now = map.stats(sel), today = map.stats([]);
  countUp($("c-in"), before.n, now.n);
  $("c-delta").innerHTML = sel.length
    ? `<b>+${fmt(now.n - today.n)}</b> with ${sel.length} crew${sel.length > 1 ? "s" : ""}<br>${sel.map((s) => `<span class="nw">${esc(s)}</span>`).join(", ")}<br>Alta <b>${today.alta} → ${now.alta}</b> of 243`
    : "Today: 9 fire stations (1 inside Tolosaldea).";
  const idx = map.data.steps.findIndex((s) => [...s].sort().join() === sel.join());
  document.querySelectorAll(".steps button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.step) === idx)));
}

function showSite(id) {
  const s = map.data.sites.find((x) => x.id === id);
  if (!s) return;
  const [ic, label] = VERDICT[s.verdict] || VERDICT.sin_revisar;
  const img = $("site-img");
  img.hidden = !s.photo;
  if (s.photo) { img.src = s.photo; img.alt = `Orthophoto of ${s.id}, ${s.name}, ${s.municipality}: 120 by 120 metres around the site`; }
  $("site-cap").innerHTML =
    `<span class="site-name"><span>${esc(s.id)}</span>${esc(siteName(s.name, s.municipality))} · ${esc(s.municipality)}</span>
     <span class="verdict v-${s.verdict}">${icon(ic)}${label}</span>
     <span class="cred">${s.photo ? `${CREDIT} · 120 × 120 m · ` : ""}study site, not authorised</span>`;
  const askBtn = el("button", "pop-ask", `Ask about ${esc(s.id)}`);
  askBtn.type = "button";
  askBtn.onclick = () => { $("site-pop").hidden = true; go("chat"); ask(`¿Qué aporta ${s.id} y qué falta comprobar?`); };
  $("site-cap").append(askBtn);
  const pop = $("site-pop");
  pop.hidden = false;
  anchorPop(pop, s);
}

// On a wide screen the callout sits next to the site it describes, with a pointer; on a phone it is a bottom sheet.
function anchorPop(pop, s) {
  pop.classList.remove("left");
  pop.style.left = pop.style.top = "";
  if (narrow()) return;
  const stage = document.querySelector(".stage").getBoundingClientRect();
  const c = $("dots").getBoundingClientRect();
  const [x, y] = map.xy(s);
  const px = c.left - stage.left + x, py = c.top - stage.top + y;
  const w = pop.offsetWidth, h = pop.offsetHeight, gap = 18;
  let left = px + gap;
  if (left + w > stage.width - 12) { left = px - gap - w; pop.classList.add("left"); }
  const top = Math.max(12, Math.min(stage.height - h - 12, py - h / 2));
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
  pop.style.setProperty("--arrow-y", `${py - top}px`);
}

// ---------------------------------------------------------------- inline visuals
// Two thin bars, computed from the same map.json as the counter: homes within 12 min and Alta homes, today vs with
// the crews this answer placed. No new numbers: the agent's own figures, drawn.
function coverageChart(sel) {
  const today = map.stats([]), now = map.stats(sel);
  const row = (label, a, b, total) => {
    const pa = (100 * a) / total, pb = (100 * (b - a)) / total;
    return `<div class="bar-row"><span class="bar-label">${label}</span>
      <span class="bar" aria-hidden="true"><i style="width:${pa}%"></i><b style="width:${pb}%"></b></span>
      <span class="bar-num">${fmt(a)} → <strong>${fmt(b)}</strong> <small>of ${fmt(total)}</small></span></div>`;
  };
  const fig = el("figure", "mini-chart coverage",
    `${row("Homes within 12 min", today.n, now.n, 3331)}${row("Alta priority", today.alta, now.alta, 243)}
     <figcaption><i class="sw-today"></i>Today <i class="sw-crews"></i>With ${esc(sel.join(", "))}</figcaption>`);
  fig.setAttribute("role", "img");
  fig.setAttribute("aria-label", `Homes within 12 minutes: ${today.n} today, ${now.n} with ${sel.join(", ")}. Alta priority: ${today.alta} to ${now.alta} of 243.`);
  return fig;
}

// Buttons on the answer that act on the map: put this answer's crews back, open the placed sites' photos.
function mapActions(sel) {
  const row = el("div", "map-actions");
  const show = el("button", "chip", `${icon("i-pin")}Show on map`);
  show.type = "button";
  show.onclick = () => { map.set(sel); if (narrow()) go("map"); };
  row.append(show);
  for (const id of sel) {
    const s = map.data.sites.find((x) => x.id === id);
    if (!s || !s.photo) continue;
    const b = el("button", "chip", `${icon("i-photo")}See ${esc(id)}`);
    b.type = "button";
    b.onclick = () => { map.set(sel); if (narrow()) go("map"); requestAnimationFrame(() => showSite(id)); };
    row.append(b);
  }
  return row;
}

// The 52-week risk strip (weekly_calendar.json), for answers about when to activate the crews.
let weekly = null;
function weeklyStrip() {
  const fig = el("figure", "mini-chart weekly", `<p class="mc-title">Risk days per week, Tolosaldea 2018–2023</p><div class="strip" aria-hidden="true"></div><div class="months" aria-hidden="true"></div><figcaption></figcaption>`);
  fig.setAttribute("role", "img");
  (weekly ||= fetch("/data/weekly_calendar.json").then((r) => r.json())).then((w) => {
    const max = Math.max(...w.weeks.map((x) => x.risk_days));
    const strip = fig.querySelector(".strip");
    for (const x of w.weeks) {
      const c = el("i");
      const v = x.risk_days / max;
      c.style.background = `color-mix(in oklab, var(--hi) ${Math.round(12 + 88 * v)}%, #1a1f24)`;
      if (x.month === 7 || x.month === 8) c.className = "summer";
      c.title = `Week ${x.week}: ${x.risk_days.toFixed(2)} risk days`;
      strip.append(c);
    }
    fig.querySelector(".months").innerHTML = "JFMAMJJASOND".split("").map((m) => `<span>${m}</span>`).join("");
    const s = w.summary.season_share;
    fig.querySelector("figcaption").innerHTML =
      `<b>${Math.round(100 * s.jul_aug)} %</b> of risk days fall in Jul–Aug (outlined) · ${Math.round(100 * s.feb_apr)} % Feb–Apr · ${Math.round(100 * s.sep_oct)} % Sep–Oct. Exploratory rule, not fire probability.`;
    fig.setAttribute("aria-label", `Weekly risk days in Tolosaldea, 2018 to 2023: ${Math.round(100 * s.jul_aug)} percent in July and August, ${Math.round(100 * s.feb_apr)} percent February to April, ${Math.round(100 * s.sep_oct)} percent September and October.`);
  }).catch(() => fig.remove());
  return fig;
}

// ---------------------------------------------------------------- findings
function renderAnswer(text) {
  const box = el("div", "answer", DOMPurify.sanitize(marked.parse(text, { gfm: true, breaks: false })));
  box.lang = "es";
  box.querySelectorAll("strong").forEach((s) => { if (/\d/.test(s.textContent)) s.classList.add("num"); });
  const first = box.firstElementChild;
  if (first) first.classList.add("lead");
  return box;
}

function receipt(ev) {
  const a = ev.args || {};
  const arg = a.candidato || a.seleccion || a.building_id || (a.k_max != null ? `k ≤ ${a.k_max}` : a.k >= 0 ? `k = ${a.k}` : a.apartado || a.modo || "");
  const li = el("li", "receipt pending", `${icon("i-dot")}<span>${esc(ev.name)}</span>${arg ? `<span class="arg">${esc(arg)}</span>` : ""}`);
  li.dataset.id = ev.id;
  return li;
}

function siteCard(att) {
  const [ic, label] = VERDICT[att.veredicto] || VERDICT.dudoso;
  const card = el("button", "site-card",
    `${att.imagen ? `<img src="${esc(att.imagen)}" alt="" width="800" height="800">` : "<span></span>"}
     <span><span class="t"><span>${esc(att.candidato)}</span>${esc(siteName(att.nombre, att.municipio))} · ${esc(att.municipio)}</span><br>
     <span class="verdict v-${att.veredicto}">${icon(ic)}${label}</span><br>
     <span class="cred">${att.imagen ? CREDIT : "No orthophoto checked yet"}</span></span>`);
  card.type = "button";
  card.setAttribute("aria-label", `Show ${att.candidato} on the map`);
  card.onclick = () => showSite(att.candidato);
  return card;
}

function addFinding(question) {
  const n = ++count;
  const art = el("article", "finding");
  art.id = `f${n}`;
  art.setAttribute("aria-busy", "true");
  art.append(el("header", "f-head", `<span class="n">F${n}</span><h3 lang="es">${esc(question)}</h3>`));
  const body = el("div", "f-body");
  const working = el("p", "working", `Reading the question…<span class="live"></span>`);
  body.append(working);
  art.append(body);
  $("feed-empty").hidden = true;
  $("notebook").append(art);
  art.scrollIntoView({ block: "start" }); // jump, don't glide
  return { art, body, working };
}

async function ask(question) {
  question = question.trim();
  if (!question || busy) return;
  busy = true;
  setBusy(true, "flAIre is working…");
  const { art, body, working } = addFinding(question);
  const receipts = el("ol", "receipts");
  receipts.setAttribute("aria-label", "Tools used");
  const extras = [];
  let tools = 0, answered = false, crews = null, weather = false;
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ thread, message: question }),
    });
    if (!res.ok || !res.body) throw new Error(`The server answered ${res.status}. Check the server window, then Ask Again.`);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "tool_start") {
          tools++;
          receipts.append(receipt(ev));
          working.firstChild.textContent = "Running tools on the data…";
          working.querySelector(".live").textContent = ev.name;
          if (ev.name === "perfil_meteorologico") weather = true;
          setBusy(true, `${tools} tool${tools > 1 ? "s" : ""}`);
        } else if (ev.type === "tool_end") {
          const r = receipts.querySelector(`[data-id="${CSS.escape(ev.id)}"]`);
          if (r) { r.classList.replace("pending", ev.ok ? "ok" : "fail"); r.querySelector("use").setAttribute("href", ev.ok ? "#i-check" : "#i-cross"); }
          if (ev.selection) { map.set(ev.selection); crews = ev.selection; }
          if (ev.attachment?.kind === "photo") extras.push(siteCard(ev.attachment));
          if (ev.attachment?.kind === "report") {
            const a = el("a", "report-link", `Open the report with maps ${icon("i-arrow")}`);
            a.href = ev.attachment.url; a.target = "_blank"; a.rel = "noopener";
            extras.push(a);
          }
        } else if (ev.type === "answer") {
          answered = true;
          working.remove();
          const ans = renderAnswer(ev.text);
          const lead = ans.querySelector(".lead");
          // The key sentence stays in view; everything else folds under "How this was computed".
          const how = el("details", "how", `<summary>How this was computed <span class="tools"></span>${icon("i-down")}</summary>`);
          const hb = el("div", "how-body");
          const rest = el("div", "answer");
          [...ans.children].filter((c) => c !== lead).forEach((c) => rest.append(c));
          hb.append(rest, receipts);
          how.append(hb);
          const visuals = [];
          if (crews && crews.length) visuals.push(coverageChart(crews), mapActions(crews));
          if (weather) visuals.push(weeklyStrip());
          body.append(ans, ...visuals, ...extras, how);
        } else if (ev.type === "error") {
          throw new Error(ev.text);
        } else if (ev.type === "done") {
          const how = body.querySelector(".how");
          if (how) {
            how.querySelector(".tools").textContent = `· ${tools} tool${tools === 1 ? "" : "s"}, ${ev.seconds} s`;
            how.querySelector(".how-body").append(el("p", "f-meta", `Saved to transcripts/chat_${thread}.json`));
          }
        }
      }
    }
    if (!answered) throw new Error("The agent stopped without an answer. Ask Again, or rephrase the question.");
  } catch (err) {
    working.remove();
    const box = el("div", "error", `<b>No answer.</b> ${esc(err.message)}<br>`);
    const retry = el("button", "ghost", "Ask Again");
    retry.type = "button";
    retry.onclick = () => { art.remove(); count--; ask(question); };
    box.append(retry);
    body.append(box);
  } finally {
    art.removeAttribute("aria-busy");
    busy = false;
    setBusy(false, "");
  }
}

function setBusy(on, text) {
  $("ask").disabled = on;
  $("status").textContent = text;
  document.querySelectorAll(".starters button").forEach((b) => (b.disabled = on));
}

function grow() {
  const q = $("q");
  q.style.height = "auto";
  q.style.height = Math.min(q.scrollHeight, 180) + "px";
}

// The home photo: drop an image next to this file plus hero.json {"file": "...", "credit": "..."}.
// Without it, the home keeps the faded forest map. A photo is never shown without its credit.
async function loadHero() {
  try {
    const r = await fetch("hero.json");
    if (!r.ok) return;
    const h = await r.json();
    if (!h.file || !h.credit) return;
    document.querySelector(".home-bg").style.setProperty("--hero", `url("${encodeURI(h.file)}")`);
    $("hero-credit").textContent = `Photo: ${h.credit}`;
    $("hero-credit").hidden = false;
  } catch { /* keep the forest map */ }
}

// ---------------------------------------------------------------- wiring
function init() {
  for (const box of ["starters", "starters-feed"]) {
    for (const s of SUGGESTIONS) {
      const b = el("button", "", esc(s));
      b.type = "button";
      b.onclick = () => { go("chat"); ask(s); };
      $(box).append(b);
    }
  }
  // A short placeholder on small screens, kept in step if the window is resized.
  const small = matchMedia("(max-width: 600px)"), long = $("q-home").placeholder;
  const setPh = () => ($("q-home").placeholder = small.matches ? "Pregunta a flAIre…" : long);
  small.addEventListener("change", setPh);
  setPh();
  document.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  document.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => $(b.dataset.open).showModal()));
  $("ask-home").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("q-home").value;
    $("q-home").value = "";
    go("chat");
    ask(v);
  });
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("q").value;
    $("q").value = "";
    grow();
    ask(v);
  });
  $("q").addEventListener("input", grow);
  $("q").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("composer").requestSubmit(); }
  });
  document.querySelectorAll(".steps button").forEach((b) => (b.onclick = () => map.set(map.data.steps[Number(b.dataset.step)])));
  $("key-btn").onclick = () => {
    const open = $("key").hidden;
    $("key").hidden = !open;
    $("key-btn").setAttribute("aria-expanded", String(open));
  };
  $("site-close").onclick = () => ($("site-pop").hidden = true);
  // The map's marks are mouse-only, so the Key also lists the study sites as buttons (keyboard and screen readers).
  map.ready = () => {
    for (const s of map.data.sites) {
      const b = el("button", "site-link", `<span>${esc(s.id)}</span> ${esc(s.municipality)}`);
      b.type = "button";
      b.onclick = () => showSite(s.id);
      $("site-list").append(b);
    }
  };
  $("new-notebook").onclick = () => {
    if (busy || (count && !confirm("Start a new notebook? The findings on screen will be cleared (each one is still saved in transcripts/)."))) return;
    thread = newThread();
    count = 0;
    $("notebook").replaceChildren();
    $("feed-empty").hidden = false;
    map.set([]);
  };
  addEventListener("keydown", (e) => { if (e.key === "Escape") $("site-pop").hidden = true; });
  map.load();
  loadHero();
  $("q-home").focus();
}

init();
