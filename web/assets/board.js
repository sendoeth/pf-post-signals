"use strict";
// Leaderboard: every position in data/charts.json, filtered, sorted and ranked. All values come
// from the bundle (the records); the rules below are mirrored independently in tests/board_test.js.

const fmtPct = x => (x > 0 ? "+" : x < 0 ? "-" : "") + (Math.abs(x) * 100).toFixed(2) + "%";
const fmtPrice = p => p.toLocaleString("en-US", { maximumFractionDigits: 8 });
const fmtTime = iso => iso.slice(0, 10) + " " + iso.slice(11, 16) + " UTC";
const fmtDate = iso => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const signClass = x => x == null ? "unresolved" : x > 0 ? "gain" : x < 0 ? "loss" : "";
const AVATAR_FILE = /^[a-z0-9_]{1,15}\.jpg$/;
const DEFAULTS = { time: "all", side: "all", state: "all", author: "all", asset: "all", sort: "return" };
const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, attrs, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
}
function svg(tag, attrs) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  return n;
}
function age(fromIso, toIso) {
  const m = Math.max(0, Math.floor((Date.parse(toIso) - Date.parse(fromIso)) / 60000));
  const d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
  return d ? `${d}d` : h ? `${h}h` : `${m}m`;
}

// One row per drawn post. Return = for the call when a side is stated, else the price move.
function rowsFrom(bundle) {
  const rows = [];
  for (const a of bundle.assets) for (const p of a.posts) {
    const side = p.side === 1 ? "long" : p.side === -1 ? "short" : "none";
    const ret = PFPS.result(p);          // closed: frozen realized return; open: since post (for the call)
    const best = p.best ? (p.side ? p.best.for_call : p.best.move) : null;
    rows.push({ p, asset: a, side, ret, best, id: p.post.id, assetName: a.name, author: p.post.author, posted: p.post.posted_at,
      state: p.closed ? "closed" : "open" });
  }
  return rows;
}

function applyFilters(rows, f, asOf) {
  const ref = Date.parse(asOf);
  return rows.filter(r =>
    (f.time === "all" || (f.time === "7d" ? Date.parse(r.posted) >= ref - 7 * 864e5 : r.posted.slice(0, 10) === asOf.slice(0, 10))) &&
    (f.side === "all" || r.side === f.side) &&
    (f.state === "all" || r.state === f.state) &&
    (f.author === "all" || r.author === f.author) &&
    (f.asset === "all" || r.assetName === f.asset));
}

function sortRows(rows, sort) {
  const key = r => sort === "best" ? r.best : sort === "newest" ? Date.parse(r.posted) : r.ret;
  return rows.slice().sort((x, y) => {
    const a = key(x), b = key(y);
    if (a == null && b != null) return 1;           // unresolved last
    if (b == null && a != null) return -1;
    if (a !== b && a != null) return b - a;          // high first
    if (x.posted !== y.posted) return x.posted < y.posted ? 1 : -1;   // then newest
    return x.id + x.assetName < y.id + y.assetName ? -1 : 1;
  });
}

function readFilters() {
  const q = new URLSearchParams(location.search), f = {};
  for (const k of Object.keys(DEFAULTS)) f[k] = q.get(k) || DEFAULTS[k];
  return f;
}
function writeUrl(f) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v !== DEFAULTS[k]) q.set(k, v);
  const s = q.toString();
  history.replaceState(null, "", s ? "?" + s : location.pathname);
}

function avatar(handle, avatars) {
  const raw = avatars[handle.toLowerCase()];
  const ok = raw && typeof raw.file === "string" && AVATAR_FILE.test(raw.file) && raw.file === handle.toLowerCase() + ".jpg";
  const box = el("span", { class: "avatar", "data-avatar": ok ? "image" : "initials", "aria-hidden": "true" });
  if (ok) {
    const img = el("img", { src: "avatars/" + raw.file, alt: "" });
    img.addEventListener("error", () => { box.replaceChildren(handle.slice(0, 2).toUpperCase()); box.setAttribute("data-avatar", "initials"); });
    box.append(img);
  } else box.textContent = handle.replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "?";
  if (box.getAttribute("data-avatar") === "initials") { box.style.backgroundColor = PFPS.authorColor(handle); box.style.color = "#fff"; }
  return box;
}

// Price path from the entry bar to the record's latest bar (the bundle's line for that asset).
function sparkline(r) {
  const p = r.p, box = svg("svg", { class: "spark", viewBox: "0 0 120 34", "aria-hidden": "true" });
  if (!p.entry || !p.latest) { box.setAttribute("data-points", "0"); return box; }
  const end = p.closed ? p.closed.exit.at : p.latest.at;      // a closed position stops at its exit
  const bars = r.asset.series.filter(([t]) => t >= p.entry.at && t <= end);
  box.setAttribute("data-points", String(bars.length));
  if (bars.length < 2) return box;
  const vals = bars.map(b => b[1]), lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const x = i => (i / (bars.length - 1)) * 116 + 2, y = v => 31 - ((v - lo) / span) * 28;
  box.append(svg("line", { class: "base", x1: 2, x2: 118, y1: y(p.entry.price), y2: y(p.entry.price) }));
  box.append(svg("polyline", { class: "path " + signClass(r.ret), points: bars.map((b, i) => x(i).toFixed(1) + "," + y(b[1]).toFixed(1)).join(" ") }));
  return box;
}

function renderStats(rows) {
  const box = document.getElementById("stats");
  const done = rows.filter(r => r.ret != null);
  const stat = (name, label, value, cls, raw) => {
    const s = el("div", { class: "stat", "data-stat": name });
    s.append(el("span", { class: "label" }, label));
    const v = el("strong", { class: cls || "" }, value);
    if (raw !== undefined) v.setAttribute("data-raw", JSON.stringify(raw));
    s.append(v);
    return s;
  };
  const avg = done.length ? done.reduce((s, r) => s + r.ret, 0) / done.length : null;
  const hit = done.length ? done.filter(r => r.ret > 0).length / done.length : null;
  const top = done.length ? done.reduce((m, r) => (r.ret > m.ret ? r : m)) : null;
  box.replaceChildren(
    stat("count", "Positions", String(rows.length), "", rows.length),
    stat("hit_rate", "In profit", hit == null ? "–" : `${Math.round(hit * 100)}%`, "", hit),
    stat("avg_return", "Average return", avg == null ? "–" : fmtPct(avg), signClass(avg), avg),
    stat("best_call", "Best call", top ? `${fmtPct(top.ret)} · ${top.assetName} @${top.author}` : "–", top ? signClass(top.ret) : "", top ? top.id + "|" + top.assetName : null));
}

// Per-author summary over the rows matching every filter except the author (so authors can be
// compared side by side). Sample-size flags follow step 3: under 10 calls "insufficient sample",
// under 30 "unreliable sample"; a small sample is never presented as a track record.
const MIN_N_REPORTABLE = 10, MIN_N_RELIABLE = 30;
function authorSummary(rows) {
  const by = {};
  for (const r of rows) (by[r.author] = by[r.author] || []).push(r);
  return Object.keys(by).sort().map(a => {
    const done = by[a].filter(r => r.ret != null), n = done.length;
    const best = n ? done.reduce((m, r) => (r.ret > m.ret ? r : m)) : null, worst = n ? done.reduce((m, r) => (r.ret < m.ret ? r : m)) : null;
    return { author: a, calls: by[a].length, resolved: n, hit: n ? done.filter(r => r.ret > 0).length / n : null,
      avg: n ? done.reduce((s, r) => s + r.ret, 0) / n : null, best, worst,
      flag: n < MIN_N_REPORTABLE ? "insufficient sample" : n < MIN_N_RELIABLE ? "unreliable sample" : "ok" };
  });
}
function renderAuthors(summary, selected, avatars) {
  const body = document.querySelector("#authors tbody");
  body.replaceChildren();
  for (const s of summary) {
    const tr = el("tr", { "data-author": s.author, class: s.author === selected ? "selected" : "" });
    const who = el("td", { class: "a-who" });
    who.append(avatar(s.author, avatars), el("span", null, "@" + s.author));
    const cell = (name, text, raw, cls) => { const td = el("td", { "data-field": name, class: cls || "" }, text); if (raw !== undefined) td.setAttribute("data-raw", JSON.stringify(raw)); return td; };
    const callText = r => r ? `${fmtPct(r.ret)} ${r.assetName}` : "–";
    tr.append(who, cell("calls", String(s.calls), s.calls),
      cell("hit", s.hit == null ? "–" : `${Math.round(s.hit * 100)}%`, s.hit),
      cell("avg", s.avg == null ? "–" : fmtPct(s.avg), s.avg, signClass(s.avg)),
      cell("best", callText(s.best), s.best ? s.best.id + "|" + s.best.assetName : null, s.best ? signClass(s.best.ret) : ""),
      cell("worst", callText(s.worst), s.worst ? s.worst.id + "|" + s.worst.assetName : null, s.worst ? signClass(s.worst.ret) : ""),
      cell("flag", s.flag, s.flag, "flag " + (s.flag === "ok" ? "ok" : "warn")));
    body.append(tr);
  }
}

function renderRows(rows, asOf, avatars) {
  const list = document.getElementById("rows");
  list.replaceChildren();
  rows.forEach((r, i) => {
    const p = r.p;
    const li = el("li", { "data-post-id": r.id, "data-asset": r.assetName, "data-rank": String(i + 1) });
    const a = el("a", { class: "row", href: PFPS.positionUrl(r.id, r.assetName) });
    a.append(el("span", { class: "rank", "data-field": "rank" }, String(i + 1)));
    const who = el("span", { class: "who" });
    who.append(avatar(r.author, avatars));
    const meta = el("span", { class: "meta" });
    const line1 = el("span", { class: "line1" });
    line1.append(el("span", { class: "ticker", "data-field": "asset" }, r.assetName));
    line1.append(el("span", { class: "badge " + r.side, "data-field": "side" }, r.side === "none" ? "NO SIDE" : r.side.toUpperCase()));
    if (p.closed) line1.append(el("span", { class: "tag closed", "data-field": "closed_tag", title: PFPS.statusTip(p) }, "closed"));
    if (p.asset.stand_in) line1.append(el("span", { class: "tag", "data-field": "stand_in", title: p.asset.stand_in.reason }, "stand-in"));
    if (p.asset.adjustments && p.asset.adjustments.length) line1.append(el("span", { class: "tag", "data-field": "adjusted", title: p.asset.adjustments.map(a => `${a.kind} on ${fmtTime(a.at)}`).join("; ") }, "split-adj."));
    meta.append(line1);
    const line2 = el("span", { class: "line2" });
    line2.append(el("span", { "data-field": "author" }, "@" + r.author), " · ");
    line2.append(el("time", { datetime: r.posted, title: fmtTime(r.posted), "data-field": "posted" }, `${fmtDate(r.posted)} · ${age(r.posted, asOf)}`));
    meta.append(line2);
    if (p.post.text) meta.append(el("span", { class: "quote", "data-field": "quote" }, "“" + p.post.text.replace(/\s+/g, " ").trim() + "”"));
    who.append(meta);
    a.append(who);
    const sp = el("span", { class: "col-spark" });
    sp.append(sparkline(r));
    a.append(sp);
    a.append(el("span", { class: "col-px px", "data-field": "prices", title: p.closed ? `exit; now ${fmtPrice(p.latest.price)} (if still held ${fmtPct(PFPS.ifHeld(p))})` : "" },
      p.entry ? `${fmtPrice(p.entry.price)} → ${p.closed ? fmtPrice(p.closed.exit.price) + " exit" : p.latest ? fmtPrice(p.latest.price) : "–"}` : "no entry bar"));
    a.append(el("span", { class: "r ret " + signClass(r.ret), "data-field": "return", "data-raw": JSON.stringify(r.ret) },
      r.ret == null ? "unresolved" : fmtPct(r.ret)));
    const bestCell = el("span", { class: "r col-best best " + signClass(r.best), "data-field": "best", "data-raw": JSON.stringify(r.best) },
      r.best == null ? "–" : "▲ " + fmtPct(r.best));
    a.append(bestCell);
    a.append(el("span", { class: "status", "data-field": "status", "data-raw": JSON.stringify(p.status), title: PFPS.statusTip(p) }, PFPS.statusLabel(p)));
    li.append(a);
    list.append(li);
  });
  document.getElementById("empty").hidden = rows.length > 0;
}

function fillSelect(id, values) {
  const s = document.getElementById(id);
  for (const v of values) s.append(el("option", { value: v }, v));
}

async function main() {
  const getJson = u => fetch(u).then(r => { if (!r.ok) throw new Error(u + " HTTP " + r.status); return r.json(); });
  const [bundle, avatars] = await Promise.all([getJson("data/charts.json"), getJson("avatars/index.json").catch(() => ({}))]);
  const asOf = bundle.prices_as_of || new Date().toISOString().slice(0, 19) + "Z";
  const all = rowsFrom(bundle);
  document.getElementById("asof").textContent =
    `${all.length} positions from ${new Set(all.map(r => r.author)).size} author${new Set(all.map(r => r.author)).size === 1 ? "" : "s"} · ` +
    (bundle.prices_as_of ? `prices as of ${fmtTime(bundle.prices_as_of)} (daily refresh)` : "prices not refreshed yet");
  document.getElementById("asof").setAttribute("data-prices-as-of", bundle.prices_as_of || "");
  fillSelect("f-author", [...new Set(all.map(r => r.author))].sort());
  fillSelect("f-asset", [...new Set(all.map(r => r.assetName))].sort());
  const f = readFilters();
  for (const k of Object.keys(DEFAULTS)) {
    const s = document.getElementById("f-" + k);
    // match url values case-insensitively (?author=corbanu -> Corbanu); unknown values -> default
    const hit = [...s.options].find(o => o.value.toLowerCase() === String(f[k]).toLowerCase());
    f[k] = hit ? hit.value : DEFAULTS[k];
    s.value = f[k];
  }
  writeUrl(f);   // invalid or non-canonical values in the address bar are rewritten to the state shown
  const draw = () => {
    const rows = sortRows(applyFilters(all, f, asOf), f.sort);
    renderAuthors(authorSummary(applyFilters(all, { ...f, author: "all" }, asOf)), f.author, avatars);
    renderStats(rows);
    renderRows(rows, asOf, avatars);
    document.body.setAttribute("data-shown", String(rows.length));
  };
  document.getElementById("filters").addEventListener("change", e => {
    const k = e.target.name;
    if (k in DEFAULTS) { f[k] = e.target.value; writeUrl(f); draw(); }
  });
  document.getElementById("filters").addEventListener("submit", e => e.preventDefault());
  draw();
  document.body.setAttribute("data-ready", "1");
}

main().catch(e => {
  document.getElementById("rows").replaceChildren(el("li", { class: "error" }, "Could not load the positions: " + e.message));
  document.body.setAttribute("data-ready", "error");
});
