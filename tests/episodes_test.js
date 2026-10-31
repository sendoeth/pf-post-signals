// Episodes in the browser: every episode thesis is a bubble on its asset's chart (solid = call,
// dashed = thought) inside the plot, clicking it opens a card with every timestamped moment, the
// toggle hides them, episode-only assets (oil, the dollar, the AI trade) get their own chart, the
// chart still works without data/episodes.json, and the static episode pages load cleanly on
// desktop and phone widths.
// Run: LD_LIBRARY_PATH=/home/postfiat/chromium-libs/lib node tests/episodes_test.js
const fs = require('fs');
const path = require('path');
const http = require('http');
const os = require('os');
const puppeteer = require('/home/postfiat/node_modules/puppeteer');

const ROOT = path.join(__dirname, '..');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg' };
const failures = [];
const fail = m => { failures.push(m); console.log('  FAIL ' + m); };

function serve(dir) {
  return new Promise(ok => {
    const s = http.createServer((req, res) => {
      const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
      const file = path.resolve(dir, rel);
      if (!file.startsWith(dir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
      fs.createReadStream(file).pipe(res);
    });
    s.listen(0, '127.0.0.1', () => ok(s));
  });
}

(async () => {
  const web = path.join(ROOT, 'web');
  const eb = JSON.parse(fs.readFileSync(path.join(web, 'data', 'episodes.json'), 'utf8'));
  const charts = JSON.parse(fs.readFileSync(path.join(web, 'data', 'charts.json'), 'utf8'));
  const MAP = { GOLD: 'GOLD', SILVER: 'SILVER', COPPER: 'COPPER', BTC: 'BTC', ETH: 'ETH', STOCKS: 'STOCKS', OIL: 'OIL' };
  const want = {};
  for (const ep of eb.episodes) for (const t of ep.theses) (want[MAP[t.asset] || t.asset] = want[MAP[t.asset] || t.asset] || []).push({ ep, t });

  const srv = await serve(web), base = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium', args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  let checked = 0, cards = 0;
  for (const width of [1180, 390]) {
    for (const [asset, items] of Object.entries(want)) {
      const page = await browser.newPage();
      await page.setViewport({ width, height: 1000 });
      const errs = [];
      page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
      page.on('pageerror', e => errs.push(String(e)));
      await page.goto(`${base}chart.html?asset=${asset}`, { waitUntil: 'networkidle0' });
      await page.waitForFunction(() => document.body.dataset.ready === '1');
      const sel = await page.$eval('#asset', s => s.value);
      if (sel !== asset) fail(`${asset}@${width}: picker shows ${sel}`);
      const got = await page.$$eval('.ep-bubble', ns => ns.map(n => {
        const c = n.querySelector('.ep-ring'), vb = n.ownerSVGElement.viewBox.baseVal;
        return { cls: n.getAttribute('class'), slug: n.getAttribute('data-episode'), x: +c.getAttribute('cx'), y: +c.getAttribute('cy'), w: vb.width, h: vb.height };
      }));
      if (got.length !== items.length) fail(`${asset}@${width}: ${got.length} episode bubbles, want ${items.length}`);
      for (const g of got) {
        const it = items.find(i => i.ep.slug === g.slug);
        if (!it || g.cls !== `ep-bubble ${it.t.kind} ${it.t.direction}`) fail(`${asset}@${width}: bubble class ${g.cls}`);
        if (!(g.x > 0 && g.x < g.w && g.y > 0 && g.y < g.h)) fail(`${asset}@${width}: bubble outside the plot (${g.x},${g.y})`);
        checked++;
      }
      const posts = (charts.assets.find(a => a.name === asset) || { posts: [] }).posts.filter(p => p.entry).length;
      const nPosts = await page.$$eval('.bubble', b => b.length);
      if (nPosts !== posts) fail(`${asset}@${width}: ${nPosts} post bubbles, want ${posts}`);
      // click the first episode bubble (on its ring, not the stem)
      await page.click('.ep-bubble .ep-ring');
      const card = await page.$eval('#card', c => ({ slug: c.getAttribute('data-episode'), moments: c.querySelectorAll('.ep-moments li').length,
        link: (c.querySelector('[data-field="episode_url"]') || {}).getAttribute ? c.querySelector('[data-field="episode_url"]').getAttribute('href') : null }));
      const it = items[0];
      if (card.slug !== it.ep.slug || card.moments !== it.t.moments.length) fail(`${asset}@${width}: card ${JSON.stringify(card)}, want ${it.t.moments.length} moments`);
      if (card.link !== `episode-${it.ep.slug}.html#t-${it.t.asset.toLowerCase()}`) fail(`${asset}@${width}: card link ${card.link}`);
      const sel2 = await page.$$eval('.ep-bubble.selected', n => n.length);
      if (sel2 !== 1) fail(`${asset}@${width}: ${sel2} selected episode bubbles`);
      cards++;
      // the table lists the thesis too, and the toggle hides both
      const rows = await page.$$eval('#posts tr.ep-row', r => r.length);
      if (rows !== items.length) fail(`${asset}@${width}: ${rows} episode rows in the table`);
      await page.click('#show-ep');
      const after = await page.$$eval('.ep-bubble, #posts tr.ep-row', n => n.length);
      if (after !== 0) fail(`${asset}@${width}: toggle off left ${after} episode marks`);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (over > 0) fail(`${asset}@${width}: horizontal overflow ${over}px`);
      if (errs.length) fail(`${asset}@${width}: console errors ${errs.join(' | ')}`);
      await page.close();
    }
  }

  // without data/episodes.json the chart is exactly the posts chart
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'quanty-noep-'));
  fs.cpSync(web, tmp, { recursive: true });
  fs.rmSync(path.join(tmp, 'data', 'episodes.json'));
  const srv2 = await serve(tmp);
  {
    const page = await browser.newPage();
    const errs = [];
    page.on('pageerror', e => errs.push(String(e)));
    await page.goto(`http://127.0.0.1:${srv2.address().port}/chart.html?asset=GOLD`, { waitUntil: 'networkidle0' });
    await page.waitForFunction(() => document.body.dataset.ready === '1');
    const r = await page.evaluate(() => ({ ep: document.querySelectorAll('.ep-bubble').length, opts: [...document.querySelectorAll('#asset option')].length,
      tog: document.querySelector('.ep-toggle').hidden }));
    if (r.ep !== 0 || r.opts !== charts.assets.length || !r.tog || errs.length) fail(`no episodes.json: ${JSON.stringify(r)} ${errs.join(' | ')}`);
    await page.close();
  }
  srv2.close();
  fs.rmSync(tmp, { recursive: true, force: true });

  // the static pages
  let pages = 0;
  for (const name of ['episodes.html', ...eb.episodes.map(e => `episode-${e.slug}.html`)]) {
    for (const width of [1100, 390]) {
      const page = await browser.newPage();
      await page.setViewport({ width, height: 900 });
      await page.setJavaScriptEnabled(false);
      const errs = [];
      page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
      const res = await page.goto(base + name, { waitUntil: 'networkidle0' });
      const r = await page.evaluate(() => ({ nfa: document.querySelectorAll('#nfa').length, over: document.documentElement.scrollWidth - window.innerWidth,
        moments: document.querySelectorAll('.moment').length, theses: document.querySelectorAll('.thesis').length }));
      if (res.status() !== 200 || r.nfa !== 1 || r.over > 0 || errs.length) fail(`${name}@${width}: ${JSON.stringify(r)} ${errs.join(' | ')}`);
      if (name.startsWith('episode-')) {
        const ep = eb.episodes.find(e => name === `episode-${e.slug}.html`);
        const nm = ep.theses.reduce((n, t) => n + t.moments.length, 0);
        if (r.moments !== nm || r.theses !== ep.theses.length) fail(`${name}: ${r.theses} theses / ${r.moments} moments, want ${ep.theses.length} / ${nm}`);
      }
      pages++;
      await page.close();
    }
  }
  await browser.close();
  srv.close();
  console.log(`episode bubbles checked ${checked} (${Object.keys(want).length} assets x 2 widths), cards opened ${cards}, static page loads ${pages} (no JS)`);
  console.log(failures.length ? `FAIL (${failures.length})` : 'ALL PASS');
  process.exit(failures.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
