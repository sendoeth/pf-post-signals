// Load each as-of dashboard exactly like signal_api.js and record the unmodified classifier output.
// usage: node run_asof.js  ->  data/counterfactual_regimes.json
const fs = require('fs');
const path = require('path');
const puppeteer = require('/home/postfiat/node_modules/puppeteer');

const HERE = __dirname;
const index = JSON.parse(fs.readFileSync(path.join(HERE, 'work', 'asof', 'index.json'), 'utf8'));

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
        };
      });
      if (rc.lastDate !== asof) throw new Error(`window mismatch ${asof} vs ${rc.lastDate}`);
      out.push({ asof, ...rc });
      process.stderr.write(`${asof} ${rc.regime} ${rc.confidence}\n`);
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(HERE, 'data', 'counterfactual_regimes.json'), JSON.stringify(out, null, 1));
})();
