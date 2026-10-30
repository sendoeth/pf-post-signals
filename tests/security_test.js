// Step 8 security test (headless Chromium).
//  1. real site: the leaderboard (index.html, several filtered views), chart.html (every bubble
//     clicked) and every position page at both intervals:
//     every request goes to the site's own origin, 0 CSP violations, 0 console errors, canary unset
//  2. attack site (local only): a throwaway copy of web/ whose bundle is built from
//     tests/fixtures/attack_records and whose avatars/index.json is tampered with. Refused fixtures
//     must not be drawn; drawn hostile text must show as literal text and never execute
//  3. framing: the pages inside a frame on another origin, plain and sandboxed, must break out or hide
// usage: node tests/security_test.js [--url https://.../web/]
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const { execFileSync } = require('child_process');
const puppeteer = require('/home/postfiat/node_modules/puppeteer');

const ROOT = path.resolve(__dirname, '..');
const arg = k => (process.argv.includes(k) ? process.argv[process.argv.indexOf(k) + 1] : null);
const liveUrl = arg('--url');
const TYPES = { '.html': 'text/html', '.json': 'application/json', '.js': 'text/javascript', '.css': 'text/css',
                '.svg': 'image/svg+xml', '.jpg': 'image/jpeg' };

function serve(dir, extra = {}) {
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html';
    if (extra[rel]) { res.writeHead(200, { 'content-type': 'text/html' }); res.end(extra[rel]); return; }
    const file = path.resolve(dir, rel);
    if (!file.startsWith(dir + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(ok => server.listen(0, '127.0.0.1', () => ok(server)));
}

async function watch(browser, label, log) {
  const page = await browser.newPage();
  await page.evaluateOnNewDocument(() => {
    window.__cspv = [];
    document.addEventListener('securitypolicyviolation', e => window.__cspv.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  page.on('request', r => log.requests.push(r.url()));
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') log.console.push(`${label}: ${m.type()}: ${m.text()}`); });
  page.on('pageerror', e => log.console.push(`${label}: pageerror: ${e.message}`));
  page.on('requestfailed', r => log.console.push(`${label}: requestfailed ${r.url()}`));
  page.on('response', r => { if (r.status() >= 400) log.console.push(`${label}: http ${r.status()} ${r.url()}`); });
  await page.setViewport({ width: 1280, height: 1000 });
  return page;
}

async function pageState(page) {
  return page.evaluate(() => ({ pwned: typeof window.__pwned === 'undefined' ? null : String(window.__pwned),
                                csp: window.__cspv || [], ready: document.body && document.body.dataset.ready }));
}

async function visitAll(browser, base, bundle, label, fails, log) {
  const page = await watch(browser, label, log);
  let pages = 0, clicks = 0;
  const check = async where => {
    const s = await pageState(page);
    pages++;
    if (s.pwned !== null) fails.push(`${label} ${where}: canary set to ${s.pwned}`);
    for (const v of s.csp) fails.push(`${label} ${where}: CSP violation ${v}`);
    log.csp += s.csp.length;
  };
  await page.goto(base, { waitUntil: 'networkidle0' });            // leaderboard (step 10)
  await page.waitForSelector('body[data-ready="1"]');
  for (const q of ['?sort=best', '?side=short', '?sort=newest&time=7d']) {
    await page.goto(base + q, { waitUntil: 'networkidle0' });
    await page.waitForSelector('body[data-ready="1"]');
  }
  await check('leaderboard');
  await page.goto(base + 'chart.html', { waitUntil: 'networkidle0' });
  await page.waitForSelector('body[data-ready="1"]');
  for (const a of bundle.assets) {
    await page.select('#asset', a.name);
    for (const p of a.posts.filter(p => p.entry)) {
      await (await page.$(`.bubble[data-post-id="${p.post.id}"] circle.mark`)).click();
      clicks++;
    }
  }
  await check('chart.html');
  for (const a of bundle.assets) for (const p of a.posts) for (const iv of ['', '&interval=1h']) {
    await page.goto(`${base}position.html?post=${p.post.id}&asset=${encodeURIComponent(a.name)}${iv}`, { waitUntil: 'networkidle0' });
    await page.waitForSelector('body[data-ready]');
    await check(`position ${a.name} ${p.post.id}${iv}`);
  }
  await page.close();
  return { pages, clicks };
}

(async () => {
  const fails = [], log = { requests: [], console: [], csp: 0 };
  const servers = [];
  const browser = await puppeteer.launch({ headless: true, executablePath: '/snap/bin/chromium',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'] });
  let real, attack = null, frames = [];
  try {
    // 1. real site
    const web = path.join(ROOT, 'web');
    const s1 = liveUrl ? null : await serve(web);
    if (s1) servers.push(s1);
    const base = liveUrl || `http://127.0.0.1:${s1.address().port}/`;
    const bundle = JSON.parse(fs.readFileSync(path.join(web, 'data', 'charts.json'), 'utf8'));
    const before = log.requests.length;
    real = await visitAll(browser, base, bundle, 'site', fails, log);
    const origin = new URL(base).origin;
    const realReq = log.requests.slice(before);
    const origins = [...new Set(realReq.map(u => new URL(u).origin))];
    real.requests = realReq.length; real.origins = origins;
    real.paths = [...new Set(realReq.map(u => new URL(u).pathname))].sort();
    for (const o of origins) if (o !== origin) fails.push(`site: request to another origin ${o}`);

    // 2. attack site (local copy of web/ with the hostile bundle and a tampered avatar index)
    if (!liveUrl) {
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pfps-attack-'));
      fs.cpSync(web, tmp, { recursive: true });
      execFileSync('python3', [path.join(ROOT, 'build_chart.py'), '--records', path.join(ROOT, 'tests', 'fixtures', 'attack_records'),
                               '--out', path.join(tmp, 'data', 'charts.json')], { cwd: ROOT });
      fs.writeFileSync(path.join(tmp, 'avatars', 'index.json'), JSON.stringify({
        bobloukas: { file: '../position.html', source: 'tampered', sha256: 'x' } }));
      const ab = JSON.parse(fs.readFileSync(path.join(tmp, 'data', 'charts.json'), 'utf8'));
      const expected = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests', 'fixtures', 'attack_expected.json'), 'utf8'));
      const drawn = ab.assets.flatMap(a => a.posts.map(p => p.record_file));
      const refused = ab.refused.map(r => r.file);
      const rows = [];
      for (const [file, e] of Object.entries(expected)) {
        const got = drawn.includes(file) ? 'drawn' : refused.includes(file) ? 'refused' : 'missing';
        rows.push([path.basename(file, '.json'), e.expected, got]);
        if (!e.expected.startsWith(got)) fails.push(`attack ${file}: expected ${e.expected}, got ${got}`);
      }
      const s2 = await serve(tmp);
      servers.push(s2);
      const abase = `http://127.0.0.1:${s2.address().port}/`;
      const b2 = log.requests.length;
      const visited = await visitAll(browser, abase, ab, 'attack', fails, log);
      const aorigins = [...new Set(log.requests.slice(b2).map(u => new URL(u).origin))];
      for (const o of aorigins) if (o !== new URL(abase).origin) fails.push(`attack: request to another origin ${o}`);
      // the hostile text is on screen as literal text, and created no elements
      const page = await watch(browser, 'attack-dom', log);
      await page.goto(abase, { waitUntil: 'networkidle0' });              // leaderboard quotes the post text
      await page.waitForSelector('body[data-ready="1"]');
      const board = await page.evaluate(() => ({
        literal: document.getElementById('rows').textContent.includes('<script>window.__pwned="script tag"</script>'),
        injected: document.querySelectorAll('#rows script, #rows iframe, #rows img:not(.avatar img), #rows [onerror], #rows [onload], #rows a[href^="javascript:"]').length,
        canary: typeof window.__pwned === 'undefined' ? null : String(window.__pwned) }));
      if (!board.literal || board.injected || board.canary !== null) fail(`attack leaderboard: literal ${board.literal}, injected ${board.injected}, canary ${board.canary}`);
      await page.goto(abase + 'chart.html', { waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready="1"]');
      const textPost = ab.assets[0].posts.find(p => (p.post.text || '').includes('<script>'));
      await (await page.$(`.bubble[data-post-id="${textPost.post.id}"] circle.mark`)).click();
      const dom = await page.evaluate(() => {
        const c = document.getElementById('card');
        return { literal: c.textContent.includes('<script>window.__pwned="script tag"</script>'),
                 injected: c.querySelectorAll('script, iframe, svg, img, [onerror], [onload], a[href^="javascript:"]').length };
      });
      await page.goto(`${abase}position.html?post=${textPost.post.id}&asset=BTC`, { waitUntil: 'networkidle0' });
      await page.waitForSelector('body[data-ready="1"]');
      const pos = await page.evaluate(() => ({
        literal: document.querySelector('[data-field="text"]').textContent.includes('<img src=x onerror='),
        injected: document.querySelectorAll('#app script, #app iframe, #app [onerror], #app [onload], #app a[href^="javascript:"]').length,
        avatar: document.getElementById('entry-bubble').getAttribute('data-avatar'),
        canary: typeof window.__pwned === 'undefined' ? null : String(window.__pwned) }));
      await page.close();
      if (!dom.literal || dom.injected) fail(`attack card: literal ${dom.literal}, injected elements ${dom.injected}`);
      if (!pos.literal || pos.injected) fail(`attack position page: literal ${pos.literal}, injected elements ${pos.injected}`);
      if (pos.avatar !== 'initials') fail(`attack: tampered avatar index used (${pos.avatar}), expected initials`);
      if (pos.canary !== null) fail(`attack: canary set to ${pos.canary}`);
      attack = { rows, pages: visited.pages, clicks: visited.clicks, origins: aorigins, dom, pos, board };
    }

    // 3. framing: our pages inside frames on another origin
    const targets = [base, `${base}position.html?post=2104977267109896477&asset=SILVER`];
    let n = 0;
    const host = await serve(fs.mkdtempSync(path.join(os.tmpdir(), 'pfps-frame-')), Object.fromEntries(targets.flatMap(t => [
      [`plain${n}.html`, `<!doctype html><title>framer</title><iframe src="${t}" width="800" height="600"></iframe>`],
      [`sandboxed${n++}.html`, `<!doctype html><title>framer</title><iframe sandbox="allow-scripts" src="${t}" width="800" height="600"></iframe>`]])));
    servers.push(host);
    const hbase = `http://127.0.0.1:${host.address().port}/`;
    for (let i = 0; i < targets.length; i++) for (const kind of ['plain', 'sandboxed']) {
      const page = await browser.newPage();
      await page.goto(`${hbase}${kind}${i}.html`, { waitUntil: 'networkidle0' }).catch(() => {});
      await new Promise(r => setTimeout(r, 1500));
      const top = page.url();
      let outcome;
      if (!top.startsWith(hbase)) outcome = 'broke out (top window now shows the site)';
      else {
        const f = page.frames().find(x => x !== page.mainFrame());
        const hidden = f ? await f.evaluate(() => document.documentElement.hasAttribute('data-framed') &&
          getComputedStyle(document.body).display === 'none').catch(() => null) : null;
        outcome = hidden ? 'hidden inside the frame' : `NOT PROTECTED (hidden=${hidden})`;
      }
      frames.push([kind, targets[i].replace(base, ''), outcome]);
      if (outcome.startsWith('NOT')) fails.push(`framing ${kind} ${targets[i]}: ${outcome}`);
      await page.close();
    }
  } finally {
    await browser.close();
    servers.forEach(s => s.close());
  }
  for (const c of log.console) fails.push(`console: ${c}`);
  console.log(`site ${liveUrl || 'local'}: ${real.pages} page states checked (leaderboard + chart + ${real.pages - 2} position loads), ${real.clicks} bubbles clicked, ` +
    `${real.requests} requests, origins: ${real.origins.join(', ')}`);
  console.log(`  resources loaded: ${real.paths.join(' ')}`);
  if (attack) {
    console.log(`attack fixtures: ${attack.rows.map(r => `${r[0]}=${r[2]}`).join(', ')}`);
    console.log(`attack site: ${attack.pages} page states, ${attack.clicks} bubbles clicked, origins: ${attack.origins.join(', ')}; ` +
      `card shows payload as text: ${attack.dom.literal}, injected elements: ${attack.dom.injected}; position page text literal: ${attack.pos.literal}, ` +
      `injected: ${attack.pos.injected}, tampered avatar -> ${attack.pos.avatar}; leaderboard quote literal: ${attack.board.literal}, injected: ${attack.board.injected}; canary: ${attack.pos.canary === null ? 'unset' : attack.pos.canary}`);
  }
  for (const f of frames) console.log(`framing ${f[0]} ${f[1] || 'index'}: ${f[2]}`);
  console.log(`canary window.__pwned: ${fails.some(f => f.includes('canary')) ? 'SET' : 'unset on every page'}; CSP violations: ${log.csp}; console errors: ${log.console.length}`);
  for (const f of fails) console.log(' -', f);
  console.log(fails.length ? `FAIL (${fails.length})` : 'ALL PASS');
  process.exit(fails.length ? 1 : 0);
  function fail(m) { fails.push(m); }
})().catch(e => { console.error(e); process.exit(2); });
