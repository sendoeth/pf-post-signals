// Step 7 position-page test: open web/position.html for every drawn post (default interval and 1h),
// check the recap against the record file on disk, best % since post against a recomputation from
// the record's series, the avatar bubble against the chart's own coordinate of the entry candle,
// the entry candle's open against the record entry price, and zero console errors. Also checks the
// main page links each card and table row to the right position page.
// usage: node tests/position_test.js [--url https://.../web/] [--screenshots DIR]
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
const HORIZONS = ['1', '7', '30'];
// plain status wording, mirrored from web/assets/common.js
const statusLabel = p => p.status === 'resolved' ? 'all horizons in' : p.status === 'pending' ? 'no price yet' : p.status === 'no_entry' ? 'no price at post time'
  : (h => h.length ? h.map(x => x + 'd').join(', ') + ' pending' : p.status)(['1', '7', '30'].filter(x => p.unresolved && p.unresolved[x]));
const slug = (id, asset) => `${id.replace(/[^A-Za-z0-9_-]/g, '-')}_${asset.replace(/[^A-Za-z0-9_-]/g, '-')}`;


const pct = x => (x > 0 ? '+' : x < 0 ? '-' : '') + (Math.abs(x) * 100).toFixed(2) + '%';
const price = p => p.toLocaleString('en-US', { maximumFractionDigits: 8 });
const time = iso => iso.slice(0, 10) + ' ' + iso.slice(11, 16) + ' UTC';
const ZERO = /(^|[^\d.])[+-]?0(\.0+)?%/;

function bestOf(rec) {
  if (!rec.entry) return null;
  const p0 = rec.entry.price, side = rec.side;
  let top = null;
  for (const [at, pr] of rec.series) {
    const score = side ? side * (pr / p0 - 1) : pr;
    if (!top || score > top[0]) top = [score, at, pr];
  }
  const best = { at: top[1], price: top[2], move: top[2] / p0 - 1, basis: side ? 'call side' : 'highest price' };
  if (side) best.for_call = side * (top[2] / p0 - 1);
  return best;
}

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
  // provider revisions logged by refresh.py: the record keeps the frozen entry, the candle shows the
  // provider's current open. Only exactly that logged (bar, fetched) pair is accepted.
  const logPath = path.join(ROOT, 'data', 'refresh_log.json');
  const revised = new Set(fs.existsSync(logPath) ? JSON.parse(fs.readFileSync(logPath, 'utf8')).revisions
    .filter(r => r.what === 'entry').map(r => `${r.bar}|${r.fetched}`) : []);
  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  const fails = [], consoleErrors = [];
  const fail = m => fails.push(m);
  let pages = 0, fields = 0, placements = 0, unresolved = 0;
  try {
    const page = await browser.newPage();
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleErrors.push(`${page.url()} ${m.type()}: ${m.text()}`); });
    page.on('pageerror', e => consoleErrors.push(`${page.url()} pageerror: ${e.message}`));
    page.on('requestfailed', r => consoleErrors.push(`requestfailed: ${r.url()}`));
    page.on('response', r => { if (r.status() >= 400) consoleErrors.push(`http ${r.status()}: ${r.url()}`); });
    await page.setViewport({ width: 1280, height: 1000 });

    // main page: every card and table row links to its position page
    await page.goto(base + 'chart.html', { waitUntil: 'networkidle0' });
    await page.waitForSelector('body[data-ready="1"]');
    for (const a of bundle.assets) {
      await page.select('#asset', a.name);
      for (const p of a.posts) {
        const want = `pos-${slug(p.post.id, a.name)}.html`;
        const row = await page.$eval(`#posts a.row-link[data-post-id="${p.post.id}"]`, n => n.getAttribute('href')).catch(() => null);
        if (row !== want) fail(`main ${a.name} ${p.post.id}: table link ${row} != ${want}`);
        if (!p.entry) continue;
        await (await page.$(`.bubble[data-post-id="${p.post.id}"] circle.mark`)).click();
        const card = await page.$eval('#card a.open-position', n => n.getAttribute('href')).catch(() => null);
        if (card !== want) fail(`main ${a.name} ${p.post.id}: card link ${card} != ${want}`);
      }
    }

    for (const a of bundle.assets) for (const p of a.posts) for (const interval of [null, '1h']) {
      const blob = fs.readFileSync(path.join(ROOT, p.record_file));
      if (crypto.createHash('sha256').update(blob).digest('hex') !== p.record_sha256) fail(`${p.record_file}: sha256 differs from bundle`);
      const rec = JSON.parse(blob);
      // default interval: the prerendered static page (as linked from the leaderboard); 1h: the query form
      const url = interval ? `${base}position.html?post=${encodeURIComponent(p.post.id)}&asset=${encodeURIComponent(a.name)}&interval=${interval}` : `${base}pos-${slug(p.post.id, a.name)}.html`;
      await page.goto(url, { waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready]', { timeout: 20000 });
      const tag = `${a.name} ${p.post.id}${interval ? ' @1h' : ''}`;
      if (await page.$eval('body', b => b.dataset.ready) !== '1') { fail(`${tag}: page did not load`); continue; }
      pages++;
      const got = await page.evaluate(() => {
        const app = document.getElementById('app'), pos = window.__position;
        const f = Object.fromEntries([...app.querySelectorAll('[data-field]')].map(n => [n.getAttribute('data-field'),
          { text: n.textContent, raw: n.hasAttribute('data-raw') ? JSON.parse(n.getAttribute('data-raw')) : undefined, href: n.getAttribute('href') }]));
        const step = pos.step(), entry = pos.post.entry;
        let place = null, candle = null;
        if (entry) {
          const t = step === 3600 ? Date.parse(entry.at) / 1000 : Math.floor(Date.parse(entry.at) / 1000 / step) * step;
          const box = document.getElementById('chart-box').getBoundingClientRect();
          const b = document.getElementById('entry-bubble'), r = b.getBoundingClientRect();
          place = { x: pos.chart.timeScale().timeToCoordinate(t), y: pos.series.priceToCoordinate(entry.price),
                    cx: r.left + r.width / 2 - box.left, cy: r.top + r.height / 2 - box.top, hidden: b.hidden,
                    avatar: b.getAttribute('data-avatar'), img: b.querySelector('img') ? b.querySelector('img').naturalWidth : null };
          const c = pos.series.data().find(d => d.time === t);
          candle = c ? { time: c.time, open: c.open } : null;
        }
        return { id: app.dataset.postId, asset: app.dataset.asset, interval: pos.interval, fields: f, place, candle };
      });
      const eq = (name, text, raw) => {
        fields++;
        const f = got.fields[name];
        if (!f) return fail(`${tag}: no ${name}`);
        if (f.text !== text) fail(`${tag}: ${name} shows ${JSON.stringify(f.text)}, record gives ${JSON.stringify(text)}`);
        if (raw !== undefined && JSON.stringify(f.raw) !== JSON.stringify(raw)) fail(`${tag}: ${name} raw ${JSON.stringify(f.raw)} != ${JSON.stringify(raw)}`);
      };
      if (got.id !== rec.post.id || got.asset !== rec.asset.name) fail(`${tag}: page shows ${got.id} ${got.asset}`);
      const side = rec.side === 1 ? 'long' : rec.side === -1 ? 'short' : null;
      eq('prices_as_of', bundle.prices_as_of ? 'Prices as of ' + time(bundle.prices_as_of) + ' (daily refresh)' : 'Prices not refreshed yet', bundle.prices_as_of || null);
      eq('author', '@' + rec.post.author);
      eq('posted_at', time(rec.post.posted_at), rec.post.posted_at);
      eq('text', rec.post.text || 'Post text not saved: open it on X.');
      eq('asset', `${rec.asset.name} (${rec.asset.source}:${rec.asset.symbol})`);
      eq('side', side || 'no side stated', rec.side ?? null);
      eq('side_badge', side ? side.toUpperCase() : 'NO SIDE');
      eq('status', statusLabel(rec), rec.status);
      eq('entry', rec.entry ? `${price(rec.entry.price)} @ ${time(rec.entry.at)}` : 'no entry bar', rec.entry);
      eq('latest', rec.latest ? `${price(rec.latest.price)} @ ${time(rec.latest.at)}` : 'no bar yet', rec.latest);
      eq('change_since_post', rec.change_since_post == null ? 'unresolved' : pct(rec.change_since_post), rec.change_since_post);
      const best = bestOf(rec);
      eq('best', best ? `${pct(side ? best.for_call : best.move)} at ${price(best.price)} @ ${time(best.at)}` : 'no entry bar', best);
      for (const [prefix, vals] of [['move_', rec.moves]].concat(rec.signed_returns ? [['signed_', rec.signed_returns]] : [])) for (const h of HORIZONS) {
        const v = vals[h];
        eq(prefix + h, v == null ? 'unresolved · ' + rec.unresolved[h] : pct(v), v);
        if (v == null) { unresolved++; if (ZERO.test(got.fields[prefix + h].text)) fail(`${tag}: unresolved ${prefix}${h} shows a zero`); }
      }
      if (!/^\d+(d \d+h|h \d+m|m) ago$/.test((got.fields.age || {}).text || '')) fail(`${tag}: age ${JSON.stringify((got.fields.age || {}).text)}`);
      fields++;
      if (!got.fields.url || got.fields.url.href !== rec.post.url) fail(`${tag}: x link ${got.fields.url && got.fields.url.href}`);
      if (got.fields.url && got.fields.url.text !== (rec.post.source === 'corbanu' ? 'read the article' : 'open on X')) fail(`${tag}: source link text ${got.fields.url.text}`);
      for (const [k, v] of [['stand_in', rec.asset.stand_in], ['adjustments', rec.asset.adjustments], ['trade', rec.trade], ['asset_choice', rec.asset_choice]]) {
        fields++;
        if (v === undefined) { if (got.fields[k]) fail(`${tag}: ${k} shown but the record has none`); continue; }
        if (!got.fields[k] || JSON.stringify(got.fields[k].raw) !== JSON.stringify(v)) fail(`${tag}: ${k} raw ${got.fields[k] && JSON.stringify(got.fields[k].raw)} != record`);
      }
      if (rec.entry) {
        placements++;
        const pl = got.place;
        if (pl.hidden || pl.x == null || pl.y == null) fail(`${tag}: entry bubble hidden or entry candle off-screen`);
        else if (Math.abs(pl.cx - pl.x) > 1.5 || Math.abs(pl.cy - pl.y) > 1.5) fail(`${tag}: bubble at ${pl.cx.toFixed(1)},${pl.cy.toFixed(1)}, entry candle at ${pl.x.toFixed(1)},${pl.y.toFixed(1)}`);
        if (pl.avatar === 'image' && !(pl.img > 0)) fail(`${tag}: avatar image did not load`);
        if (!got.candle) fail(`${tag}: no candle at the entry bar`);
        else if (got.interval === '1h' && got.candle.open !== rec.entry.price && !revised.has(`${rec.entry.at}|${got.candle.open}`)) fail(`${tag}: entry candle open ${got.candle.open} != record ${rec.entry.price}`);
      }
    }

    if (shotDir) {
      fs.mkdirSync(shotDir, { recursive: true });
      const silver = bundle.assets.find(a => a.name === 'SILVER').posts[0];
      await page.goto(`${base}position.html?post=${silver.post.id}&asset=SILVER`, { waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready="1"]');
      await page.screenshot({ path: path.join(shotDir, 'position_desktop.png'), fullPage: true });
      const btc = bundle.assets.find(a => a.name === 'BTC').posts.slice(-1)[0];
      await page.goto(`${base}position.html?post=${btc.post.id}&asset=BTC`, { waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready="1"]');
      await page.screenshot({ path: path.join(shotDir, 'position_btc_desktop.png'), fullPage: true });
      await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
      await page.goto(`${base}position.html?post=${silver.post.id}&asset=SILVER`, { waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready="1"]');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 0) fail(`phone: page scrolls horizontally by ${overflow}px`);
      await page.screenshot({ path: path.join(shotDir, 'position_phone.png'), fullPage: true });
    }
  } finally {
    await browser.close();
    if (server) server.close();
  }
  for (const e of consoleErrors) fail(`console: ${e}`);
  console.log(`page ${base}`);
  console.log(`position pages opened ${pages} (${pages / 2} posts x default + 1h), recap fields checked ${fields}, ` +
    `entry-bubble placements checked ${placements}, unresolved cells ${unresolved}, console errors ${consoleErrors.length}`);
  for (const f of fails) console.log(' -', f);
  console.log(fails.length ? `FAIL (${fails.length})` : 'ALL PASS');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
