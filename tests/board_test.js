// Step 10 leaderboard test (headless Chromium). The ranking rules are re-implemented here
// independently of web/assets/board.js and compared against what the page shows:
//  A. every filter x sort combination (time 3 x side 4 x author (n+1) x asset (n+1) x sort 3), each
//     loaded fresh from its shareable URL: row order, ranks, ids, returns, best, stats, empty state,
//     and the selects showing the URL's values
//  B. the controls: every option of every select changed in the page updates rows and the URL
//  C. default view: every field of every row equals its record file on disk (sha256-checked)
//  D. sparklines: point count = bundle bars from entry to latest; unknown URL values -> defaults
//  E. 0 console errors, 0 CSP violations, no horizontal scroll on a phone; screenshots
// usage: node tests/board_test.js [--url https://.../web/] [--screenshots DIR]
const fs = require('fs');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const puppeteer = require('/home/postfiat/node_modules/puppeteer');

const ROOT = path.resolve(__dirname, '..');
const WEB = path.join(ROOT, 'web');
const arg = k => (process.argv.includes(k) ? process.argv[process.argv.indexOf(k) + 1] : null);
const liveUrl = arg('--url');
const shotDir = arg('--screenshots') ? path.resolve(arg('--screenshots')) : null;
const TYPES = { '.html': 'text/html', '.json': 'application/json', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg' };

const pct = x => (x > 0 ? '+' : x < 0 ? '-' : '') + (Math.abs(x) * 100).toFixed(2) + '%';
const price = p => p.toLocaleString('en-US', { maximumFractionDigits: 8 });
const DEFAULTS = { time: 'all', side: 'all', author: 'all', asset: 'all', sort: 'return' };

function model(bundle) {
  const rows = [];
  for (const a of bundle.assets) for (const p of a.posts) {
    const ret = p.change_since_post == null ? null : p.side ? p.side * p.change_since_post : p.change_since_post;
    const best = p.best ? (p.side ? p.best.for_call : p.best.move) : null;
    rows.push({ id: p.post.id, asset: a.name, side: p.side === 1 ? 'long' : p.side === -1 ? 'short' : 'none', author: p.post.author,
                posted: p.post.posted_at, ret, best, p, series: a.series });
  }
  return rows;
}
function expected(rows, f, asOf) {
  const ref = Date.parse(asOf), day = asOf.slice(0, 10);
  const kept = rows.filter(r => (f.time === 'all' || (f.time === '7d' ? Date.parse(r.posted) >= ref - 7 * 864e5 : r.posted.slice(0, 10) === day))
    && (f.side === 'all' || r.side === f.side) && (f.author === 'all' || r.author === f.author) && (f.asset === 'all' || r.asset === f.asset));
  const key = r => f.sort === 'best' ? r.best : f.sort === 'newest' ? Date.parse(r.posted) : r.ret;
  kept.sort((x, y) => {
    const a = key(x), b = key(y);
    if ((a == null) !== (b == null)) return a == null ? 1 : -1;
    if (a !== b) return b - a;
    if (x.posted !== y.posted) return x.posted < y.posted ? 1 : -1;
    return x.id + x.asset < y.id + y.asset ? -1 : 1;
  });
  const done = kept.filter(r => r.ret != null);
  const stats = { count: kept.length, hit_rate: done.length ? done.filter(r => r.ret > 0).length / done.length : null,
    avg_return: done.length ? done.reduce((s, r) => s + r.ret, 0) / done.length : null,
    best_call: done.length ? (t => t.id + '|' + t.asset)(done.reduce((m, r) => (r.ret > m.ret ? r : m))) : null };
  return { rows: kept, stats };
}
const query = f => { const q = new URLSearchParams(); for (const [k, v] of Object.entries(f)) if (v !== DEFAULTS[k]) q.set(k, v); const s = q.toString(); return s ? '?' + s : ''; };

function serve() {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
    const file = path.resolve(WEB, rel);
    if (!file.startsWith(WEB + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(ok => server.listen(0, '127.0.0.1', () => ok(server)));
}

async function read(page) {
  return page.evaluate(() => ({
    search: location.search,
    selects: Object.fromEntries(['time', 'side', 'author', 'asset', 'sort'].map(k => [k, document.getElementById('f-' + k).value])),
    empty: !document.getElementById('empty').hidden,
    stats: Object.fromEntries([...document.querySelectorAll('[data-stat]')].map(s => [s.dataset.stat, JSON.parse(s.querySelector('strong').dataset.raw)])),
    rows: [...document.querySelectorAll('#rows > li')].map(li => ({
      id: li.dataset.postId, asset: li.dataset.asset, rank: li.dataset.rank, href: li.querySelector('a').getAttribute('href'),
      f: Object.fromEntries([...li.querySelectorAll('[data-field]')].map(n => [n.dataset.field, { text: n.textContent, raw: n.dataset.raw !== undefined ? JSON.parse(n.dataset.raw) : undefined }])),
      points: li.querySelector('svg.spark') ? Number(li.querySelector('svg.spark').dataset.points) : null,
      avatar: li.querySelector('.avatar').dataset.avatar, img: li.querySelector('.avatar img') ? li.querySelector('.avatar img').naturalWidth : null })),
    csp: window.__cspv || [] }));
}

(async () => {
  const bundle = JSON.parse(fs.readFileSync(path.join(WEB, 'data', 'charts.json'), 'utf8'));
  const asOf = bundle.prices_as_of;
  const rows = model(bundle);
  const authors = [...new Set(rows.map(r => r.author))].sort(), assets = [...new Set(rows.map(r => r.asset))].sort();
  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium', args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  const fails = [], consoleErrors = [];
  const fail = m => fails.push(m);
  let combos = 0, nonEmpty = 0, uiChanges = 0, fieldChecks = 0, csp = 0;
  const cmp = (tag, got, f) => {
    const want = expected(rows, f, asOf);
    if (got.rows.map(r => r.id + '|' + r.asset).join(',') !== want.rows.map(r => r.id + '|' + r.asset).join(',')) return fail(`${tag}: order ${got.rows.map(r => r.asset + r.id.slice(-4))} != ${want.rows.map(r => r.asset + r.id.slice(-4))}`);
    want.rows.forEach((w, i) => {
      const g = got.rows[i];
      if (g.rank !== String(i + 1) || g.f.rank.text !== String(i + 1)) fail(`${tag}: rank of ${w.id} is ${g.rank}`);
      if (JSON.stringify(g.f.return.raw) !== JSON.stringify(w.ret) || g.f.return.text !== (w.ret == null ? 'unresolved' : pct(w.ret))) fail(`${tag}: return of ${w.id} ${g.f.return.text}`);
      if (JSON.stringify(g.f.best.raw) !== JSON.stringify(w.best)) fail(`${tag}: best of ${w.id}`);
    });
    for (const [k, v] of Object.entries(want.stats)) if (JSON.stringify(got.stats[k]) !== JSON.stringify(v)) fail(`${tag}: stat ${k} ${JSON.stringify(got.stats[k])} != ${JSON.stringify(v)}`);
    if (got.empty !== (want.rows.length === 0)) fail(`${tag}: empty state shown=${got.empty} for ${want.rows.length} rows`);
    if (want.rows.length) nonEmpty++;
  };
  try {
    const page = await browser.newPage();
    await page.evaluateOnNewDocument(() => { window.__cspv = []; document.addEventListener('securitypolicyviolation', e => window.__cspv.push(e.violatedDirective + ' ' + e.blockedURI)); });
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleErrors.push(`${m.type()}: ${m.text()}`); });
    page.on('pageerror', e => consoleErrors.push(`pageerror: ${e.message}`));
    page.on('requestfailed', r => consoleErrors.push(`requestfailed ${r.url()}`));
    page.on('response', r => { if (r.status() >= 400) consoleErrors.push(`http ${r.status()} ${r.url()}`); });
    await page.setViewport({ width: 1280, height: 1000 });
    const load = async q => { await page.goto(base + q, { waitUntil: 'networkidle0' }); await page.waitForFunction(() => document.body.dataset.ready === '1', { timeout: 20000 }); const g = await read(page); csp += g.csp.length; for (const v of g.csp) fail(`CSP ${q}: ${v}`); return g; };

    // A. every combination, fresh from its URL
    for (const time of ['all', '7d', 'today']) for (const side of ['all', 'long', 'short', 'none'])
      for (const author of ['all', ...authors]) for (const asset of ['all', ...assets]) for (const sort of ['return', 'best', 'newest']) {
        const f = { time, side, author, asset, sort }, q = query(f);
        const got = await load(q);
        combos++;
        cmp(`url ${q || '(default)'}`, got, f);
        if (JSON.stringify(got.selects) !== JSON.stringify(f)) fail(`url ${q}: selects show ${JSON.stringify(got.selects)}`);
        if (got.search !== q) fail(`url ${q}: page rewrote the url to ${got.search}`);
      }

    // B. the controls: change each select to each option from the default view
    for (const [k, opts] of Object.entries({ time: ['7d', 'today', 'all'], side: ['long', 'short', 'none', 'all'], author: [...authors, 'all'], asset: [...assets, 'all'], sort: ['best', 'newest', 'return'] })) {
      await load('');
      for (const v of opts) {
        await page.select('#f-' + k, v);
        const f = { ...DEFAULTS, [k]: v }, got = await read(page);
        uiChanges++;
        cmp(`select ${k}=${v}`, got, f);
        if (got.search !== query(f)) fail(`select ${k}=${v}: url ${got.search} != ${query(f)}`);
      }
    }

    // C + D. default view, every field against the record file
    const def = await load('');
    const want = expected(rows, DEFAULTS, asOf).rows;
    want.forEach((w, i) => {
      const g = def.rows[i], p = w.p;
      const blob = fs.readFileSync(path.join(ROOT, p.record_file));
      if (crypto.createHash('sha256').update(blob).digest('hex') !== p.record_sha256) fail(`${p.record_file}: sha256 differs`);
      const rec = JSON.parse(blob), tag = `row ${w.asset} ${w.id}`;
      const eq = (name, text) => { fieldChecks++; if (!g.f[name] || g.f[name].text !== text) fail(`${tag}: ${name} shows ${JSON.stringify(g.f[name] && g.f[name].text)} want ${JSON.stringify(text)}`); };
      eq('asset', rec.asset.name);
      eq('side', rec.side === 1 ? 'LONG' : rec.side === -1 ? 'SHORT' : 'NO SIDE');
      eq('author', '@' + rec.post.author);
      eq('prices', rec.entry ? `${price(rec.entry.price)} → ${rec.latest ? price(rec.latest.price) : '–'}` : 'no entry bar');
      eq('status', rec.status);
      if (rec.post.text) eq('quote', '“' + rec.post.text.replace(/\s+/g, ' ').trim() + '”');
      const ret = rec.change_since_post == null ? null : rec.side ? rec.side * rec.change_since_post : rec.change_since_post;
      eq('return', ret == null ? 'unresolved' : pct(ret));
      fieldChecks++;
      if (g.href !== `position.html?post=${rec.post.id}&asset=${encodeURIComponent(rec.asset.name)}`) fail(`${tag}: link ${g.href}`);
      const bars = w.series.filter(([t]) => rec.entry && rec.latest && t >= rec.entry.at && t <= rec.latest.at).length;
      if (g.points !== bars) fail(`${tag}: sparkline ${g.points} points, bundle has ${bars} bars entry->latest`);
      if (g.avatar === 'image' && !(g.img > 0)) fail(`${tag}: avatar image did not load`);
    });
    const odd = await load('?side=bogus&sort=evil&time=1d&asset=%3Cb%3E');
    if (JSON.stringify(odd.selects) !== JSON.stringify(DEFAULTS)) fail(`unknown url values not reset: ${JSON.stringify(odd.selects)}`);
    // every row link opens its position page
    for (const r of want.slice(0, 3)) {
      await page.goto(base + `position.html?post=${r.id}&asset=${encodeURIComponent(r.asset)}`, { waitUntil: 'networkidle0' });
      await page.waitForFunction(() => document.body.dataset.ready, { timeout: 20000 });
      if (await page.evaluate(() => document.body.dataset.ready) !== '1') fail(`link target for ${r.id} did not load`);
    }

    // E. screenshots + phone
    if (shotDir) fs.mkdirSync(shotDir, { recursive: true });
    for (const [name, vp, q] of [['desktop', { width: 1280, height: 1000 }, ''], ['desktop_filtered', { width: 1280, height: 1000 }, '?side=short&sort=best'],
      ['phone', { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true }, ''], ['phone_filtered', { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true }, '?asset=BTC&time=7d']]) {
      await page.setViewport(vp);
      await load(q);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 0) fail(`${name}: page scrolls horizontally by ${overflow}px`);
      if (shotDir) await page.screenshot({ path: path.join(shotDir, `board_${name}.png`), fullPage: true });
    }
  } finally {
    await browser.close();
    if (server) server.close();
  }
  for (const e of consoleErrors) fail(`console: ${e}`);
  console.log(`page ${base}`);
  console.log(`filter/sort combinations loaded from their URL: ${combos} (${nonEmpty} with rows, ${combos - nonEmpty} correctly empty); select changes: ${uiChanges}; ` +
    `default-view fields checked against records: ${fieldChecks}; rows ${rows.length}; CSP violations ${csp}; console errors ${consoleErrors.length}`);
  for (const f of fails.slice(0, 40)) console.log(' -', f);
  if (fails.length > 40) console.log(` ... ${fails.length - 40} more`);
  console.log(fails.length ? `FAIL (${fails.length})` : 'ALL PASS');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
