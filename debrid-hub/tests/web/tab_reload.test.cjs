// Clicking back to the Library tab must reload its content -- otherwise a
// link added elsewhere (e.g. via Discover) wouldn't show up until the user
// remembered to hit the separate Refresh button.
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

async function run() {
  const suite = new Suite('Library tab reloads its content when switched back to');

  const providersResp = { auth_required: false, providers: [] };
  const linksResp = { count: 0, total: 0, errors: {}, links: [] };
  const linksCalls = [];
  function fakeFetch(reqPath) {
    let body = {};
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) { linksCalls.push(reqPath); body = linksResp; }
    else if (reqPath.startsWith('/api/addons')) body = { addons: [], store_error: null };
    else if (reqPath.startsWith('/api/discover/catalogs')) body = { sections: [] };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { document } = dom.window;
  const q = s => document.querySelector(s);

  await waitFor(() => q('#tabDiscover'));
  await waitFor(() => linksCalls.length === 1);
  suite.assert('one /api/links call on initial boot', linksCalls.length === 1);

  q('#tabDiscover').click();
  await waitFor(() => !q('#discoverView').hidden);
  suite.assert('switching to Discover does not itself reload Library', linksCalls.length === 1);

  q('#tabLibrary').click();
  await waitFor(() => linksCalls.length === 2);
  suite.assert('switching back to Library triggers a fresh /api/links call', linksCalls.length === 2);
  suite.assert('the reload forces a real refresh, not a cached read', linksCalls[1].includes('refresh=true'));

  q('#tabDiscover').click();
  await waitFor(() => !q('#discoverView').hidden);
  q('#tabLibrary').click();
  await waitFor(() => linksCalls.length === 3);
  q('#tabLibrary').click();
  suite.assert('clicking the already-active Library tab again does not reload', linksCalls.length === 3);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
