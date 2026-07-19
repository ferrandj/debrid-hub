// Discover tab: browse sections, search, detail modal (meta+streams), Add
// button, and the Extensions settings modal.
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

async function run() {
  const suite = new Suite('Discover: browse, search, detail, extensions');

  const providersResp = { auth_required: false, providers: [] };
  const linksResp = { count: 0, total: 0, errors: {}, links: [] };
  let addonsList = [
    { id: 'a1', name: 'Cinemeta', resources: ['catalog', 'meta'], types: ['movie'], catalogs: [{ type: 'movie', id: 'top', name: 'Popular', searchable: true }] },
    { id: 'a2', name: 'Lumio', resources: ['stream'], types: ['movie'], catalogs: [] },
  ];
  const catalogSections = { sections: [{ addon_id: 'a1', addon_name: 'Cinemeta', type: 'movie', catalog_id: 'top', name: 'Popular' }] };
  const catalogItems = { items: [
    { id: 'tt1', type: 'movie', name: 'Test Movie One', poster: 'https://x/1.jpg', year: '2020' },
    { id: 'tt2', type: 'movie', name: 'Test Movie Two', poster: 'https://x/2.jpg', year: '2021' },
  ] };
  const searchItems = { items: [{ id: 'tt9', type: 'movie', name: 'French Fried Vacation', poster: 'https://x/9.jpg', year: '1978' }] };
  const metaResp = { meta: { name: 'Test Movie One', description: 'A test synopsis.', poster: 'https://x/1.jpg', background: 'https://x/bg.jpg', releaseInfo: '2020', imdbRating: '7.5', runtime: '95 min', genres: ['Comedy'], app_extras: { cast: [{ name: 'Actor A', character: 'Role A', photo: 'https://x/a.jpg' }] } } };
  const streamsResp = { streams: [
    { addon_id: 'a2', addon_name: 'Lumio', name: '[TB] Lumio', description: '1080p release', size: 5_000_000_000, filename: 'test.mkv', token: 'TOKEN123' },
    { addon_id: 'a2', addon_name: 'Lumio', name: '[AD] Lumio', description: '1080p release', size: 2_000_000_000, filename: 'test-ad.mkv', token: 'TOKEN_FAIL' },
  ] };

  const addCalls = [], delCalls = [], triggerCalls = [];
  function fakeFetch(reqPath, opts = {}) {
    const method = (opts && opts.method) || 'GET';
    let body = {};
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) body = linksResp;
    else if (reqPath.startsWith('/api/addons/') && method === 'DELETE') {
      delCalls.push(reqPath);
      addonsList = addonsList.filter(a => !reqPath.endsWith('/' + a.id));
      body = { ok: true };
    } else if (reqPath.startsWith('/api/addons') && method === 'POST') {
      addCalls.push(JSON.parse(opts.body).url);
      body = { ok: true, addon: { id: 'a3', name: 'New Addon', resources: ['catalog'], types: ['movie'], catalogs: [] } };
    } else if (reqPath.startsWith('/api/addons')) body = { addons: addonsList, store_error: null };
    else if (reqPath.startsWith('/api/discover/catalogs')) body = catalogSections;
    else if (reqPath.startsWith('/api/discover/catalog?')) body = catalogItems;
    else if (reqPath.startsWith('/api/discover/search')) body = searchItems;
    else if (reqPath.startsWith('/api/discover/meta')) body = metaResp;
    else if (reqPath.startsWith('/api/discover/streams')) body = streamsResp;
    else if (reqPath.startsWith('/api/discover/add')) {
      const token = JSON.parse(opts.body).token;
      triggerCalls.push(token);
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
  suite.assert('starts on Library view', !q('#libraryView').hidden && q('#discoverView').hidden);

  q('#tabDiscover').click();
  await waitFor(() => !q('#discoverView').hidden);
  suite.assert('switching tabs shows Discover, hides Library', q('#discoverView').hidden === false && q('#libraryView').hidden === true);
  suite.assert('tray is hidden on the Discover view', !q('#tray').classList.contains('show'));

  await waitFor(() => qa('.disc-section').length > 0);
  suite.assert('section header rendered from /api/discover/catalogs', q('.disc-section h3').textContent.includes('Cinemeta') && q('.disc-section h3').textContent.includes('Popular'));
  await waitFor(() => qa('.disc-card').length === 2);
  suite.assert('catalog items rendered as poster cards', qa('.disc-card').length === 2);
  suite.assert('card shows title/year', qa('.disc-title')[0].textContent === 'Test Movie One');

  q('#discoverQ').value = 'french';
  q('#discoverQ').dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  await waitFor(() => qa('.disc-card').length === 1 && qa('.disc-card')[0].dataset.id === 'tt9', 3000);
  suite.assert('search replaces the browse view with results', qa('.disc-card').length === 1 && q('.disc-title').textContent === 'French Fried Vacation');

  qa('.disc-card')[0].click();
  await waitFor(() => !q('#detailModal').hidden);
  await waitFor(() => q('#detailBody').innerHTML.includes('Test Movie One'));
  suite.assert('detail modal shows the meta name', q('#detailBody').innerHTML.includes('Test Movie One'));
  suite.assert('detail modal shows the description', q('#detailBody').innerHTML.includes('A test synopsis'));
  suite.assert('detail modal shows cast', q('.cast-card') !== null && q('.cast-card').textContent.includes('Actor A'));
  suite.assert('detail modal shows a background image', q('.detail-bg') !== null);
  await waitFor(() => qa('.src-item').length === 2);
  suite.assert('detail modal lists all stream sources', qa('.src-item').length === 2 && q('.src-item').textContent.includes('Lumio'));

  qa('.src-item button[data-token]')[0].click();
  await waitFor(() => triggerCalls.length === 1);
  suite.assert('Add button triggers discover/add with the right token', triggerCalls[0] === 'TOKEN123');
  await waitFor(() => q('#toast').classList.contains('show'));
  suite.assert('successful add shows a success toast', q('#toast').textContent.includes('Added'));

  qa('.src-item button[data-token]')[1].click();
  await waitFor(() => triggerCalls.length === 2);
  await waitFor(() => q('#toast').textContent.includes('Résolution impossible'));
  suite.assert('failed add surfaces the addon\'s own reason, not just a status code', q('#toast').textContent.includes('Résolution impossible'));
  suite.assert('failed add toast is styled as an error', q('#toast').classList.contains('err'));

  q('#detailClose').click();
  suite.assert('detail modal closes', q('#detailModal').hidden === true);

  q('#addonsBtn').click();
  await waitFor(() => !q('#addonsModal').hidden);
  await waitFor(() => qa('.addon-row').length === 2);
  suite.assert('extensions modal lists configured addons', qa('.addon-row').length === 2);
  suite.assert('extensions modal never displays a raw manifest url', !q('#addonsList').innerHTML.includes('manifest.json'));

  q('#addonUrlInput').value = 'https://example.com/manifest.json';
  q('#addonAddBtn').click();
  await waitFor(() => addCalls.length === 1);
  suite.assert('adding an extension posts the url', addCalls[0] === 'https://example.com/manifest.json');
  await waitFor(() => q('#addonUrlInput').value === '');
  suite.assert('input is cleared after a successful add', q('#addonUrlInput').value === '');

  const rmBtn = qa('.addon-rm')[0];
  const removedId = rmBtn.dataset.id;
  rmBtn.click();
  await waitFor(() => delCalls.length === 1);
  suite.assert('removing an extension calls DELETE with the right id', delCalls[0] === '/api/addons/' + removedId);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
