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

function fail(msg) {
  document.getElementById("app").replaceChildren(el("div", { class: "panel error", "data-error": "1" }, msg));
  document.body.setAttribute("data-ready", "error");
}

async function main() {
  const q = new URLSearchParams(location.search), id = q.get("post"), assetName = q.get("asset");
  if (!id) return fail("No post given. Open a post from the main chart.");
  const getJson = u => fetch(u).then(r => { if (!r.ok) throw new Error(u + " HTTP " + r.status); return r.json(); });
  const [bundle, avatars] = await Promise.all([getJson("data/charts.json"), getJson("avatars/index.json").catch(() => ({}))]);
  const matches = bundle.assets.flatMap(a => a.posts.filter(p => p.post.id === id && (!assetName || a.name === assetName)).map(p => [a, p]));
  if (!matches.length) return fail(`Post ${id}${assetName ? " on " + assetName : ""} is not in the data.`);
  const [asset, p] = matches[0];
  const ohlc = await getJson(`data/ohlc/${encodeURIComponent(asset.name)}.json`);
  document.title = `${p.asset.name} · @${p.post.author} · position`;
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
  const meta = el("span", { class: "meta" });
  meta.append(el("span", { "data-field": "posted_at", "data-raw": JSON.stringify(p.post.posted_at) }, fmtTime(p.post.posted_at)), " · ");
  meta.append(el("a", { href: p.post.url, target: "_blank", rel: "noopener noreferrer", "data-field": "url" }, "open on X"));
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
  right.append(el("span", null, p.latest ? fmtPrice(p.latest.price) : "–"));
  if (p.change_since_post != null) right.append(el("span", { class: "chip " + (dir === "up" ? "up" : dir === "down" ? "down" : "") }, fmtPct(p.change_since_post)));
  const forCall = sideName && p.change_since_post != null ? p.side * p.change_since_post : null;
  const since = el("span", { class: "since", "data-field": "header_since" }, "since post · " + age(p.post.posted_at, nowMs));
  if (forCall != null) { since.append(" · "); since.append(el("span", { class: signClass(forCall) }, `${fmtPct(forCall)} for the ${sideName}`)); }
  right.append(since);
  head.append(right);
  pos.append(head);

  const span = (sec(ohlc.candles[ohlc.candles.length - 1][0]) - (p.entry ? sec(p.entry.at) : sec(ohlc.candles[0][0]))) / 86400;
  const want = new URLSearchParams(location.search).get("interval");
  let interval = INTERVALS[want] ? want : span <= 7 ? "1h" : span <= 30 ? "4h" : "1D";
  const bar = el("div", { class: "toolbar", role: "group", "aria-label": "Candle interval" });
  for (const k of Object.keys(INTERVALS)) {
    const b = el("button", { type: "button", "data-interval": k, "aria-pressed": String(k === interval) }, k);
    b.addEventListener("click", () => { interval = k; for (const x of bar.children) x.setAttribute("aria-pressed", String(x === b)); draw(); });
    bar.append(b);
  }
  pos.append(bar);
  const box = el("div", { id: "chart-box" });
  const chartEl = el("div", { id: "chart" }), overlay = el("div", { id: "overlay" });
  box.append(chartEl, overlay);
  pos.append(box);
  pos.append(el("p", { class: "as-of", "data-field": "prices_as_of", "data-raw": JSON.stringify(bundle.prices_as_of || null) },
    bundle.prices_as_of ? "Prices as of " + fmtTime(bundle.prices_as_of) + " (daily refresh)" : "Prices not refreshed yet"));
  pos.append(el("p", { class: "attribution" },
    "Candles: hourly opens/highs/lows/closes from " + ohlc.source + ":" + ohlc.symbol + " fetched " + fmtTime(ohlc.fetched_at) +
    ", display only. Charting by TradingView Lightweight Charts."));
  app.append(pos);

  // recap: every value from the record (best since post from the record's own series)
  const recap = el("section", { class: "panel recap" });
  recap.append(el("h2", null, "Recap"));
  const dl = el("dl");
  field(dl, "asset", "Asset", `${p.asset.name} (${p.asset.source}:${p.asset.symbol})`);
  field(dl, "side", "Side", sideName || "no side stated", p.side ?? null);
  field(dl, "status", "Status", p.status, p.status);
  field(dl, "entry", "Entry", p.entry ? `${fmtPrice(p.entry.price)} @ ${fmtTime(p.entry.at)}` : "no entry bar", p.entry);
  field(dl, "latest", "Latest", p.latest ? `${fmtPrice(p.latest.price)} @ ${fmtTime(p.latest.at)}` : "no bar yet", p.latest);
  field(dl, "change_since_post", "Since post", p.change_since_post == null ? "unresolved" : fmtPct(p.change_since_post), p.change_since_post,
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
  recap.append(dl);
  recap.append(el("p", { class: "notes", "data-field": "record_file" }, `Record ${p.record_file} · sha256 ${p.record_sha256}`));
  app.append(recap);

  // chart
  const chart = LightweightCharts.createChart(chartEl, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: css("--muted"), fontSize: 11, attributionLogo: true },
    grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
    rightPriceScale: { borderColor: css("--axis"), scaleMargins: { top: 0.15, bottom: 0.12 } },
    timeScale: { borderColor: css("--axis"), timeVisible: true, secondsVisible: false, rightOffset: 4 },
    localization: { priceFormatter: fmtPrice, timeFormatter: t => new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC" },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: { vertTouchDrag: false },
  });
  const series = chart.addCandlestickSeries({
    upColor: css("--up"), downColor: css("--down"), wickUpColor: css("--up"), wickDownColor: css("--down"), borderVisible: false,
    priceFormat: { type: "custom", formatter: fmtPrice, minMove: 1e-8 },
  });
  if (p.latest) series.createPriceLine({ price: p.latest.price, color: css("--muted"), lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: "latest" });
  window.__position = { chart, series, post: p, get interval() { return interval; }, step: () => INTERVALS[interval] };

  const bubble = avatarNode(p.post.author, avatars, "");
  bubble.id = "entry-bubble";
  bubble.setAttribute("title", "@" + p.post.author + " posted here");
  const svgNS = "http://www.w3.org/2000/svg", svg = document.createElementNS(svgNS, "svg");
  const line = document.createElementNS(svgNS, "line"), label = document.createElementNS(svgNS, "text");
  line.setAttribute("class", "best-line"); label.setAttribute("class", "best-label");
  svg.append(line, label);
  overlay.append(svg, bubble);

  function place() {
    if (!p.entry) { bubble.hidden = true; svg.style.display = "none"; return; }
    const step = INTERVALS[interval];
    const ex = chart.timeScale().timeToCoordinate(bucket(p.entry.at, step)), ey = series.priceToCoordinate(p.entry.price);
    bubble.hidden = ex == null || ey == null;
    if (!bubble.hidden) { bubble.style.left = ex + "px"; bubble.style.top = ey + "px"; }
    bubble.setAttribute("data-x", ex); bubble.setAttribute("data-y", ey);
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
  function draw() {
    const step = INTERVALS[interval];
    const data = aggregate(ohlc.candles, step);
    series.setData(data);
    const from = p.entry ? bucket(p.entry.at, step) - step * 12 : data[0].time;
    chart.timeScale().setVisibleRange({ from: Math.max(from, data[0].time), to: data[data.length - 1].time });
    requestAnimationFrame(() => requestAnimationFrame(place));
  }
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => requestAnimationFrame(place));
  chart.subscribeCrosshairMove(() => requestAnimationFrame(place));
  new ResizeObserver(() => requestAnimationFrame(place)).observe(box);
  draw();
  setTimeout(() => { place(); document.body.setAttribute("data-ready", "1"); }, 150);
}

if (!window.LightweightCharts) fail("The chart library did not load.");
else main().catch(e => fail("Could not load the position: " + e.message));
