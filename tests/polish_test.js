// Step 20: the advice notice, clickable closes, price at the post, markers inside the plot.
//  A. the notice (#nfa, same text) on the leaderboard, chart view, position.html, every pos-*.html and
//     every caller-*.html; the leaderboard notes link to it
//  B. every visible exit mark (the opened call's and other callers') is a button: click and Enter open a
//     close card with the closing post (id, text, link), exit words, the exit bar and the realized result,
//     all equal to the record; BobLoukas silver checked field by field
//  C. price at the post: the opened call's card, every other call's card and every chart-view card show
//     the record's entry bar (raw) under "Price at the post"
//  D. markers inside the plot: on every position page, at 8 zoom / scroll positions (default, fit all,
//     full history, tight zoom on the entry, entry at the left edge, entry at the right edge, scrolled
//     past it on each side): the overlay is exactly the plot area and clips, and every visible bubble,
//     exit mark has its centre inside it; markers whose bar is outside the view are hidden
// usage: node tests/polish_test.js [--url https://.../web/] [--screenshots DIR]
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
const NOTICE = 'Not financial advice. The calls on this site are public posts by their authors, tracked and priced for analysis.';
const SILVER = '1776235528741937435';

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
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

(async () => {
  const bundle = JSON.parse(fs.readFileSync(path.join(WEB, 'data', 'charts.json'), 'utf8'));
  const recs = {};
  for (const a of bundle.assets) for (const p of a.posts) recs[`${p.post.id}|${a.name}`] = { a, p, rec: JSON.parse(fs.readFileSync(path.join(ROOT, p.record_file), 'utf8')) };
  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium', args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  const fails = [], consoleErrors = [];
  const fail = m => fails.push(m);
  const n = { noticePages: 0, closeCards: 0, keyboardCloses: 0, priceCards: 0, chartCards: 0, views: 0, markersChecked: 0, hiddenOutside: 0 };
  try {
    const page = await browser.newPage();
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') consoleErrors.push(`${page.url()} ${m.type()}: ${m.text()}`); });
    page.on('pageerror', e => consoleErrors.push(`${page.url()} pageerror: ${e.message}`));
    page.on('requestfailed', r => consoleErrors.push(`requestfailed: ${r.url()} ${r.failure() && r.failure().errorText}`));
    page.on('response', r => { if (r.status() >= 400) consoleErrors.push(`http ${r.status()}: ${r.url()}`); });
    await page.setViewport({ width: 1280, height: 1000 });

    // A. the notice everywhere
    const pages = ['', 'chart.html', 'position.html'].concat(Object.values(recs).map(r => `pos-${slug(r.p.post.id, r.a.name)}.html`))
      .concat(Object.keys(bundle.ratings.callers).map(h => `caller-${h.toLowerCase().replace(/[^a-z0-9_-]/g, '-')}.html`));
    for (const u of pages) {
      await page.goto(base + u, { waitUntil: 'domcontentloaded' });
      const got = await page.$eval('#nfa', x => ({ text: x.textContent.replace(/\s+/g, ' ').trim(), shown: x.offsetHeight > 0 })).catch(() => null);
      n.noticePages++;
      if (!got || !got.text.startsWith(NOTICE) || !got.shown) fail(`notice missing or different on /${u}: ${JSON.stringify(got)}`);
    }
    await page.goto(base, { waitUntil: 'networkidle0' });
    if (!(await page.$('p.notes a[href="#nfa"]'))) fail('leaderboard notes do not link to the notice');
    if (shotDir) {
      fs.mkdirSync(shotDir, { recursive: true });
      await (await page.$('#nfa')).screenshot({ path: path.join(shotDir, 'notice_leaderboard.png') });
    }

    const openPos = async (id, asset, q = '') => {
      await page.goto(`${base}pos-${slug(id, asset)}.html${q}`, { waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready]', { timeout: 20000 });
      return page.$eval('body', b => b.dataset.ready);
    };
    const readCard = () => page.evaluate(() => {
      const c = document.getElementById('call-card');
      return { hidden: c.hidden, kind: c.dataset.card, id: c.dataset.postId,
        f: Object.fromEntries([...c.querySelectorAll('[data-field]')].map(x => [x.dataset.field, { text: x.textContent, raw: x.dataset.raw === undefined ? undefined : JSON.parse(x.dataset.raw), href: x.getAttribute('href') }])),
        labels: [...c.querySelectorAll('dt')].map(x => x.textContent) };
    });
    const checkClose = (card, r, tag) => {
      const c = r.closed, ev = (r.lifecycle && r.lifecycle.events || []).find(e => e.post.id === c.post_id);
      if (card.hidden || card.kind !== 'close' || card.id !== r.post.id) return fail(`${tag}: no close card (got ${card.kind || 'nothing'} ${card.id || ''})`);
      const f = k => card.f[k] || {};
      if (!same(f('close_exit').raw, c.exit)) fail(`${tag}: exit ${JSON.stringify(card.f.close_exit.raw)} != ${JSON.stringify(c.exit)}`);
      if (!same(f('close_entry').raw, r.entry)) fail(`${tag}: entry differs`);
      const res = r.side ? c.for_call : c.move;
      if (f('close_result').raw !== res) fail(`${tag}: realized ${f('close_result').raw} != ${res}`);
      if (c.by !== 'ledger') {
        if (f('close_url').href !== c.post_url) fail(`${tag}: closing post link ${f('close_url').href} != ${c.post_url}`);
        if (ev && ev.post.text && !(f('close_text').text || '').startsWith(ev.post.text.replace(/\s+/g, ' ').trim().slice(0, 60))) fail(`${tag}: closing post text`);
        if (ev && ev.terms.length && !same(f('close_terms').raw, ev.terms)) fail(`${tag}: exit words`);
      }
    };

    // B. BobLoukas silver: the close card in detail, by click and by keyboard
    const silver = recs[`${SILVER}|SILVER`].rec;
    await openPos(SILVER, 'SILVER');
    await page.click('#exit-mark');
    let card = await readCard();
    checkClose(card, silver, 'silver click');
    n.closeCards++;
    const F = k => card.f[k] || { text: '', href: '' };
    if (!F('close_terms').text.includes('rotated out of')) fail('silver: exit words do not include "rotated out of"');
    if (!F('close_exit').text.startsWith('80.125 @ 2026-01-09 16:00 UTC')) fail(`silver: exit text "${F('close_exit').text}"`);
    if (!(F('close_url').href || '').endsWith('/2009654117799739530')) fail(`silver: closing post link "${F('close_url').href}"`);
    if (shotDir) await (await page.$('section.pos')).screenshot({ path: path.join(shotDir, 'silver_close_card.png') });
    if (await page.$('#call-card:not([hidden]) .card-close')) await page.click('#call-card .card-close');
    await page.focus('#exit-mark');
    await page.keyboard.press('Enter');
    card = await readCard();
    checkClose(card, silver, 'silver keyboard');
    n.keyboardCloses++;
    // C on silver: the opened call's own card (price at the post)
    await page.click('#entry-bubble');
    card = await readCard();
    if (card.kind !== 'call' || !same((card.f.card_entry || {}).raw, silver.entry) || !card.labels.includes('Price at the post')) fail(`silver: opened call card ${JSON.stringify(card.f.card_entry || null)}`);
    n.priceCards++;
    if (shotDir) await (await page.$('section.pos')).screenshot({ path: path.join(shotDir, 'silver_price_at_post_card.png') });

    // B, C, D on every position page
    for (const { a, p, rec } of Object.values(recs)) {
      if (!p.entry) continue;
      const tag = `${a.name} ${p.post.id}`;
      if (await openPos(p.post.id, a.name) !== '1') { fail(`${tag}: did not load`); continue; }
      await page.evaluate(() => window.__position.fitCalls());
      await settle(page);
      // exit marks: own and others'
      const exits = await page.$$eval('.exit-btn:not([hidden])', xs => xs.map(x => x.dataset.postId));
      for (const id of exits) {
        await page.click(`.exit-btn[data-post-id="${id}"]:not([hidden])`).catch(e => fail(`${tag}: exit mark ${id} not clickable`));
        const r = (Object.values(recs).find(x => x.p.post.id === id && x.a.name === a.name) || {}).rec;
        if (!r || !r.closed) { fail(`${tag}: exit mark for ${id} without a closed record`); continue; }
        checkClose(await readCard(), r, `${tag} exit ${id}`);
        n.closeCards++;
      }
      // price at the post: the opened call and the other calls
      for (const id of [p.post.id].concat(await page.$$eval('.call-bubble:not([hidden])', xs => xs.map(x => x.dataset.postId)))) {
        const sel = id === p.post.id ? '#entry-bubble' : `.call-bubble[data-post-id="${id}"]`;
        if (!(await page.$(sel + ':not([hidden])'))) continue;
        await page.click(sel).catch(() => {});
        const c = await readCard(), r = Object.values(recs).find(x => x.p.post.id === id && x.a.name === a.name).rec;
        n.priceCards++;
        if (c.id !== id || !same(c.f.card_entry && c.f.card_entry.raw, r.entry) || !c.labels.includes('Price at the post')) fail(`${tag}: card for ${id} price at the post ${JSON.stringify(c.f.card_entry)}`);
      }
      // D. markers inside the plot at 8 views
      const views = ['default', 'fit', 'full', 'tight', 'entryLeft', 'entryRight', 'pastLeft', 'pastRight'];
      for (const v of views) {
        if (v === 'default') { await openPos(p.post.id, a.name); }
        else await page.evaluate(view => {
          const pos = window.__position, ts = pos.chart.timeScale(), step = pos.step(), data = pos.series.data();
          const t = step === 3600 ? Date.parse(pos.post.entry.at) / 1000 : Math.floor(Date.parse(pos.post.entry.at) / 1000 / step) * step;
          const i = Math.max(0, data.findIndex(d => d.time >= t));
          const set = (from, to) => ts.setVisibleLogicalRange({ from, to });
          if (view === 'fit') pos.fitCalls();
          else if (view === 'full') document.querySelector('.toolbar button[data-range="all"]').click();
          else if (view === 'tight') set(i - 3, i + 3);
          else if (view === 'entryLeft') set(i - 0.4, i + 40);
          else if (view === 'entryRight') set(i - 40, i + 0.4);
          else if (view === 'pastLeft') set(i + 5, i + 60);
          else if (view === 'pastRight') set(i - 60, i - 5);
        }, v);
        await settle(page);
        const g = await page.evaluate(() => {
          const pos = window.__position, box = document.getElementById('chart-box'), ov = document.getElementById('overlay');
          const b = box.getBoundingClientRect(), o = ov.getBoundingClientRect();
          const plot = { W: pos.chart.timeScale().width(), H: box.clientHeight - pos.chart.timeScale().height() };
          const marks = [...ov.querySelectorAll('#entry-bubble, .call-bubble, #exit-mark, .call-exit')].map(m => {
            const r = m.getBoundingClientRect();
            return { id: m.id || m.className, hidden: m.hidden || getComputedStyle(m).display === 'none', cx: r.left + r.width / 2 - b.left, cy: r.top + r.height / 2 - b.top };
          });
          return { plot, ov: { x: o.left - b.left, y: o.top - b.top, w: o.width, h: o.height, overflow: getComputedStyle(ov).overflow }, marks };
        });
        n.views++;
        if (Math.abs(g.ov.w - g.plot.W) > 1 || Math.abs(g.ov.h - g.plot.H) > 1 || g.ov.x !== 0 || g.ov.y !== 0) fail(`${tag} ${v}: overlay ${JSON.stringify(g.ov)} != plot ${JSON.stringify(g.plot)}`);
        if (g.ov.overflow !== 'hidden') fail(`${tag} ${v}: overlay does not clip (${g.ov.overflow})`);
        for (const m of g.marks) {
          if (m.hidden) { n.hiddenOutside++; continue; }
          n.markersChecked++;
          if (m.cx < -0.5 || m.cx > g.plot.W + 0.5 || m.cy < -0.5 || m.cy > g.plot.H + 0.5) fail(`${tag} ${v}: ${m.id} drawn at ${m.cx.toFixed(1)},${m.cy.toFixed(1)} outside the plot ${g.plot.W}x${g.plot.H}`);
        }
        if (shotDir && p.post.id === SILVER && v === 'entryRight') await (await page.$('section.pos')).screenshot({ path: path.join(shotDir, 'silver_chart_entry_at_edge.png') });
      }
    }

    // C. chart view cards
    await page.goto(base + 'chart.html', { waitUntil: 'networkidle0' });
    await page.waitForSelector('body[data-ready="1"]');
    for (const a of bundle.assets) {
      await page.select('#asset', a.name);
      for (const p of a.posts) {
        if (!p.entry) continue;
        await (await page.$(`.bubble[data-post-id="${p.post.id}"] circle.mark`)).click();
        const c = await page.evaluate(() => { const e = document.querySelector('#card [data-field="entry"]'); return { raw: JSON.parse(e.dataset.raw), label: e.previousElementSibling.textContent,
          closing: (document.querySelector('#card [data-field="closing_post"]') || {}).textContent || null }; });
        n.chartCards++;
        if (!same(c.raw, p.entry) || c.label !== 'Price at the post') fail(`chart ${a.name} ${p.post.id}: ${JSON.stringify(c)}`);
        if (p.closed && !c.closing) fail(`chart ${a.name} ${p.post.id}: closed call without its closing post`);
      }
    }
  } finally {
    await browser.close();
    if (server) server.close();
  }
  for (const e of consoleErrors) fail(`console: ${e}`);
  console.log(`page ${base}`);
  console.log(`notice on ${n.noticePages} pages, close cards ${n.closeCards} (+${n.keyboardCloses} by keyboard), price-at-post cards ${n.priceCards}, chart-view cards ${n.chartCards}, ` +
    `views checked ${n.views} (8 per position page), visible markers inside the plot ${n.markersChecked}, hidden outside the view ${n.hiddenOutside}, console errors ${consoleErrors.length}`);
  // failures by check, a few examples each (one check failing everywhere must not hide the others)
  const kinds = [['notice', /notice/], ['close card', /close card|closing post|exit words|exit mark|realized|exit text|entry differs/], ['price at the post', /price at the post|opened call card|chart .*Price/],
                 ['outside the plot', /outside the plot/], ['overlay', /overlay/], ['console', /^console/]];
  const by = {};
  for (const f of fails) { const k = (kinds.find(([, re]) => re.test(f)) || ['other'])[0]; (by[k] = by[k] || []).push(f); }
  for (const [k, list] of Object.entries(by)) {
    console.log(`${k}: ${list.length} failure(s)`);
    for (const f of list.slice(0, 4)) console.log('   -', f);
  }
  console.log(fails.length ? `FAIL (${fails.length})` : 'ALL PASS');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
