// Debug modal must scroll (was unbounded height) and collapse per provider.
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

async function run() {
  const suite = new Suite('Debug modal: scroll + per-provider collapse');
  const providersResp = { auth_required: false, providers: [{ name: 'mock', healthy: true, capabilities: ['delete'] }] };
  const linksResp = {
    count: 0, total: 0, errors: {}, links: [],
    debug: {
      alldebrid: Array.from({ length: 5 }, (_, i) => ({
        method: 'GET', url: 'https://api.alldebrid.com/v4/x' + i,
        params: { agent: 'debrid-hub', apikey: '***' }, status: 200,
        body: '{"ok":true,"payload":"' + 'x'.repeat(200) + '"}',
      })),
      torbox: [{ method: 'GET', url: 'https://api.torbox.app/v1/api/torrents/mylist', params: { bypass_cache: 'true' }, status: 200, body: '{"data":[]}' }],
    },
  };
  function fakeFetch(path) {
    let body = {};
    if (path.startsWith('/api/providers')) body = providersResp;
    else if (path.startsWith('/api/links')) body = linksResp;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { window } = dom;
  const { document } = window;
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];

  await waitFor(() => q('#debugBtn'));
  q('#debugBtn').click();
  await waitFor(() => !q('#debugModal').hidden);

  const providers = qa('.dbg-provider');
  suite.assert('two provider sections rendered', providers.length === 2);
  suite.assert('each provider section is a native <details>', providers.every(p => p.tagName === 'DETAILS'));
  suite.assert('provider sections start open', providers.every(p => p.open));

  const alldebridSection = providers.find(p => p.querySelector('summary').textContent.includes('alldebrid'));
  alldebridSection.open = false;
  suite.assert('a provider section can be collapsed', alldebridSection.open === false);

  const cardStyle = window.getComputedStyle(q('.debug-card'));
  const bodyStyle = window.getComputedStyle(q('#debugBody'));
  suite.assert('.debug-card has a bounded max-height', cardStyle.maxHeight && cardStyle.maxHeight !== 'none');
  suite.assert('.debug-card is a flex column (header/note/actions stay fixed)', cardStyle.display === 'flex' && cardStyle.flexDirection === 'column');
  suite.assert('#debugBody scrolls independently (overflow-y: auto)', bodyStyle.overflowY === 'auto');
  suite.assert('#debugBody can shrink within the flex column (min-height: 0)', parseFloat(bodyStyle.minHeight) === 0);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
