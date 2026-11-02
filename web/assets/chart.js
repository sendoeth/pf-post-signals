"use strict";
const SVGNS = "http://www.w3.org/2000/svg";
const HORIZONS = ["1", "7", "30"];
const state = { bundle: null, asset: null, selected: null, avatars: {}, showEpisodes: true };
let clipSeq = 0;
const authorColor = PFPS.authorColor;

// Formatting (mirrored independently in tests/browser_test.js).
function fmtPct(x) {
  const sign = x > 0 ? "+" : x < 0 ? "-" : "";
  return sign + (Math.abs(x) * 100).toFixed(2) + "%";
}
function signClass(x) { return x == null ? "unresolved" : x > 0 ? "gain" : x < 0 ? "loss" : ""; }
function fmtPrice(p) { return p.toLocaleString("en-US", { maximumFractionDigits: 8 }); }
function fmtTime(iso) { return iso.slice(0, 10) + " " + iso.slice(11, 16) + " UTC"; }
function direction(post) {
  // closed: the move to the exit (the result); open: the move since the post
  const c = post.closed ? post.closed.move : post.change_since_post;
  return c == null ? "none" : c > 0 ? "up" : c < 0 ? "down" : "flat";
}
function missing(t0, t1, source) {
  const a = Date.parse(t0), b = Date.parse(t1);
  if (["binance", "okx", "bybit", "gate"].includes(source)) return b - a > 2 * 3600e3;   // 24/7 crypto spot venues
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
  if (!a.series.length) {   // every post on this asset is waiting for its first bar (market closed): nothing to draw yet
    root.append(svg("text", { class: "tick", x: W / 2, y: H / 2, "text-anchor": "middle", "data-empty": "1" }, "No prices after these posts yet: the entry fills in on the next daily refresh."));
    return;
  }
  const series = a.series, t0 = Date.parse(series[0][0]);
  const eps = state.showEpisodes ? (a.episodes || []).filter(it => it.t.price.at_episode) : [];
  const t1 = Math.max(Date.parse(series[series.length - 1][0]), ...eps.map(it => Date.parse(it.t.price.at_episode.at)));
  const drawn = a.posts.filter(p => p.entry);
  const STACK = 36, HIT = 16, R = 12; // STACK > 2 * HIT: stacked hit areas never overlap; R = avatar radius
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
  // ticks: every 1 / 2 / 7 / 14 days, or the 1st of every month (every 2nd month past ~14 months)
  // when the range is long, with a label width check so labels never run into each other
  const days = (t1 - t0) / 864e5, every = days > 40 ? 14 : days > 14 ? 7 : days > 5 ? 2 : 1;
  const monthly = days > 150, monthStep = days > 420 ? 2 : 1;
  const first = new Date(t0); first.setUTCHours(0, 0, 0, 0);
  let lastPx = -Infinity;
  for (let d = new Date(first), i = 0; d.getTime() <= t1; d.setUTCDate(d.getUTCDate() + 1), i++) {
    if (d.getTime() < t0) continue;
    if (monthly ? d.getUTCDate() !== 1 || d.getUTCMonth() % monthStep : i % every) continue;
    if (x(d.toISOString()) - lastPx < 44) continue;
    lastPx = x(d.toISOString());
    const iso = d.toISOString(), px = x(iso);
    if (px > W - m.r - 20) continue;
    root.append(svg("text", { class: "tick", x: px, y: H - m.b + 18, "text-anchor": "middle" },
      monthly ? d.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" }) + (d.getUTCMonth() === 0 ? " " + d.getUTCFullYear() : "")
              : d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })));
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

  // Placement: each bubble starts at its entry point; one that would overlap a bubble already placed
  // moves up past it, then (no room above) down, then one hit width left / right at a time, always
  // inside the plot, on a stem from its entry point. So every post keeps its own click area, also
  // when a long history squeezes many posts into a few pixels.
  const placed = [];
  const clash = (cx, cy) => placed.find(q => Math.abs(q.x - cx) < 2 * HIT && Math.abs(q.y - cy) < 2 * HIT);
  const top = m.t + R, bottom = H - m.b - R, left = m.l + R, right = W - m.r - R;
  function spot(px, py) {
    for (let dx = 0; dx < 40; dx++) {
      for (const sx of dx ? [1, -1] : [1]) {
        const cx = px + sx * dx * 2 * HIT;
        if (cx < left || cx > right) continue;
        let cy = Math.min(Math.max(py, top), bottom), q, g = 0;
        while ((q = clash(cx, cy)) && g++ < 40) cy = q.y - STACK;
        if (!clash(cx, cy) && cy >= top) return [cx, cy];
        cy = Math.min(Math.max(py, top), bottom); g = 0;
        while ((q = clash(cx, cy)) && g++ < 40) cy = q.y + STACK;
        if (!clash(cx, cy) && cy <= bottom) return [cx, cy];
      }
    }
    return [px, py];
  }
  for (const c of clusters) {
    c.forEach((p, k) => {
      const px = x(p.entry.at), py = y(p.entry.price);
      const [bxx, cy] = spot(px, py);
      placed.push({ x: bxx, y: cy });
      const dir = direction(p);
      const node = svg("g", { class: "bubble", tabindex: "0", role: "button", "data-post-id": p.post.id, "data-asset": a.name,
        "aria-label": `${p.post.author} ${fmtTime(p.post.posted_at)}, ${p.change_since_post == null ? "no move" : fmtPct(p.change_since_post)} since post` });
      if (cy !== py || bxx !== px) node.append(svg("line", { class: "stem", x1: px, x2: bxx, y1: py, y2: cy, "data-entry-x": px, "data-entry-y": py }));
      node.append(svg("circle", { class: "hit", cx: bxx, cy, r: HIT, "data-entry-x": px, "data-entry-y": py }));
      const side = p.side === 1 ? "long" : p.side === -1 ? "short" : "none";
      const handle = p.post.author.toLowerCase(), meta = state.avatars[handle];
      const okAvatar = meta && typeof meta.file === "string" && /^[a-z0-9_]{1,15}\.jpg$/.test(meta.file) && meta.file === handle + ".jpg";
      if (okAvatar) {
        const id = "clip-" + (++clipSeq);
        const cp = svg("clipPath", { id });
        cp.append(svg("circle", { cx: bxx, cy, r: R }));
        node.append(cp, svg("image", { class: "face", href: "avatars/" + meta.file, x: bxx - R, y: cy - R, width: 2 * R, height: 2 * R, "clip-path": `url(#${id})`, "data-avatar": "image" }));
      } else {
        node.append(svg("circle", { class: "face initial", cx: bxx, cy, r: R, fill: authorColor(p.post.author), "data-avatar": "initials" }));
        node.append(svg("text", { class: "initial-text", x: bxx, y: cy + 4, "text-anchor": "middle" }, p.post.author.replace(/[^A-Za-z0-9]/g, "").slice(0, 1).toUpperCase()));
      }
      node.append(svg("circle", { class: "mark ring " + side, cx: bxx, cy, r: R, "data-side": side }));
      const bx = bxx + R * 0.78, by = cy + R * 0.78;
      node.append(svg("circle", { class: "badge " + dir, cx: bx, cy: by, r: 6, "data-dir": dir }));
      node.append(svg("text", { class: "badge-text", x: bx, y: by + 2.6, "text-anchor": "middle" }, dir === "up" ? "▲" : dir === "down" ? "▼" : "•"));
      node.addEventListener("click", () => select(p));
      node.addEventListener("dblclick", () => { location.href = positionUrl(p); });
      node.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(p); } });
      if (state.selected === p) node.classList.add("selected");
      root.append(node);
    });
  }
  // Episode theses (podcasts / videos): solid = a call, dashed ring = a thought; the arrow is the lean.
  // Placed with the same spot() so they never cover a post; never rated.
  for (const it of eps) {
    const t = it.t, at = t.price.at_episode, px = x(at.at), py = y(at.price);
    const [cx, cy] = spot(px, py);
    placed.push({ x: cx, y: cy });
    const node = svg("g", { class: `ep-bubble ${t.kind} ${t.direction}`, tabindex: "0", role: "button", "data-episode": it.ep.slug, "data-asset": t.asset,
      "aria-label": `${it.ep.show} ${it.ep.recorded_on}: ${t.kind} ${EP_WORD[t.direction]} on ${t.label}` });
    if (cy !== py || cx !== px) node.append(svg("line", { class: "stem", x1: px, x2: cx, y1: py, y2: cy }));
    node.append(svg("circle", { class: "hit", cx, cy, r: HIT }));
    node.append(svg("circle", { class: "ep-ring", cx, cy, r: R }));
    const d = t.direction === "bullish" ? `M${cx} ${cy + 6}V${cy - 6}M${cx - 5} ${cy - 1}L${cx} ${cy - 6}L${cx + 5} ${cy - 1}`
      : t.direction === "bearish" ? `M${cx} ${cy - 6}V${cy + 6}M${cx - 5} ${cy + 1}L${cx} ${cy + 6}L${cx + 5} ${cy + 1}` : `M${cx - 6} ${cy}H${cx + 6}`;
    node.append(svg("path", { class: "ep-arrow", d }));
    node.addEventListener("click", () => selectEpisode(it));
    node.addEventListener("dblclick", () => { location.href = episodeUrl(it); });
    node.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectEpisode(it); } });
    if (state.selected === it) node.classList.add("selected");
    root.append(node);
  }
}

// ---- episodes (data/episodes.json, optional: the chart works the same without it) ----
const EP_WORD = { bullish: "bullish", bearish: "bearish", neutral: "wait / stand aside" };
const EP_CHART_ASSET = { GOLD: "GOLD", SILVER: "SILVER", COPPER: "COPPER", BTC: "BTC", ETH: "ETH", STOCKS: "STOCKS", OIL: "OIL" };
function episodeUrl(it) { return `episode-${it.ep.slug}.html#t-${it.t.asset.toLowerCase()}`; }
function validThesis(ep, t) {
  return ep && typeof ep.slug === "string" && /^[a-z0-9-]{1,80}$/.test(ep.slug) && t && typeof t.asset === "string" && /^[A-Z0-9_]{1,16}$/.test(t.asset)
    && ["call", "thought"].includes(t.kind) && ["bullish", "bearish", "neutral"].includes(t.direction)
    && t.price && Array.isArray(t.series) && t.series.every(b => Array.isArray(b) && typeof b[0] === "string" && typeof b[1] === "number" && isFinite(b[1]))
    && (!t.price.at_episode || (typeof t.price.at_episode.at === "string" && typeof t.price.at_episode.price === "number"));
}
function attachEpisodes(bundle, eb) {
  const list = eb && Array.isArray(eb.episodes) ? eb.episodes : [];
  for (const ep of list) for (const t of ep.theses || []) {
    if (!validThesis(ep, t)) continue;
    const name = EP_CHART_ASSET[t.asset] || t.asset;
    let a = bundle.assets.find(x => x.name === name);
    if (!a) {   // an asset only an episode talks about (oil, the dollar, the AI trade): drawn from the episode's own prices
      a = { name, label: t.label, source: t.price.source, symbol: t.price.symbol, series: [], posts: [], episodeOnly: true };
      bundle.assets.push(a);
    }
    if (a.episodeOnly) {
      const bars = new Map(a.series.map(b => [b[0], b[1]]));
      for (const b of t.series) if (!bars.has(b[0])) bars.set(b[0], b[1]);
      a.series = [...bars.entries()].sort((p, q) => (p[0] < q[0] ? -1 : 1));
    }
    (a.episodes = a.episodes || []).push({ ep, t });
  }
}
function selectEpisode(it) {
  state.selected = it;
  const c = document.getElementById("card"), t = it.t, ep = it.ep, pr = t.price;
  c.replaceChildren();
  c.removeAttribute("data-post-id");
  c.setAttribute("data-episode", ep.slug);
  c.setAttribute("data-asset", t.asset);
  c.append(el("h2", null, ep.show));
  c.append(el("p", { class: "meta" }, `${ep.title} · recorded ${ep.recorded_on}`));
  c.append(el("p", { class: "ep-lean " + t.direction, "data-field": "lean" },
    `${t.kind === "call" ? "Call" : "Thought"}: ${EP_WORD[t.direction]}${t.later ? " · later " + EP_WORD[t.later] : ""}`));
  if (t.text) c.append(el("blockquote", { "data-field": "text" }, t.text));
  const dl = el("dl");
  field(dl, "asset", "Asset", `${t.label} (${pr.source}:${pr.symbol})`);
  field(dl, "entry", "Price at the episode", pr.at_episode ? `${fmtPrice(pr.at_episode.price)} @ ${fmtTime(pr.at_episode.at)}` : "no bar", pr.at_episode);
  field(dl, "latest", "Latest", pr.latest ? `${fmtPrice(pr.latest.price)} @ ${fmtTime(pr.latest.at)}` : "no bar yet", pr.latest);
  field(dl, "change", "Since the episode", pr.change == null ? "no trading since the episode yet" : fmtPct(pr.change), pr.change, signClass(pr.change));
  if (pr.with_lean != null) field(dl, "with_lean", "For the lean", fmtPct(pr.with_lean), pr.with_lean, signClass(pr.with_lean));
  c.append(dl);
  const ol = el("ol", { class: "ep-moments", "data-field": "moments" });
  for (const m of t.moments || []) {
    const li = el("li");
    li.append(el("strong", null, `${m.t} · ${m.kind === "call" ? "call" : "thought"}, ${EP_WORD[m.direction] || m.direction}`),
      document.createTextNode(` · ${m.speaker}: “${String(m.quote).slice(0, 220)}”`));
    ol.append(li);
  }
  c.append(el("p", { class: "meta" }, `${(t.moments || []).length} moments in the episode`), ol);
  c.append(el("a", { class: "open-position", href: episodeUrl(it), "data-field": "episode_url" }, "Open the episode page →"));
  c.append(el("p", { class: "notes" }, "Episode stances are the speakers' views, not tracked positions: they are never rated."));
  for (const n of document.querySelectorAll(".bubble, .ep-bubble")) n.classList.toggle("selected", n.getAttribute("data-episode") === ep.slug && n.getAttribute("data-asset") === t.asset);
  for (const r of document.querySelectorAll("#posts tbody tr")) r.classList.toggle("selected", r.getAttribute("data-episode") === ep.slug);
  if (window.matchMedia("(max-width: 860px)").matches) c.scrollIntoView({ block: "nearest" });
}

function positionUrl(p) { return PFPS.positionUrl(p.post.id, p.asset.name); }
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
  const rt = state.bundle.ratings && state.bundle.ratings.callers[p.post.author];
  const sc = el("p", { class: "meta" });
  const scoreLink = el("a", { href: PFPS.callerUrl(p.post.author), "data-field": "caller_score", "data-raw": JSON.stringify(rt ? rt.score : null) },
    rt ? `Caller score ${rt.display} / 100${rt.label ? " · " + rt.label : ""}` : "Caller score –");
  sc.append(scoreLink);
  c.append(sc);
  c.append(el("p", { class: "meta", "data-field": "posted_at", "data-raw": JSON.stringify(p.post.posted_at) }, "Posted " + fmtTime(p.post.posted_at)));
  if (p.post.text) c.append(el("blockquote", { "data-field": "text" }, p.post.text));
  else c.append(el("p", { class: "empty", "data-field": "text" }, "Post text not saved: open it on X."));
  const dl = el("dl");
  field(dl, "asset", "Asset", `${p.asset.name} (${p.asset.source}:${p.asset.symbol})`);
  field(dl, "side", "Side", p.side === 1 ? "long" : p.side === -1 ? "short" : "not given", p.side ?? null);
  field(dl, "status", "Status", PFPS.statusLabel(p), p.status);
  dl.lastChild.setAttribute("title", PFPS.statusTip(p));
  field(dl, "entry", "Price at the post", p.entry ? `${fmtPrice(p.entry.price)} @ ${fmtTime(p.entry.at)}` : "no entry bar", p.entry);
  field(dl, "latest", "Latest", p.latest ? `${fmtPrice(p.latest.price)} @ ${fmtTime(p.latest.at)}` : "no bar yet", p.latest);
  const dir = direction(p);
  if (p.closed) {
    const res = PFPS.result(p);
    field(dl, "closed", "Closed (realized)", `${fmtPct(res)} · exit ${fmtPrice(p.closed.exit.price)} @ ${fmtTime(p.closed.exit.at)}`, p.closed);
    dl.lastChild.className = res > 0 ? "dir-up" : res < 0 ? "dir-down" : "";
    const ev = PFPS.closeEvent(p);
    dl.append(el("dt", null, "Closing post"));
    const cp = el("dd", { "data-field": "closing_post", "data-raw": JSON.stringify(ev ? ev.post.id : p.closed.post_id) });
    if (p.closed.by === "ledger") cp.append("exit event in Corbanu's published ledger");
    else {
      cp.append(el("a", { href: p.closed.post_url, target: "_blank", rel: "noopener noreferrer" }, ev ? fmtTime(ev.post.posted_at) : "the closing post"));
      if (ev && ev.post.text) cp.append(` · “${ev.post.text.replace(/\s+/g, " ").trim().slice(0, 140)}”`);
    }
    dl.append(cp);
  }
  field(dl, "change_since_post", p.closed ? "If still held (since post)" : "Since post", p.change_since_post == null ? "unresolved" : fmtPct(p.change_since_post),
    p.change_since_post, signClass(p.change_since_post));
  for (const h of HORIZONS) {
    const v = p.moves[h];
    field(dl, "move_" + h, h + "d move", v == null ? "unresolved · " + p.unresolved[h] : fmtPct(v), v, signClass(v));
  }
  if (p.signed_returns) for (const h of HORIZONS) {
    const v = p.signed_returns[h];
    field(dl, "signed_" + h, h + "d for the call", v == null ? "unresolved · " + p.unresolved[h] : fmtPct(v), v, signClass(v));
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
  document.getElementById("card").removeAttribute("data-episode");
  for (const n of document.querySelectorAll(".bubble, .ep-bubble")) n.classList.toggle("selected", n.getAttribute("data-post-id") === p.post.id);
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
      el("td", { class: signClass(p.change_since_post) }, p.change_since_post == null ? "unresolved" : fmtPct(p.change_since_post)),
      el("td", { class: signClass(p.moves["7"]) }, p.moves["7"] == null ? "unresolved" : fmtPct(p.moves["7"])),
      el("td", { title: PFPS.statusTip(p) }, PFPS.statusLabel(p)));
    tr.addEventListener("click", () => select(p));
    tr.addEventListener("keydown", ev => { if (ev.key === "Enter") select(p); });
    tb.append(tr);
  }
  if (!state.showEpisodes) return;
  for (const it of state.asset.episodes || []) {
    const t = it.t, pr = t.price;
    const tr = el("tr", { "data-episode": it.ep.slug, tabindex: "0", class: "ep-row" });
    const first = el("td");
    first.append(el("a", { href: episodeUrl(it), class: "row-link" }, it.ep.recorded_on));
    tr.append(first, el("td", null, it.ep.show),
      el("td", null, EP_WORD[t.direction]),
      el("td", null, pr.at_episode ? fmtPrice(pr.at_episode.price) : "no bar"),
      el("td", { class: signClass(pr.change) }, pr.change == null ? "no bar since" : fmtPct(pr.change)),
      el("td", null, "–"),
      el("td", null, "episode " + t.kind));
    tr.addEventListener("click", () => selectEpisode(it));
    tr.addEventListener("keydown", ev => { if (ev.key === "Enter") selectEpisode(it); });
    tb.append(tr);
  }
}

function setAsset(name) {
  state.asset = state.bundle.assets.find(a => a.name === name);
  state.selected = null;
  document.getElementById("card").replaceChildren(el("p", { class: "empty" }, "Select a post to see its card."));
  const a = state.asset, last = a.series.length ? a.series[a.series.length - 1][0] : null;
  document.getElementById("summary").textContent =
    `${a.posts.length} post${a.posts.length === 1 ? "" : "s"}` + (a.episodes ? ` · ${a.episodes.length} episode thes${a.episodes.length === 1 ? "is" : "es"}` : "") +
    ` · ${a.source}:${a.symbol} hourly open · ${last ? "last bar " + fmtTime(last) : "no bar after the posts yet"}` +
    (state.bundle.prices_as_of ? ` · prices as of ${fmtTime(state.bundle.prices_as_of)}` : "");
  document.getElementById("summary").setAttribute("data-prices-as-of", state.bundle.prices_as_of || "");
  render(); table();
}

Promise.all([
  fetch("data/charts.json").then(r => { if (!r.ok) throw new Error("charts.json HTTP " + r.status); return r.json(); }),
  fetch("avatars/index.json").then(r => (r.ok ? r.json() : {})).catch(() => ({})),
  fetch("data/episodes.json").then(r => (r.ok ? r.json() : null)).catch(() => null),
]).then(([b, avatars, eb]) => {
  state.bundle = b;
  state.avatars = avatars;
  attachEpisodes(b, eb);
  const sel = document.getElementById("asset");
  for (const a of b.assets) sel.append(el("option", { value: a.name },
    a.episodeOnly ? `${a.label || a.name} (episode)` : `${a.name} (${a.posts.length}${a.episodes ? " + " + a.episodes.length + " ep" : ""})`));
  const tog = document.getElementById("show-ep");
  if (tog) {
    tog.closest("label").hidden = !b.assets.some(a => a.episodes);
    tog.addEventListener("change", () => { state.showEpisodes = tog.checked; if (state.selected && state.selected.ep) setAsset(state.asset.name); else { render(); table(); } });
  }
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
