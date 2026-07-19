// Series/season grouping, selection, and delete in the Library view.
const fs = require('fs');
const path = require('path');
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

const FIXTURE = path.join(__dirname, 'fixtures', 'mock_links.json');

async function run() {
  const suite = new Suite('Library: grouping, selection, delete');
  const mock = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
  // deep-clone so this run doesn't mutate the on-disk fixture or leak state
  // into other test modules that also load it.
  const data = JSON.parse(JSON.stringify(mock));

  const providersResp = { auth_required: false, providers: [{ name: 'mock', healthy: true, capabilities: ['delete'] }] };
  const deleteCalls = [];
  function fakeFetch(reqPath, opts = {}) {
    let body;
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) body = data;
    else if (reqPath.startsWith('/api/delete')) {
      const ids = JSON.parse(opts.body).ids;
      deleteCalls.push(ids);
      body = { deleted: Object.fromEntries(ids.map(i => [i, { ok: true }])) };
      data.links = data.links.filter(l => !ids.includes(l.id));
      data.count = data.links.length;
    } else body = {};
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { window } = dom;
  const { document } = window;
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];

  await waitFor(() => qa('.grp.series').length > 0);
  suite.assert('series groups rendered (Cosmos Lab, Pioneer One, Sintel Chronicles)', qa('.grp.series').length === 3);
  suite.assert('column header exists exactly once', qa('#thead').length === 1);
  suite.assert('4 standalone files rendered as loose rows', qa('#rows > .row').length === 4);
  suite.assert('seasons collapsed by default', qa('.grp.season').length === 0);

  const cosmos = qa('.grp.series').find(g => g.dataset.key.includes('cosmos lab'));
  cosmos.click();
  await waitFor(() => qa('.grp.season').length > 0);
  suite.assert('expanding a series reveals its seasons', qa('.grp.season').length === 3);

  const s1 = qa('.grp.season').find(g => g.dataset.key.endsWith('§1'));
  (s1 || qa('.grp.season')[0]).click();
  await waitFor(() => qa('.row.ep').length > 0);
  suite.assert('expanding a season reveals its episodes', qa('.row.ep').length === 3);

  const cosmos2 = qa('.grp.series').find(g => g.dataset.key.includes('cosmos lab'));
  const cbox = cosmos2.querySelector('.gsel');
  cbox.checked = true;
  cbox.dispatchEvent(new window.Event('change', { bubbles: true }));
  await waitFor(() => q('#tray').classList.contains('show'));
  suite.assert('series checkbox selects all 8 descendant episodes', q('#selCount').textContent === '8');

  const beforeCount = data.links.length;
  const cosmos3 = qa('.grp.series').find(g => g.dataset.key.includes('cosmos lab'));
  cosmos3.querySelector('.gdel').click();
  await waitFor(() => deleteCalls.length > 0 && qa('.grp.series').length === 2);
  suite.assert('group delete calls the API with all 8 descendant ids', deleteCalls[0] && deleteCalls[0].length === 8);
  suite.assert('deleted series disappears from the tree', !qa('.grp.series').some(g => g.dataset.key.includes('cosmos lab')));
  suite.assert('backing data reduced by 8 after delete', data.links.length === beforeCount - 8);

  q('#groupChk').checked = false;
  q('#groupChk').dispatchEvent(new window.Event('change', { bubbles: true }));
  await waitFor(() => qa('.grp').length === 0);
  suite.assert('toggling grouping off shows a flat list matching remaining data', qa('.grp').length === 0 && qa('#rows > .row').length === data.links.length);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
