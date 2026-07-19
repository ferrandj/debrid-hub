<p align="center"><img src="docs/assets/banner.png" alt="Debrid Hub — all your downloads, one powerful hub" width="720"/></p>

# Debrid Hub

One place to see every link across your debrid accounts — **Real-Debrid, AllDebrid, TorBox** — search and sort them, and copy direct URLs straight into **JDownloader2**. Ships a **CLI**, a **REST API**, and a **web UI** from a single container.

## What it does

- Aggregates links from every configured provider into one normalized list.
- Cross-debrid: you don't pick a service, it just shows everything.
- Search by filename/host, sort by name/size/date/host/provider/kind.
- **Series grouping**: TV episodes are folded into collapsible **Series › Seasons › Episodes** trees (parsed from filenames — `S01E02`, `1x02`, `Season 1 Episode 2`), so a show with 40 episodes is one row you can expand. Toggle it off for a flat list. Series names are matched case-insensitively (`From` and `FROM` merge).
- **Quality / language badges**: resolution (4K/2160p, 1080p, 720p, …), HDR/DV/REMUX, and language tags (Multi, VFF, VOSTFR, TrueFrench, …) are parsed from the filename and shown under each row.
- **Cross-provider dedup**: the same release cached by more than one debrid service shows up once — ties broken in favor of **TorBox**, then Real-Debrid, then AllDebrid.
- **Manage downloads in place**: delete a single file, a whole season, or an entire series — or multi-select and delete in bulk — straight from the UI/CLI/API. Deletions hit each provider's own API.
- Resolves the actual direct download URL on demand (links are metered/locked on some services, so this happens when you copy, not when you browse).
- **JD2 tray**: tick several links, hit *Copy for JD2*, and every direct URL lands on your clipboard newline-separated. JDownloader2 monitors the clipboard by default, so it auto-catches them into the LinkGrabber — or just paste.
- **Debug mode**: `?debug=true` on `/api/links`, `debrid-hub list --debug`, or the **🐛 Debug** button in the UI show the exact outbound request/response for every provider call that last listing made (secrets redacted) — for when a provider changes their API out from under you.

## Quick start (Docker, e.g. on your NAS)

```bash
cp .env.example .env      # fill in the keys you have
docker compose up -d --build
# open http://<nas-ip>:8080
```

Try it with no keys first:

```bash
DEBRID_HUB_MOCK=1 docker compose up --build
```

## Quick start (local)

```bash
pip install -e .
export DEBRID_REALDEBRID_TOKEN=...   # and/or the others
debrid-hub serve                     # http://localhost:8080
```

## Getting your keys

| Provider | Where |
|---|---|
| Real-Debrid | https://real-debrid.com/apitoken |
| AllDebrid | https://alldebrid.com/apikeys/ |
| TorBox | https://torbox.app/settings → Developer / API |

Set only the ones you use; empty vars disable that provider. You don't have to use
env vars at all — you can add keys later from the **UI, CLI, or API** (see below).

## Configuring keys (UI / CLI / API)

Keys can come from env vars **or** be saved at runtime, **encrypted at rest**
(Fernet / AES) under `DEBRID_HUB_DATA_DIR`. A key saved this way overrides the
matching env var; removing it falls back to the env var. Providers rebuild live —
no restart needed.

- **UI**: click **⚙ Keys**, paste a key per provider, Save.
- **CLI**: `debrid-hub config set realdebrid <key>` (omit the key to be prompted
  hidden), `debrid-hub config list`, `debrid-hub config remove <provider>`.
- **API**: `PUT /api/config` with `{"realdebrid":"…"}` (see REST table).

The store is encrypted with a master key from `DEBRID_HUB_SECRET_KEY`, or an
auto-generated `secret.key` kept alongside the store. In Docker, mount a volume at
`DEBRID_HUB_DATA_DIR` (the compose file does this) so keys survive a recreate.
Endpoints and CLI never echo a stored key back — only whether one is set.

## CLI

```bash
debrid-hub providers                 # credential health per service
debrid-hub config set torbox <key>   # save a key (encrypted); omit key to prompt
debrid-hub config list               # which providers are set + source
debrid-hub config remove torbox      # drop a stored key
debrid-hub list                      # table of everything
debrid-hub list -s ubuntu --sort size --order desc
debrid-hub list -p torbox -k torrent
debrid-hub list --urls               # direct URLs only, one per line
debrid-hub list -s 1080p --urls | xclip -selection clipboard   # → paste into JD2
debrid-hub list --json               # machine-readable
debrid-hub resolve <link-id>         # id comes from `list --json`
debrid-hub rm <link-id> [<id>…]      # delete link(s); -y to skip the prompt
debrid-hub list --debug              # force refresh + print raw provider requests/responses
debrid-hub serve --port 8080
```

> **Deleting is irreversible.** Real-Debrid and AllDebrid saved links delete just
> that link; AllDebrid magnets and every TorBox item delete the **whole
> torrent/magnet**, i.e. every file inside it. The UI/CLI warn before doing so.

## REST API

Base URL `http://host:8080`. If `DEBRID_HUB_API_KEY` is set, send `Authorization: Bearer <key>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/providers` | configured providers + health + each one's `capabilities` (e.g. `["delete"]`) |
| GET | `/api/config` | which provider keys are set + source (never the value) |
| PUT | `/api/config` | body `{"realdebrid":"…"}` → save key(s), encrypted; `""` clears |
| DELETE | `/api/config/{provider}` | remove a stored key |
| GET | `/api/links` | aggregated list; query: `search, provider, kind, sort, order, refresh, debug` |
| POST | `/api/resolve` | body `{"ids":["…"]}` (or `{"id":"…"}`) → direct URLs |
| POST | `/api/delete` | body `{"ids":["…"]}` (or `{"id":"…"}`) → delete from provider; per-id `{"ok":true}`/`{"error":…}` |
| GET | `/health` | liveness |

```bash
curl -s localhost:8080/api/links?search=ubuntu | jq '.links[0]'
curl -s -X POST localhost:8080/api/resolve \
  -H 'content-type: application/json' -d '{"ids":["<id>"]}'
curl -s -X POST localhost:8080/api/delete \
  -H 'content-type: application/json' -d '{"ids":["<id>"]}'
```

Interactive docs at `/docs` (Swagger UI) and the machine-readable schema at
`/openapi.json`, so you can wire this into other tools.

## Documentation

- [`docs/PRODUCT.md`](docs/PRODUCT.md) — product & architecture overview, written to be parsable by both people and AI agents.
- [`docs/API.md`](docs/API.md) — full REST reference with request/response shapes and examples.
- [`docs/openapi.json`](docs/openapi.json) — OpenAPI 3.1 spec (also served live at `/openapi.json`; Swagger UI at `/docs`).
- [`llms.txt`](llms.txt) — a compact index for LLMs/agents, following the [llms.txt](https://llmstxt.org) convention.

## Exposing it safely

Behind Cloudflare Tunnel or Tailscale, no extra auth is strictly needed. If it's reachable from the internet, set `DEBRID_HUB_API_KEY`; the UI will prompt for it once and remember it in your browser.

## Adding another debrid service

Subclass `Provider` in `src/debrid_hub/providers/`, implement `list_links()` and `resolve()`, and register it in `Aggregator._build()`. The UI and CLI pick it up automatically. Provider-specific data for resolving a link travels inside each link's opaque id, so the server stays stateless. To support deletion, set `capabilities = ("delete",)` and implement `delete(hint)`; carry whatever identifier the delete endpoint needs inside the link's `resolve_hint["del"]`.

## Notes

- The listing is cached for `DEBRID_HUB_CACHE_TTL` seconds (default 60); **Refresh** forces a re-fetch (and bypasses TorBox's own server-side listing cache too, so a just-deleted item doesn't reappear).
- Real-Debrid links come from your `/downloads` history (already direct). AllDebrid saved links + ready magnets and TorBox torrents/web/usenet are resolved when you copy them.
- AllDebrid only exposes file links for magnets whose status is **Ready**.
- Series grouping, quality/language badges, and cross-provider dedup are inferred client-side from filenames/size; they're display conveniences, not metadata from the providers. Files that don't match stay as-is.
- If a provider's listing comes back empty or wrong after they change their API, check `debrid-hub list --debug` (or `?debug=true` / the UI's Debug button) before assuming it's a credentials problem — it shows the exact request and response.
