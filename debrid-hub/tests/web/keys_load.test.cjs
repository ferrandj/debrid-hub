// The "⟳ Load" button in the Keys panel: re-reads the encrypted store so a
// key written out-of-band (e.g. `debrid-hub config set` via docker exec)
// becomes visible without a restart.
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

async function run() {
  const suite = new Suite('Keys panel: Load button reloads store state');
  const providersResp = { auth_required: false, providers: [] };
  let configState = {
    providers: [
      { provider: 'realdebrid', configured: false, source: 'none' },
      { provider: 'alldebrid', configured: false, source: 'none' },
      { provider: 'torbox', configured: false, source: 'none' },
    ],
    encrypted: true, store_error: null,
  };
  const linksResp = { count: 0, total: 0, errors: {}, links: [] };
  const calls = [];

  function fakeFetch(path, opts = {}) {
    calls.push({ path, method: (opts && opts.method) || 'GET' });
    let body = {};
    if (path.startsWith('/api/providers')) body = providersResp;
    else if (path.startsWith('/api/config/reload')) {
      configState = { ...configState, providers: configState.providers.map(p => p.provider === 'torbox' ? { provider: 'torbox', configured: true, source: 'stored' } : p) };
      body = { ok: true, providers: configState.providers };
    } else if (path.startsWith('/api/config')) body = configState;
    else if (path.startsWith('/api/links')) body = linksResp;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { document } = dom.window;
  const q = s => document.querySelector(s);

  await waitFor(() => q('#settings'));
  q('#settings').click();
  await waitFor(() => !q('#cfgModal').hidden);

  suite.assert('Load button present in Keys modal', !!q('#cfgReload'));
  const rowBefore = [...document.querySelectorAll('.cfg-row')].find(r => r.textContent.includes('TorBox'));
  suite.assert('TorBox shows not-set before reload', rowBefore && rowBefore.textContent.includes('not set'));

  q('#cfgReload').click();
  await waitFor(() => calls.some(c => c.path === '/api/config/reload' && c.method === 'POST'));
  suite.assert('Load button POSTs to /api/config/reload', true);

  await waitFor(() => {
    const row = [...document.querySelectorAll('.cfg-row')].find(r => r.textContent.includes('TorBox'));
    return row && row.querySelector('.badge.stored');
  });
  suite.assert('modal refreshes to show TorBox as stored after Load', true);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
