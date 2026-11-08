// Step 29 browser test: every position page of a reply or quote with a stored context keeps its "Reply context"
// section after web/assets/position.js has rendered the page (the script replaces the prerendered content), with
// the stored parent copy and no console errors; web/context.html shows every context and the agreement table.
// usage: node tests/context_test.js [--url https://.../web/]
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
  const ctx = JSON.parse(fs.readFileSync(path.join(WEB, 'data', 'context.json'), 'utf8'));
  const server = liveUrl ? null : await serve();
  const base = liveUrl || `http://127.0.0.1:${server.address().port}/`;
  const br = await puppeteer.launch({ executablePath: '/snap/bin/chromium', args: ['--no-sandbox'] });
  let fails = 0, pages = 0;
  const fail = m => { fails++; console.log('FAIL ' + m); };
  try {
    for (const en of ctx.entries) {
      for (const rec of en.recorded) {
        const p = await br.newPage();
        const errs = [];
        p.on('console', m => m.type() === 'error' && errs.push(m.text()));
        p.on('pageerror', e => errs.push(String(e)));
        await p.goto(`${base}pos-${slug(en.post, rec.asset)}.html?nc=${Date.now()}`, { waitUntil: 'networkidle0' });
        await p.waitForSelector('#app[data-post-id] .panel.pos', { timeout: 20000 }).catch(() => null);
        const r = await p.evaluate(() => {
          const s = document.querySelector('#app [data-field="reply_context"]');
          return { rendered: !!document.querySelector('#app[data-post-id] .panel.pos'), post: s && s.getAttribute('data-post'),
                   status: s && s.getAttribute('data-status'), parent: s && (s.querySelector('[data-field="parent_text"]') || {}).textContent,
                   afterPost: !!(s && s.previousElementSibling && s.previousElementSibling.classList.contains('post')) };
        });
        pages++;
        const want = en.posts.parent ? en.posts.parent.text : null;
        if (!r.rendered) fail(`${en.post} ${rec.asset}: the script did not render the page`);
        else if (r.post !== en.post) fail(`${en.post} ${rec.asset}: no reply context after rendering`);
        else if (want !== null && r.parent !== want) fail(`${en.post} ${rec.asset}: the parent copy differs`);
        else if (!r.afterPost) fail(`${en.post} ${rec.asset}: the context is not right after the post`);
        else if (errs.length) fail(`${en.post} ${rec.asset}: console errors ${errs.join(' | ')}`);
        else console.log(`ok   pos-${slug(en.post, rec.asset)}.html: reply context (${r.status}) kept after rendering`);
        await p.close();
      }
    }
    const p = await br.newPage();
    const errs = [];
    p.on('pageerror', e => errs.push(String(e)));
    await p.goto(`${base}context.html?nc=${Date.now()}`, { waitUntil: 'networkidle0' });
    const c = await p.evaluate(() => ({ blocks: document.querySelectorAll('section[data-field="reply_context"]').length,
                                        rows: document.querySelectorAll('[data-field="agreement"] tbody tr').length,
                                        overflow: document.documentElement.scrollWidth - window.innerWidth }));
    if (c.blocks !== ctx.entries.length) fail(`context.html shows ${c.blocks} contexts, the data has ${ctx.entries.length}`);
    else if (c.rows !== ctx.agreement_rows.length) fail(`context.html agreement table has ${c.rows} rows, the data ${ctx.agreement_rows.length}`);
    else if (errs.length) fail('context.html errors ' + errs.join(' | '));
    else console.log(`ok   context.html: ${c.blocks} contexts, ${c.rows} agreement rows`);
  } finally {
    await br.close();
    if (server) server.close();
  }
  console.log(fails ? `FAILED: ${fails} of ${pages + 1} pages` : `ALL PASS: ${pages} position pages kept their reply context; context.html complete`);
  process.exit(fails ? 1 : 0);
})();
