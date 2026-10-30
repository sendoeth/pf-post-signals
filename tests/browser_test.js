// Step 5 browser test: load web/index.html in headless Chromium, click every bubble of every asset,
// and check the opened card against the record file on disk. Fails on any mismatch or console error.
// usage: node tests/browser_test.js [--screenshots DIR] [--url https://.../web/] [--expect ID,ID]
//   default: serve web/ on 127.0.0.1. --expect: these posts must be drawn as bubbles; with
//   --screenshots, each one's card is captured as post_<id>.png
const fs = require('fs');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const puppeteer = require('/home/postfiat/node_modules/puppeteer');

const ROOT = path.resolve(__dirname, '..');
const WEB = path.join(ROOT, 'web');
const liveUrl = process.argv.includes('--url') ? process.argv[process.argv.indexOf('--url') + 1] : null;
const expect = process.argv.includes('--expect') ? process.argv[process.argv.indexOf('--expect') + 1].split(',') : [];
const shotDir = process.argv.includes('--screenshots') ? path.resolve(process.argv[process.argv.indexOf('--screenshots') + 1]) : null;
const HORIZONS = ['1', '7', '30'];

// Independent copies of the page's formatting rules.
const pct = x => (x > 0 ? '+' : x < 0 ? '-' : '') + (Math.abs(x) * 100).toFixed(2) + '%';
const price = p => p.toLocaleString('en-US', { maximumFractionDigits: 8 });
const time = iso => iso.slice(0, 10) + ' ' + iso.slice(11, 16) + ' UTC';
const ZERO = /(^|[^\d.])[+-]?0(\.0+)?%/;

function serve() {
  const types = { '.html': 'text/html', '.json': 'application/json', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg' };
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
    const file = path.resolve(WEB, rel);
    if (!file.startsWith(WEB + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404); res.end(); return;
    }
    res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(ok => server.listen(0, '127.0.0.1', () => ok(server)));
}

(async () => {
  const bundle = JSON.parse(fs.readFileSync(path.join(WEB, 'data', 'charts.json'), 'utf8'));
  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  const fails = [], consoleErrors = [];
  let cards = 0, fieldsChecked = 0, unresolvedChecked = 0, stacked = 0;
  const fail = m => fails.push(m);
  try {
    const page = await browser.newPage();
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleErrors.push(`${m.type()}: ${m.text()}`); });
    page.on('pageerror', e => consoleErrors.push(`pageerror: ${e.message}`));
    page.on('requestfailed', r => consoleErrors.push(`requestfailed: ${r.url()}`));
    page.on('response', r => { if (r.status() >= 400) consoleErrors.push(`http ${r.status()}: ${r.url()}`); });
    await page.setViewport({ width: 1280, height: 900 });
    await page.goto(base, { waitUntil: 'networkidle0' });
    await page.waitForSelector('body[data-ready="1"]', { timeout: 15000 });

    for (const asset of bundle.assets) {
      await page.select('#asset', asset.name);
      const ids = await page.$$eval('.bubble', ns => ns.map(n => [n.getAttribute('data-post-id'), n.getAttribute('data-asset')]));
      const want = asset.posts.filter(p => p.entry).map(p => p.post.id).sort();
      if (JSON.stringify(ids.map(i => i[0]).sort()) !== JSON.stringify(want)) fail(`${asset.name}: bubbles ${ids} != posts with an entry ${want}`);
      if (ids.some(i => i[1] !== asset.name)) fail(`${asset.name}: bubble from another asset`);

      // every bubble needs its own hit area: no two hit circles in the asset may overlap
      const hits = await page.$$eval('.bubble', ns => ns.map(n => { const r = n.querySelector('circle.hit').getBoundingClientRect();
        return [n.getAttribute('data-post-id'), r.x + r.width / 2, r.y + r.height / 2, r.width / 2]; }));
      for (let i = 0; i < hits.length; i++) for (let j = i + 1; j < hits.length; j++) {
        const [a, b] = [hits[i], hits[j]];
        if (Math.hypot(a[1] - b[1], a[2] - b[2]) < a[3] + b[3]) fail(`${asset.name}: hit areas of ${a[0]} and ${b[0]} overlap`);
      }
      const groups = {};
      for (const p of asset.posts.filter(p => p.entry)) (groups[p.entry.at] = groups[p.entry.at] || []).push(p.post.id);
      for (const g of Object.values(groups)) if (g.length > 1) stacked += g.length;

      for (const [id] of ids) {
        const p = asset.posts.find(x => x.post.id === id);
        const blob = fs.readFileSync(path.join(ROOT, p.record_file));
        if (crypto.createHash('sha256').update(blob).digest('hex') !== p.record_sha256) fail(`${p.record_file}: sha256 differs from bundle`);
        const rec = JSON.parse(blob);
        const h = await page.$(`.bubble[data-post-id="${id}"] circle.mark`);
        await h.click();
        const got = await page.$eval('#card', c => ({
          id: c.getAttribute('data-post-id'), asset: c.getAttribute('data-asset'),
          fields: Object.fromEntries([...c.querySelectorAll('[data-field]')].map(n => [n.getAttribute('data-field'),
            { text: n.textContent, raw: n.hasAttribute('data-raw') ? JSON.parse(n.getAttribute('data-raw')) : undefined, href: n.getAttribute('href') }])),
        }));
        cards++;
        const tag = `${asset.name} ${id}`;
        const eq = (name, text, raw) => {
          fieldsChecked++;
          const f = got.fields[name];
          if (!f) return fail(`${tag}: card has no ${name}`);
          if (f.text !== text) fail(`${tag}: ${name} shows ${JSON.stringify(f.text)}, record gives ${JSON.stringify(text)}`);
          if (raw !== undefined && JSON.stringify(f.raw) !== JSON.stringify(raw)) fail(`${tag}: ${name} raw ${JSON.stringify(f.raw)} != record ${JSON.stringify(raw)}`);
        };
        if (got.id !== rec.post.id || got.asset !== rec.asset.name) fail(`${tag}: card opened for ${got.id} ${got.asset}`);
        eq('posted_at', 'Posted ' + time(rec.post.posted_at), rec.post.posted_at);
        eq('text', rec.post.text || 'Post text not saved: open it on X.');
        eq('asset', `${rec.asset.name} (${rec.asset.source}:${rec.asset.symbol})`);
        eq('side', rec.side === 1 ? 'long' : rec.side === -1 ? 'short' : 'not given', rec.side ?? null);
        eq('status', rec.status, rec.status);
        eq('entry', rec.entry ? `${price(rec.entry.price)} @ ${time(rec.entry.at)}` : 'no entry bar', rec.entry);
        eq('latest', rec.latest ? `${price(rec.latest.price)} @ ${time(rec.latest.at)}` : 'no bar yet', rec.latest);
        eq('change_since_post', rec.change_since_post == null ? 'unresolved' : pct(rec.change_since_post), rec.change_since_post);
        const groupsToCheck = [['move_', rec.moves]].concat(rec.signed_returns ? [['signed_', rec.signed_returns]] : []);
        for (const [prefix, vals] of groupsToCheck) for (const hz of HORIZONS) {
          const v = vals[hz];
          eq(prefix + hz, v == null ? 'unresolved · ' + rec.unresolved[hz] : pct(v), v);
          if (v == null) {
            unresolvedChecked++;
            const t = got.fields[prefix + hz] && got.fields[prefix + hz].text;
            if (!t || ZERO.test(t) || !t.startsWith('unresolved')) fail(`${tag}: unresolved ${prefix}${hz} rendered as ${JSON.stringify(t)}`);
          }
        }
        if (!rec.signed_returns && Object.keys(got.fields).some(k => k.startsWith('signed_'))) fail(`${tag}: signed returns shown without a side`);
        fieldsChecked++;
        if (!got.fields.url || got.fields.url.href !== rec.post.url) fail(`${tag}: link ${got.fields.url && got.fields.url.href} != ${rec.post.url}`);
      }
    }

    for (const id of expect) {
      const asset = bundle.assets.find(a => a.posts.some(p => p.post.id === id));
      if (!asset) { fail(`expected post ${id} is not in the bundle`); continue; }
      await page.setViewport({ width: 1280, height: 900 });
      await page.select('#asset', asset.name);
      const mark = await page.$(`.bubble[data-post-id="${id}"] circle.mark`);
      if (!mark) { fail(`expected post ${id} has no bubble on ${asset.name}`); continue; }
      await mark.click();
      const opened = await page.$eval('#card', c => c.getAttribute('data-post-id'));
      if (opened !== id) fail(`expected post ${id}: bubble opened ${opened}`);
      console.log(`expected post ${id}: bubble on ${asset.name}, card opens ${opened === id ? 'OK' : 'WRONG'}`);
      if (shotDir) {
        fs.mkdirSync(shotDir, { recursive: true });
        await page.screenshot({ path: path.join(shotDir, `post_${id}.png`), fullPage: true });
      }
    }

    if (shotDir && !expect.length) {
      fs.mkdirSync(shotDir, { recursive: true });
      const sameHour = bundle.assets.find(a => a.name === 'BTC');
      await page.select('#asset', 'BTC');
      const g = {};
      for (const p of sameHour.posts) (g[p.entry.at] = g[p.entry.at] || []).push(p.post.id);
      const pick = Object.values(g).find(x => x.length > 1) || [sameHour.posts[0].post.id];
      await (await page.$(`.bubble[data-post-id="${pick[pick.length - 1]}"] circle.mark`)).click();
      await page.screenshot({ path: path.join(shotDir, 'desktop.png'), fullPage: true });
      await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
      await page.reload({ waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready="1"]');
      await page.select('#asset', 'SILVER');
      const silver = bundle.assets.find(a => a.name === 'SILVER');
      const last = silver.posts[silver.posts.length - 1].post.id;
      await (await page.$(`.bubble[data-post-id="${last}"] circle.mark`)).tap();
      const cardId = await page.$eval('#card', c => c.getAttribute('data-post-id'));
      if (cardId !== last) fail(`phone: tap opened ${cardId}, expected ${last}`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 0) fail(`phone: page scrolls horizontally by ${overflow}px`);
      await page.screenshot({ path: path.join(shotDir, 'phone.png'), fullPage: true });
    }
  } finally {
    await browser.close();
    if (server) server.close();
  }
  for (const e of consoleErrors) fail(`console: ${e}`);
  console.log(`page ${base}`);
  console.log(`assets ${bundle.assets.length}, cards opened ${cards}, card fields checked ${fieldsChecked}, ` +
    `unresolved cells checked ${unresolvedChecked}, same-hour bubbles ${stacked}, console errors ${consoleErrors.length}`);
  for (const f of fails) console.log(' -', f);
  console.log(fails.length ? `FAIL (${fails.length})` : 'ALL PASS');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
