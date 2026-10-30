"use strict";
const SVGNS = "http://www.w3.org/2000/svg";
const HORIZONS = ["1", "7", "30"];
const state = { bundle: null, asset: null, selected: null };

// Formatting (mirrored independently in tests/browser_test.js).
function fmtPct(x) {
  const sign = x > 0 ? "+" : x < 0 ? "-" : "";
  return sign + (Math.abs(x) * 100).toFixed(2) + "%";
}
function fmtPrice(p) { return p.toLocaleString("en-US", { maximumFractionDigits: 8 }); }
function fmtTime(iso) { return iso.slice(0, 10) + " " + iso.slice(11, 16) + " UTC"; }
function direction(post) {
  const c = post.change_since_post;
  return c == null ? "none" : c > 0 ? "up" : c < 0 ? "down" : "flat";
}
function missing(t0, t1, source) {
  const a = Date.parse(t0), b = Date.parse(t1);
  if (source === "binance") return b - a > 2 * 3600e3;
  for (let d = new Date(t0.slice(0, 10) + "T00:00:00Z"); ; ) {
    d.setUTCDate(d.getUTCDate() + 1);
    if (d.getTime() + 864e5 > b) return false;   // only whole days strictly between the bars
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) return true;
  }
}
function el(tag, attrs, text) {
  const n = attrs && attrs.svg ? document.createElementNS(SVGNS, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) if (k !== "svg") n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
}
function svg(tag, attrs, text) { return el(tag, Object.assign({ svg: true }, attrs), text); }

function niceTicks(min, max, count) {
  const span = max - min || Math.abs(max) || 1;
  const step0 = span / count, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0);
  const ticks = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(+t.toPrecision(12));
  return ticks;
}

function render() {
  const a = state.asset, root = document.getElementById("chart");
  while (root.lastChild && root.lastChild.tagName !== "title") root.removeChild(root.lastChild);
  const W = Math.max(320, document.getElementById("chart-wrap").clientWidth - 8);
  const H = W < 560 ? 300 : 380;
  const m = { l: W < 560 ? 52 : 64, r: 16, t: 18, b: 30 };
  root.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const series = a.series, t0 = Date.parse(series[0][0]), t1 = Date.parse(series[series.length - 1][0]);
  const drawn = a.posts.filter(p => p.entry);
  const STACK = 28, HIT = 13; // STACK > 2 * HIT: stacked hit areas never overlap
  let lo = Math.min(...series.map(b => b[1])), hi = Math.max(...series.map(b => b[1]));
  const pad = (hi - lo) * 0.06 || hi * 0.01;
  lo -= pad; hi += pad;
  const plotH = H - m.t - m.b;
  // Posts closer than two hit radii on the x axis (same entry bar, or hours apart on a long
  // range) form a cluster; each later bubble sits at least STACK above the previous one, on a
  // stem from its own entry point, so every post stays separately clickable.
  const xOf = t => (Date.parse(t) - t0) / (t1 - t0 || 1) * (W - m.l - m.r);
  const sorted = drawn.slice().sort((p, q) => p.entry.at < q.entry.at ? -1 : p.entry.at > q.entry.at ? 1 : p.post.id < q.post.id ? -1 : 1);
  const clusters = [];
  for (const p of sorted) {
    const c = clusters[clusters.length - 1];
    if (c && xOf(p.entry.at) - xOf(c[c.length - 1].entry.at) < 2 * HIT) c.push(p); else clusters.push([p]);
  }
  const maxStack = Math.max(0, ...clusters.map(c => c.length - 1));
  hi += (hi - lo) * Math.min(0.6, (maxStack * STACK + 14) / plotH);
  const x = t => m.l + (Date.parse(t) - t0) / (t1 - t0 || 1) * (W - m.l - m.r);
  const y = p => m.t + (hi - p) / (hi - lo) * plotH;

  for (const v of niceTicks(lo, hi, 5)) {
    if (v < lo || v > hi) continue;
    root.append(svg("line", { class: "gridline", x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }));
    root.append(svg("text", { class: "tick", x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, fmtPrice(v)));
  }
  root.append(svg("line", { class: "axis", x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }));
  const days = (t1 - t0) / 864e5, every = days > 40 ? 14 : days > 14 ? 7 : days > 5 ? 2 : 1;
  const first = new Date(t0); first.setUTCHours(0, 0, 0, 0);
  for (let d = new Date(first), i = 0; d.getTime() <= t1; d.setUTCDate(d.getUTCDate() + 1), i++) {
    if (d.getTime() < t0 || i % every) continue;
    const iso = d.toISOString(), px = x(iso);
    if (px > W - m.r - 20) continue;
    root.append(svg("text", { class: "tick", x: px, y: H - m.b + 18, "text-anchor": "middle" },
      d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })));
  }
  // A stretch with no bars across a whole weekday (or > 2 h on a 24/7 asset) is missing data,
  // not a closed market: drawn dashed so it is not read as prices.
  const pt = b => x(b[0]).toFixed(1) + "," + y(b[1]).toFixed(1);
  let solid = "", gaps = "";
  series.forEach((b, i) => {
    if (i && missing(series[i - 1][0], b[0], a.source)) { gaps += "M" + pt(series[i - 1]) + "L" + pt(b); solid += "M" + pt(b); }
    else solid += (i ? "L" : "M") + pt(b);
  });
  root.append(svg("path", { class: "price", d: solid }));
  if (gaps) root.append(svg("path", { class: "price gap", d: gaps, "data-gap": "1" }));

  const cross = svg("line", { class: "crosshair", y1: m.t, y2: H - m.b, visibility: "hidden" });
  const hover = svg("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: plotH, fill: "transparent" });
  root.append(cross, hover);
  const tip = document.getElementById("tip"), times = series.map(b => Date.parse(b[0]));
  hover.addEventListener("pointermove", ev => {
    const r = root.getBoundingClientRect(), vx = (ev.clientX - r.left) * W / r.width;
    const t = t0 + (vx - m.l) / (W - m.l - m.r) * (t1 - t0);
    let i = times.findIndex(v => v >= t); if (i < 0) i = times.length - 1;
    if (i > 0 && t - times[i - 1] < times[i] - t) i--;
    const b = series[i], px = x(b[0]);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
    tip.replaceChildren(el("strong", null, fmtPrice(b[1])), document.createElement("br"), document.createTextNode(fmtTime(b[0])));
    tip.hidden = false;
    const left = px * r.width / W;
    tip.style.left = Math.min(left + 12, r.width - tip.offsetWidth - 4) + "px";
    tip.style.top = "12px";
  });
  hover.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; });

  for (const c of clusters) {
    let prevY = Infinity;
    c.forEach((p, k) => {
      const px = x(p.entry.at), py = y(p.entry.price);
      const cy = Math.min(py, prevY - STACK);
      prevY = cy;
      const dir = direction(p);
      const node = svg("g", { class: "bubble", tabindex: "0", role: "button", "data-post-id": p.post.id, "data-asset": a.name,
        "aria-label": `${p.post.author} ${fmtTime(p.post.posted_at)}, ${p.change_since_post == null ? "no move" : fmtPct(p.change_since_post)} since post` });
      if (cy !== py) node.append(svg("line", { class: "stem", x1: px, x2: px, y1: py, y2: cy + 9 }));
      node.append(svg("circle", { class: "hit", cx: px, cy, r: HIT }));
      node.append(svg("circle", { class: "mark", cx: px, cy, r: 9, fill: dir === "up" ? "var(--up)" : dir === "down" ? "var(--down)" : "var(--flat)" }));
      node.append(svg("text", { x: px, y: cy + 3.2, "text-anchor": "middle" }, dir === "up" ? "▲" : dir === "down" ? "▼" : "•"));
      node.setAttribute("data-href", positionUrl(p));
      node.addEventListener("click", () => select(p));
      node.addEventListener("dblclick", () => { location.href = positionUrl(p); });
      node.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(p); } });
      if (state.selected === p) node.classList.add("selected");
      root.append(node);
    });
  }
}

function positionUrl(p) { return `position.html?post=${encodeURIComponent(p.post.id)}&asset=${encodeURIComponent(p.asset.name)}`; }
function field(dl, name, label, value, raw, cls) {
  dl.append(el("dt", null, label));
  const dd = el("dd", { "data-field": name }, value);
  if (raw !== undefined) dd.setAttribute("data-raw", JSON.stringify(raw));
  if (cls) dd.className = cls;
  dl.append(dd);
}

function card(p) {
  const c = document.getElementById("card");
  c.replaceChildren();
  c.setAttribute("data-post-id", p.post.id);
  c.setAttribute("data-asset", p.asset.name);
  c.append(el("h2", null, "@" + p.post.author));
  c.append(el("p", { class: "meta", "data-field": "posted_at", "data-raw": JSON.stringify(p.post.posted_at) }, "Posted " + fmtTime(p.post.posted_at)));
  if (p.post.text) c.append(el("blockquote", { "data-field": "text" }, p.post.text));
  else c.append(el("p", { class: "empty", "data-field": "text" }, "Post text not saved: open it on X."));
  const dl = el("dl");
  field(dl, "asset", "Asset", `${p.asset.name} (${p.asset.source}:${p.asset.symbol})`);
  field(dl, "side", "Side", p.side === 1 ? "long" : p.side === -1 ? "short" : "not given", p.side ?? null);
  field(dl, "status", "Status", p.status, p.status);
  field(dl, "entry", "Entry", p.entry ? `${fmtPrice(p.entry.price)} @ ${fmtTime(p.entry.at)}` : "no entry bar", p.entry);
  field(dl, "latest", "Latest", p.latest ? `${fmtPrice(p.latest.price)} @ ${fmtTime(p.latest.at)}` : "no bar yet", p.latest);
  const dir = direction(p);
  field(dl, "change_since_post", "Since post", p.change_since_post == null ? "unresolved" : fmtPct(p.change_since_post),
    p.change_since_post, p.change_since_post == null ? "unresolved" : dir === "up" ? "dir-up" : dir === "down" ? "dir-down" : "");
  for (const h of HORIZONS) {
    const v = p.moves[h];
    field(dl, "move_" + h, h + "d move", v == null ? "unresolved · " + p.unresolved[h] : fmtPct(v), v, v == null ? "unresolved" : "");
  }
  if (p.signed_returns) for (const h of HORIZONS) {
    const v = p.signed_returns[h];
    field(dl, "signed_" + h, h + "d for the call", v == null ? "unresolved · " + p.unresolved[h] : fmtPct(v), v, v == null ? "unresolved" : "");
  }
  c.append(dl);
  c.append(el("p", null, ""), el("a", { class: "open-position", href: positionUrl(p), "data-field": "position_url" }, "Open position page →"));
  const link = el("a", { href: p.post.url, target: "_blank", rel: "noopener noreferrer", "data-field": "url" }, "Open the post on X");
  c.append(el("p", null), link);
  c.append(el("p", { class: "notes", "data-field": "record_file" }, `Record ${p.record_file} · sha256 ${p.record_sha256.slice(0, 12)}…`));
}

function select(p) {
  state.selected = p;
  card(p);
  for (const n of document.querySelectorAll(".bubble")) n.classList.toggle("selected", n.getAttribute("data-post-id") === p.post.id);
  for (const r of document.querySelectorAll("#posts tbody tr")) r.classList.toggle("selected", r.getAttribute("data-post-id") === p.post.id);
  if (window.matchMedia("(max-width: 860px)").matches) document.getElementById("card").scrollIntoView({ block: "nearest" });
}

function table() {
  const tb = document.querySelector("#posts tbody");
  tb.replaceChildren();
  for (const p of state.asset.posts) {
    const tr = el("tr", { "data-post-id": p.post.id, tabindex: "0" });
    const first = el("td");
    first.append(el("a", { href: positionUrl(p), class: "row-link", "data-post-id": p.post.id }, fmtTime(p.post.posted_at)));
    tr.append(first, el("td", null, "@" + p.post.author),
      el("td", null, p.side === 1 ? "long" : p.side === -1 ? "short" : "–"),
      el("td", null, p.entry ? fmtPrice(p.entry.price) : "no entry"),
      el("td", null, p.change_since_post == null ? "unresolved" : fmtPct(p.change_since_post)),
      el("td", null, p.moves["7"] == null ? "unresolved" : fmtPct(p.moves["7"])),
      el("td", null, p.status));
    tr.addEventListener("click", () => select(p));
    tr.addEventListener("keydown", ev => { if (ev.key === "Enter") select(p); });
    tb.append(tr);
  }
}

function setAsset(name) {
  state.asset = state.bundle.assets.find(a => a.name === name);
  state.selected = null;
  document.getElementById("card").replaceChildren(el("p", { class: "empty" }, "Select a post to see its card."));
  const a = state.asset, last = a.series[a.series.length - 1][0];
  document.getElementById("summary").textContent =
    `${a.posts.length} post${a.posts.length === 1 ? "" : "s"} · ${a.source}:${a.symbol} hourly open · last bar ${fmtTime(last)}` +
    (state.bundle.prices_as_of ? ` · prices as of ${fmtTime(state.bundle.prices_as_of)}` : "");
  document.getElementById("summary").setAttribute("data-prices-as-of", state.bundle.prices_as_of || "");
  render(); table();
}

fetch("data/charts.json").then(r => { if (!r.ok) throw new Error("charts.json HTTP " + r.status); return r.json(); }).then(b => {
  state.bundle = b;
  const sel = document.getElementById("asset");
  for (const a of b.assets) sel.append(el("option", { value: a.name }, `${a.name} (${a.posts.length})`));
  sel.addEventListener("change", () => setAsset(sel.value));
  const notes = document.getElementById("notes");
  notes.append(el("li", null, `${b.records_scanned} records scanned, ${b.posts_drawn} posts drawn, ${b.superseded.length} superseded, ${b.refused.length} refused (${b.schema}).`));
  for (const s of b.superseded) notes.append(el("li", null, `Superseded: ${s.file} by ${s.by} (same post and asset, later last bar wins).`));
  for (const r of b.refused) notes.append(el("li", null, `Refused, not drawn: ${r.file}: ${r.reasons.join("; ")}`));
  notes.append(el("li", null, "Prices are hourly bar opens (Binance / Yahoo), not fills. Moves are price changes from the entry bar; “for the call” applies the post's side."));
  const want = new URLSearchParams(location.search).get("asset");
  setAsset(b.assets.some(a => a.name === want) ? want : b.assets[0].name);
  sel.value = state.asset.name;
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(render, 120); });
  document.body.setAttribute("data-ready", "1");
}).catch(err => {
  document.getElementById("card").replaceChildren(el("p", null, "Could not load the chart data: " + err.message));
  document.body.setAttribute("data-ready", "error");
});
