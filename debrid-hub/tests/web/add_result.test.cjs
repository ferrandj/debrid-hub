// Add-result popup: the exact request/response for a *failed* discover/add
// attempt must be visible and inspectable (not just a toast that vanishes),
// since diagnosing a stuck integration (e.g. AllDebrid via an addon) depends
// on seeing the addon's own status/detail. Successful adds should stay quiet
// (toast only) -- the user doesn't want a popup on the happy path.
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

async function run() {
  const suite = new Suite('Add-result popup: only shown on failure, with the exact call and response');

  const providersResp = { auth_required: false, providers: [] };
  const linksResp = { count: 0, total: 0, errors: {}, links: [] };
  const catalogSections = { sections: [{ addon_id: 'a1', addon_name: 'Cinemeta', type: 'movie', catalog_id: 'top', name: 'Popular' }] };
  const catalogItems = { items: [{ id: 'tt1', type: 'movie', name: 'Test Movie', poster: 'https://x/1.jpg', year: '2020' }] };
  const metaResp = { meta: { name: 'Test Movie', poster: 'https://x/1.jpg' } };
  const streamsResp = { streams: [
    { addon_id: 'a2', addon_name: 'Lumio', name: '[TB] Lumio release', token: 'TOKEN_OK' },
    { addon_id: 'a2', addon_name: 'Lumio', name: '[AD] Lumio release', token: 'TOKEN_FAIL' },
  ] };

  function fakeFetch(reqPath, opts = {}) {
    let body = {};
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) body = linksResp;
    else if (reqPath.startsWith('/api/addons')) body = { addons: [], store_error: null };
    else if (reqPath.startsWith('/api/discover/catalogs')) body = catalogSections;
    else if (reqPath.startsWith('/api/discover/catalog?')) body = catalogItems;
    else if (reqPath.startsWith('/api/discover/meta')) body = metaResp;
    else if (reqPath.startsWith('/api/discover/streams')) body = streamsResp;
    else if (reqPath.startsWith('/api/discover/add')) {
      const token = JSON.parse(opts.body).token;
      body = token === 'TOKEN_FAIL'
        ? { ok: false, status: 404, detail: 'Résolution impossible' }
        : { ok: true, status: 200, detail: null };
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { document } = dom.window;
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];

  await waitFor(() => q('#tabDiscover'));
  q('#tabDiscover').click();
  await waitFor(() => qa('.disc-card').length === 1);
  qa('.disc-card')[0].click();
  await waitFor(() => !q('#detailModal').hidden);
  await waitFor(() => qa('.src-item').length === 2);

  suite.assert('popup starts closed', q('#addResultModal').hidden);

  qa('.src-item button[data-token]')[0].click();
  await waitFor(() => q('#toast').classList.contains('show'));
  suite.assert('a successful add does not open the popup, only a toast', q('#addResultModal').hidden);
  suite.assert('success toast confirms the add', q('#toast').textContent.includes('Added'));

  qa('.src-item button[data-token]')[1].click();
  await waitFor(() => !q('#addResultModal').hidden);
  suite.assert('popup opens on a failed add', !q('#addResultModal').hidden);
  suite.assert('popup shows the failing status code', q('#addResultBody').textContent.includes('404'));
  suite.assert('popup shows the addon\'s own failure reason', q('#addResultBody').textContent.includes('Résolution impossible'));
  suite.assert('failed response is styled as an error', !!q('#addResultBody .st.err'));

  const ev = new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true });
  document.dispatchEvent(ev);
  suite.assert('Escape key closes the popup', q('#addResultModal').hidden);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
