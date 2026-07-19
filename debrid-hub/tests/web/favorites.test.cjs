// Favorites: mark a catalog item (or a series/movie in the detail modal) as
// favorite, see it in its own "Favorites" section at the top of the browse
// view, and have the star state stay in sync across every card for that item.
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

async function run() {
  const suite = new Suite('Favorites: mark in catalog, see them in the catalog');

  const providersResp = { auth_required: false, providers: [] };
  const linksResp = { count: 0, total: 0, errors: {}, links: [] };
  const catalogSections = { sections: [{ addon_id: 'a1', addon_name: 'Cinemeta', type: 'movie', catalog_id: 'top', name: 'Popular' }] };
  const catalogItems = { items: [
    { id: 'tt1', type: 'movie', name: 'Movie One', poster: 'https://x/1.jpg', year: '2020' },
    { id: 'tt2', type: 'movie', name: 'Movie Two', poster: 'https://x/2.jpg', year: '2021' },
  ] };
  const metaByID = {
    tt2: { name: 'Movie Two', poster: 'https://x/2.jpg', releaseInfo: '2021', description: 'A test movie.' },
  };

  let favorites = [];
  const postCalls = [], deleteCalls = [];
  function fakeFetch(reqPath, opts = {}) {
    const method = (opts && opts.method) || 'GET';
    let body = {};
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) body = linksResp;
    else if (reqPath.startsWith('/api/addons')) body = { addons: [], store_error: null };
    else if (reqPath.startsWith('/api/discover/catalogs')) body = catalogSections;
    else if (reqPath.startsWith('/api/discover/catalog?')) body = catalogItems;
    else if (reqPath.startsWith('/api/discover/meta')) {
      const id = decodeURIComponent(reqPath.split('id=')[1].split('&')[0]);
      body = { meta: metaByID[id] || { name: id } };
    } else if (reqPath.startsWith('/api/discover/streams')) body = { streams: [] };
    else if (reqPath.startsWith('/api/favorites') && method === 'POST') {
      const req = JSON.parse(opts.body);
      postCalls.push(req);
      favorites = favorites.filter(f => !(f.type === req.type && f.id === req.id));
      const entry = { ...req, added_at: new Date().toISOString() };
      favorites.unshift(entry);
      body = { favorite: entry };
    } else if (reqPath.startsWith('/api/favorites') && method === 'DELETE') {
      const url = new URL('http://x' + reqPath);
      const type = url.searchParams.get('type'), id = url.searchParams.get('id');
      deleteCalls.push({ type, id });
      favorites = favorites.filter(f => !(f.type === type && f.id === id));
      body = { ok: true };
    } else if (reqPath.startsWith('/api/favorites')) body = { favorites };
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { document } = dom.window;
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];

  await waitFor(() => q('#tabDiscover'));
  q('#tabDiscover').click();
  await waitFor(() => qa('.disc-card').length === 2);

  suite.assert('cards start unfavorited', qa('.fav-btn').every(b => !b.classList.contains('on') && b.textContent === '☆'));
  suite.assert('no favorites section yet', !q('#favSection'));

  const card1Fav = qa('.disc-card')[0].querySelector('.fav-btn');
  card1Fav.click();
  await waitFor(() => postCalls.length === 1);
  suite.assert('clicking the star favorites the item via POST', postCalls[0].type === 'movie' && postCalls[0].id === 'tt1' && postCalls[0].name === 'Movie One');
  suite.assert('clicking the star does not open the detail modal', q('#detailModal').hidden);

  await waitFor(() => !!q('#favSection'));
  suite.assert('a Favorites section appears at the top of the catalog', !!q('#favSection'));
  suite.assert('the clicked card is now marked as favorited', card1Fav.classList.contains('on') && card1Fav.textContent === '★');
  await waitFor(() => qa('#favSection .disc-card').length === 1);
  suite.assert('the favorited item appears inside the Favorites section', q('#favSection .disc-title').textContent === 'Movie One');
  suite.assert('the item still also appears in its normal catalog row', qa('.disc-card').length === 3);

  // Open the second (unfavorited) item's detail and favorite it from there.
  qa('.disc-card').find(c => c.dataset.id === 'tt2').click();
  await waitFor(() => !q('#detailModal').hidden);
  await waitFor(() => q('#detailBody').innerHTML.includes('Movie Two'));
  const detailFav = q('.fav-btn.detail-fav');
  suite.assert('detail modal shows an unfilled star for an unfavorited item', detailFav && !detailFav.classList.contains('on'));

  detailFav.click();
  await waitFor(() => postCalls.length === 2);
  suite.assert('favoriting from the detail modal posts the right item', postCalls[1].type === 'movie' && postCalls[1].id === 'tt2' && postCalls[1].name === 'Movie Two');
  await waitFor(() => detailFav.classList.contains('on'));
  suite.assert('the detail star fills in immediately', detailFav.classList.contains('on') && detailFav.textContent === '★');

  q('#detailClose').click();
  await waitFor(() => qa('#favSection .disc-card').length === 2);
  suite.assert('favoriting from the detail modal also updates the catalog Favorites section', qa('#favSection .disc-card').length === 2);

  // Unfavorite tt1 from inside the Favorites section itself.
  const favSectionTt1Btn = qa('#favSection .disc-card').find(c => c.dataset.id === 'tt1').querySelector('.fav-btn');
  favSectionTt1Btn.click();
  await waitFor(() => deleteCalls.length === 1);
  suite.assert('unfavoriting sends a DELETE with the right type/id', deleteCalls[0].type === 'movie' && deleteCalls[0].id === 'tt1');

  await waitFor(() => qa('#favSection .disc-card').length === 1);
  suite.assert('the item is removed from the Favorites section', qa('#favSection .disc-card').length === 1 && q('#favSection .disc-title').textContent === 'Movie Two');
  const catalogTt1Btn = qa('.disc-card').find(c => c.dataset.id === 'tt1' && !c.closest('#favSection')).querySelector('.fav-btn');
  suite.assert('the matching card in the normal catalog row is unmarked too', !catalogTt1Btn.classList.contains('on') && catalogTt1Btn.textContent === '☆');

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
