"use strict";
// Wordfeud-motor – gränssnitt (vanilla JS)

const $ = (sel, root = document) => root.querySelector(sel);
const app = $("#app");
let CFG = null;

const BONUS = { ".": ["", ""], d: ["dl", "DL"], t: ["tl", "TL"], D: ["dw", "DW"], T: ["tw", "TW"] };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------- hjälpfunktioner ----------
async function api(method, path, body) {
  const res = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg).join("; ");
    throw new Error(msg || `Fel ${res.status}`);
  }
  return data;
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), isErr ? 5000 : 2500);
}
const fail = e => toast(e.message || String(e), true);

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const PLIES = [1, 2, 3, 4, 5, 10, 0];                  // 0 = till slutet
const pliesName = p => p === 0 ? "Till slutet" : String(p);
const pos = (r, c, h) => `rad ${r + 1}, kol ${c + 1} ${h ? "→" : "↓"}`;
const fmtDate = s => s ? s.replace("T", " ").slice(0, 16) : "";
const tileValue = (letter, blank) => blank ? 0 : (CFG.values[letter] ?? 0);

// ---------- brädrendering ----------
function boardHTML(layout, { tiles = [], ghost = [], sel = null, last = [] } = {}) {
  const N = CFG.size;
  const grid = Array.from({ length: N }, () => Array(N).fill(null));
  for (const t of tiles) grid[t.row][t.col] = { ...t, kind: "" };
  const lastSet = new Set(last.map(p => p.row * N + p.col));
  for (const t of ghost) if (!grid[t.row][t.col]) grid[t.row][t.col] = { ...t, kind: "ghost" };
  let h = "";
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
    const [cls, label] = BONUS[layout[r][c]];
    const isStart = r === CFG.start[0] && c === CFG.start[1];
    const t = grid[r][c];
    const isSel = sel && sel.row === r && sel.col === c;
    let inner = t ? "" : (isStart && !label ? "" : label);
    if (t) {
      const k = [t.kind, t.blank ? "blank" : "", lastSet.has(r * N + c) ? "last" : ""].join(" ");
      inner = `<div class="tile ${k}">${t.blank ? t.letter.toLowerCase() : t.letter}<span class="v">${tileValue(t.letter, t.blank)}</span></div>`;
    }
    if (isSel && !t) inner += `<span class="arrow">${sel.horizontal ? "→" : "↓"}</span>`;
    h += `<div class="sq ${cls} ${isStart && !t && !label ? "start" : ""} ${isSel ? "sel" : ""}" data-r="${r}" data-c="${c}">${inner}</div>`;
  }
  return h;
}

function onSquare(el, fn) {
  el.addEventListener("click", e => {
    const sq = e.target.closest(".sq");
    if (sq) fn(+sq.dataset.r, +sq.dataset.c);
  });
}

// ---------- startsida ----------
async function viewHome() {
  $("#top-extra").innerHTML = "";
  const games = await api("GET", "/api/games");
  const dictWarn = !CFG.dict_available.normal
    ? `<div class="banner">Ordlistan saknas. Kör <code>python scripts/fetch_saldo.py</code> och starta om servern.</div>` : "";
  const unv = CFG.unverified.length
    ? `<div class="banner">Ej verifierat i config: ${CFG.unverified.join(", ")}</div>` : "";
  app.innerHTML = `
    ${dictWarn}${unv}
    <div class="panel">
      <div class="row"><h2 class="grow">Matcher</h2><button class="primary" id="new">Ny match</button></div>
      <div class="games-list">
        ${games.length ? games.map(g => `
          <div class="g">
            <div><a href="#/game/${esc(g.id)}">${esc(g.name)}</a>
              ${g.opponent ? `<span class="muted">mot ${esc(g.opponent)}</span>` : ""}<br>
              <span class="muted">${fmtDate(g.updated)} · ${g.moves} drag · ${g.dict_mode}</span></div>
            <div class="row"><b>${g.scores.me}–${g.scores.opp}</b>
              <button class="small danger" data-del="${esc(g.id)}">Ta bort</button></div>
          </div>`).join("") : `<p class="muted">Inga sparade matcher ännu.</p>`}
      </div>
    </div>`;
  $("#new").onclick = () => location.hash = "#/new";
  app.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm("Ta bort matchen?")) return;
    await api("DELETE", `/api/games/${b.dataset.del}`).catch(fail);
    viewHome();
  });
}

// ---------- ny match ----------
function viewNew() {
  $("#top-extra").innerHTML = "";
  let layout = CFG.standard_layout.map(r => r.split(""));
  let brush = ".";
  app.innerHTML = `
    <div class="panel">
      <h2>Ny match</h2>
      <div class="row">
        <label>Matchnamn <input id="name" placeholder="t.ex. Kalle 3"></label>
        <label>Motståndare <input id="opp"></label>
        <label>Ordlista <select id="mode">
          <option value="normal">Normal (med böjningar)</option>
          <option value="strikt">Strikt (bara grundformer)</option></select></label>
        <label>Vem börjar? <select id="starter">
          <option value="me">Jag</option><option value="opp">Motståndaren</option></select></label>
      </div>
    </div>
    <div class="game">
      <div><div class="board" id="board"></div></div>
      <div class="panel">
        <h3>Bonusrutor</h3>
        <p class="muted">Välj typ och klicka på rutorna, eller slumpa ett bräde. Stämmer brädet med standardlayouten behöver du inte ändra något.</p>
        <div class="row palette" id="pal">
          ${[".", "d", "t", "D", "T"].map(k => `<button data-k="${k}" class="${BONUS[k][0]}">${BONUS[k][1] || "Ingen"}</button>`).join("")}
        </div>
        <div class="row" style="margin-top:8px">
          <button id="std">Standardlayout</button><button id="rnd">Slumpa bräde</button><button id="clear">Töm</button>
        </div>
        <div class="checklist" id="check"></div>
        <div class="row" style="margin-top:14px"><button class="primary" id="create">Skapa match</button></div>
      </div>
    </div>`;
  // Manuella ändringar sedan senaste standard/slump/töm – skyddas av en bekräftelsefråga.
  let manual = false;
  const NEED = CFG.bonus_counts || {};
  const problems = () => {
    const have = {};
    for (const row of layout) for (const ch of row) have[ch] = (have[ch] || 0) + 1;
    return Object.entries(NEED).map(([k, need]) => ({ k, have: have[k] || 0, need }));
  };
  const drawCheck = () => {
    const items = problems();
    const ok = items.every(x => x.have === x.need);
    $("#check").innerHTML = items.map(({ k, have, need }) => {
      const d = need - have;
      const [cls, txt] = d === 0 ? ["ok", "✓"] : d > 0 ? ["miss", `${d} saknas`] : ["over", `${-d} för många`];
      return `<div class="ci ${cls}"><span class="chip ${BONUS[k][0]}">${BONUS[k][1]}</span>
        <span class="mono">${have}/${need}</span> <span>${txt}</span></div>`;
    }).join("") + `<div class="${ok ? "okc" : "error"} csum">${ok ? "Brädet är godkänt." : "Brädet godkänns först när antalet av varje sort stämmer."}</div>`;
    $("#create").disabled = !ok;
  };
  const draw = () => {
    $("#board").innerHTML = boardHTML(layout.map(r => r.join("")));
    app.querySelectorAll("#pal button").forEach(b => b.classList.toggle("on", b.dataset.k === brush));
    drawCheck();
  };
  const overwrite = (what) => !manual || confirm(`Du har ändrat bonusrutor för hand. Vill du ${what} och skriva över det du lagt ut?`);
  const randomLayout = () => {
    const N = CFG.size, [sr, sc] = CFG.start;
    const cells = [];
    for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) if (r !== sr || c !== sc) cells.push([r, c]);
    for (let i = cells.length - 1; i > 0; i--) {           // Fisher–Yates
      const j = Math.floor(Math.random() * (i + 1));
      [cells[i], cells[j]] = [cells[j], cells[i]];
    }
    const out = Array.from({ length: N }, () => Array(N).fill("."));
    let i = 0;
    for (const [k, n] of Object.entries(NEED)) for (let x = 0; x < n; x++) { const [r, c] = cells[i++]; out[r][c] = k; }
    return out;
  };
  onSquare($("#board"), (r, c) => {
    if (layout[r][c] !== brush) { layout[r][c] = brush; manual = true; }
    draw();
  });
  $("#pal").onclick = e => { const b = e.target.closest("button"); if (b) { brush = b.dataset.k; draw(); } };
  $("#std").onclick = () => {
    if (!overwrite("använda standardlayouten")) return;
    layout = CFG.standard_layout.map(r => r.split("")); manual = false; draw();
  };
  $("#rnd").onclick = () => {
    if (!overwrite("slumpa ett nytt bräde")) return;
    layout = randomLayout(); manual = false; draw();
  };
  $("#clear").onclick = () => {
    if (!overwrite("tömma brädet")) return;
    layout = layout.map(r => r.map(() => ".")); manual = false; draw();
  };
  $("#create").onclick = async () => {
    try {
      const g = await api("POST", "/api/games", {
        name: $("#name").value || "Match", opponent: $("#opp").value,
        layout: layout.map(r => r.join("")), dict_mode: $("#mode").value, starter: $("#starter").value,
      });
      location.hash = `#/game/${g.id}`;
    } catch (e) { fail(e); }
  };
  draw();
}

// ---------- matchvy ----------
const S = {};   // tillstånd för matchvyn

async function viewGame(id) {
  stopSim();
  Object.assign(S, { id, game: null, sel: null, player: "me", preview: null, analysis: null, chosen: null, ex: null, sim: null, simNote: null, estimate: null });
  S.game = await api("GET", `/api/games/${id}`);
  app.innerHTML = `
    <div id="banners"></div>
    <div class="game">
      <div>
        <div class="board" id="board"></div>
        <div class="panel" style="margin-top:8px">
          <div class="row">
            <span id="selinfo" class="muted">Klicka på en ruta för att välja start. Klicka igen för att byta riktning.</span>
          </div>
          <div class="row" style="margin-top:6px">
            <input class="word" id="word" placeholder="ORD" autocomplete="off" autocapitalize="characters" spellcheck="false">
            <button id="dir">→ Vågrätt</button>
          </div>
          <div class="row" style="margin-top:6px">
            <span>Tur:</span>
            <button id="pl-me" class="on">Jag</button><button id="pl-opp">Motståndare</button>
            <button class="primary" id="playbtn" disabled>Lägg ord</button>
          </div>
          <div class="muted" style="margin-top:4px">Skriv ordet som vanligt. Blank väljs automatiskt utifrån din hand.
            Ange blank själv genom att blanda: <span class="mono">HUSet</span> = blank som E och T.</div>
          <div id="prev" style="margin-top:6px"></div>
          <div class="row" style="margin-top:8px">
            <button id="passbtn">Pass</button><button id="exbtn">Byte</button>
            <button id="undo">Ångra</button>
          </div>
          <div id="expanel" class="expanel hidden"></div>
        </div>
      </div>
      <div>
        <div class="panel">
          <div class="row">
            <label>Jag <input class="score" type="number" id="sc-me"></label>
            <label id="opp-label">Motståndare <input class="score" type="number" id="sc-opp"></label>
            <span class="muted" id="passes"></span>
          </div>
          <div class="row" style="margin-top:8px">
            <label>Min hand <input class="rack" id="rack" maxlength="7" autocomplete="off" autocapitalize="characters" spellcheck="false"></label>
            <span class="muted">? = blank</span>
          </div>
          <div class="racktiles" id="racktiles"></div>
        </div>
        <div class="panel">
          <div class="row">
            <h3 class="grow">Analys</h3>
            <button class="primary" id="analyze">Analysera</button>
            <button id="simstop" class="hidden">Stoppa</button>
          </div>
          <details id="simset" class="simset">
            <summary>Inställningar</summary>
            <div class="row">
              <label>Motståndare <select id="st-opp">
                <option value="perfect">Perfekt</option><option value="human">Mänsklig</option></select></label>
              <label title="Drag efter ditt drag, växelvis: motståndaren först, sedan du osv.">Drag framåt <select id="st-plies">${PLIES.map(p => `<option value="${p}">${pliesName(p)}</option>`).join("")}</select></label>
              <label>Kandidater <input type="number" id="st-cand" min="1" max="60" class="score"></label>
            </div>
            <div class="row">
              <label title="Tomt eller 0 = så många som ryms inom tidsbudgeten">Iterationer <input type="number" id="st-iter" min="0" class="score" placeholder="max"></label>
              <span class="muted" id="st-itermax"></span>
              <label>Sortera <select id="st-sort">
                <option value="win">vinstchans</option><option value="margin">marginal</option></select></label>
            </div>
            <div class="row">
              <label><input type="checkbox" id="inclex"> byten/pass</label>
              <label><input type="checkbox" id="st-prune"> gallra dåliga drag</label>
              <label>Seed <input type="number" id="st-seed" class="score"></label>
              <label title="0 = automatiskt (antal kärnor − 1)">Processer <input type="number" id="st-workers" min="0" max="61" class="score"></label>
            </div>
            <div class="muted estimate" id="st-est"></div>
          </details>
          <div id="analysis"><p class="muted">Analysera rankar alla drag efter poäng och simulerar sedan de bästa (vinstchans och marginal).</p></div>
        </div>
        <div class="panel">
          <h3>Brickor</h3>
          <div id="tiles"></div>
        </div>
        <div class="panel">
          <h3>Ordlista</h3>
          <div class="row">
            <input id="dword" placeholder="ord" autocomplete="off" style="width:9em">
            <button id="dcheck">Kolla</button>
            <button id="dadd">Lägg till ord</button><button id="drem">Ta bort ord</button>
          </div>
          <div class="row" style="margin-top:6px">
            <label>Läge <select id="dmode"><option value="normal">Normal</option><option value="strikt">Strikt</option></select></label>
            <span class="muted" id="dres"></span>
          </div>
        </div>
        <div class="panel">
          <h3>Draglogg</h3>
          <div class="log" id="log"></div>
        </div>
      </div>
    </div>`;
  bindGame();
  renderGame();
  setPlayer(S.game.to_move);
  loadSettings().catch(fail);
}

function renderGame() {
  const g = S.game;
  $("#top-extra").innerHTML = `${esc(g.name)}${g.opponent ? " – " + esc(g.opponent) : ""}`;
  const banners = [];
  if (g.dict_missing) banners.push("Ordlistan saknas – kör python scripts/fetch_saldo.py");
  if (g.tile_status.error) banners.push("Felinmatat: " + g.tile_status.error);
  if (g.game_over) banners.push(g.game_over);
  $("#banners").innerHTML = banners.map(b => `<div class="banner">${esc(b)}</div>`).join("");
  $("#sc-me").value = g.scores.me;
  $("#sc-opp").value = g.scores.opp;
  if (document.activeElement !== $("#rack")) $("#rack").value = g.rack;
  $("#dmode").value = g.dict_mode;
  $("#passes").textContent = g.consecutive_passes ? `${g.consecutive_passes} pass i rad` : "";
  $("#racktiles").innerHTML = [...g.rack].map(ch =>
    `<div class="rt">${ch === "?" ? "?" : ch}<span class="v">${ch === "?" ? 0 : CFG.values[ch] ?? ""}</span></div>`).join("");
  renderBoard();
  renderTiles();
  renderLog();
  renderPreview();
}

function renderBoard() {
  const g = S.game;
  let ghost = [];
  if (S.chosen) ghost = S.chosen.placements;
  else if (S.preview) ghost = S.preview.placements;
  const lastPlay = [...g.log].reverse().find(e => e.kind === "play");
  $("#board").innerHTML = boardHTML(g.layout, { tiles: g.tiles, ghost, sel: S.sel, last: lastPlay ? lastPlay.placements : [] });
  $("#selinfo").textContent = S.sel ? `Start: ${pos(S.sel.row, S.sel.col, S.sel.horizontal)}`
    : "Klicka på en ruta för att välja start. Klicka igen för att byta riktning.";
  $("#dir").textContent = (!S.sel || S.sel.horizontal) ? "→ Vågrätt" : "↓ Lodrätt";
}

function renderTiles() {
  const ts = S.game.tile_status;
  if (ts.error) { $("#tiles").innerHTML = `<p class="error">${esc(ts.error)}</p>`; return; }
  const parts = Object.entries(ts.unseen).map(([k, n]) => `${k === "?" ? "?" : k}×${n}`);
  const oppRack = Math.min(CFG.rack_size, ts.unseen_count);
  $("#tiles").innerHTML = `
    <div class="muted">Osedda: <b>${ts.unseen_count}</b> · i påsen: <b>${ts.bag}</b> · motståndarens hand: ${oppRack}</div>
    <div class="unseen">${parts.join("  ")}</div>`;
}

function renderLog() {
  const log = S.game.log;
  const name = p => p === "me" ? "Jag" : (S.game.opponent || "Motståndare");
  $("#log").innerHTML = log.length ? [...log].reverse().map(e => {
    const what = e.kind === "play" ? `<b class="mono">${esc(e.word)}</b> ${pos(e.row, e.col, e.horizontal)} – ${e.score} p`
      : e.kind === "pass" ? "pass"
      : `byte av ${e.count || e.word.length || "?"} ${(e.count || e.word.length) === 1 ? "bricka" : "brickor"}${e.word ? ` (<span class="mono">${esc(e.word)}</span>)` : ""}`;
    return `<div>${name(e.player)}: ${what}</div>`;
  }).join("") : `<span class="muted">Inga drag ännu.</span>`;
}

function renderPreview() {
  const p = S.preview, el = $("#prev");
  $("#playbtn").disabled = !p;
  if (S.previewError) { el.innerHTML = `<div class="warn">${esc(S.previewError)}</div>`; return; }
  if (!p) { el.innerHTML = ""; return; }
  const words = p.words.map(w =>
    `<span class="${w.valid ? "okc" : "error"} mono">${esc(w.text)}${w.valid ? " ✓" : " ✗"}</span>`).join(" ");
  const invalid = p.words.filter(w => !w.valid).map(w => w.text.toUpperCase());
  el.innerHTML = `
    <div><b>${p.score} p</b>${p.bingo ? " (inkl. bonus för alla 7 brickor)" : ""} · ${words}</div>
    ${p.blanks.length ? `<div class="muted">Blank används som: <b>${p.blanks.join(", ")}</b></div>` : ""}
    ${p.warnings.map(w => `<div class="warn">${esc(w)}</div>`).join("")}
    ${invalid.length ? `<div class="row" style="margin-top:4px">${invalid.map(w =>
      `<button class="small" data-approve="${esc(w)}">Godkänn ${esc(w)}</button>`).join("")}</div>` : ""}`;
  el.querySelectorAll("[data-approve]").forEach(b => b.onclick = async () => {
    try {
      await api("POST", "/api/dict/add", { word: b.dataset.approve, mode: S.game.dict_mode });
      toast(`${b.dataset.approve} tillagt i ordlistan`);
      await refreshPreview();
    } catch (e) { fail(e); }
  });
}

const refetchEstimate = debounce(() => fetchEstimate(), 600);

async function refreshGame(g) {
  const before = S.game ? JSON.stringify([S.game.rack, S.game.tiles, S.game.dict_mode]) : null;
  S.game = g || await api("GET", `/api/games/${S.id}`);
  if (before !== JSON.stringify([S.game.rack, S.game.tiles, S.game.dict_mode])) {
    S.estimate = null;                         // ställningen har ändrats
    renderEstimate();
    if ($("#simset") && $("#simset").open) refetchEstimate();
  }
  renderGame();
  setPlayer(S.game.to_move);
  if (S.ex) {
    S.ex.selected = new Set([...S.ex.selected].filter(i => i < S.game.rack.length));
    renderExchange();
  }
}

async function refreshPreview() {
  const word = $("#word").value.trim();
  S.previewError = null;
  if (!S.sel || !word) { S.preview = null; renderPreview(); renderBoard(); return; }
  try {
    S.preview = await api("POST", `/api/games/${S.id}/preview`, { ...S.sel, word, player: S.player });
  } catch (e) { S.preview = null; S.previewError = e.message; }
  renderPreview(); renderBoard();
}
const updatePreview = debounce(refreshPreview, 200);

// ---------- byte ----------
function openExchange() {
  S.ex = { selected: new Set(), count: 7 };
  renderExchange();
}

function closeExchange() {
  S.ex = null;
  const el = $("#expanel");
  if (el) { el.classList.add("hidden"); el.innerHTML = ""; }
  const b = $("#exbtn");
  if (b) b.classList.remove("on");
}

function renderExchange() {
  const el = $("#expanel"), ex = S.ex;
  if (!ex) return closeExchange();
  $("#exbtn").classList.add("on");
  el.classList.remove("hidden");
  const bag = S.game.tile_status.bag;
  const bagNote = bag !== null && bag < 7
    ? `<div class="warn">Påsen har bara ${bag} brickor – byte är inte tillåtet (minst 7).</div>` : "";
  if (S.player === "me") {
    const rack = S.game.rack;
    if (!rack) {
      el.innerHTML = `${bagNote}<p class="muted">Fyll i din hand först, sedan väljer du vilka brickor du byter.</p>
        <button id="excancel">Avbryt</button>`;
    } else {
      const chosen = [...ex.selected].map(i => rack[i]).join("");
      el.innerHTML = `${bagNote}
        <div><b>Vilka brickor byter du?</b> <span class="muted">Tryck på brickorna.</span></div>
        <div class="racktiles pick">${[...rack].map((ch, i) =>
          `<div class="rt ${ex.selected.has(i) ? "picked" : ""}" data-i="${i}">${ch}<span class="v">${ch === "?" ? 0 : CFG.values[ch] ?? ""}</span></div>`).join("")}
        </div>
        <div class="row" style="margin-top:8px">
          <button class="small" id="exall">Alla</button><button class="small" id="exnone">Inga</button>
          <button class="primary" id="exgo" ${chosen ? "" : "disabled"}>Byt ${chosen.length || ""} ${chosen.length === 1 ? "bricka" : "brickor"}</button>
          <button id="excancel">Avbryt</button>
        </div>`;
      el.querySelectorAll(".pick .rt").forEach(t => t.onclick = () => {
        const i = +t.dataset.i;
        ex.selected.has(i) ? ex.selected.delete(i) : ex.selected.add(i);
        renderExchange();
      });
      $("#exall").onclick = () => { ex.selected = new Set([...rack].map((_, i) => i)); renderExchange(); };
      $("#exnone").onclick = () => { ex.selected = new Set(); renderExchange(); };
      $("#exgo").onclick = () => doExchange({ tiles: chosen });
    }
  } else {
    const max = Math.min(CFG.rack_size, S.game.tile_status.unseen_count ?? CFG.rack_size);
    el.innerHTML = `${bagNote}
      <div><b>Hur många brickor byter ${esc(S.game.opponent || "motståndaren")}?</b></div>
      <div class="row" style="margin-top:6px">${Array.from({ length: max }, (_, k) => k + 1).map(n =>
        `<button class="small ${ex.count === n ? "on" : ""}" data-n="${n}">${n}</button>`).join("")}</div>
      <div class="row" style="margin-top:8px">
        <button class="primary" id="exgo">Byt ${ex.count} ${ex.count === 1 ? "bricka" : "brickor"}</button>
        <button id="excancel">Avbryt</button>
      </div>`;
    el.querySelectorAll("[data-n]").forEach(b => b.onclick = () => { ex.count = +b.dataset.n; renderExchange(); });
    $("#exgo").onclick = () => doExchange({ count: ex.count });
  }
  $("#excancel").onclick = closeExchange;
}

async function doExchange(what) {
  const who = S.player;
  try {
    const g = await api("POST", `/api/games/${S.id}/exchange`, { player: who, ...what });
    closeExchange();
    clearAnalysis();
    await refreshGame(g);
    if (who === "me") {
      toast("Byte registrerat – fyll i dina nya brickor");
      $("#rack").focus();
    } else toast("Byte registrerat – din tur");
  } catch (e) { fail(e); }
}

function setPlayer(p) {
  S.player = p;
  if (S.ex) renderExchange();
  if (S.preview || S.previewError) updatePreview();
  $("#pl-me").classList.toggle("on", p === "me");
  $("#pl-opp").classList.toggle("on", p === "opp");
}

function bindGame() {
  onSquare($("#board"), (r, c) => {
    S.chosen = null;
    if (S.sel && S.sel.row === r && S.sel.col === c) S.sel.horizontal = !S.sel.horizontal;
    else S.sel = { row: r, col: c, horizontal: S.sel ? S.sel.horizontal : true };
    renderBoard(); updatePreview();
    $("#word").focus({ preventScroll: true });
  });
  $("#dir").onclick = () => {
    if (!S.sel) return toast("Välj en startruta först");
    S.sel.horizontal = !S.sel.horizontal; renderBoard(); updatePreview();
  };
  $("#word").addEventListener("input", () => { S.chosen = null; updatePreview(); });
  $("#word").addEventListener("keydown", e => { if (e.key === "Enter" && S.preview) playWord(); });
  const chooseTurn = async (p) => {
    if (p === S.game.to_move) return;
    if (S.game.log.length) {
      return toast(`Det är ${S.game.to_move === "me" ? "din" : (S.game.opponent ? S.game.opponent + "s" : "motståndarens")} tur. Ångra senaste draget om något blev fel.`, true);
    }
    try { await refreshGame(await api("PATCH", `/api/games/${S.id}`, { starter: p })); toast("Ändrat vem som börjar"); }
    catch (e) { fail(e); }
  };
  $("#pl-me").onclick = () => chooseTurn("me");
  $("#pl-opp").onclick = () => chooseTurn("opp");
  $("#playbtn").onclick = playWord;

  $("#passbtn").onclick = async () => {
    try {
      await refreshGame(await api("POST", `/api/games/${S.id}/pass`, { player: S.player }));
      clearAnalysis();
      toast(`Pass registrerat – ${S.player === "me" ? "motståndarens" : "din"} tur`);
      closeExchange();
    } catch (e) { fail(e); }
  };
  $("#exbtn").onclick = () => S.ex ? closeExchange() : openExchange();
  $("#undo").onclick = async () => {
    try { await refreshGame(await api("POST", `/api/games/${S.id}/undo`)); toast("Ångrat"); clearAnalysis(); }
    catch (e) { fail(e); }
  };

  const saveRack = debounce(async () => {
    try { await refreshGame(await api("PATCH", `/api/games/${S.id}`, { rack: $("#rack").value })); }
    catch (e) { fail(e); }
  }, 400);
  $("#rack").addEventListener("input", saveRack);
  const saveScores = debounce(async () => {
    try {
      await refreshGame(await api("PATCH", `/api/games/${S.id}`,
        { scores: { me: +$("#sc-me").value || 0, opp: +$("#sc-opp").value || 0 } }));
    } catch (e) { fail(e); }
  }, 500);
  $("#sc-me").addEventListener("input", saveScores);
  $("#sc-opp").addEventListener("input", saveScores);
  $("#dmode").onchange = async () => {
    try { await refreshGame(await api("PATCH", `/api/games/${S.id}`, { dict_mode: $("#dmode").value })); toast("Ordlisteläge ändrat"); }
    catch (e) { fail(e); }
  };

  $("#analyze").onclick = analyze;
  $("#simstop").onclick = () => stopSim(false);
  ["#st-opp", "#st-plies", "#st-cand", "#st-iter", "#st-sort", "#inclex", "#st-prune", "#st-seed", "#st-workers"]
    .forEach(sel => $(sel).addEventListener("change", saveSettings));
  $("#simset").addEventListener("toggle", () => { if ($("#simset").open && !S.estimate) fetchEstimate(); });

  const dictCall = async (action) => {
    const word = $("#dword").value.trim();
    if (!word) return;
    try {
      if (action === "check") {
        const r = await api("GET", `/api/dict/check?word=${encodeURIComponent(word)}&mode=${S.game.dict_mode}`);
        $("#dres").innerHTML = r.valid ? `<span class="okc">${esc(r.word)} finns</span>` : `<span class="error">${esc(r.word)} finns inte</span>`;
      } else {
        const r = await api("POST", `/api/dict/${action}`, { word, mode: S.game.dict_mode });
        $("#dres").textContent = action === "add" ? `${r.word} tillagt` : `${r.word} borttaget`;
        await refreshPreview();
        if (S.analysis) $("#analysis").insertAdjacentHTML("afterbegin",
          `<div class="warn">Ordlistan har ändrats – tryck Analysera igen för uppdaterade drag.</div>`);
      }
    } catch (e) { fail(e); }
  };
  $("#dcheck").onclick = () => dictCall("check");
  $("#dadd").onclick = () => dictCall("add");
  $("#drem").onclick = () => dictCall("remove");
}

async function playWord() {
  if (!S.sel || !S.preview) return;
  const p = S.preview;
  const bad = p.words.some(w => !w.valid) || p.warnings.length;
  if (bad && !confirm("Draget har varningar:\n" + p.warnings.join("\n") + "\n\nLägg ändå?")) return;
  try {
    const r = await api("POST", `/api/games/${S.id}/play`, { ...S.sel, word: $("#word").value.trim(), player: S.player });
    $("#word").value = "";
    S.preview = null; S.sel = null;
    clearAnalysis();
    await refreshGame(r.game);
    const extra = r.warnings.filter(w => w.startsWith("Handen"));
    toast(`${r.score} p` + (extra.length ? " – " + extra.join("; ") : ""));

  } catch (e) { fail(e); }
}

// ---------- analys ----------
const moveKey = m => m.kind + "|" + m.exchanged + "|" +
  m.placements.map(p => `${p.row},${p.col},${p.letter},${p.blank ? 1 : 0}`).join(";");

async function loadSettings() {
  S.settings = await api("GET", "/api/settings");
  const st = S.settings;
  $("#st-opp").value = st.opponent_model;
  $("#st-plies").value = String(st.plies);
  $("#st-cand").value = st.candidates;
  $("#st-iter").value = st.iterations || "";
  $("#st-sort").value = st.sort;
  $("#inclex").checked = st.include_exchanges;
  $("#st-prune").checked = st.prune;
  $("#st-seed").value = st.seed;
  $("#st-workers").value = st.workers;
  renderEstimate();
}

async function saveSettings(e) {
  if (!S.settings) return;
  const st = { ...S.settings };
  st.opponent_model = $("#st-opp").value;
  st.plies = +$("#st-plies").value;
  st.candidates = Math.min(60, Math.max(1, Math.round(+$("#st-cand").value || 15)));
  st.iterations = Math.max(0, Math.round(+$("#st-iter").value || 0));
  st.sort = $("#st-sort").value;
  st.include_exchanges = $("#inclex").checked;
  st.prune = $("#st-prune").checked;
  st.seed = Math.round(+$("#st-seed").value || 0);
  st.workers = Math.max(0, Math.round(+$("#st-workers").value || 0));
  try { S.settings = await api("PUT", "/api/settings", st); toast("Inställningar sparade"); }
  catch (err) { return fail(err); }
  // Antal kandidater, byten och processer påverkar hur många iterationer som ryms.
  if (e && ["st-cand", "inclex", "st-workers"].includes(e.target.id)) { S.estimate = null; fetchEstimate(); }
  else renderEstimate();
}

// ---------- tidsbudget ----------
async function fetchEstimate() {
  if (!S.game || !S.game.rack || !$("#simset").open) return renderEstimate();
  const gid = S.id, rack = S.game.rack;
  $("#st-est").textContent = "Beräknar hur många iterationer som ryms…";
  try {
    const est = await api("GET", `/api/games/${gid}/estimate`);
    if (S.id === gid && S.game.rack === rack) { S.estimate = est; }
  } catch (e) { S.estimate = { error: e.message }; }
  renderEstimate();
}

function renderEstimate() {
  const el = $("#st-est"), sel = $("#st-plies");
  if (!el || !sel) return;
  const est = S.estimate;
  const byPlies = {};
  if (est && est.options) for (const o of est.options) byPlies[o.plies] = o;
  for (const opt of sel.options) {
    const o = byPlies[opt.value];
    opt.disabled = !!o && !o.feasible;
    opt.textContent = pliesName(+opt.value) + (o ? (o.feasible ? ` (max ${o.max_iterations} it.)` : " (ryms ej)") : "");
  }
  const cur = S.settings ? byPlies[S.settings.plies] : null;
  $("#st-itermax").textContent = cur ? (cur.feasible ? `max ${cur.max_iterations} på ${est.max_seconds} s` : "ryms inte") : "";
  if (!est) {
    el.textContent = S.game && S.game.rack ? "" : "Fyll i handen för att se hur många iterationer som ryms.";
    return;
  }
  if (est.error) { el.innerHTML = `<span class="error">${esc(est.error)}</span>`; return; }
  el.innerHTML = `Uppskattning för ställningen: ca ${est.moves_left} drag kvar i matchen ·
    ${est.ply_ms} ms per motståndardrag${est.blank_share ? ` (blank i ${Math.round(100 * est.blank_share)} % av händerna)` : ""} ·
    ${est.kept_blanks ? `${est.kept_blanks} ${est.kept_blanks === 1 ? "kandidat sparar" : "kandidater sparar"} blank (ditt nästa drag upp till ${Math.round(est.kept_blank_ply_ms)} ms) ·` : ""}
    ${est.candidates} kandidater · ${est.workers} ${est.workers === 1 ? "process" : "processer"} · max ${est.max_seconds} s.
    ${cur && !cur.feasible ? `<div class="error">${esc(pliesName(S.settings.plies))} ryms inte inom ${est.max_seconds} s – välj färre drag framåt eller färre kandidater.</div>` : ""}`;
}

function stopSim(forget = true) {
  if (S.simTimer) { clearTimeout(S.simTimer); S.simTimer = null; }
  if (S.sim && S.sim.status === "running") {
    api("POST", `/api/sim/${S.sim.job}/stop`).then(r => {
      if (!forget && S.sim && S.sim.job === r.job) { S.sim = { ...r, notes: S.sim.notes }; renderAnalysis(); }
    }).catch(() => {});
  }
  if (forget) S.sim = null;
  const b = $("#simstop");
  if (b) b.classList.add("hidden");
}

function clearAnalysis() {
  stopSim();
  S.analysis = null; S.chosen = null; S.simNote = null;
  const el = $("#analysis");
  if (el) el.innerHTML = "";
}

async function analyze() {
  const btn = $("#analyze");
  btn.disabled = true; btn.textContent = "Analyserar…";
  stopSim();
  try {
    const t0 = performance.now();
    const inc = $("#inclex").checked;
    S.analysis = await api("POST", `/api/games/${S.id}/analyze`, { include_exchanges: inc, include_pass: inc, limit: 100 });
    S.analysis.ms = Math.round(performance.now() - t0);
    S.chosen = null;
    S.simNote = null;
    if (S.game.game_over) S.simNote = null;
    else if (S.game.to_move !== "me") S.simNote = "Simuleringen körs när det är din tur.";
    else {
      try {
        S.sim = await api("POST", `/api/games/${S.id}/simulate`, {});
        S.estimate = S.sim.estimate;
        renderEstimate();
        $("#simstop").classList.remove("hidden");
        pollSim();
      } catch (e) {
        S.simNote = "Ingen simulering: " + e.message;
        S.estimate = null;
        if ($("#simset").open) fetchEstimate(); else $("#simset").open = true;   // visa vad som ryms
      }
    }
    renderAnalysis();
  } catch (e) { fail(e); }
  finally { btn.disabled = false; btn.textContent = "Analysera"; }
}

function pollSim() {
  S.simTimer = setTimeout(async () => {
    if (!S.sim) return;
    const job = S.sim.job, notes = S.sim.notes;
    let r;
    try { r = await api("GET", `/api/sim/${job}`); }
    catch (e) { S.simTimer = null; return fail(e); }
    if (!S.sim || S.sim.job !== job) return;      // ny analys har startats
    S.sim = { ...r, notes };
    renderAnalysis();
    if (r.status === "running" || r.status === "pending") pollSim();
    else {
      S.simTimer = null;
      $("#simstop").classList.add("hidden");
      if (r.status === "error") toast("Simuleringen misslyckades: " + r.error, true);
    }
  }, 700);
}

function moveCells(m) {
  const what = m.kind === "play" ? `<span class="mono">${esc(m.word)}</span>` : m.kind === "pass" ? "Pass" : `Byt <span class="mono">${esc(m.exchanged)}</span>`;
  const where = m.kind === "play" ? pos(m.row, m.col, m.horizontal) : "";
  return `<td>${what}</td><td class="muted">${where}</td><td class="num">${m.kind === "play" ? m.score : ""}</td>
      <td class="mono">${esc(m.leave) || "–"}</td>`;
}

const signed = x => (x > 0 ? "+" : "") + x.toFixed(1);

function renderAnalysis() {
  const a = S.analysis;
  if (!a) return;
  const sim = S.sim;
  const chosenKey = S.chosen ? moveKey(S.chosen) : null;
  S.rows = [];
  let rows = "";
  if (sim) {
    for (const m of sim.candidates) {
      const i = S.rows.push(m) - 1;
      const wse = m.win_se != null ? `<span class="se">±${m.win_se.toFixed(1)}</span>` : "";
      const mse = m.margin_se != null ? `<span class="se">±${m.margin_se.toFixed(1)}</span>` : "";
      const tip = m.pruned ? "Gallrad: klart sämre än bästa draget" : `Statiskt värde (poäng + leave): ${m.static}`;
      rows += `<tr data-i="${i}" class="${moveKey(m) === chosenKey ? "chosen" : ""} ${m.pruned ? "pruned" : ""}" title="${esc(tip)}">
        ${moveCells(m)}<td class="num">${m.win != null ? m.win.toFixed(1) + wse : "…"}</td>
        <td class="num">${m.margin != null ? signed(m.margin) + mse : "…"}</td>
        <td class="num muted">${m.n}</td></tr>`;
    }
  }
  const simKeys = new Set(S.rows.map(moveKey));
  const rest = a.moves.filter(m => !simKeys.has(moveKey(m)));
  if (sim && rest.length) rows += `<tr class="sep"><td colspan="7">Ej simulerade drag (efter poäng)</td></tr>`;
  for (const m of rest) {
    const i = S.rows.push(m) - 1;
    rows += `<tr data-i="${i}" class="${moveKey(m) === chosenKey ? "chosen" : ""}">
      ${moveCells(m)}<td class="num muted">–</td><td class="num muted">–</td><td class="num muted">–</td></tr>`;
  }
  let simInfo = "";
  if (sim) {
    const st = sim.settings;
    const state = { running: "pågår…", done: "klar", stopped: "stoppad", error: "fel", pending: "startar…" }[sim.status] || sim.status;
    const pruned = sim.candidates.length - sim.active;
    const target = sim.target_iterations != null ? `/${sim.target_iterations}` : "";
    simInfo = `<div class="muted">Simulering ${state} · ${sim.iterations}${target} iterationer · ${sim.elapsed} s ·
      ${sim.rollouts} rollouts (${sim.rate}/s) · ${st.opponent_model === "human" ? "mänsklig" : "perfekt"} motståndare ·
      ${st.plies === 0 ? "till slutet" : st.plies + " drag framåt"}${pruned ? ` · ${pruned} gallrade` : ""}</div>`;
    if (sim.time_limited) simInfo += `<div class="warn">Tidsgränsen ${st.max_seconds} s nåddes efter ${sim.iterations} iterationer – uppskattningen var för optimistisk.</div>`;
    else if (sim.status === "done" && sim.active <= 1 && sim.candidates.length > 1 && sim.iterations < (sim.target_iterations || 0))
      simInfo += `<div class="muted">Avslutad i förtid: alla andra drag gallrades bort som klart sämre.</div>`;
    if (sim.error) simInfo += `<div class="error">${esc(sim.error)}</div>`;
    for (const n of sim.notes || []) simInfo += `<div class="warn">${esc(n)}</div>`;
  }
  const notes = a.notes.map(n => `<div class="warn">${esc(n)}</div>`).join("")
    + (S.simNote ? `<div class="muted">${esc(S.simNote)}</div>` : "");
  const wrap = $("#analysis .tablewrap");
  const scroll = wrap ? wrap.scrollTop : 0;
  $("#analysis").innerHTML = `
    ${notes}
    <div class="muted">${a.total_plays} lagliga läggningar (visar topp ${Math.min(100, a.total_plays)}) · ${a.ms} ms</div>
    ${simInfo}
    <div id="chosenbar" class="row" style="margin:6px 0"></div>
    <div class="tablewrap"><table>
      <thead><tr><th>Drag</th><th>Position</th><th class="num">Poäng</th><th>Kvar</th>
        <th class="num">Vinst %</th><th class="num">Marginal</th><th class="num">Sim.</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  $("#analysis .tablewrap").scrollTop = scroll;
  $("#analysis tbody").onclick = e => {
    const tr = e.target.closest("tr[data-i]");
    if (!tr) return;
    const m = S.rows[+tr.dataset.i];
    S.chosen = chosenKey === moveKey(m) ? null : m;
    renderAnalysis(); renderBoard();
  };
  renderChosenBar();
}

function renderChosenBar() {
  const m = S.chosen, bar = $("#chosenbar");
  if (!bar) return;
  if (!m) { bar.innerHTML = `<span class="muted">Klicka på ett drag för att förhandsvisa det.</span>`; return; }
  const label = m.kind === "play" ? `${m.word} ${pos(m.row, m.col, m.horizontal)} – ${m.score} p`
    : m.kind === "pass" ? "Pass" : `Byt ${m.exchanged}`;
  if (S.game.to_move !== "me") {
    bar.innerHTML = `<b>${esc(label)}</b> <span class="muted">– väntar på ${esc(S.game.opponent ? S.game.opponent + "s" : "motståndarens")} drag</span>`;
    return;
  }
  bar.innerHTML = `<b>${esc(label)}</b> <button class="primary small" id="dochosen">Lägg draget</button>`;
  $("#dochosen").onclick = async () => {
    try {
      let g;
      if (m.kind === "play") {
        const r = await api("POST", `/api/games/${S.id}/play`,
          { row: m.row, col: m.col, horizontal: m.horizontal, word: m.word, player: "me" });
        g = r.game; toast(`${r.score} p – fyll i nya brickor i handen`);
      } else if (m.kind === "pass") {
        g = await api("POST", `/api/games/${S.id}/pass`, { player: "me" });
      } else {
        g = await api("POST", `/api/games/${S.id}/exchange`, { player: "me", tiles: m.exchanged });
        toast("Byte registrerat – fyll i dina nya brickor");
      }
      S.sel = null; S.preview = null;
      clearAnalysis();
      await refreshGame(g);
      $("#rack").focus();
    } catch (e) { fail(e); }
  };
}

// ---------- routing ----------
async function route() {
  try {
    if (!CFG) CFG = await api("GET", "/api/config");
    const h = location.hash || "#/";
    if (h.startsWith("#/game/")) await viewGame(decodeURIComponent(h.slice(7)));
    else if (h === "#/new") viewNew();
    else await viewHome();
  } catch (e) {
    app.innerHTML = `<div class="panel error">${esc(e.message)}</div>`;
  }
}
window.addEventListener("hashchange", route);
route();
