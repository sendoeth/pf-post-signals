// Step 15: caller scores on the live pages.
//  A. every caller's score recomputed here from the bundle's positions (a second implementation of
//     quanty.rating.v1, written separately from rate.py) = bundle.ratings (score to 1e-9, counts, order, display)
//  B. leaderboard author table: score cells, default score order, every header sort (score, author,
//     calls, in profit, avg return) by click, kept in ?asort= and restored on reload, also combined
//     with filters; caller links
//  C. every caller page: score, inputs, components, raw, weight and every call's result / A_i = the
//     recomputation; every call link opens a position page
//  D. every position page: the caller's score chip (raw + link); the caller card on the chart overlay
//  E. chart view: every bubble's card shows its caller's score
//  plus 0 console errors and 0 CSP violations on every page
// usage: node tests/ratings_test.js [--url https://.../web/] [--screenshots DIR]
const fs = require('fs');
const path = require('path');
const http = require('http');
const puppeteer = require('/home/postfiat/node_modules/puppeteer');

const ROOT = path.resolve(__dirname, '..');
const WEB = path.join(ROOT, 'web');
const arg = k => (process.argv.includes(k) ? process.argv[process.argv.indexOf(k) + 1] : null);
const liveUrl = arg('--url');
const shotDir = arg('--screenshots') ? path.resolve(arg('--screenshots')) : null;
const slug = (id, asset) => `${id.replace(/[^A-Za-z0-9_-]/g, '-')}_${asset.replace(/[^A-Za-z0-9_-]/g, '-')}`;
const callerPage = h => `caller-${h.toLowerCase().replace(/[^a-z0-9_-]/g, '-')}.html`;

// A. second implementation: plain loops over the bundle positions
function recompute(bundle) {
  const callers = {};
  for (const a of bundle.assets) for (const p of a.posts) {
    const c = callers[p.post.author] || (callers[p.post.author] = { total: 0, entry: 0, rs: [], calls: [] });
    c.total++;
    let r = null;
    if (p.closed) r = p.side ? p.closed.for_call : p.closed.move;
    else if (p.change_since_post != null) r = p.side ? p.side * p.change_since_post : p.change_since_post;
    const counted = !!(p.entry && p.side && r != null);
    if (p.entry) c.entry++;
    if (counted) c.rs.push(r);
    c.calls.push({ id: p.post.id, asset: a.name, posted: p.post.posted_at, r, counted, q: counted ? 50 + 50 * Math.tanh(r * 10) : null });
  }
  for (const [name, c] of Object.entries(callers)) {
    const n = c.rs.length;
    c.calls.sort((x, y) => x.posted < y.posted ? -1 : x.posted > y.posted ? 1 : x.id < y.id ? -1 : x.id > y.id ? 1 : x.asset < y.asset ? -1 : 1);
    if (!n) { Object.assign(c, { n, score: 50, H: null, A: null, C: null, raw: null, w: 0 }); continue; }
    let wins = 0, qs = 0;
    for (const r of c.rs) { if (r > 0) wins++; qs += 50 + 50 * Math.tanh(r * 10); }
    const H = 100 * wins / n, A = qs / n, C = 100 * n / c.entry, raw = 0.45 * H + 0.40 * A + 0.15 * C, w = n / (n + 10);
    Object.assign(c, { n, wins, H, A, C, raw, w, score: 50 + w * (raw - 50) });
  }
  const order = Object.keys(callers).sort((x, y) => callers[y].score - callers[x].score || (x.toLowerCase() < y.toLowerCase() ? -1 : 1));
  return { callers, order };
}
const close = (a, b, tol = 1e-9) => (a == null && b == null) || (a != null && b != null && Math.abs(a - b) <= tol);

function serve() {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
    const file = path.resolve(WEB, rel);
    if (!file.startsWith(WEB + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    const type = { '.html': 'text/html', '.json': 'application/json', '.jpg': 'image/jpeg', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml' }[path.extname(file)] || 'application/octet-stream';
    res.writeHead(200, { 'content-type': type });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(ok => server.listen(0, '127.0.0.1', () => ok(server)));
}

(async () => {
  const bundle = JSON.parse(fs.readFileSync(path.join(WEB, 'data', 'charts.json'), 'utf8'));
  const rt = bundle.ratings, mine = recompute(bundle);
  const fails = [], consoleErrors = [];
  const fail = m => fails.push(m);
  const n = { recomputed: 0, callsCompared: 0, sorts: 0, reloads: 0, callerPages: 0, callerFields: 0, callLinks: 0, positionChips: 0, overlayCards: 0, chartCards: 0, csp: 0 };

  // A
  if (rt.version !== 'quanty.rating.v1') fail(`version ${rt.version}`);
  if (JSON.stringify(rt.order) !== JSON.stringify(mine.order)) fail(`order ${rt.order} != recomputed ${mine.order}`);
  for (const [name, m] of Object.entries(mine.callers)) {
    const g = rt.callers[name];
    n.recomputed++;
    if (!g) { fail(`@${name}: missing from bundle.ratings`); continue; }
    if (!close(g.score, m.score) || g.scored !== m.n || g.calls_total !== m.total || g.with_entry !== m.entry) fail(`@${name}: bundle ${g.score}/${g.scored}/${g.calls_total}/${g.with_entry} != ${m.score}/${m.n}/${m.total}/${m.entry}`);
    if (m.n && (!close(g.components.hit, m.H) || !close(g.components.quality, m.A) || !close(g.components.clarity, m.C) || !close(g.raw, m.raw) || !close(g.weight, m.w))) fail(`@${name}: components differ`);
    const half = (Math.round(m.score * 10 + 1e-9) / 10).toFixed(1);
    if (g.display !== half) fail(`@${name}: display ${g.display} != ${half}`);
    const lbl = m.n < 10 ? 'small sample' : m.n < 30 ? 'limited sample' : null;
    if (g.label !== lbl) fail(`@${name}: label ${g.label} != ${lbl}`);
    m.calls.forEach((x, i) => {
      n.callsCompared++;
      const y = g.calls[i];
      if (!y || y.post_id !== x.id || y.asset !== x.asset || y.counted !== x.counted || !close(y.result, x.r) || !close(y.quality == null ? null : y.quality, x.q)) fail(`@${name}: call ${i} ${JSON.stringify(y)} != ${JSON.stringify(x)}`);
    });
  }

  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium', args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  try {
    const page = await browser.newPage();
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleErrors.push(`${page.url()} ${m.type()}: ${m.text()}`); });
    page.on('pageerror', e => consoleErrors.push(`${page.url()} pageerror: ${e.message}`));
    page.on('requestfailed', r => consoleErrors.push(`requestfailed: ${r.url()} ${r.failure() && r.failure().errorText}`));
    page.on('response', r => { if (r.status() >= 400) consoleErrors.push(`http ${r.status()}: ${r.url()}`); });
    await page.evaluateOnNewDocument(() => { window.__cspv = []; document.addEventListener('securitypolicyviolation', e => window.__cspv.push(e.violatedDirective + ' ' + e.blockedURI)); });
    await page.setViewport({ width: 1280, height: 1000 });
    const csp = async () => { const v = await page.evaluate(() => window.__cspv || []); n.csp += v.length; for (const x of v) fail(`${page.url()}: CSP ${x}`); };
    const ready = async () => { await page.waitForSelector('body[data-ready]', { timeout: 20000 }); };

    // B. leaderboard author table
    const authorRows = () => page.evaluate(() => [...document.querySelectorAll('#authors tbody tr')].map(tr => ({
      author: tr.dataset.author, score: JSON.parse(tr.querySelector('[data-field="score"]').dataset.raw || 'null'),
      text: tr.querySelector('[data-field="score"]').textContent, calls: JSON.parse(tr.querySelector('[data-field="calls"]').dataset.raw),
      hit: JSON.parse(tr.querySelector('[data-field="hit"]').dataset.raw), avg: JSON.parse(tr.querySelector('[data-field="avg"]').dataset.raw),
      link: tr.querySelector('a.caller-link').getAttribute('href') })));
    const expectOrder = (rows, asort) => rows.slice().sort((x, y) => {
      if (asort === 'author') return x.author.toLowerCase() < y.author.toLowerCase() ? -1 : 1;
      const k = r => asort === 'score' ? r.score : r[asort];
      const a = k(x), b = k(y);
      if (a == null && b != null) return 1;
      if (b == null && a != null) return -1;
      if (a !== b && a != null) return b - a;
      return x.author.toLowerCase() < y.author.toLowerCase() ? -1 : 1;
    }).map(r => r.author);
    for (const filters of ['', 'side=long', 'state=open&time=7d']) {
      await page.goto(base + (filters ? '?' + filters : ''), { waitUntil: 'networkidle0' }); await ready();
      let rows = await authorRows();
      if (!filters && JSON.stringify(rows.map(r => r.author)) !== JSON.stringify(rt.order)) fail(`leaderboard default author order ${rows.map(r => r.author)} != ${rt.order}`);
      for (const r of rows) {
        const g = rt.callers[r.author];
        if (!close(r.score, g.score, 0) || !r.text.startsWith(g.display)) fail(`leaderboard @${r.author}: score ${r.score} ${r.text}`);
        if (r.link !== callerPage(r.author)) fail(`leaderboard @${r.author}: link ${r.link}`);
      }
      for (const asort of ['calls', 'hit', 'avg', 'author', 'score']) {
        await page.click(`#authors th button[data-asort="${asort}"]`);
        n.sorts++;
        rows = await authorRows();
        const want = expectOrder(rows, asort);
        if (JSON.stringify(rows.map(r => r.author)) !== JSON.stringify(want)) fail(`?${filters} asort=${asort}: order ${rows.map(r => r.author)} != ${want}`);
        const q = new URLSearchParams(await page.evaluate(() => location.search));
        if ((q.get('asort') || 'score') !== asort) fail(`?${filters} asort=${asort}: url ${q}`);
        for (const [k, v] of new URLSearchParams(filters)) if (q.get(k) !== v) fail(`?${filters} asort=${asort}: filter ${k} lost from the url`);
        const pressed = await page.evaluate(() => [...document.querySelectorAll('#authors th[aria-sort]')].map(t => t.dataset.asort));
        if (JSON.stringify(pressed) !== JSON.stringify([asort])) fail(`asort=${asort}: aria-sort on ${pressed}`);
        await page.reload({ waitUntil: 'networkidle0' }); await ready();
        n.reloads++;
        const again = await authorRows();
        if (JSON.stringify(again.map(r => r.author)) !== JSON.stringify(want)) fail(`?${filters} asort=${asort}: after reload ${again.map(r => r.author)}`);
      }
      await csp();
    }
    await page.goto(base + '?asort=bogus', { waitUntil: 'networkidle0' }); await ready();
    if (await page.evaluate(() => location.search) !== '') fail('?asort=bogus was not rewritten to the default');
    if (shotDir) {
      fs.mkdirSync(shotDir, { recursive: true });
      await page.goto(base, { waitUntil: 'networkidle0' }); await ready();
      await (await page.$('section.authors')).screenshot({ path: path.join(shotDir, 'author_table_scores.png') });
    }

    // C. caller pages
    for (const [name, m] of Object.entries(mine.callers)) {
      const res = await page.goto(base + callerPage(name), { waitUntil: 'networkidle0' });
      if (res.status() !== 200) { fail(`caller page @${name}: HTTP ${res.status()}`); continue; }
      n.callerPages++;
      const got = await page.evaluate(() => ({
        f: Object.fromEntries([...document.querySelectorAll('[data-field]')].filter(x => !x.closest('tr')).map(x => [x.dataset.field, x.dataset.raw === undefined ? null : JSON.parse(x.dataset.raw)])),
        calls: [...document.querySelectorAll('tr[data-post-id]')].map(tr => ({ id: tr.dataset.postId, asset: tr.dataset.asset, counted: tr.dataset.counted === 'true',
          r: JSON.parse(tr.querySelector('[data-field="call_result"]').dataset.raw), q: JSON.parse(tr.querySelector('[data-field="call_quality"]').dataset.raw),
          href: tr.querySelector('a').getAttribute('href') })),
        title: document.title }));
      const chk = (k, v) => { n.callerFields++; if (!close(got.f[k], v)) fail(`caller page @${name}: ${k} ${got.f[k]} != ${v}`); };
      chk('score', m.score); chk('score_exact', m.score); chk('calls_total', m.total); chk('with_entry', m.entry); chk('scored', m.n);
      if (m.n) { chk('hit', m.H); chk('quality', m.A); chk('clarity', m.C); chk('raw', m.raw); chk('weight', m.w); chk('wins', m.wins); }
      if (got.f.caller !== name) fail(`caller page @${name}: shows ${got.f.caller}`);
      if (!got.title.includes(rt.callers[name].display)) fail(`caller page @${name}: title ${got.title}`);
      if (got.calls.length !== m.calls.length) fail(`caller page @${name}: ${got.calls.length} calls listed, ${m.calls.length} expected`);
      m.calls.forEach((x, i) => {
        const y = got.calls[i] || {};
        n.callerFields++;
        if (y.id !== x.id || y.asset !== x.asset || y.counted !== x.counted || !close(y.r, x.r) || !close(y.q, x.q)) fail(`caller page @${name}: call ${i} ${JSON.stringify(y)} != ${JSON.stringify(x)}`);
        if (y.href !== `pos-${slug(x.id, x.asset)}.html`) fail(`caller page @${name}: call ${i} link ${y.href}`);
      });
      for (const href of [...new Set(got.calls.map(c => c.href))]) {
        const r = await page.goto(base + href, { waitUntil: 'domcontentloaded' });
        n.callLinks++;
        if (r.status() !== 200) fail(`caller page @${name}: ${href} HTTP ${r.status()}`);
      }
      if (shotDir && name === 'BobLoukas') {
        await page.goto(base + callerPage(name), { waitUntil: 'networkidle0' });
        await page.setViewport({ width: 900, height: 900 });
        await page.screenshot({ path: path.join(shotDir, 'caller_bobloukas_breakdown.png'), fullPage: true });
        await page.setViewport({ width: 1280, height: 1000 });
      }
      await csp();
    }

    // D. position pages: the score chip, and one overlay card per page
    for (const a of bundle.assets) for (const p of a.posts) {
      await page.goto(`${base}pos-${slug(p.post.id, a.name)}.html`, { waitUntil: 'networkidle0' }); await ready();
      const g = rt.callers[p.post.author];
      const chip = await page.$eval('#app [data-field="caller_score"]', x => ({ raw: JSON.parse(x.dataset.raw), href: x.getAttribute('href'), text: x.textContent })).catch(() => null);
      n.positionChips++;
      if (!chip || !close(chip.raw, g.score, 0) || chip.href !== callerPage(p.post.author) || !chip.text.includes(g.display)) fail(`position ${a.name} ${p.post.id}: chip ${JSON.stringify(chip)}`);
      const other = await page.$('.call-bubble:not([hidden])');
      if (other) {
        await other.click();
        const card = await page.evaluate(() => { const c = document.getElementById('call-card'), s = c.querySelector('[data-field="card_score"]'), au = c.querySelector('[data-field="card_author"]');
          return { author: au && au.textContent.slice(1), raw: s && JSON.parse(s.dataset.raw), href: s && s.getAttribute('href') }; });
        n.overlayCards++;
        const cg = rt.callers[card.author];
        if (!cg || !close(card.raw, cg.score, 0) || card.href !== callerPage(card.author)) fail(`position ${a.name} ${p.post.id}: overlay card ${JSON.stringify(card)}`);
      }
      if (shotDir && p.post.id === '2116199680157647216') await (await page.$('section.post')).screenshot({ path: path.join(shotDir, 'position_score_chip.png') });
      await csp();
    }

    // E. chart view cards
    await page.goto(base + 'chart.html', { waitUntil: 'networkidle0' }); await ready();
    for (const a of bundle.assets) {
      await page.select('#asset', a.name);
      for (const p of a.posts) {
        if (!p.entry) continue;
        await (await page.$(`.bubble[data-post-id="${p.post.id}"] circle.mark`)).click();
        const s = await page.$eval('#card [data-field="caller_score"]', x => ({ raw: JSON.parse(x.dataset.raw), href: x.getAttribute('href') })).catch(() => null);
        n.chartCards++;
        const g = rt.callers[p.post.author];
        if (!s || !close(s.raw, g.score, 0) || s.href !== callerPage(p.post.author)) fail(`chart ${a.name} ${p.post.id}: card score ${JSON.stringify(s)}`);
      }
    }
    await csp();
  } finally {
    await browser.close();
    if (server) server.close();
  }
  for (const e of consoleErrors) fail(`console: ${e}`);
  console.log(`page ${base}`);
  for (const name of mine.order) {
    const m = mine.callers[name];
    console.log(`  @${name}: recomputed ${m.score.toFixed(6)} (bundle ${rt.callers[name].score.toFixed(6)}, shown ${rt.callers[name].display}) · n ${m.n} · H ${m.H == null ? '-' : m.H.toFixed(4)} A ${m.A == null ? '-' : m.A.toFixed(4)} C ${m.C == null ? '-' : m.C.toFixed(4)} raw ${m.raw == null ? '-' : m.raw.toFixed(4)} w ${m.w.toFixed(4)}`);
  }
  console.log(`callers recomputed ${n.recomputed}, calls compared ${n.callsCompared}, author-table sorts ${n.sorts} (+${n.reloads} reloads), caller pages ${n.callerPages} (${n.callerFields} fields, ${n.callLinks} call links), ` +
    `position chips ${n.positionChips}, overlay cards ${n.overlayCards}, chart cards ${n.chartCards}, CSP violations ${n.csp}, console errors ${consoleErrors.length}`);
  for (const f of fails.slice(0, 60)) console.log(' -', f);
  console.log(fails.length ? `FAIL (${fails.length})` : 'ALL PASS');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
