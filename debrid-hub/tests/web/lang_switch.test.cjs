// French/English language switch: flags toggle UI text and persist the choice.
const { loadPage, waitFor, Suite } = require('./_harness.cjs');

async function run() {
  const suite = new Suite('Language switch: EN/FR flags');

  const providersResp = { auth_required: false, providers: [] };
  const linksResp = { count: 0, total: 0, errors: {}, links: [] };
  function fakeFetch(reqPath) {
    let body = {};
    if (reqPath.startsWith('/api/providers')) body = providersResp;
    else if (reqPath.startsWith('/api/links')) body = linksResp;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  }

  const dom = loadPage({ fetchImpl: fakeFetch });
  const { document } = dom.window;
  const q = s => document.querySelector(s);

  await waitFor(() => q('#langSwitch'));
  await waitFor(() => q('#rows') && q('#rows').textContent.trim().length > 0);

  suite.assert('starts in English', q('#tabLibrary').textContent === 'Library');
  suite.assert('English flag marked active by default', q('.lang-btn[data-lang="en"]').classList.contains('on'));
  suite.assert('French flag not active by default', !q('.lang-btn[data-lang="fr"]').classList.contains('on'));
  suite.assert('empty-library message is in English', q('#rows').textContent.includes('Nothing here'));

  q('.lang-btn[data-lang="fr"]').click();
  await waitFor(() => q('#tabLibrary').textContent === 'Bibliothèque');

  suite.assert('switching to French updates static labels', q('#tabLibrary').textContent === 'Bibliothèque' && q('#tabDiscover').textContent === 'Découvrir');
  suite.assert('French flag becomes active', q('.lang-btn[data-lang="fr"]').classList.contains('on'));
  suite.assert('English flag becomes inactive', !q('.lang-btn[data-lang="en"]').classList.contains('on'));
  suite.assert('dynamic content re-renders in French', q('#rows').textContent.includes('Rien ici'));
  suite.assert('choice is persisted to localStorage', dom.window.localStorage.getItem('debridhub_lang') === 'fr');
  suite.assert('<html lang> attribute updates', document.documentElement.lang === 'fr');

  q('.lang-btn[data-lang="en"]').click();
  await waitFor(() => q('#tabLibrary').textContent === 'Library');
  suite.assert('switching back to English works', q('#tabLibrary').textContent === 'Library');
  suite.assert('English persisted', dom.window.localStorage.getItem('debridhub_lang') === 'en');

  return suite.report();
}

module.exports = { run };
if (require.main === module) {
  run().then(r => process.exit(r.ok ? 0 : 1)).catch(e => { console.error(e); process.exit(2); });
}
