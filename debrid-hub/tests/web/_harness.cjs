// Shared jsdom test harness for src/debrid_hub/web/index.html. The app has no
// build step and is one self-contained file, so "loading" it for a test means
// literally executing that HTML+JS in a jsdom window with `fetch` swapped for
// a caller-supplied fake -- no real network, no real server.
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const HTML_PATH = path.join(__dirname, '..', '..', 'src', 'debrid_hub', 'web', 'index.html');

function loadPage({ fetchImpl } = {}) {
  const html = fs.readFileSync(HTML_PATH, 'utf8');
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => console.log('  [jsdom error]', e.message.split('\n')[0]));
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    virtualConsole: vc,
    url: 'http://localhost/',
    beforeParse(window) {
      if (fetchImpl) window.fetch = fetchImpl;
      window.confirm = () => true; // auto-confirm destructive-action dialogs
      window.prompt = () => null;
      try {
        Object.defineProperty(window.navigator, 'clipboard', {
          value: { writeText: () => Promise.resolve() },
          configurable: true,
        });
      } catch (e) { /* already defined in this jsdom version */ }
    },
  });
  return dom;
}

function waitFor(cond, ms = 2000) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    const iv = setInterval(() => {
      let ok = false;
      try { ok = cond(); } catch (e) { /* condition not evaluable yet */ }
      if (ok) { clearInterval(iv); resolve(); }
      else if (Date.now() - t0 > ms) { clearInterval(iv); reject(new Error('timeout waiting for condition')); }
    }, 20);
  });
}

/** Collects named pass/fail assertions and reports a summary. Every test
 * module returns one of these from its exported `run()`. */
class Suite {
  constructor(name) {
    this.name = name;
    this.results = [];
  }
  assert(label, cond) {
    this.results.push([label, !!cond]);
  }
  report() {
    let ok = true;
    console.log(`\n=== ${this.name} ===`);
    for (const [label, passed] of this.results) {
      console.log((passed ? '  ✓ ' : '  ✗ ') + label);
      if (!passed) ok = false;
    }
    const total = this.results.length;
    const failed = this.results.filter(([, p]) => !p).length;
    return { name: this.name, ok, total, failed };
  }
}

module.exports = { loadPage, waitFor, Suite, HTML_PATH };
