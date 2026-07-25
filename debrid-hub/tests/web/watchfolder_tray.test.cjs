// JD2 tray: when a watch folder is configured, the clipboard option must
// stay available alongside "Start Download", not be replaced by it.
const fs = require('fs');
const path = require('path');
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

const FIXTURE = path.join(__dirname, 'fixtures', 'mock_links.json');

async function run() {
  const suite = new Suite('JD2 tray: clipboard and watch-folder buttons both available');
  const mock = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  const data = JSON.parse(JSON.stringify(mock));

  const providersResp = { auth_required: false, providers: [{ name: 'mock', healthy: true, capabilities: ['delete'] }] };
  const dropCalls = [];
  let clipboardWrites = 0;
  function fakeFetch(reqPath, opts = {}) {
    let body = {};
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) body = data;
    else if (reqPath.startsWith('/api/watchfolder/drop')) {
      const req = JSON.parse(opts.body);
      dropCalls.push(req);
      body = { ok: true, written: req.ids.length, file: 'Test_20260101-000000.txt', errors: null };
    } else if (reqPath.startsWith('/api/watchfolder')) body = { enabled: true, cleanup_minutes: 60 };
    else if (reqPath.startsWith('/api/resolve')) {
      const ids = JSON.parse(opts.body).ids;
      body = { resolved: Object.fromEntries(ids.map(i => [i, { url: 'https://resolved.example/' + i }])) };
    } else body = {};
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { window } = dom;
  const { document } = window;
  const q = s => document.querySelector(s);

  let clipboardText = null;
  window.navigator.clipboard.writeText = t => { clipboardText = t; clipboardWrites++; return Promise.resolve(); };

  await waitFor(() => q('.row .rsel'));
  await waitFor(() => q('#copyJd').dataset.mode === 'folder');

  suite.assert('watch-folder mode: primary button becomes Start Download', q('#copyJd').textContent.includes('Start Download'));
  suite.assert('watch-folder mode: clipboard button stays visible too', !q('#copyJdClipboard').hidden);
  suite.assert('clipboard button still says Copy for JD2', q('#copyJdClipboard').textContent.includes('Copy for JD2'));

  const cbox = q('.row .rsel');
  cbox.checked = true;
  cbox.dispatchEvent(new window.Event('change', { bubbles: true }));
  await waitFor(() => q('#tray').classList.contains('show'));

  q('#copyJd').click();
  await waitFor(() => dropCalls.length === 1);
  suite.assert('Start Download writes to the watch folder', dropCalls.length === 1);
  suite.assert('clipboard was not touched by Start Download', clipboardWrites === 0);

  q('#copyJdClipboard').click();
  await waitFor(() => clipboardWrites === 1);
  suite.assert('Copy for JD2 always copies to the clipboard, even in watch-folder mode', clipboardWrites === 1 && !!clipboardText);
  suite.assert('watch folder was not touched by the clipboard button', dropCalls.length === 1);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
