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

### `GET /health`
Liveness. `{ "status": "ok", "providers": ["torbox","mock"] }`

## Errors

- `400` — bad request body (e.g. no `id`/`ids`, or `PUT /api/config` with no known field).
- `401` — missing/invalid Bearer key (when auth is enabled).
- `404` — unknown provider on `DELETE /api/config/{provider}`.
- `500` — server/store failure (message in `detail`).

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
```
