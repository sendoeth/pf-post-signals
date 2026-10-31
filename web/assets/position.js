"use strict";
const HORIZONS = ["1", "7", "30"];
const INTERVALS = { "1h": 3600, "4h": 14400, "1D": 86400 };

// Formatting: same rules as index.html (mirrored in tests/position_test.js).
const fmtPct = x => (x > 0 ? "+" : x < 0 ? "-" : "") + (Math.abs(x) * 100).toFixed(2) + "%";
const fmtPrice = p => p.toLocaleString("en-US", { maximumFractionDigits: 8 });
const fmtTime = iso => iso.slice(0, 10) + " " + iso.slice(11, 16) + " UTC";
const sec = iso => Math.floor(Date.parse(iso) / 1000);
function age(fromIso, nowMs) {
  const m = Math.max(0, Math.floor((nowMs - Date.parse(fromIso)) / 60000));
  const d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m % 60}m` : `${m}m`;
}
const signClass = x => x == null ? "unresolved" : x > 0 ? "gain" : x < 0 ? "loss" : "";
function el(tag, attrs, text) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (text != null) n.textContent = text;
  return n;
}
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function initials(h) { return h.replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "?"; }
const AVATAR_FILE = /^[a-z0-9_]{1,15}\.jpg$/;   // only <handle>.jpg from our own avatars/ folder
function avatarNode(handle, avatars, cls) {
  const raw = avatars[handle.toLowerCase()];
  const meta = raw && typeof raw.file === "string" && AVATAR_FILE.test(raw.file) && raw.file === handle.toLowerCase() + ".jpg" ? raw : null;
  const box = el("span", { class: cls, "data-avatar": meta ? "image" : "initials" });
  if (meta) {
    const img = el("img", { src: "avatars/" + meta.file, alt: "" });
    img.addEventListener("error", () => { box.replaceChildren(initials(handle)); box.setAttribute("data-avatar", "initials"); });
    box.append(img);
  } else box.textContent = initials(handle);
  if (box.getAttribute("data-avatar") === "initials") { box.style.backgroundColor = PFPS.authorColor(handle); box.style.color = "#fff"; }
  return box;
}
function field(dl, name, label, text, raw, cls) {
  dl.append(el("dt", null, label));
  const dd = el("dd", { "data-field": name }, text);
  if (raw !== undefined) dd.setAttribute("data-raw", JSON.stringify(raw));
  if (cls) dd.className = cls;
  dl.append(dd);
}
// Display-only aggregation of 1h candles into UTC-aligned buckets.
function aggregate(candles, step) {
  if (step === 3600) return candles.map(c => ({ time: sec(c[0]), open: c[1], high: c[2], low: c[3], close: c[4] }));
  const out = [];
  for (const c of candles) {
    const t = Math.floor(sec(c[0]) / step) * step, last = out[out.length - 1];
    if (last && last.time === t) { last.high = Math.max(last.high, c[2]); last.low = Math.min(last.low, c[3]); last.close = c[4]; }
    else out.push({ time: t, open: c[1], high: c[2], low: c[3], close: c[4] });
  }
  return out;
}
// the candle a bar falls in: itself at 1h (Yahoo stock bars start at :30), else its UTC bucket
const bucket = (iso, step) => step === 3600 ? sec(iso) : Math.floor(sec(iso) / step) * step;

// the caller's 0-100 score (bundle.ratings, rate.py), linking to their caller page
function scoreChip(author, ratings, fieldName) {
  const rt = ratings && ratings.callers[author];
  const a = el("a", { class: "score-chip", href: PFPS.callerUrl(author), "data-field": fieldName || "caller_score" });
  if (!rt) { a.textContent = "score –"; a.setAttribute("data-raw", "null"); return a; }
  a.setAttribute("data-raw", JSON.stringify(rt.score));
  a.setAttribute("title", `Quanty Quants score: rank ${rt.rank} of ${ratings.order.length}, ${rt.scored} scored calls. Open the breakdown.`);
  a.append("score ", el("strong", null, rt.display));
  if (rt.label) a.append(` · ${rt.label}`);
  return a;
}

// ?callers= : absent = every caller, "none" = only the opened call, else a comma list of handles
function parseCallers(v, authors) {
  const all = authors.map(a => a.toLowerCase());
  if (v == null || v === "all") return new Set(all);
  if (v === "none") return new Set();
  return new Set(v.toLowerCase().split(",").filter(h => all.includes(h)));
}
function callersParam(shown, authors) {
  const all = authors.map(a => a.toLowerCase());
  if (all.every(a => shown.has(a))) return null;
  if (!shown.size) return "none";
  return all.filter(a => shown.has(a)).join(",");
}

function fail(msg) {
  document.getElementById("app").replaceChildren(el("div", { class: "panel error", "data-error": "1" }, msg));
  document.body.setAttribute("data-ready", "error");
}

async function main() {
  // position.html?post=..&asset=.. or a prerendered pos-<slug>.html (<main data-post data-asset>)
  const q = new URLSearchParams(location.search), main = document.querySelector("main");
  const id = q.get("post") || main.dataset.post, assetName = q.get("asset") || main.dataset.asset;
  if (!id) return fail("No post given. Open a post from the main chart.");
  const getJson = u => fetch(u).then(r => { if (!r.ok) throw new Error(u + " HTTP " + r.status); return r.json(); });
  const [bundle, avatars] = await Promise.all([getJson("data/charts.json"), getJson("avatars/index.json").catch(() => ({}))]);
  const matches = bundle.assets.flatMap(a => a.posts.filter(p => p.post.id === id && (!assetName || a.name === assetName)).map(p => [a, p]));
  if (!matches.length) return fail(`Post ${id}${assetName ? " on " + assetName : ""} is not in the data.`);
  const [asset, p] = matches[0];
  const ohlc = await getJson(`data/ohlc/${encodeURIComponent(asset.name)}.json`);
  document.title = `${p.asset.name} · @${p.post.author} · Quanty Quants`;
  render(asset, p, ohlc, avatars, bundle);
}

function render(asset, p, ohlc, avatars, bundle) {
  const app = document.getElementById("app");
  app.replaceChildren();
  app.setAttribute("data-post-id", p.post.id);
  app.setAttribute("data-asset", p.asset.name);
  const nowMs = Date.now();
  const sideName = p.side === 1 ? "long" : p.side === -1 ? "short" : null;
  const dir = p.change_since_post == null ? "none" : p.change_since_post > 0 ? "up" : p.change_since_post < 0 ? "down" : "flat";

  // the post
  const post = el("section", { class: "panel post" });
  const who = el("div", { class: "who" });
  who.append(avatarNode(p.post.author, avatars, "avatar"));
  const name = el("div");
  name.append(el("strong", { "data-field": "author" }, "@" + p.post.author));
  name.append(scoreChip(p.post.author, bundle.ratings));
  const meta = el("span", { class: "meta" });
  meta.append(el("span", { "data-field": "posted_at", "data-raw": JSON.stringify(p.post.posted_at) }, fmtTime(p.post.posted_at)), " · ");
  meta.append(el("a", { href: p.post.url, target: "_blank", rel: "noopener noreferrer", "data-field": "url" },
    p.post.source === "corbanu" ? "read the article" : "open on X"));
  name.append(meta);
  who.append(name);
  post.append(who);
  post.append(p.post.text ? el("p", { class: "text", "data-field": "text" }, p.post.text)
                          : el("p", { class: "text notes", "data-field": "text" }, "Post text not saved: open it on X."));
  app.append(post);

  // position header + chart
  const pos = el("section", { class: "panel pos" });
  const head = el("div", { class: "head" });
  const left = el("div");
  left.append(el("span", { class: "ticker" }, p.asset.name));
  left.append(el("span", { class: "badge " + (sideName || "none"), "data-field": "side_badge" }, sideName ? sideName.toUpperCase() : "NO SIDE"));
  if (p.entry) left.append(el("span", { class: "at" }, "@ " + fmtPrice(p.entry.price)));
  head.append(left);
  const right = el("div", { class: "now" });
  if (p.closed) {
    // closed: the headline is the frozen result; the current price only appears as "if still held"
    const res = PFPS.result(p), held = PFPS.ifHeld(p);
    right.append(el("span", { class: "closed-badge", "data-field": "closed_badge" }, "CLOSED"), " ");
    right.append(el("span", null, fmtPrice(p.closed.exit.price)));
    right.append(el("span", { class: "chip " + (res > 0 ? "up" : res < 0 ? "down" : ""), "data-field": "header_result" }, fmtPct(res)));
    const since = el("span", { class: "since", "data-field": "header_since" },
      `closed ${fmtTime(p.closed.exit.at).slice(0, 10)} · ${sideName ? "for the " + sideName : "price move"} · if still held `);
    since.append(el("span", { class: signClass(held) }, held == null ? "–" : fmtPct(held)));
    right.append(since);
  } else {
    right.append(el("span", null, p.latest ? fmtPrice(p.latest.price) : "–"));
    if (p.change_since_post != null) right.append(el("span", { class: "chip " + (dir === "up" ? "up" : dir === "down" ? "down" : "") }, fmtPct(p.change_since_post)));
    const forCall = sideName && p.change_since_post != null ? p.side * p.change_since_post : null;
    const since = el("span", { class: "since", "data-field": "header_since" }, "since post · " + age(p.post.posted_at, nowMs));
    if (forCall != null) { since.append(" · "); since.append(el("span", { class: signClass(forCall) }, `${fmtPct(forCall)} for the ${sideName}`)); }
    right.append(since);
  }
  head.append(right);
  pos.append(head);

  const span = (sec(ohlc.candles[ohlc.candles.length - 1][0]) - (p.entry ? sec(p.entry.at) : sec(ohlc.candles[0][0]))) / 86400;
  const want = new URLSearchParams(location.search).get("interval");
  let interval = INTERVALS[want] ? want : span <= 7 ? "1h" : span <= 30 ? "4h" : "1D";
  const bar = el("div", { class: "toolbar", role: "group", "aria-label": "Candle interval" });
  for (const k of Object.keys(INTERVALS)) {
    const b = el("button", { type: "button", "data-interval": k, "aria-pressed": String(k === interval) }, k);
    b.addEventListener("click", () => { interval = k; for (const x of bar.querySelectorAll("[data-interval]")) x.setAttribute("aria-pressed", String(x === b)); draw(); });
    bar.append(b);
  }
  const fullBtn = el("button", { type: "button", "data-range": "all", title: "Show the whole fetched history, including the lookback before the first call" }, "Full history");
  fullBtn.addEventListener("click", () => showRange(sec(ohlc.candles[0][0]), sec(ohlc.candles[ohlc.candles.length - 1][0])));
  bar.append(fullBtn);
  pos.append(bar);

  // step 14: every tracked caller's calls on this asset, one toggle per caller (state in the url)
  const others = asset.posts.filter(o => o !== p && o.entry);
  const authors = [...new Set(asset.posts.map(o => o.post.author))].sort((x, y) => x.toLowerCase() < y.toLowerCase() ? -1 : 1);
  const shown = parseCallers(new URLSearchParams(location.search).get("callers"), authors);
  const callersBar = el("div", { class: "callers", role: "group", "aria-label": "Callers on this chart", "data-field": "callers" });
  const allBtn = el("button", { type: "button", "data-callers": "all" }, "All callers");
  const noneBtn = el("button", { type: "button", "data-callers": "none" }, "None");
  callersBar.append(allBtn, noneBtn);
  const callerBtns = authors.map(a => {
    const b = el("button", { type: "button", "data-caller": a.toLowerCase(), "aria-pressed": "false" });
    b.append(avatarNode(a, avatars, "mini"), "@" + a);
    const n = asset.posts.filter(o => o.post.author === a).length;
    b.append(el("span", { class: "count" }, String(n)));
    b.addEventListener("click", () => { shown.has(a.toLowerCase()) ? shown.delete(a.toLowerCase()) : shown.add(a.toLowerCase()); syncCallers(); });
    return b;
  });
  callersBar.append(...callerBtns);
  allBtn.addEventListener("click", () => { for (const a of authors) shown.add(a.toLowerCase()); syncCallers(); });
  noneBtn.addEventListener("click", () => { shown.clear(); syncCallers(); });
  pos.append(callersBar);
  const box = el("div", { id: "chart-box" });
  const chartEl = el("div", { id: "chart" }), overlay = el("div", { id: "overlay" });
  box.append(chartEl, overlay);
  pos.append(box);
  const readout = el("p", { class: "readout", id: "readout", "aria-live": "off" }, "Hover the chart for a candle's prices.");
  pos.append(readout);
  const card = el("div", { class: "call-card", id: "call-card", hidden: "" });
  pos.append(card);
  pos.append(el("p", { class: "as-of", "data-field": "prices_as_of", "data-raw": JSON.stringify(bundle.prices_as_of || null) },
    bundle.prices_as_of ? "Prices as of " + fmtTime(bundle.prices_as_of) + " (daily refresh)" : "Prices not refreshed yet"));
  const lb = ohlc.lookback;
  pos.append(el("p", { class: "attribution", "data-field": "history", "data-raw": JSON.stringify({ daily_until: ohlc.daily_until || null, lookback: lb || null }) },
    "Candles: " + (ohlc.daily_until ? "daily bars before " + fmtTime(ohlc.daily_until) + ", hourly after" : "hourly") +
    " opens/highs/lows/closes from " + ohlc.source + ":" + ohlc.symbol + " fetched " + fmtTime(ohlc.fetched_at) + ". " +
    (lb ? `History from ${fmtTime(ohlc.candles[0][0])}: ${lb.days} days before the first call on ${asset.name} (${fmtTime(lb.first_call)})` +
      (lb.starts_at_listing ? ", or the market's first bar if it listed later" : "") + ". " : "") +
    "Display only: entries, exits and returns come from the records. Charting by TradingView Lightweight Charts."));
  app.append(pos);

  // recap: every value from the record (best since post from the record's own series)
  const recap = el("section", { class: "panel recap" });
  recap.append(el("h2", null, "Recap"));
  const dl = el("dl");
  field(dl, "asset", "Asset", `${p.asset.name} (${p.asset.source}:${p.asset.symbol})`);
  field(dl, "side", "Side", sideName || "no side stated", p.side ?? null);
  field(dl, "status", "Status", PFPS.statusLabel(p), p.status);
  dl.lastChild.setAttribute("title", PFPS.statusTip(p));
  field(dl, "entry", "Entry", p.entry ? `${fmtPrice(p.entry.price)} @ ${fmtTime(p.entry.at)}` : "no entry bar", p.entry);
  field(dl, "latest", "Latest", p.latest ? `${fmtPrice(p.latest.price)} @ ${fmtTime(p.latest.at)}` : "no bar yet", p.latest);
  field(dl, "change_since_post", p.closed ? "Since post (if still held)" : "Since post", p.change_since_post == null ? "unresolved" : fmtPct(p.change_since_post), p.change_since_post,
    signClass(p.change_since_post));
  const best = p.best;
  field(dl, "best", sideName ? "Best for the call" : "Best (highest) since post",
    best ? `${fmtPct(sideName ? best.for_call : best.move)} at ${fmtPrice(best.price)} @ ${fmtTime(best.at)}` : "no entry bar", best,
    best ? signClass(sideName ? best.for_call : best.move) : "unresolved");
  field(dl, "age", "Called", age(p.post.posted_at, nowMs) + " ago");
  for (const h of HORIZONS) {
    const v = p.moves[h];
    field(dl, "move_" + h, h + "d move", v == null ? "unresolved · " + p.unresolved[h] : fmtPct(v), v, signClass(v));
  }
  if (p.signed_returns) for (const h of HORIZONS) {
    const v = p.signed_returns[h];
    field(dl, "signed_" + h, h + "d for the call", v == null ? "unresolved · " + p.unresolved[h] : fmtPct(v), v, signClass(v));
  }
  if (p.closed) {
    const ev = PFPS.closeEvent(p), res = PFPS.result(p), held = PFPS.ifHeld(p);
    field(dl, "closed", "Closed (realized)", `${fmtPct(res)} ${sideName ? "for the " + sideName : "price move"} · exit ${fmtPrice(p.closed.exit.price)} @ ${fmtTime(p.closed.exit.at)}`
      + (p.closed.exit.interval === "1d" ? " (daily bar)" : ""), p.closed, signClass(res));
    const cp = el("dd", { "data-field": "closing_post" });
    if (p.closed.by === "ledger") cp.append("exit event in Corbanu's published ledger");
    else {
      cp.append(el("a", { href: p.closed.post_url, target: "_blank", rel: "noopener noreferrer" }, ev ? `${fmtTime(ev.post.posted_at)} post` : "the closing post"));
      if (ev && ev.post.text) cp.append(` · “${ev.post.text.replace(/\s+/g, " ").trim().slice(0, 160)}”`);
      if (ev && ev.terms.length) cp.append(` · matched: ${ev.terms.join(", ")}`);
      if (p.closed.stated_time) cp.append(` · the post says "${p.closed.stated_time}"; the exit uses the first bar after the post`);
    }
    dl.append(el("dt", null, "Closing post"), cp);
    field(dl, "if_still_held", "If still held", held == null ? "–" : `${fmtPct(held)} (now ${fmtPrice(p.latest.price)} @ ${fmtTime(p.latest.at)}), not the result`, held, signClass(held));
  }
  if (p.lifecycle && p.lifecycle.events.length) {
    const ol = el("ol", { class: "timeline", "data-field": "lifecycle" });
    for (const ev of p.lifecycle.events) {
      const li = el("li", { "data-type": ev.type, "data-post-id": ev.post.id });
      li.append(el("strong", null, { trim: "trim", close: "close", flip: "flip", review: "review", not_close: "not a close" }[ev.type]), " · ");
      li.append(el("a", { href: ev.post.url, target: "_blank", rel: "noopener noreferrer" }, fmtTime(ev.post.posted_at)));
      if (ev.bar) li.append(` · ${fmtPrice(ev.bar.price)} (${ev.for_call != null ? fmtPct(ev.for_call) + " for the call" : fmtPct(ev.move)})`);
      li.append(el("span", { class: "why" }, ` · ${ev.terms.length ? "“" + ev.terms.join("”, “") + "” · " : ""}${ev.reason}${ev.after_close ? " (after the close)" : ""}`));
      ol.append(li);
    }
    dl.append(el("dt", null, "Lifecycle"), (() => { const dd = el("dd"); dd.append(ol); return dd; })());
  }
  if (p.resolved_with && p.resolved_with.daily_until && p.entry && p.entry.interval === "1d")
    field(dl, "resolution", "Resolution", `daily bars before ${fmtTime(p.resolved_with.daily_until)} (older than the hourly history), hourly after; `
      + "a horizon that lands on the same daily bar as the entry reads 0.00%");
  if (p.asset.stand_in) field(dl, "stand_in", "Priced via", `stand-in for ${p.asset.stand_in.for}. ${p.asset.stand_in.reason}`, p.asset.stand_in);
  if (p.asset.adjustments && p.asset.adjustments.length)
    field(dl, "adjustments", "Adjusted", p.asset.adjustments.map(a => `${a.kind} on ${fmtTime(a.at)} (earlier prices divided by ${a.ratio})`).join("; "), p.asset.adjustments);
  if (p.trade) {
    field(dl, "trade", "Published trade",
      `reference ${fmtPrice(p.trade.reference_price)} · weight ${p.trade.target_weight_pct > 0 ? "+" : ""}${p.trade.target_weight_pct}% · ${p.trade.venue}`, p.trade);
  }
  if (p.asset_choice) field(dl, "asset_choice", "Asset chosen by",
    p.asset_choice.method + (p.asset_choice.reason ? ": " + p.asset_choice.reason : p.asset_choice.terms && p.asset_choice.terms.length ? " (" + p.asset_choice.terms.join(", ") + ")" : ""), p.asset_choice);
  recap.append(dl);
  recap.append(el("p", { class: "notes", "data-field": "record_file" }, `Record ${p.record_file} · sha256 ${p.record_sha256}`));
  app.append(recap);

  // chart
  const chart = LightweightCharts.createChart(chartEl, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: css("--muted"), fontSize: 11, attributionLogo: true },
    grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
    rightPriceScale: { borderColor: css("--axis"), scaleMargins: { top: 0.15, bottom: 0.12 } },
    timeScale: { borderColor: css("--axis"), timeVisible: true, secondsVisible: false, rightOffset: 4, minBarSpacing: 0.2 },
    localization: { priceFormatter: fmtPrice, timeFormatter: t => new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC" },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: { vertTouchDrag: false },
  });
  const series = chart.addCandlestickSeries({
    upColor: css("--up"), downColor: css("--down"), wickUpColor: css("--up"), wickDownColor: css("--down"), borderVisible: false,
    priceFormat: { type: "custom", formatter: fmtPrice, minMove: 1e-8 },
  });
  if (p.latest) series.createPriceLine({ price: p.latest.price, color: css("--muted"), lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: p.closed ? "now (if held)" : "latest" });
  window.__position = { chart, series, post: p, get interval() { return interval; }, step: () => INTERVALS[interval], authors, shown: () => [...shown].sort(), fitCalls: () => fitCalls() };

  const bubble = avatarNode(p.post.author, avatars, "");
  bubble.id = "entry-bubble";
  bubble.setAttribute("title", "@" + p.post.author + " posted here");
  const svgNS = "http://www.w3.org/2000/svg", svg = document.createElementNS(svgNS, "svg");
  const line = document.createElementNS(svgNS, "line"), label = document.createElementNS(svgNS, "text");
  line.setAttribute("class", "best-line"); label.setAttribute("class", "best-label");
  svg.append(line, label);
  const exitMark = el("span", { id: "exit-mark", title: p.closed ? "closed here" : "" }, "✕");
  exitMark.hidden = true;
  overlay.append(svg, bubble, exitMark);
  bubble.classList.add("opened");
  // shown calls outside the visible range: a pill at that edge zooms out to fit every shown call
  const edgeL = el("button", { type: "button", class: "edge left", "data-edge": "left", hidden: "" }), edgeR = el("button", { type: "button", class: "edge right", "data-edge": "right", hidden: "" });
  edgeL.addEventListener("click", () => fitCalls()); edgeR.addEventListener("click", () => fitCalls());
  box.append(edgeL, edgeR);
  const stems = document.createElementNS(svgNS, "g");
  svg.prepend(stems);
  const nodes = others.map(o => {
    const side = o.side === 1 ? "long" : o.side === -1 ? "short" : "none";
    const mv = o.closed ? o.closed.move : o.change_since_post;   // badge = price direction (to the exit if closed), as on the chart view
    const dir = mv == null ? "none" : mv > 0 ? "up" : mv < 0 ? "down" : "flat";
    const n = avatarNode(o.post.author, avatars, "call-bubble " + side);
    n.setAttribute("role", "button"); n.setAttribute("tabindex", "0");
    n.setAttribute("data-post-id", o.post.id); n.setAttribute("data-author", o.post.author.toLowerCase()); n.setAttribute("data-side", side);
    n.setAttribute("title", `@${o.post.author} ${side === "none" ? "" : side + " "}${fmtTime(o.post.posted_at)}${o.closed ? " (closed)" : ""}`);
    n.setAttribute("aria-label", n.getAttribute("title"));
    const badge = el("span", { class: "dir " + dir, "data-dir": dir }, dir === "up" ? "▲" : dir === "down" ? "▼" : "•");
    n.append(badge);
    n.addEventListener("click", () => openCard(o));
    n.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openCard(o); } });
    const x = o.closed ? el("span", { class: "call-exit", "data-post-id": o.post.id, title: `@${o.post.author} closed here` }, "✕") : null;
    const stem = document.createElementNS(svgNS, "line");
    stem.setAttribute("class", "stem");
    stems.append(stem);
    overlay.append(n);
    if (x) overlay.append(x);
    return { o, n, x, stem };
  });

  function openCard(o) {
    card.hidden = false;
    card.replaceChildren();
    card.setAttribute("data-post-id", o.post.id);
    for (const t of nodes) t.n.classList.toggle("selected", t.o === o);
    const side = o.side === 1 ? "long" : o.side === -1 ? "short" : null, r = PFPS.result(o);
    const who = el("div", { class: "who" });
    who.append(avatarNode(o.post.author, avatars, "avatar"));
    const nm = el("div");
    nm.append(el("strong", { "data-field": "card_author" }, "@" + o.post.author));
    nm.append(scoreChip(o.post.author, bundle.ratings, "card_score"));
    nm.append(el("span", { class: "meta", "data-field": "card_posted_at" }, fmtTime(o.post.posted_at)));
    who.append(nm);
    card.append(who);
    if (o.post.text) card.append(el("p", { class: "card-text" }, o.post.text.replace(/\s+/g, " ").trim().slice(0, 220)));
    const d = el("dl");
    field(d, "card_side", "Side", side || "no side stated", o.side ?? null);
    field(d, "card_entry", "Entry", `${fmtPrice(o.entry.price)} @ ${fmtTime(o.entry.at)}`, o.entry);
    field(d, "card_result", o.closed ? "Closed (realized)" : side ? "For the call, since post" : "Since post", r == null ? "unresolved" : fmtPct(r), r, signClass(r));
    field(d, "card_status", "Status", PFPS.statusLabel(o), o.status);
    card.append(d);
    const links = el("p", { class: "card-links" });
    links.append(el("a", { href: PFPS.positionUrl(o.post.id, asset.name), "data-field": "card_position_url" }, "Open position page →"), " · ",
      el("a", { href: o.post.url, target: "_blank", rel: "noopener noreferrer", "data-field": "card_url" }, o.post.source === "corbanu" ? "read the article" : "open on X"));
    const close = el("button", { type: "button", class: "card-close", "aria-label": "Close the card" }, "×");
    close.addEventListener("click", () => { card.hidden = true; for (const t of nodes) t.n.classList.remove("selected"); });
    card.append(links, close);
  }

  function syncCallers() {
    const q = new URLSearchParams(location.search);
    const v = callersParam(shown, authors);
    if (v == null) q.delete("callers"); else q.set("callers", v);
    const qs = q.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
    allBtn.setAttribute("aria-pressed", String(authors.every(a => shown.has(a.toLowerCase()))));
    noneBtn.setAttribute("aria-pressed", String(shown.size === 0));
    for (const b of callerBtns) b.setAttribute("aria-pressed", String(shown.has(b.dataset.caller)));
    if (!card.hidden && !shown.has((nodes.find(t => t.o.post.id === card.dataset.postId) || { o: { post: { author: "" } } }).o.post.author.toLowerCase())) card.hidden = true;
    requestAnimationFrame(place);
  }

  function place() {
    if (!p.entry) { bubble.hidden = true; svg.style.display = "none"; return; }
    const step = INTERVALS[interval];
    if (p.closed) {
      const xx = chart.timeScale().timeToCoordinate(bucket(p.closed.exit.at, step)), xy = series.priceToCoordinate(p.closed.exit.price);
      exitMark.hidden = xx == null || xy == null;
      if (!exitMark.hidden) { exitMark.style.left = xx + "px"; exitMark.style.top = xy + "px"; }
      exitMark.setAttribute("data-x", xx); exitMark.setAttribute("data-y", xy);
    }
    const ex = chart.timeScale().timeToCoordinate(bucket(p.entry.at, step)), ey = series.priceToCoordinate(p.entry.price);
    bubble.hidden = ex == null || ey == null;
    if (!bubble.hidden) { bubble.style.left = ex + "px"; bubble.style.top = ey + "px"; }
    bubble.setAttribute("data-x", ex); bubble.setAttribute("data-y", ey);
    placeOthers(step, bubble.hidden ? null : { x: ex, y: ey, r: 15 });
    const bx = best ? chart.timeScale().timeToCoordinate(bucket(best.at, step)) : null, by = best ? series.priceToCoordinate(best.price) : null;
    const gain = best ? (sideName ? best.for_call : best.move) : 0;
    if (ex == null || ey == null || bx == null || by == null || gain <= 0) { svg.style.display = "none"; return; }
    svg.style.display = "";
    const color = css("--up");   // the marker shows a gain for the call, so it is always the positive colour
    line.setAttribute("x1", ex); line.setAttribute("y1", ey); line.setAttribute("x2", bx); line.setAttribute("y2", by);
    line.setAttribute("stroke", color);
    label.textContent = fmtPct(gain);
    label.setAttribute("fill", color);
    // label just beyond the best point, away from the entry side, kept inside the pane
    const up = by < ey, nearRight = bx > box.clientWidth - 140;
    label.setAttribute("x", nearRight ? bx - 8 : bx + 8);
    label.setAttribute("y", up || nearRight ? by - 10 : by + 18);   // near the right edge stay clear of the price-axis tags
    label.setAttribute("text-anchor", nearRight ? "end" : "start");
  }
  // Other calls: each bubble starts at its own entry candle; a bubble that would overlap one already
  // placed (the opened call first, then by entry time) moves up past it (down if that leaves the
  // pane), on a stem from its entry point, so every bubble keeps its own click area.
  function placeOthers(step, opened) {
    const placed = opened ? [opened] : [], W = chart.timeScale().width(), H = box.clientHeight, R = 13;
    let left = 0, right = 0;
    const clash = (x, y) => placed.find(q => Math.abs(q.x - x) < q.r + R + 1 && Math.abs(q.y - y) < q.r + R + 1);
    for (const t of nodes.slice().sort((a, b) => a.o.entry.at < b.o.entry.at ? -1 : a.o.entry.at > b.o.entry.at ? 1 : 0)) {
      const on = shown.has(t.o.post.author.toLowerCase());
      const x = chart.timeScale().timeToCoordinate(bucket(t.o.entry.at, step)), y = series.priceToCoordinate(t.o.entry.price);
      const visible = on && x != null && y != null && x >= 0 && x <= W && y >= 0 && y <= H;
      if (on && x != null && x < 0) left++;
      if (on && x != null && x > W) right++;
      t.n.hidden = !visible;
      t.n.setAttribute("data-shown", String(on));
      t.stem.style.display = "none";
      if (t.x) {
        const xx = chart.timeScale().timeToCoordinate(bucket(t.o.closed.exit.at, step)), xy = series.priceToCoordinate(t.o.closed.exit.price);
        t.x.hidden = !on || xx == null || xy == null || xx < 0 || xx > W;
        if (!t.x.hidden) { t.x.style.left = xx + "px"; t.x.style.top = xy + "px"; }
      }
      if (!visible) continue;
      let cy = y, q, guard = 0;
      while ((q = clash(x, cy)) && guard++ < 60) cy = q.y - q.r - R - 2;
      if (cy < R) { cy = y; guard = 0; while ((q = clash(x, cy)) && guard++ < 60) cy = q.y + q.r + R + 2; }
      placed.push({ x, y: cy, r: R });
      t.n.style.left = x + "px"; t.n.style.top = cy + "px";
      t.n.setAttribute("data-x", x); t.n.setAttribute("data-y", y);
      if (Math.abs(cy - y) > 0.5) {
        t.stem.style.display = "";
        t.stem.setAttribute("x1", x); t.stem.setAttribute("y1", y); t.stem.setAttribute("x2", x); t.stem.setAttribute("y2", cy);
      }
    }
    edgeL.hidden = !left; edgeL.textContent = `◀ ${left} earlier call${left === 1 ? "" : "s"}`;
    edgeR.hidden = !right; edgeR.textContent = `${right} later call${right === 1 ? "" : "s"} ▶`;
    edgeL.setAttribute("data-count", left); edgeR.setAttribute("data-count", right);
  }
  // zoom out (keeping the interval) so the opened call and every shown call are in view
  function fitCalls() {
    const ts = [p.entry, ...nodes.filter(t => shown.has(t.o.post.author.toLowerCase())).map(t => t.o.entry)].filter(Boolean).map(e => sec(e.at));
    const first = Math.min(...ts), last = sec(ohlc.candles[ohlc.candles.length - 1][0]);
    showRange(first - Math.max(12 * 3600, (last - first) * 0.03), last);
  }
  // range = [fromSec, toSec] or null (the opened call's default view)
  function draw(range) {
    const step = INTERVALS[interval];
    const data = aggregate(ohlc.candles, step);
    series.setData(data);
    if (range) {
      // by bar index: a time range starting in a market gap, or holding more bars than fit, would be shifted
      let i0 = data.findIndex(d => d.time >= range[0]);
      if (i0 < 0) i0 = 0;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(-0.5, i0 - 2), to: data.length - 1 + 4 });
    } else {
      const from = p.entry ? bucket(p.entry.at, step) - step * 12 : data[0].time;
      chart.timeScale().setVisibleRange({ from: Math.max(from, data[0].time), to: data[data.length - 1].time });
    }
    requestAnimationFrame(() => requestAnimationFrame(place));
  }
  // show [from, to]: the finest interval (current or coarser) whose candles fit the chart width
  // (the chart keeps at least ~0.5px per bar, so too many bars would not fit)
  function showRange(from, to) {
    const keys = Object.keys(INTERVALS), width = chart.timeScale().width() || box.clientWidth;
    let k = keys.indexOf(interval);
    const count = key => aggregate(ohlc.candles.filter(c => sec(c[0]) >= from - INTERVALS[key] && sec(c[0]) <= to), INTERVALS[key]).length;
    while (k < keys.length - 1 && count(keys[k]) > width / 2) k++;
    interval = keys[k];
    for (const x of bar.querySelectorAll("[data-interval]")) x.setAttribute("aria-pressed", String(x.dataset.interval === interval));
    draw([from, to]);
  }
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => requestAnimationFrame(place));
  chart.subscribeCrosshairMove(param => {
    requestAnimationFrame(place);
    const c = param && param.time != null ? param.seriesData.get(series) : null;
    if (!c) return;
    const daily = ohlc.daily_until && c.time < sec(ohlc.daily_until);
    readout.textContent = `${fmtTime(new Date(c.time * 1000).toISOString())} · ${daily ? "daily bar" : interval === "1h" ? "hourly bar" : interval + " candle"} · `
      + `O ${fmtPrice(c.open)} H ${fmtPrice(c.high)} L ${fmtPrice(c.low)} C ${fmtPrice(c.close)}`
      + (p.entry && c.time < bucket(p.entry.at, INTERVALS[interval]) ? " · before this call" : "");
    readout.setAttribute("data-daily", String(!!daily));
  });
  new ResizeObserver(() => requestAnimationFrame(place)).observe(box);
  draw();
  syncCallers();
  setTimeout(() => { place(); document.body.setAttribute("data-ready", "1"); }, 150);
}

if (!window.LightweightCharts) fail("The chart library did not load.");
else main().catch(e => fail("Could not load the position: " + e.message));
