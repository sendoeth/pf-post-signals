// Step 30 browser test: after the page scripts have rendered, every tagged asset still shows its sector tag on the
// leaderboard rows (web/assets/board.js) and keeps the prerendered sector section on its position pages
// (web/assets/position.js replaces the prerendered content); caller pages and web/sectors.html are static.
// No console errors. usage: node tests/sectors_test.js [--url https://.../web/]
const fs = require('fs');
const path = require('path');
const http = require('http');
const puppeteer = require('/home/postfiat/node_modules/puppeteer');

const ROOT = path.resolve(__dirname, '..');
const WEB = path.join(ROOT, 'web');
const arg = k => (process.argv.includes(k) ? process.argv[process.argv.indexOf(k) + 1] : null);
const liveUrl = arg('--url');
const slug = (id, asset) => `${id.replace(/[^A-Za-z0-9_-]/g, '-')}_${asset.replace(/[^A-Za-z0-9_-]/g, '-')}`;

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
  const getJson = async (base, rel) => (liveUrl ? (await fetch(base + rel)).json() : JSON.parse(fs.readFileSync(path.join(WEB, rel), 'utf8')));
  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  const sec = await getJson(base, 'data/sectors.json');
  const tagged = Object.keys(sec.by_asset || {});
  const br = await puppeteer.launch({ executablePath: '/snap/bin/chromium', args: ['--no-sandbox'] });
  let fails = 0, checks = 0;
  const fail = m => { fails++; console.log('FAIL ' + m); };
  const ok = m => { checks++; console.log('ok   ' + m); };
  const open = async url => {
    const p = await br.newPage();
    const errs = [];
    p.on('console', m => m.type() === 'error' && errs.push(m.text()));
    p.on('pageerror', e => errs.push(String(e)));
    await p.goto(url, { waitUntil: 'networkidle0' });
    return { p, errs };
  };
  try {
    if (!tagged.length) fail('no tagged assets in data/sectors.json');
    // leaderboard: rows re-rendered by board.js
    {
      const { p, errs } = await open(base + 'index.html');
      await p.waitForSelector('body[data-ready="1"]', { timeout: 20000 });
      const rows = await p.$$eval('#rows li', lis => lis.map(li => ({ asset: li.dataset.asset, stat: li.dataset.static || '',
        tags: [...li.querySelectorAll('[data-field="sector"]')].map(t => t.dataset.sector) })));
      if (rows.some(r => r.stat)) fail('leaderboard still shows prerendered rows: board.js did not render');
      for (const asset of tagged) {
        const want = sec.by_asset[asset].map(s => s.id).sort().join(',');
        const mine = rows.filter(r => r.asset === asset);
        if (!mine.length) continue;
        if (mine.every(r => r.tags.slice().sort().join(',') === want)) ok(`leaderboard: ${mine.length} ${asset} row(s) tagged ${want} after board.js`);
        else fail(`leaderboard: ${asset} rows tags ${JSON.stringify(mine.map(r => r.tags))}, want ${want}`);
      }
      const stray = rows.filter(r => !tagged.includes(r.asset) && r.tags.length);
      if (stray.length) fail('untagged assets show tags: ' + stray.map(r => r.asset).join(','));
      if (errs.length) fail('leaderboard console errors: ' + errs.join(' | '));
      await p.close();
    }
    // position pages: position.js replaces the content and must keep the sector section
    for (const s of sec.sectors) {
      for (const m of s.members) {
        for (const c of m.calls) {
          const { p, errs } = await open(base + `pos-${slug(c.post_id, m.asset)}.html`);
          await p.waitForFunction(() => document.querySelector('#app [data-field="author"]') && !document.querySelector('#app [data-static]'), { timeout: 20000 })
            .catch(() => null);
          const got = await p.$$eval('#app [data-field="sector_tags"] [data-field="sector"]', a => a.map(x => x.getAttribute('href')));
          const rendered = await p.$eval('#app', a => !a.querySelector('[data-static]')).catch(() => false);
          if (rendered && got.includes(`sectors.html#${s.id}`)) ok(`pos-${slug(c.post_id, m.asset)}.html keeps the ${s.id} tag after position.js`);
          else fail(`pos-${slug(c.post_id, m.asset)}.html: rendered=${rendered} tags=${JSON.stringify(got)}`);
          if (errs.length) fail(`pos ${c.post_id} console errors: ` + errs.join(' | '));
          await p.close();
        }
      }
    }
    // sectors page: static, every sector, asset and call listed
    {
      const { p, errs } = await open(base + 'sectors.html');
      for (const s of sec.sectors) {
        const n = await p.$$eval(`section[data-sector="${s.id}"] li[data-post-id]`, x => x.length);
        const want = s.members.reduce((a, m) => a + m.calls.length, 0);
        if (n === want) ok(`sectors.html#${s.id}: ${s.members.length} asset(s), ${n} call(s)`);
        else fail(`sectors.html#${s.id}: ${n} calls listed, want ${want}`);
      }
      if (errs.length) fail('sectors.html console errors: ' + errs.join(' | '));
      await p.close();
    }
  } finally {
    await br.close();
    if (server) server.close();
  }
  console.log(`${fails ? 'FAILED' : 'OK'}: ${checks} checks, ${fails} failures (${liveUrl || 'local web/'})`);
  process.exit(fails ? 1 : 0);
})();
