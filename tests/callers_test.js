// Step 14: every tracked caller's calls on the position chart + history before the first call.
// For every position page:
//  - one bubble per other call on the same asset (with an entry), ring = side, badge = price direction
//  - every caller subset via ?callers= (all, none, each combination): shown set, bubble visibility, the
//    opened call always present, the state surviving a reload; clicking each toggle rewrites the url
//  - after "fit calls": each visible bubble's anchor = the chart's own coordinate of its entry candle,
//    no two bubbles (opened call included) overlap, each opens its own card with the right links,
//    closed calls show an exit mark
//  - the candles start before the first call on the asset (lookback from the ohlc file), daily bars
//    are labelled "daily bar" in the hover readout
// usage: node tests/callers_test.js [--url https://.../web/] [--screenshots DIR]
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
const pct = x => (x > 0 ? '+' : x < 0 ? '-' : '') + (Math.abs(x) * 100).toFixed(2) + '%';
// mirrors PFPS.result in web/assets/common.js
const result = p => p.closed ? (p.side ? p.closed.for_call : p.closed.move) : p.change_since_post == null ? null : (p.side ? p.side * p.change_since_post : p.change_since_post);
const subsets = xs => xs.reduce((acc, x) => acc.concat(acc.map(s => s.concat([x]))), [[]]);
const param = (set, all) => all.every(a => set.includes(a)) ? null : !set.length ? 'none' : all.filter(a => set.includes(a)).join(',');

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
const settle = page => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 60)))));

(async () => {
  const bundle = JSON.parse(fs.readFileSync(path.join(WEB, 'data', 'charts.json'), 'utf8'));
  const index = JSON.parse(fs.readFileSync(path.join(WEB, 'data', 'ohlc', 'index.json'), 'utf8'));
  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium', args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  const fails = [], consoleErrors = [];
  const fail = m => fails.push(m);
  const n = { pages: 0, combos: 0, reloads: 0, clicks: 0, bubbles: 0, cards: 0, exits: 0, overlapPairs: 0, toggleClicks: 0, dailyReadouts: 0 };
  try {
    const page = await browser.newPage();
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleErrors.push(`${page.url()} ${m.type()}: ${m.text()}`); });
    page.on('pageerror', e => consoleErrors.push(`${page.url()} pageerror: ${e.message}`));
    page.on('requestfailed', r => consoleErrors.push(`requestfailed: ${r.url()} ${r.failure() && r.failure().errorText}`));
    page.on('response', r => { if (r.status() >= 400) consoleErrors.push(`http ${r.status()}: ${r.url()}`); });
    await page.setViewport({ width: 1280, height: 1000 });
    const open = async url => {
      await page.goto(url, { waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready]', { timeout: 20000 });
      return page.$eval('body', b => b.dataset.ready);
    };
    const state = () => page.evaluate(() => ({
      search: location.search, shown: window.__position.shown(),
      opened: (b => b && !b.hidden)(document.getElementById('entry-bubble')),
      bubbles: [...document.querySelectorAll('.call-bubble')].map(b => ({ id: b.dataset.postId, author: b.dataset.author, shown: b.dataset.shown, side: b.dataset.side,
        dir: b.querySelector('.dir') && b.querySelector('.dir').dataset.dir, hidden: b.hidden })),
      pressed: Object.fromEntries([...document.querySelectorAll('.callers button')].map(b => [b.dataset.caller || b.dataset.callers, b.getAttribute('aria-pressed')])),
    }));

    for (const a of bundle.assets) for (const p of a.posts) {
      if (!p.entry) continue;
      const tag = `${a.name} ${p.post.id}`, pageUrl = `${base}pos-${slug(p.post.id, a.name)}.html`;
      const others = a.posts.filter(o => o !== p && o.entry);
      const authors = [...new Set(a.posts.map(o => o.post.author.toLowerCase()))].sort();
      if (await open(pageUrl) !== '1') { fail(`${tag}: page did not load`); continue; }
      n.pages++;

      // default: every caller shown, one bubble per other call, ring/badge from the record
      let s = await state();
      if (s.search !== '') fail(`${tag}: default url has ${s.search}`);
      if (JSON.stringify(s.shown) !== JSON.stringify(authors)) fail(`${tag}: default shown ${s.shown} != ${authors}`);
      if (s.bubbles.length !== others.length) fail(`${tag}: ${s.bubbles.length} bubbles, ${others.length} other calls`);
      for (const o of others) {
        const b = s.bubbles.find(x => x.id === o.post.id);
        if (!b) { fail(`${tag}: no bubble for ${o.post.id}`); continue; }
        const side = o.side === 1 ? 'long' : o.side === -1 ? 'short' : 'none', mv = o.closed ? o.closed.move : o.change_since_post;
        const dir = mv == null ? 'none' : mv > 0 ? 'up' : mv < 0 ? 'down' : 'flat';
        if (b.side !== side || b.dir !== dir || b.author !== o.post.author.toLowerCase()) fail(`${tag}: bubble ${o.post.id} ${b.side}/${b.dir}/${b.author} != ${side}/${dir}`);
      }

      // history before the first call, from the ohlc file's lookback
      const meta = index.files[a.name];
      const hist = await page.evaluate(() => ({ first: window.__position.series.data()[0].time,
        raw: JSON.parse(document.querySelector('[data-field="history"]').getAttribute('data-raw')) }));
      const firstCall = Math.min(...a.posts.filter(o => o.entry).map(o => Date.parse(o.entry.at) / 1000));
      if (!(hist.first < firstCall)) fail(`${tag}: first candle ${hist.first} is not before the first call ${firstCall}`);
      if (JSON.stringify(hist.raw.lookback) !== JSON.stringify(meta.lookback) || hist.raw.daily_until !== meta.daily_until) fail(`${tag}: history note differs from the ohlc index`);

      // fit every call into view: anchors, no overlaps, cards, exit marks
      await page.evaluate(() => window.__position.fitCalls());
      await settle(page);
      const geo = await page.evaluate(() => {
        const pos = window.__position, step = pos.step(), box = document.getElementById('chart-box').getBoundingClientRect();
        const bucket = iso => step === 3600 ? Date.parse(iso) / 1000 : Math.floor(Date.parse(iso) / 1000 / step) * step;
        const bundlePosts = window.__others || null;
        const rect = n => { const r = n.getBoundingClientRect(); return { l: r.left - box.left, t: r.top - box.top, r: r.right - box.left, b: r.bottom - box.top }; };
        const nodes = [...document.querySelectorAll('.call-bubble')].filter(b => !b.hidden);
        const op = document.getElementById('entry-bubble');
        return { pills: [...document.querySelectorAll('.edge')].filter(e => !e.hidden).length,
          opened: op.hidden ? null : rect(op),
          bubbles: nodes.map(b => ({ id: b.dataset.postId, ax: +b.dataset.x, ay: +b.dataset.y, rect: rect(b) })),
          exits: [...document.querySelectorAll('.call-exit')].filter(x => !x.hidden).map(x => x.dataset.postId),
          coords: Object.fromEntries([...document.querySelectorAll('.call-bubble')].map(b => [b.dataset.postId, null])), step };
      });
      const coords = await page.evaluate(list => {
        const pos = window.__position, step = pos.step();
        const bucket = iso => step === 3600 ? Date.parse(iso) / 1000 : Math.floor(Date.parse(iso) / 1000 / step) * step;
        return list.map(o => ({ id: o.id, x: pos.chart.timeScale().timeToCoordinate(bucket(o.at)), y: pos.series.priceToCoordinate(o.price) }));
      }, others.map(o => ({ id: o.post.id, at: o.entry.at, price: o.entry.price })));
      if (geo.pills) fail(`${tag}: ${geo.pills} edge pill(s) still shown after fitting every call`);
      for (const c of coords) {
        const b = geo.bubbles.find(x => x.id === c.id);
        if (!b) { fail(`${tag}: bubble ${c.id} not visible after fit`); continue; }
        n.bubbles++;
        if (Math.abs(b.ax - c.x) > 1.5 || Math.abs(b.ay - c.y) > 1.5) fail(`${tag}: bubble ${c.id} anchored at ${b.ax},${b.ay}, entry candle at ${c.x},${c.y}`);
        const cx = (b.rect.l + b.rect.r) / 2;
        if (Math.abs(cx - c.x) > 1.5) fail(`${tag}: bubble ${c.id} drawn at x ${cx}, entry candle x ${c.x}`);
      }
      const rects = geo.bubbles.map(b => [b.id, b.rect]).concat(geo.opened ? [['opened', geo.opened]] : []);
      for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
        n.overlapPairs++;
        const [ia, A] = rects[i], [ib, B] = rects[j];
        if (A.l < B.r - 0.5 && B.l < A.r - 0.5 && A.t < B.b - 0.5 && B.t < A.b - 0.5) fail(`${tag}: bubbles ${ia} and ${ib} overlap`);
      }
      const wantExits = others.filter(o => o.closed).map(o => o.post.id).sort();
      if (JSON.stringify(geo.exits.slice().sort()) !== JSON.stringify(wantExits)) fail(`${tag}: exit marks ${geo.exits} != closed calls ${wantExits}`);
      n.exits += geo.exits.length;
      for (const o of others) {
        const handle = await page.$(`.call-bubble[data-post-id="${o.post.id}"]:not([hidden])`);
        if (!handle) continue;
        await handle.click();
        n.clicks++;
        const card = await page.evaluate(() => {
          const c = document.getElementById('call-card');
          const f = Object.fromEntries([...c.querySelectorAll('[data-field]')].map(x => [x.dataset.field, { text: x.textContent, href: x.getAttribute('href'), raw: x.getAttribute('data-raw') }]));
          return { hidden: c.hidden, id: c.dataset.postId, f };
        });
        const r = result(o);
        if (card.hidden || card.id !== o.post.id) { fail(`${tag}: click on ${o.post.id} opened ${card.id}`); continue; }
        n.cards++;
        if (card.f.card_position_url.href !== `pos-${slug(o.post.id, a.name)}.html`) fail(`${tag}: card position link ${card.f.card_position_url.href}`);
        if (card.f.card_url.href !== o.post.url) fail(`${tag}: card post link ${card.f.card_url.href}`);
        if (card.f.card_author.text !== '@' + o.post.author) fail(`${tag}: card author ${card.f.card_author.text}`);
        if (card.f.card_result.text !== (r == null ? 'unresolved' : pct(r)) || JSON.parse(card.f.card_result.raw) !== r) fail(`${tag}: card result ${card.f.card_result.text} != ${r}`);
        if (JSON.stringify(JSON.parse(card.f.card_entry.raw)) !== JSON.stringify(o.entry)) fail(`${tag}: card entry differs`);
      }

      // every caller combination through the url, then a reload
      for (const set of subsets(authors)) {
        const v = param(set, authors);
        const url = pageUrl + (v == null ? '' : '?callers=' + encodeURIComponent(v));
        for (const pass of ['load', 'reload']) {
          if (pass === 'load') { if (await open(url) !== '1') { fail(`${tag}: ${url} did not load`); continue; } }
          else { await page.reload({ waitUntil: 'networkidle0' }); await page.waitForSelector('body[data-ready]'); n.reloads++; }
          n.combos++;
          const st = await state();
          if (JSON.stringify(st.shown) !== JSON.stringify(set.slice().sort())) fail(`${tag} ${pass} ${v}: shown ${st.shown}`);
          if (st.search !== (v == null ? '' : '?callers=' + encodeURIComponent(v))) fail(`${tag} ${pass} ${v}: url ${st.search}`);
          if (!st.opened) fail(`${tag} ${pass} ${v}: the opened call is not shown`);
          for (const b of st.bubbles) {
            const on = set.includes(b.author);
            if (b.shown !== String(on)) fail(`${tag} ${pass} ${v}: bubble ${b.id} shown=${b.shown}`);
            if (!on && !b.hidden) fail(`${tag} ${pass} ${v}: bubble ${b.id} of a hidden caller is visible`);
          }
          for (const au of authors) if (st.pressed[au] !== String(set.includes(au))) fail(`${tag} ${pass} ${v}: toggle ${au} pressed=${st.pressed[au]}`);
          if (st.pressed.all !== String(set.length === authors.length) || st.pressed.none !== String(!set.length)) fail(`${tag} ${pass} ${v}: all/none pressed ${st.pressed.all}/${st.pressed.none}`);
        }
      }

      // clicking the toggles rewrites the url: start from all, switch each caller off, then none, then all
      await open(pageUrl);
      let cur = authors.slice();
      for (const au of authors) {
        await page.click(`.callers button[data-caller="${au}"]`); n.toggleClicks++;
        cur = cur.filter(x => x !== au);
        const st = await state(), v = param(cur, authors);
        if (st.search !== (v == null ? '' : '?callers=' + encodeURIComponent(v))) fail(`${tag}: after toggling ${au} url ${st.search}, want ${v}`);
      }
      await page.click('.callers button[data-callers="all"]'); n.toggleClicks++;
      if ((await state()).search !== '') fail(`${tag}: "All callers" left ${(await state()).search}`);
      await page.click('.callers button[data-callers="none"]'); n.toggleClicks++;
      if ((await state()).search !== '?callers=none') fail(`${tag}: "None" gave ${(await state()).search}`);

      // a daily bar in the hover readout
      if (meta.daily_until) {
        await open(pageUrl + '?interval=1h');
        await page.click('.toolbar button[data-range="all"]');
        await settle(page);
        const pt = await page.evaluate(du => {
          const pos = window.__position, d = pos.series.data().find(c => c.time < Date.parse(du) / 1000 - 30 * 86400);
          const box = document.getElementById('chart').getBoundingClientRect();
          return { x: box.left + pos.chart.timeScale().timeToCoordinate(d.time), y: box.top + 100, time: d.time };
        }, meta.daily_until);
        await page.mouse.move(pt.x, pt.y);
        await settle(page);
        const ro = await page.$eval('#readout', r => ({ text: r.textContent, daily: r.dataset.daily }));
        n.dailyReadouts++;
        if (ro.daily !== 'true' || !/daily bar/.test(ro.text)) fail(`${tag}: readout over a pre-${meta.daily_until} bar says ${ro.text}`);
      }
    }

    if (shotDir) {
      fs.mkdirSync(shotDir, { recursive: true });
      await page.setViewport({ width: 1000, height: 900 });
      const shot = async (url, name, prep) => {
        await open(url);
        if (prep) await prep();
        await settle(page);
        const el = await page.$('section.pos');
        await el.screenshot({ path: path.join(shotDir, name) });
      };
      await shot(`${base}pos-1776235528741937435_SILVER.html`, 'silver_all_callers.png');
      const gold = bundle.assets.find(a => a.name === 'GOLD').posts.slice(-1)[0];
      await shot(`${base}pos-${slug(gold.post.id, 'GOLD')}.html`, 'gold_all_callers.png', () => page.evaluate(() => window.__position.fitCalls()));
      await shot(`${base}pos-${slug(gold.post.id, 'GOLD')}.html?callers=bobloukas`, 'gold_one_caller_off.png', () => page.evaluate(() => window.__position.fitCalls()));
      await shot(`${base}pos-1776235528741937435_SILVER.html`, 'silver_pre_call_history.png', () => page.click('.toolbar button[data-range="all"]'));
    }
  } finally {
    await browser.close();
    if (server) server.close();
  }
  for (const e of consoleErrors) fail(`console: ${e}`);
  console.log(`page ${base}`);
  console.log(`position pages ${n.pages}, caller combinations ${n.combos} (incl. ${n.reloads} reloads), toggle clicks ${n.toggleClicks}, ` +
    `bubbles anchored ${n.bubbles}, bubble pairs checked for overlap ${n.overlapPairs}, cards opened ${n.cards}, exit marks ${n.exits}, daily readouts ${n.dailyReadouts}, console errors ${consoleErrors.length}`);
  for (const f of fails.slice(0, 60)) console.log(' -', f);
  console.log(fails.length ? `FAIL (${fails.length})` : 'ALL PASS');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
