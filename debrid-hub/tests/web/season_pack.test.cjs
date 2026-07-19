// Redundant whole-season files (season .nfo, "complete season" release) move
// into a greyed "To ignore" group once per-episode files for that season exist.
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

const mkLink = (id, name, size) => ({
  id, name, size, provider: 'torbox', host: 'torbox', kind: 'torrent', added: '2026-01-01T00:00:00Z',
  direct_url: null, resolvable: true,
});

async function run() {
  const suite = new Suite('Library: redundant season-pack -> "To ignore"');
  let links = [
    mkLink('e1', 'Show.Name.S02E01.1080p.mkv', 900000000),
    mkLink('e2', 'Show.Name.S02E02.1080p.mkv', 900000000),
    mkLink('e3', 'Show.Name.S02E03.1080p.mkv', 900000000),
    mkLink('pack', 'Show.Name.S02.COMPLETE.1080p.mkv', 2700000000),
    mkLink('lonepack', 'Other.Show.S03.COMPLETE.1080p.mkv', 2700000000), // no per-episode alt -> stays normal
  ];
  const providersResp = { auth_required: false, providers: [{ name: 'torbox', healthy: true, capabilities: ['delete'] }] };
  const deleteCalls = [];
  function fakeFetch(reqPath, opts = {}) {
    let body = {};
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) body = { count: links.length, total: links.length, errors: {}, links };
    else if (reqPath.startsWith('/api/delete')) {
      const ids = JSON.parse(opts.body).ids;
      deleteCalls.push(ids);
      body = { deleted: Object.fromEntries(ids.map(i => [i, { ok: true }])) };
      links = links.filter(l => !ids.includes(l.id));
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { window } = dom;
  const { document } = window;
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];

  await waitFor(() => qa('.grp.series').length > 0);
  suite.assert('lone season-pack (no per-episode alt) stays a normal row', [...document.querySelectorAll('#rows > .row .name')].some(n => n.textContent.includes('Other.Show.S03.COMPLETE')));

  const ignoreGrp = q('.grp.ignore');
  suite.assert('"To ignore" group renders for the redundant pack', !!ignoreGrp);
  suite.assert('ignore group reports 1 item', ignoreGrp && ignoreGrp.querySelector('.gmeta').textContent.includes('1 item'));
  suite.assert('ignore group is visually de-emphasized', window.getComputedStyle(ignoreGrp).opacity === '0.55');
  suite.assert('redundant pack is not a normal top-level row', ![...document.querySelectorAll('#rows > .row .name')].some(n => n.textContent.includes('COMPLETE') && n.textContent.includes('Show.Name')));

  ignoreGrp.click();
  await waitFor(() => qa('.row.ep').some(r => r.textContent.includes('S02.COMPLETE')));
  suite.assert('expanding "To ignore" reveals the redundant file', true);

  const ignoreGrp2 = q('.grp.ignore');
  const cbox = ignoreGrp2.querySelector('.gsel');
  cbox.checked = true;
  cbox.dispatchEvent(new window.Event('change', { bubbles: true }));
  await waitFor(() => q('#tray').classList.contains('show'));
  suite.assert('selecting the ignore group selects its item', q('#selCount').textContent === '1');

  q('.grp.ignore').querySelector('.gdel').click();
  await waitFor(() => deleteCalls.length > 0);
  suite.assert('deleting the ignore group targets the right id', deleteCalls[0] && deleteCalls[0][0] === 'pack');
  await waitFor(() => !q('.grp.ignore'));
  suite.assert('ignore group disappears once its only item is gone', true);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
