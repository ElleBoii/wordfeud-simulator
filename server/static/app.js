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
        <p class="muted">Välj typ och klicka på rutorna. Stämmer brädet med standardlayouten behöver du inte ändra något.</p>
        <div class="row palette" id="pal">
          ${[".", "d", "t", "D", "T"].map(k => `<button data-k="${k}" class="${BONUS[k][0]}">${BONUS[k][1] || "Ingen"}</button>`).join("")}
        </div>
        <div class="row" style="margin-top:8px">
          <button id="std">Standardlayout</button><button id="clear">Töm</button>
        </div>
        <div class="row" style="margin-top:14px"><button class="primary" id="create">Skapa match</button></div>
      </div>
    </div>`;
  const draw = () => {
    $("#board").innerHTML = boardHTML(layout.map(r => r.join("")));
    app.querySelectorAll("#pal button").forEach(b => b.classList.toggle("on", b.dataset.k === brush));
  };
  onSquare($("#board"), (r, c) => { layout[r][c] = brush; draw(); });
  $("#pal").onclick = e => { const b = e.target.closest("button"); if (b) { brush = b.dataset.k; draw(); } };
  $("#std").onclick = () => { layout = CFG.standard_layout.map(r => r.split("")); draw(); };
  $("#clear").onclick = () => { layout = layout.map(r => r.map(() => ".")); draw(); };
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
  Object.assign(S, { id, game: null, sel: null, player: "me", preview: null, analysis: null, chosen: null, ex: null });
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
            <label><input type="checkbox" id="inclex" checked> byten/pass</label>
            <button class="primary" id="analyze">Analysera</button>
          </div>
          <div id="analysis"><p class="muted">Rankar alla lagliga drag efter poäng. Vinstchans kommer med simuleringen (fas 4).</p></div>
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

async function refreshGame(g) {
  S.game = g || await api("GET", `/api/games/${S.id}`);
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
    S.analysis = null; S.chosen = null;
    $("#analysis").innerHTML = "";
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
      toast(`Pass registrerat – ${S.player === "me" ? "motståndarens" : "din"} tur`);
      closeExchange();
    } catch (e) { fail(e); }
  };
  $("#exbtn").onclick = () => S.ex ? closeExchange() : openExchange();
  $("#undo").onclick = async () => {
    try { await refreshGame(await api("POST", `/api/games/${S.id}/undo`)); toast("Ångrat"); S.analysis = null; }
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
    S.preview = null; S.chosen = null; S.analysis = null; S.sel = null;
    await refreshGame(r.game);
    $("#analysis").innerHTML = "";
    const extra = r.warnings.filter(w => w.startsWith("Handen"));
    toast(`${r.score} p` + (extra.length ? " – " + extra.join("; ") : ""));

  } catch (e) { fail(e); }
}

// ---------- analys ----------
async function analyze() {
  const btn = $("#analyze");
  btn.disabled = true; btn.textContent = "Analyserar…";
  try {
    const t0 = performance.now();
    const inc = $("#inclex").checked;
    S.analysis = await api("POST", `/api/games/${S.id}/analyze`, { include_exchanges: inc, include_pass: inc, limit: 100 });
    S.analysis.ms = Math.round(performance.now() - t0);
    S.chosen = null;
    renderAnalysis();
  } catch (e) { fail(e); }
  finally { btn.disabled = false; btn.textContent = "Analysera"; }
}

function renderAnalysis() {
  const a = S.analysis;
  if (!a) return;
  const rows = a.moves.map((m, i) => {
    const what = m.kind === "play" ? `<span class="mono">${esc(m.word)}</span>` : m.kind === "pass" ? "Pass" : `Byt <span class="mono">${esc(m.exchanged)}</span>`;
    const where = m.kind === "play" ? pos(m.row, m.col, m.horizontal) : "";
    return `<tr data-i="${i}" class="${S.chosen === m ? "chosen" : ""}">
      <td>${what}</td><td class="muted">${where}</td><td class="num">${m.kind === "play" ? m.score : ""}</td>
      <td class="mono">${esc(m.leave) || "–"}</td><td class="num muted">–</td><td class="num muted">–</td><td class="num muted">–</td></tr>`;
  }).join("");
  $("#analysis").innerHTML = `
    ${a.notes.map(n => `<div class="warn">${esc(n)}</div>`).join("")}
    <div class="muted">${a.total_plays} lagliga läggningar (visar topp ${Math.min(100, a.total_plays)}) · ${a.ms} ms</div>
    <div id="chosenbar" class="row" style="margin:6px 0"></div>
    <div class="tablewrap"><table>
      <thead><tr><th>Drag</th><th>Position</th><th class="num">Poäng</th><th>Kvar</th>
        <th class="num">Vinst %</th><th class="num">Marginal</th><th class="num">Sim.</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  $("#analysis tbody").onclick = e => {
    const tr = e.target.closest("tr");
    if (!tr) return;
    const m = a.moves[+tr.dataset.i];
    S.chosen = S.chosen === m ? null : m;
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
      S.chosen = null; S.analysis = null; S.sel = null; S.preview = null;
      $("#analysis").innerHTML = "";
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
