// Step 10 leaderboard test (headless Chromium). The ranking rules are re-implemented here
// independently of web/assets/board.js and compared against what the page shows:
//  A. every filter x sort combination (time 3 x side 4 x status 3 x author (n+1) x asset (n+1) x sort 3), set in
//     the page; every 25th also loaded fresh from its shareable URL: row order, ranks, ids, returns,
//     best, stats, per-author summary + sample flags, empty state, and the selects / URL
//  B. the controls: every option of every select changed in the page updates rows and the URL
//  C. default view: every field of every row equals its record file on disk (sha256-checked)
//  D. sparklines: point count = bundle bars from entry to latest; unknown URL values -> defaults,
//     removed from the address bar
//  F. (local only) a test-only site copy with a pending post: it reads "unresolved" and ranks last
//     by return and by best, first by newest; it counts in Positions but not in the averages
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
const DEFAULTS = { time: 'all', side: 'all', state: 'all', author: 'all', asset: 'all', sort: 'return' };
// plain status wording, mirrored from web/assets/common.js
const statusLabel = p => p.status === 'closed' ? 'closed' : p.status === 'resolved' ? 'all horizons in' : p.status === 'pending' ? 'no price yet' : p.status === 'no_entry' ? 'no price at post time'
  : (h => h.length ? h.map(x => x + 'd').join(', ') + ' pending' : p.status)(['1', '7', '30'].filter(x => p.unresolved && p.unresolved[x]));
const slug = (id, asset) => `${id.replace(/[^A-Za-z0-9_-]/g, '-')}_${asset.replace(/[^A-Za-z0-9_-]/g, '-')}`;


function model(bundle) {
  const rows = [];
  for (const a of bundle.assets) for (const p of a.posts) {
    // closed: the frozen realized return (step 13); open: since post, for the call when a side is stated
    const ret = p.closed ? (p.side ? p.closed.for_call : p.closed.move) : p.change_since_post == null ? null : p.side ? p.side * p.change_since_post : p.change_since_post;
    const best = p.best ? (p.side ? p.best.for_call : p.best.move) : null;
    rows.push({ id: p.post.id, asset: a.name, side: p.side === 1 ? 'long' : p.side === -1 ? 'short' : 'none', state: p.closed ? 'closed' : 'open', author: p.post.author,
                posted: p.post.posted_at, ret, best, p, series: a.series });
  }
  return rows;
}
function expected(rows, f, asOf) {
  const ref = Date.parse(asOf), day = asOf.slice(0, 10);
  const kept = rows.filter(r => (f.time === 'all' || (f.time === '7d' ? Date.parse(r.posted) >= ref - 7 * 864e5 : r.posted.slice(0, 10) === day))
    && (f.side === 'all' || r.side === f.side) && (f.state === 'all' || r.state === f.state) && (f.author === 'all' || r.author === f.author) && (f.asset === 'all' || r.asset === f.asset));
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
// step 15: authors in score order (bundle.ratings, every call), ties by name; the score itself is
// recomputed independently in tests/ratings_test.js
let RATINGS = { callers: {} };
function authorsExpected(rows, f, asOf) {
  const kept = expected(rows, { ...f, author: 'all' }, asOf).rows, by = {};
  for (const r of kept) (by[r.author] = by[r.author] || []).push(r);
  const sc = a => RATINGS.callers[a] ? RATINGS.callers[a].score : -Infinity;
  return Object.keys(by).sort((x, y) => sc(y) - sc(x) || (x.toLowerCase() < y.toLowerCase() ? -1 : 1)).map(a => {
    const done = by[a].filter(r => r.ret != null), n = done.length;
    const best = n ? done.reduce((m, r) => (r.ret > m.ret ? r : m)) : null, worst = n ? done.reduce((m, r) => (r.ret < m.ret ? r : m)) : null;
    return { author: a, score: RATINGS.callers[a] ? RATINGS.callers[a].score : undefined, calls: by[a].length, hit: n ? done.filter(r => r.ret > 0).length / n : null, avg: n ? done.reduce((s, r) => s + r.ret, 0) / n : null,
      best: best ? best.id + '|' + best.asset : null, worst: worst ? worst.id + '|' + worst.asset : null,
      flag: n < 10 ? 'insufficient sample' : n < 30 ? 'unreliable sample' : 'ok' };
  });
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
    selects: Object.fromEntries(['time', 'side', 'state', 'author', 'asset', 'sort'].map(k => [k, document.getElementById('f-' + k).value])),
    empty: !document.getElementById('empty').hidden,
    stats: Object.fromEntries([...document.querySelectorAll('[data-stat]')].map(s => [s.dataset.stat, JSON.parse(s.querySelector('strong').dataset.raw)])),
    rows: [...document.querySelectorAll('#rows > li')].map(li => ({
      id: li.dataset.postId, asset: li.dataset.asset, rank: li.dataset.rank, href: li.querySelector('a').getAttribute('href'),
      f: Object.fromEntries([...li.querySelectorAll('[data-field]')].map(n => [n.dataset.field, { text: n.textContent, raw: n.dataset.raw !== undefined ? JSON.parse(n.dataset.raw) : undefined }])),
      points: li.querySelector('svg.spark') ? Number(li.querySelector('svg.spark').dataset.points) : null,
      avatar: li.querySelector('.avatar').dataset.avatar, img: li.querySelector('.avatar img') ? li.querySelector('.avatar img').naturalWidth : null })),
    authors: [...document.querySelectorAll('#authors tbody tr')].map(tr => ({ author: tr.dataset.author,
      ...Object.fromEntries([...tr.querySelectorAll('[data-field]')].map(n => [n.dataset.field, JSON.parse(n.dataset.raw)])) })),
    csp: window.__cspv || [] }));
}

(async () => {
  const bundle = JSON.parse(fs.readFileSync(path.join(WEB, 'data', 'charts.json'), 'utf8'));
  const asOf = bundle.prices_as_of;
  RATINGS = bundle.ratings;
  const rows = model(bundle);
  const authors = [...new Set(rows.map(r => r.author))].sort(), assets = [...new Set(rows.map(r => r.asset))].sort();
  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  if (shotDir) fs.mkdirSync(shotDir, { recursive: true });
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium', args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  const fails = [], consoleErrors = [];
  const fail = m => fails.push(m);
  let combos = 0, nonEmpty = 0, uiChanges = 0, fieldChecks = 0, csp = 0, authorRows = 0, urlReloads = 0;
  const pendingChecks = [];
  let staticChecks = 0, staticPages = 0;
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
    const wa = authorsExpected(rows, f, asOf);
    authorRows += wa.length;
    const ga = got.authors.map(a => ({ author: a.author, score: a.score, calls: a.calls, hit: a.hit, avg: a.avg, best: a.best, worst: a.worst, flag: a.flag }));
    // the average is a float sum: the page adds in data order, this test in ranked order, so compare it
    // to 1e-12; every other field exactly
    const strip = xs => xs.map(x => ({ ...x, avg: null }));
    const avgOk = ga.length === wa.length && ga.every((x, i) => (x.avg == null && wa[i].avg == null) || Math.abs(x.avg - wa[i].avg) < 1e-12);
    if (JSON.stringify(strip(ga)) !== JSON.stringify(strip(wa)) || !avgOk) fail(`${tag}: author summary ${JSON.stringify(ga)} != ${JSON.stringify(wa)}`);
    if (got.empty !== (want.rows.length === 0)) fail(`${tag}: empty state shown=${got.empty} for ${want.rows.length} rows`);
    return want.rows.length > 0;
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

    // A. every combination: set in the page (all five selects), and every 25th also loaded fresh
    //    from its URL, so the shared link reproduces the same view
    await load('');
    for (const time of ['all', '7d', 'today']) for (const side of ['all', 'long', 'short', 'none']) for (const state of ['all', 'open', 'closed'])
      for (const author of ['all', ...authors]) for (const asset of ['all', ...assets]) for (const sort of ['return', 'best', 'newest']) {
        const f = { time, side, state, author, asset, sort }, q = query(f);
        await page.evaluate(f => { for (const [k, v] of Object.entries(f)) { const s = document.getElementById('f-' + k); if (s.value !== v) { s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); } } }, f);
        let got = await read(page);
        combos++;
        if (cmp(`combo ${q || '(default)'}`, got, f)) nonEmpty++;
        if (got.search !== q) fail(`combo ${q}: url ${got.search}`);
        if (combos % 25 === 0) {
          got = await load(q);
          urlReloads++;
          cmp(`url ${q || '(default)'}`, got, f);
          if (JSON.stringify(got.selects) !== JSON.stringify(f)) fail(`url ${q}: selects show ${JSON.stringify(got.selects)}`);
          if (got.search !== q) fail(`url ${q}: page rewrote the url to ${got.search}`);
        }
      }

    // B. the controls: change each select to each option from the default view
    for (const [k, opts] of Object.entries({ time: ['7d', 'today', 'all'], side: ['long', 'short', 'none', 'all'], state: ['open', 'closed', 'all'], author: [...authors, 'all'], asset: [...assets, 'all'], sort: ['best', 'newest', 'return'] })) {
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
      eq('prices', rec.entry ? `${price(rec.entry.price)} → ${rec.closed ? price(rec.closed.exit.price) + ' exit' : rec.latest ? price(rec.latest.price) : '–'}` : 'no entry bar');
      eq('status', statusLabel(rec));
      if (rec.post.text) eq('quote', '“' + rec.post.text.replace(/\s+/g, ' ').trim() + '”');
      const ret = rec.closed ? (rec.side ? rec.closed.for_call : rec.closed.move) : rec.change_since_post == null ? null : rec.side ? rec.side * rec.change_since_post : rec.change_since_post;
      eq('return', ret == null ? 'unresolved' : pct(ret));
      fieldChecks++;
      if (g.href !== `pos-${slug(rec.post.id, rec.asset.name)}.html`) fail(`${tag}: link ${g.href}`);
      const end = rec.closed ? rec.closed.exit.at : rec.latest && rec.latest.at;
      const bars = w.series.filter(([t]) => rec.entry && rec.latest && t >= rec.entry.at && t <= end).length;
      if (g.points !== bars) fail(`${tag}: sparkline ${g.points} points, bundle has ${bars} bars entry->latest (exit if closed)`);
      if (g.avatar === 'image' && !(g.img > 0)) fail(`${tag}: avatar image did not load`);
    });
    const odd = await load('?side=bogus&sort=evil&time=1d&asset=%3Cb%3E');
    if (JSON.stringify(odd.selects) !== JSON.stringify(DEFAULTS)) fail(`unknown url values not reset: ${JSON.stringify(odd.selects)}`);
    if (odd.search !== '') fail(`unknown url values not removed from the address bar: ${odd.search}`);
    cmp('invalid url', odd, DEFAULTS);
    const lower = await load('?author=' + authors[1].toLowerCase() + '&asset=' + assets[assets.length - 1].toLowerCase());
    const lf = { ...DEFAULTS, author: authors[1], asset: assets[assets.length - 1] };
    if (JSON.stringify(lower.selects) !== JSON.stringify(lf) || lower.search !== query(lf)) fail(`lower-case url not matched: ${JSON.stringify(lower.selects)} ${lower.search}`);
    else cmp('lower-case url', lower, lf);
    const partly = await load('?side=short&sort=evil');
    if (partly.search !== '?side=short') fail(`partly invalid url rewritten to ${partly.search}, want ?side=short`);
    // every row link opens its position page
    for (const r of want.slice(0, 3)) {
      await page.goto(base + `position.html?post=${r.id}&asset=${encodeURIComponent(r.asset)}`, { waitUntil: 'networkidle0' });
      await page.waitForFunction(() => document.body.dataset.ready, { timeout: 20000 });
      if (await page.evaluate(() => document.body.dataset.ready) !== '1') fail(`link target for ${r.id} did not load`);
    }

    // F. unresolved positions (local only): a test-only copy of the site whose bundle adds
    //    tests/fixtures/pending_records (a post with no entry bar yet). Never deployed.
    if (!liveUrl) {
      const os = require('os'), { execFileSync } = require('child_process');
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pfps-pending-')), recs = path.join(tmp, 'records');
      fs.cpSync(WEB, path.join(tmp, 'web'), { recursive: true });
      fs.cpSync(path.join(ROOT, 'records'), recs, { recursive: true });
      fs.cpSync(path.join(ROOT, 'tests', 'fixtures', 'pending_records'), path.join(recs, 'pending'), { recursive: true });
      execFileSync('python3', [path.join(ROOT, 'build_chart.py'), '--records', recs, '--out', path.join(tmp, 'web', 'data', 'charts.json')], { cwd: ROOT });
      const pb = JSON.parse(fs.readFileSync(path.join(tmp, 'web', 'data', 'charts.json'), 'utf8'));
      const pend = pb.assets.flatMap(a => a.posts.filter(p => p.status === 'pending').map(p => p.post.id));
      const srv = await new Promise(ok => { const s = http.createServer((req, res) => {
        const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
        const file = path.resolve(tmp, 'web', rel);
        if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
        res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' }); fs.createReadStream(file).pipe(res);
      }); s.listen(0, '127.0.0.1', () => ok(s)); });
      const pbase = `http://127.0.0.1:${srv.address().port}/`;
      for (const sort of ['return', 'best', 'newest']) {
        await page.goto(pbase + (sort === 'return' ? '' : '?sort=' + sort), { waitUntil: 'networkidle0' });
        await page.waitForFunction(() => document.body.dataset.ready === '1');
        const g = await read(page), total = g.rows.length;
        const idx = g.rows.findIndex(r => pend.includes(r.id));
        const row = g.rows[idx];
        const where = sort === 'newest' ? 'first (newest post)' : 'last';
        const ok = idx >= 0 && (sort === 'newest' ? idx === 0 : idx === total - 1) && row.f.return.text === 'unresolved' && row.f.best.text === '–'
          && row.f.prices.text === 'no entry bar' && g.stats.count === total
          && JSON.stringify(g.stats.avg_return) === JSON.stringify(expected(model(pb), { ...DEFAULTS, sort }, pb.prices_as_of || new Date().toISOString()).stats.avg_return);
        pendingChecks.push(`sort=${sort}: pending post ${pend[0]} at rank ${idx + 1} of ${total} (${where}), return "${row && row.f.return.text}", best "${row && row.f.best.text}", prices "${row && row.f.prices.text}" -> ${ok ? 'OK' : 'WRONG'}`);
        if (!ok) fail(`pending fixture, sort=${sort}: rank ${idx + 1}/${total}, ${JSON.stringify(row && row.f.return)}`);
        if (shotDir && sort === 'return') await page.screenshot({ path: path.join(shotDir, 'board_pending_fixture.png'), fullPage: true });
      }
      srv.close();
    }

    // G. the same page without JavaScript: the prerendered rows (raw HTML, no script run) are the
    //    default ranking and carry the bundle's values; every row's static position page has them too
    const get = u => new Promise((ok, no) => (u.startsWith('https') ? require('https') : http).get(u, r => { let d = ''; r.on('data', c => (d += c)); r.on('end', () => ok({ status: r.statusCode, body: d })); }).on('error', no));
    const rawIndex = (await get(base)).body;
    const lis = [...rawIndex.matchAll(/<li data-static="1" data-post-id="([^"]+)" data-asset="([^"]+)" data-rank="(\d+)">(.*?)<\/li>/gs)];
    const unesc = s => s.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    const wantDef = expected(rows, DEFAULTS, asOf).rows;
    if (lis.map(m => unesc(m[1]) + '|' + unesc(m[2])).join(',') !== wantDef.map(r => r.id + '|' + r.asset).join(',')) fail(`static rows ${lis.length}: order differs from the default ranking`);
    for (const [i, m] of lis.entries()) {
      const w = wantDef[i], body = m[4];
      const rawOf = f => { const x = body.match(new RegExp(`data-field="${f}" data-raw="([^"]*)"`)); return x ? JSON.parse(unesc(x[1])) : undefined; };
      staticChecks++;
      if (JSON.stringify(rawOf('return')) !== JSON.stringify(w.ret) || JSON.stringify(rawOf('best')) !== JSON.stringify(w.best) || rawOf('status') !== w.p.status) fail(`static row ${w.id}: values differ from the bundle`);
      if (!body.includes(`href="pos-${slug(w.id, w.asset)}.html"`)) fail(`static row ${w.id}: link`);
      if (!body.includes('>' + statusLabel(w.p) + '<')) fail(`static row ${w.id}: status label`);
      const pg = await get(base + `pos-${slug(w.id, w.asset)}.html`);
      if (pg.status !== 200) { fail(`static page for ${w.id}: HTTP ${pg.status}`); continue; }
      const pick = f => { const x = pg.body.match(new RegExp(`data-field="${f}" data-raw="([^"]*)"`)); return x ? JSON.parse(unesc(x[1])) : undefined; };
      if (JSON.stringify(pick('entry')) !== JSON.stringify(w.p.entry) || JSON.stringify(pick('latest')) !== JSON.stringify(w.p.latest)
          || JSON.stringify(pick('return')) !== JSON.stringify(w.ret) || pick('status') !== w.p.status) fail(`static page ${w.id}: values differ from the bundle`);
      if (!pg.body.includes('<meta property="og:title"')) fail(`static page ${w.id}: no link-preview tags`);
      staticPages++;
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
  console.log(`filter/sort combinations: ${combos} set in the page (${nonEmpty} with rows, ${combos - nonEmpty} correctly empty), ${urlReloads} of them also loaded fresh from their URL; author-summary rows checked: ${authorRows}; select changes: ${uiChanges}; ` +
    `default-view fields checked against records: ${fieldChecks}; without javascript: ${staticChecks} static rows + ${staticPages} static position pages equal the bundle; rows ${rows.length}; CSP violations ${csp}; console errors ${consoleErrors.length}`);
  for (const c of pendingChecks) console.log('unresolved (test-only fixture copy): ' + c);
  for (const f of fails.slice(0, 40)) console.log(' -', f);
  if (fails.length > 40) console.log(` ... ${fails.length - 40} more`);
  console.log(fails.length ? `FAIL (${fails.length})` : 'ALL PASS');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
