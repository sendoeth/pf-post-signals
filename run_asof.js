// Load each as-of dashboard exactly like signal_api.js and record the unmodified classifier output.
// usage: node run_asof.js  ->  data/counterfactual_regimes.json
const fs = require('fs');
const path = require('path');
const puppeteer = require('/home/postfiat/node_modules/puppeteer');

const HERE = __dirname;
// usage: node run_asof.js [file.html ...]  (no args: work/asof/index.json -> data/counterfactual_regimes.json)
const fileArgs = process.argv.slice(2);
const index = fileArgs.length
  ? fileArgs.map(f => ({ asof: null, file: path.resolve(f) }))
  : JSON.parse(fs.readFileSync(path.join(HERE, 'work', 'asof', 'index.json'), 'utf8'));

(async () => {
  const browser = await puppeteer.launch({
    headless: true, executablePath: '/snap/bin/chromium',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'],
  });
  const out = [];
  try {
    const page = await browser.newPage();
    for (const { asof, file } of index) {
      await page.goto('file://' + file, { waitUntil: 'networkidle0' });
      await new Promise(r => setTimeout(r, 1500));
      const rc = await page.evaluate(() => {
        const r = exeData.regimeClass;
        return {
          regime: r.regime.id || 'NEUTRAL',
          label: r.regime.label,
          confidence: r.confidence,
          isAlert: r.isAlert,
          decayingTypes: r.decayingTypes,
          lastDate: BT_DATES[BT_DATES.length - 1],
          gate: typeof PF_GATE === 'undefined' ? null : { effective: r.regime.id, raw: r.rawRegime, dataAsOf: r.dataAsOf, stale: !!r.stale, queueRegime: exeData.queue && exeData.queue[0] ? exeData.queue[0].regime : null },
        };
      });
      if (asof && rc.lastDate !== asof) throw new Error(`window mismatch ${asof} vs ${rc.lastDate}`);
      out.push({ asof: asof || rc.lastDate, ...rc });
      process.stderr.write(`${asof} ${rc.regime} ${rc.confidence}\n`);
    }
  } finally {
    await browser.close();
  }
  if (fileArgs.length) process.stdout.write(JSON.stringify(out));
  else fs.writeFileSync(path.join(HERE, 'data', 'counterfactual_regimes.json'), JSON.stringify(out, null, 1));
})();
