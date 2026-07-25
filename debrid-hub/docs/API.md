<img src="assets/logo.png" alt="" width="48" height="48" align="left" style="margin-right:12px"/>

# Debrid Hub — REST API

Base URL: `http://<host>:8080`. Content type is JSON. The canonical machine-readable
contract is [`openapi.json`](openapi.json) (OpenAPI 3.1), also served live at
`/openapi.json` with Swagger UI at `/docs`.

## Authentication

If `DEBRID_HUB_API_KEY` is set on the server, every `/api/*` route requires:

```
Authorization: Bearer <key>
```

Missing/invalid key → `401`. If the var is unset, the API is open.

## Endpoints

### `GET /api/providers`
Configured providers, their health, and capabilities.

```json
{
  "auth_required": false,
  "providers": [
    { "name": "torbox", "healthy": true, "capabilities": ["delete"] },
    { "name": "realdebrid", "healthy": true, "capabilities": ["delete"] }
  ]
}
```

### `GET /api/config`
Which provider keys are set and where from — **never the key value**.

```json
{
  "providers": [
    { "provider": "realdebrid", "configured": true, "source": "stored" },
    { "provider": "alldebrid", "configured": false, "source": "none" },
    { "provider": "torbox", "configured": true, "source": "env" }
  ],
  "encrypted": true,
  "store_error": null
}
```

### `PUT /api/config`
Store provider keys (encrypted at rest). Send any subset of the three fields. An
empty string clears that key; a field you omit is left unchanged.

Request (`ConfigRequest`):
```json
{ "realdebrid": "abc…", "torbox": "" }
```
Response: `{ "ok": true, "providers": [ …credential status… ] }`

### `DELETE /api/config/{provider}`
Remove a stored key (`provider` ∈ `realdebrid|alldebrid|torbox`). Env vars, if any,
still apply afterwards. → `{ "ok": true, "providers": […] }`

### `POST /api/config/reload`
Re-read the encrypted store from disk and rebuild the live providers from it —
no body, no key changes. `GET /api/config` already always reflects the store
file's current contents, but the providers actually used for listing/resolving/
deleting only pick up a change on reload. Use this after writing to the store
out-of-band: `debrid-hub config set` run via `docker compose exec` while the
server is already running, or a `secrets.enc`/`secret.key` pair copied into the
mounted data directory from another host. → `{ "ok": true, "providers": […] }`
(same shape as `GET /api/config`). Also exposed as the **⟳ Load** button next to
Save in the UI's Keys panel.

### `GET /api/links`
Aggregated, normalized listing.

Query params: `search`, `provider`, `kind`, `sort` (`name|size|host|provider|added|kind`),
`order` (`asc|desc`), `refresh` (`true` bypasses the cache), `debug` (`true` implies
`refresh=true` and adds a `"debug"` field — see below).

```json
{
  "count": 42,
  "total": 42,
  "errors": { "alldebrid": "RuntimeError: …" },
  "links": [
    {
      "provider": "torbox",
      "name": "Cosmos.Lab.S01E02.1080p.WEB-DL.mkv",
      "size": 780000000,
      "host": "torbox",
      "kind": "torrent",
      "added": "2026-01-03T12:00:00+00:00",
      "direct_url": null,
      "id": "eyJoIjp7…",
      "resolvable": true
    }
  ]
}
```

`errors` maps a provider to why it couldn't be reached — including a *partial*
failure where the provider still returned some links but one section of its
listing broke (see `Provider.warnings` in [`PRODUCT.md`](PRODUCT.md)). `id` is
opaque — pass it to resolve/delete. `resolvable` is `true` when the direct URL
must be fetched via `/api/resolve`.

Series grouping, quality/language badges, and cross-provider dedup (same
release cached by multiple providers → one row, preferring TorBox) are all
**client-side** — this response is always the flat, undeduped list; see
[`PRODUCT.md`](PRODUCT.md) for that logic.

With `debug=true`, the response also includes:
```json
{
  "debug": {
    "alldebrid": [
      {
        "method": "GET",
        "url": "https://api.alldebrid.com/v4.1/magnet/status",
        "params": { "agent": "debrid-hub", "apikey": "***" },
        "status": 200,
        "body": "{\"status\":\"success\",\"data\":{...}}"
      }
    ]
  }
}
```
One entry per outbound HTTP call made while listing that provider. `apikey`/
`token`/`authorization` param values are always redacted to `"***"` before this
leaves the server; body is truncated to 4000 chars. Also available via
`debrid-hub list --debug` and the **🐛 Debug** button in the web UI.

### `POST /api/resolve`
Turn link ids into final direct download URLs (may be metered on some providers).

Request (`ResolveRequest`): `{ "ids": ["<id>", …] }` (or `{ "id": "<id>" }`).

```json
{ "resolved": {
    "<id1>": { "url": "https://…" },
    "<id2>": { "error": "ValueError: …" }
} }
```

### `POST /api/delete`
Delete links from their provider accounts. **Irreversible.** Some providers can only
delete a whole torrent/magnet, which removes every file inside it (see
[`PRODUCT.md`](PRODUCT.md#supported-providers)).

Request (`DeleteRequest`): `{ "ids": ["<id>", …] }` (or `{ "id": "<id>" }`).

```json
{ "deleted": {
    "<id1>": { "ok": true },
    "<id2>": { "error": "ValueError: alldebrid: this link cannot be deleted" }
} }
```
Each id is reported independently; one failure does not abort the others.

## Watch folder (JD2 FolderWatch, alongside the clipboard)

An addition to the clipboard-based "Copy for JD2" flow (not a replacement —
both stay available in the UI): write resolved URLs into a `.crawljob` file
inside a folder mounted into the container (`DEBRID_HUB_WATCH_DIR`) that
JDownloader2's **FolderWatch** extension is watching, so links get added to
the LinkGrabber without any clipboard step. `.crawljob` is JDownloader2's own
native link-container format — one `->NEW ENTRY<-` block per URL, each with
just a `text=<url>` field — parsed directly by FolderWatch's own container
plugin. See [`PRODUCT.md`](PRODUCT.md) and the README's "JD2: clipboard or
watch folder" section for setup, including the JD2-side Watch Folders
registration this depends on.

### `GET /api/watchfolder`
Whether a watch folder is configured, and the configured cleanup interval.
```json
{ "enabled": true, "cleanup_minutes": 60 }
```

### `POST /api/watchfolder/drop`
Resolve link ids and write a `.crawljob` file (one `->NEW ENTRY<-` block per
URL) into the watch folder. `400` if no watch folder is configured.

Request (`WatchFolderDropRequest`): `{ "ids": ["<id>", …], "name": "optional label" }`
(or `{ "id": "<id>" }`). `name` becomes the file's basename (sanitized,
truncated) — defaults to `"download"` for a single item or `"<n>_links"` for
several; a timestamp is always appended.
```json
{ "ok": true, "written": 2, "file": "Ubuntu_22.04_20260724-153012.crawljob", "errors": null }
```
`errors` (if non-null) maps ids that failed to resolve to their error message,
same shape as `/api/resolve`/`/api/delete` — partial success still writes the
file with whatever resolved.

### `GET /health`
Liveness. `{ "status": "ok", "providers": ["torbox","mock"] }`

## Discover: Stremio-protocol addons

Content-discovery addon manifest URLs are managed here — encrypted at rest like
provider keys, **never returned by any endpoint once stored**. See
[`PRODUCT.md`](PRODUCT.md#discover-browsesearch-content-via-stremio-protocol-addons)
for how the protocol side works.

### `GET /api/addons`
Configured addons. Safe summaries only.
```json
{ "addons": [
    { "id": "d29ee8b9d34b", "name": "Cinemeta",
      "description": "The official addon for movie and series catalogs",
      "resources": ["catalog","meta","addon_catalog"], "types": ["movie","series"],
      "catalogs": [ { "type": "movie", "id": "top", "name": "Popular", "searchable": true } ] }
  ], "store_error": null }
```

### `POST /api/addons`
Add (or update, if the same URL is already stored) an addon by its manifest URL.
Request (`AddAddonRequest`): `{ "url": "https://…/manifest.json" }`. The server
fetches and validates the manifest before storing anything — a bad URL is a
`400`, not a silently-stored broken entry.
```json
{ "ok": true, "addon": { "id": "…", "name": "…", "resources": […], "types": […], "catalogs": […] } }
```

### `DELETE /api/addons/{addon_id}`
Remove a stored addon. → `{ "ok": true }`

### `GET /api/discover/catalogs`
Every `(addon, catalog)` pair across all configured addons — what the UI's
Discover tab renders as one browsable section (e.g. one per streaming service,
if a per-service catalog addon is configured).
```json
{ "sections": [
    { "addon_id": "…", "addon_name": "Streaming Catalogs", "type": "movie",
      "catalog_id": "nfx", "name": "Netflix" }
  ] }
```

### `GET /api/discover/catalog`
Browse one catalog page. Query: `addon` (id), `type`, `catalog` (catalog id),
optional `genre`, `skip` (pagination offset).
```json
{ "items": [
    { "id": "tt0107290", "type": "movie", "name": "Jurassic Park", "year": "1993",
      "poster": "https://…", "description": "…", "imdbRating": "8.2" }
  ] }
```

### `GET /api/discover/search`
Search across every configured addon+catalog that declares search support, in
parallel, deduped by id. Query: `q` (required), optional `type`. Same item
shape as `catalog` above.

### `GET /api/discover/meta`
Enriched metadata for one item, merged across every addon with a `meta`
resource — first addon to set a field wins it, later ones fill gaps only.
Query: `type`, `id` (IMDb/TMDb/TVDB id, whatever the addon accepts).
`404` if no configured addon has metadata for it. Response is whatever the
addon(s) return — commonly `description`, `cast`/`app_extras.cast`, `poster`,
`background`, `landscapePoster`, `logo`, `genres`, `runtime`, `imdbRating`.

### `GET /api/discover/streams`
Stream/release options for one item, fanned out to every addon with a `stream`
resource. Query: `type`, `id`. **Raw urls never appear here** — each stream
carries an opaque `token` instead.
```json
{ "streams": [
    { "addon_id": "…", "addon_name": "Lumio · Osito", "name": "[TB⚡️] Lumio",
      "description": "2160p • WEB-DL • …", "size": 55395972448,
      "filename": "The.Matrix.1999….mkv", "token": "eyJhIjoiNTIx…" }
  ] }
```

### `POST /api/discover/add`
Resolve a chosen stream — fetches its real url server-side (token decoded,
host validated against the addon it claims to come from). For a
debrid-integrated addon, **this is the step that actually adds the release to
the user's debrid account** — irreversible in the same sense as adding any
torrent to a debrid service. Request (`TriggerRequest`): `{ "token": "…" }`.
```json
{ "ok": true, "status": 200 }
```
`ok` is `200 ≤ status < 400`. A magnet/torrent-backed addon can take a while to
resolve (this request can be slow); a hoster-link-backed one is instant-or-fail.
On failure, `detail` carries the addon's own reason when it gives one (e.g.
`"Résolution impossible"` from a hoster/debrid resolution error upstream).

## Favorites

Mark catalog items (movie or series) as favorites so they show up in their
own section at the top of the Discover tab. Stored **unencrypted** in
`favorites.json` next to the other stores — nothing here is secret, just an
id, type, and the display fields needed to render a poster card again
without re-querying any addon.

### `GET /api/favorites`
```json
{ "favorites": [
    { "type": "movie", "id": "tt0133093", "name": "The Matrix", "poster": "https://…",
      "year": "1999", "added_at": "2026-07-20T10:00:00+00:00" }
  ] }
```

### `POST /api/favorites`
Request (`FavoriteRequest`): `{ "type": "movie", "id": "tt0133093", "name": "…", "poster": "…", "year": "…" }`.
`name`/`poster`/`year` are optional but recommended — without them the
favorites section can only show the bare id. Re-adding the same `type`+`id`
overwrites the existing entry (and bumps `added_at`).
```json
{ "favorite": { "type": "movie", "id": "tt0133093", "name": "…", "poster": "…", "year": "…", "added_at": "…" } }
```

### `DELETE /api/favorites`
Query: `type`, `id`. → `{ "ok": true }`. Removing an id that isn't favorited
is not an error.

## Errors

- `400` — bad request body (e.g. no `id`/`ids`, `PUT /api/config` with no known field, an addon URL that isn't a valid manifest, a discover/add token with a host mismatch).
- `401` — missing/invalid Bearer key (when auth is enabled).
- `404` — unknown provider on `DELETE /api/config/{provider}`, unknown addon id on `/api/discover/catalog`, or no addon has metadata for `/api/discover/meta`.
- `500` — server/store failure (message in `detail`).
- `502` — an addon request itself failed (`/api/discover/catalog`, `/api/discover/add`).

Per-item failures in `/api/resolve` and `/api/delete` are **not** HTTP errors — they
appear as `{"error": …}` inside the `200` response so partial success is visible.

## Examples

```bash
# list, resolve, delete
curl -s localhost:8080/api/links?search=cosmos | jq '.links[0].id'
curl -s -X POST localhost:8080/api/resolve -H 'content-type: application/json' -d '{"ids":["<id>"]}'
curl -s -X POST localhost:8080/api/delete  -H 'content-type: application/json' -d '{"ids":["<id>"]}'

# with auth
curl -s localhost:8080/api/links -H "Authorization: Bearer $DEBRID_HUB_API_KEY"

# discover: add an addon, search, get sources, add one to your debrid account
curl -s -X POST localhost:8080/api/addons -H 'content-type: application/json' \
  -d '{"url":"https://v3-cinemeta.strem.io/manifest.json"}'
curl -s "localhost:8080/api/discover/search?q=matrix&type=movie" | jq '.items[0].id'
curl -s "localhost:8080/api/discover/streams?type=movie&id=tt0133093" | jq '.streams[0].token'
curl -s -X POST localhost:8080/api/discover/add -H 'content-type: application/json' \
  -d '{"token":"<token from above>"}'
```
