// Series detail: streams must not be fetched until a season AND episode are
// picked (a series' own id has no per-episode streams in the Stremio
// protocol -- the real id is "{imdbId}:{season}:{episode}").
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

async function run() {
  const suite = new Suite('Series detail: season/episode picker gates the stream fetch');

  const providersResp = { auth_required: false, providers: [] };
  const linksResp = { count: 0, total: 0, errors: {}, links: [] };
  const searchItems = { items: [{ id: 'tt50', type: 'series', name: 'Test Show', poster: 'https://x/50.jpg', year: '2019' }] };
  const metaResp = {
    meta: {
      name: 'Test Show', description: 'A test series.', poster: 'https://x/50.jpg',
      videos: [
        { id: 'tt50:1:1', season: 1, episode: 1, name: 'Pilot' },
        { id: 'tt50:1:2', season: 1, episode: 2, name: 'Second' },
        { id: 'tt50:2:1', season: 2, episode: 1, name: 'Return' },
      ],
    },
  };
  const streamsByVideo = {
    'tt50:1:1': [{ addon_id: 'a2', addon_name: 'Lumio', name: 'Pilot release', size: 1_000_000_000, token: 'TOK_S1E1' }],
    'tt50:2:1': [{ addon_id: 'a2', addon_name: 'Lumio', name: 'Return release', size: 1_500_000_000, token: 'TOK_S2E1' }],
  };

  const streamsCalls = [];
  function fakeFetch(reqPath) {
    let body = {};
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) body = linksResp;
    else if (reqPath.startsWith('/api/addons')) body = { addons: [], store_error: null };
    else if (reqPath.startsWith('/api/discover/search')) body = searchItems;
    else if (reqPath.startsWith('/api/discover/meta')) body = metaResp;
    else if (reqPath.startsWith('/api/discover/streams')) {
      const id = decodeURIComponent(reqPath.split('id=')[1].split('&')[0]);
      streamsCalls.push(id);
      body = { streams: streamsByVideo[id] || [] };
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { document } = dom.window;
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];

  await waitFor(() => q('#tabDiscover'));
  q('#tabDiscover').click();
  await waitFor(() => !q('#discoverView').hidden);

  q('#discoverQ').value = 'test show';
  q('#discoverQ').dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  await waitFor(() => qa('.disc-card').length === 1, 3000);

  qa('.disc-card')[0].click();
  await waitFor(() => !q('#detailModal').hidden);
  await waitFor(() => q('#detailBody').innerHTML.includes('Test Show'));

  await waitFor(() => qa('.season-chip').length === 2);
  suite.assert('season chips rendered for every distinct season', qa('.season-chip').length === 2);
  suite.assert('season 1 is selected by default', qa('.season-chip')[0].classList.contains('on') && qa('.season-chip')[0].textContent.includes('1'));

  await waitFor(() => qa('.ep-row').length === 2);
  suite.assert('episode list shows only season 1 episodes', qa('.ep-row').length === 2 && q('.ep-title').textContent === 'Pilot');
  suite.assert('sources are not fetched before an episode is picked', streamsCalls.length === 0);
  suite.assert('a placeholder asks the user to pick an episode', q('#detailBody').textContent.includes('Select an episode'));

  qa('.season-chip')[1].click();
  await waitFor(() => qa('.ep-row').length === 1 && q('.ep-title').textContent === 'Return');
  suite.assert('switching season swaps the episode list', qa('.ep-row').length === 1 && q('.ep-title').textContent === 'Return');
  suite.assert('switching season alone still does not fetch streams', streamsCalls.length === 0);

  qa('.ep-row')[0].click();
  await waitFor(() => streamsCalls.length === 1);
  suite.assert('clicking an episode fetches streams for its season:episode id', streamsCalls[0] === 'tt50:2:1');
  await waitFor(() => qa('.src-item').length === 1);
  suite.assert('that episode\'s sources render', qa('.src-item').length === 1 && q('.src-item').textContent.includes('Return release'));

  qa('.season-chip')[0].click();
  await waitFor(() => qa('.ep-row').length === 2);
  qa('.ep-row')[0].click();
  await waitFor(() => streamsCalls.length === 2);
  suite.assert('picking a different episode fetches its own sources', streamsCalls[1] === 'tt50:1:1');
  await waitFor(() => q('.src-item').textContent.includes('Pilot release'));
  suite.assert('episode-specific sources are not mixed up across episodes', q('.src-item').textContent.includes('Pilot release'));

  qa('.season-chip')[1].click();
  await waitFor(() => qa('.ep-row').length === 1);
  qa('.ep-row')[0].click();
  await waitFor(() => q('.src-item').textContent.includes('Return release'));
  suite.assert('revisiting an already-loaded episode is cached, not refetched', streamsCalls.length === 2);

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
