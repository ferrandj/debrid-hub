<p align="center"><img src="docs/assets/banner.png" alt="Debrid Hub — all your downloads, one powerful hub" width="720"/></p>

# Debrid Hub

One place to see every link across your debrid accounts — **Real-Debrid, AllDebrid, TorBox** — search and sort them, and copy direct URLs straight into **JDownloader2**. Ships a **CLI**, a **REST API**, and a **web UI** from a single container.

## What it does

- Aggregates links from every configured provider into one normalized list.
- Cross-debrid: you don't pick a service, it just shows everything.
- Search by filename/host, sort by name/size/date/host/provider/kind.
- **Series grouping**: TV episodes are folded into collapsible **Series › Seasons › Episodes** trees (parsed from filenames — `S01E02`, `1x02`, `Season 1 Episode 2`), so a show with 40 episodes is one row you can expand. Toggle it off for a flat list. Series names are matched case-insensitively (`From` and `FROM` merge). A leftover whole-season file (season-level `.nfo`, or a "complete season" single release) alongside real per-episode files gets tucked into a greyed-out **To ignore** group instead of cluttering the top level.
- **Quality / language badges**: resolution (4K/2160p, 1080p, 720p, …), HDR/DV/REMUX, and language tags (Multi, VFF, VOSTFR, TrueFrench, …) are parsed from the filename and shown under each row.
- **Cross-provider dedup**: the same release cached by more than one debrid service shows up once — ties broken in favor of **TorBox**, then Real-Debrid, then AllDebrid.
- **Manage downloads in place**: delete a single file, a whole season, or an entire series — or multi-select and delete in bulk — straight from the UI/CLI/API. Deletions hit each provider's own API.
- Resolves the actual direct download URL on demand (links are metered/locked on some services, so this happens when you copy, not when you browse).
- **JD2 tray**: tick several links, hit *Copy for JD2*, and every direct URL lands on your clipboard newline-separated. JDownloader2 monitors the clipboard by default, so it auto-catches them into the LinkGrabber — or just paste.
- **JD2 watch folder (alternative to clipboard)**: set `DEBRID_HUB_WATCH_DIR` to a folder mounted into the container and the tray button becomes **Start Download** — instead of copying to the clipboard, it writes a `.txt` file (named after what you're downloading + a timestamp) with one URL per line straight into that folder, for JDownloader2's own **FolderWatch** extension to pick up. Optionally set `DEBRID_HUB_WATCH_CLEANUP_MINUTES` to auto-purge files from that folder once they're older than N minutes. See [JD2: clipboard or watch folder](#jd2-clipboard-or-watch-folder) below.
- **Debug mode**: `?debug=true` on `/api/links`, `debrid-hub list --debug`, or the **🐛 Debug** button in the UI show the exact outbound request/response for every provider call that last listing made (secrets redacted) — for when a provider changes their API out from under you.
- **Discover**: a separate tab that browses/searches content through **Stremio-protocol addons** you configure — metadata (posters, cast, descriptions) and, for debrid-integrated addons, sources you can push straight into a debrid account with one click. No Stremio app needed. See [Discover](#discover-content-via-stremio-addons) below.

## Quick start (Docker, e.g. on your NAS)

`docker-compose.yml` pulls the published image (`ghcr.io/ferrandj/debrid-hub`,
built for amd64+arm64 by CI on every push to master) — no build step needed on
the NAS itself:

```bash
cp .env.example .env      # fill in the keys you have
docker login ghcr.io -u <github-username>   # one-time: package is private, see below
docker compose pull
docker compose up -d
# open http://<nas-ip>:8080
```

**Updating later is just:**
```bash
docker compose pull && docker compose up -d
```

The GHCR package inherits this repo's (private) visibility, so pulling it
needs a one-time login with a GitHub personal access token that has the
`read:packages` scope: `echo <token> | docker login ghcr.io -u <github-username>
--password-stdin`. Generate one at github.com/settings/tokens.

Prefer to build on the NAS instead of pulling? In `docker-compose.yml`, comment
out `image:` and uncomment `build: .`, then `docker compose up -d --build`.

Try it with no keys first:

```bash
DEBRID_HUB_MOCK=1 docker compose up -d
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

**Never want a key in cleartext anywhere (compose file, shell history, env)?**
Skip env vars and the `PUT /api/config` route entirely — write straight into the
encrypted store instead, then tell the running server to pick it up:

```bash
docker compose exec debrid-hub debrid-hub config set torbox <key>   # writes to the encrypted store only
curl -X POST localhost:8080/api/config/reload                       # or the ⟳ Load button in ⚙ Keys
```

`GET /api/config` always reflects the store's current contents, but the live
providers used for listing/resolving/deleting only pick up a change on reload —
that's what `POST /api/config/reload` (and the UI's **⟳ Load** button) is for.
This is also how you move the store between hosts: copy `secrets.enc` +
`secret.key` from one `DEBRID_HUB_DATA_DIR` into another (matching
`DEBRID_HUB_SECRET_KEY` if you didn't use the generated key file), then Load.

## JD2: clipboard or watch folder

By default, the tray's **Copy for JD2** button resolves selected links and
copies them to your clipboard, newline-separated; JDownloader2 monitors the
clipboard by default and auto-catches them into the LinkGrabber.

If you'd rather not rely on the clipboard (headless server, JD2 on a
different machine, browser clipboard permissions, etc.), mount a folder into
the container and point `DEBRID_HUB_WATCH_DIR` at it:

```yaml
volumes:
  - /path/on/host/jd2-watch:/watch
environment:
  DEBRID_HUB_WATCH_DIR: "/watch"
  DEBRID_HUB_WATCH_CLEANUP_MINUTES: "60"   # optional, see below
```

Point JDownloader2's **FolderWatch** extension (Settings → Advanced Settings
→ search "folderwatch") at that same host folder. Once `DEBRID_HUB_WATCH_DIR`
is set, the tray button changes to **Start Download**: instead of copying to
the clipboard, it resolves the selected links and writes one `.txt` file —
named after what you're downloading plus a timestamp (e.g.
`Ubuntu_22.04_20260724-153012.txt`), one URL per line — straight into the
watched folder. JD2's FolderWatch picks it up on its next scan and adds the
links to the LinkGrabber, same as a clipboard catch.

Set `DEBRID_HUB_WATCH_CLEANUP_MINUTES` (minutes; unset or `0` disables) to
have Debrid Hub periodically delete files from that folder once they're older
than that many minutes — handy so leftover/ignored drop files don't pile up.
This only prunes by file age; JD2's own FolderWatch settings control whether
*it* deletes/moves a file after successfully importing it.

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
| POST | `/api/config/reload` | re-read the encrypted store from disk and rebuild providers, without changing any key |
| GET | `/api/links` | aggregated list; query: `search, provider, kind, sort, order, refresh, debug` |
| POST | `/api/resolve` | body `{"ids":["…"]}` (or `{"id":"…"}`) → direct URLs |
| POST | `/api/delete` | body `{"ids":["…"]}` (or `{"id":"…"}`) → delete from provider; per-id `{"ok":true}`/`{"error":…}` |
| GET | `/api/watchfolder` | whether a JD2 watch folder is configured + its cleanup interval |
| POST | `/api/watchfolder/drop` | body `{"ids":["…"], "name":"…"}` → resolve and write a `.txt` link file into the watch folder |
| GET / POST / DELETE | `/api/addons` | list / add / remove content-discovery addons (encrypted, URL never returned) |
| GET | `/api/discover/catalogs` \| `/catalog` \| `/search` \| `/meta` \| `/streams` | browse, search, and fetch metadata/sources across configured addons |
| POST | `/api/discover/add` | resolve a chosen stream — for a debrid-integrated addon, adds it to the debrid account |
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

## Discover: content via Stremio addons

Stremio addons are just HTTP servers implementing an open, documented protocol
(catalog/search/metadata/streams as plain JSON) — Debrid Hub talks to them
directly, generically, with no Stremio app and no addon-specific code. Add any
addon's `manifest.json` URL and it works: metadata addons populate the browse
sections and search; addons wired to a debrid account give you sources you can
push to that account with one click.

- **Add an extension**: **🧩 Extensions** → paste a `manifest.json` URL → Add.
  The URL is validated (fetched + checked it's really an addon) before being
  stored, **encrypted**, the same way as provider keys — it's never shown again.
- **Browse**: the **Discover** tab renders one row per (addon, catalog) —
  e.g. a per-streaming-service catalog addon gives you a Netflix row, a Hulu
  row, and so on, automatically, with no per-service code here.
- **Search**: searches every configured addon+catalog that supports it, in
  parallel, deduped.
- **Sources → your debrid account**: click a result to see cast/description/
  poster plus every source your stream-capable addons found; **Add** on one
  resolves it — for a debrid-integrated addon, that's the same action as
  hitting Play in Stremio, and it lands the release in your debrid account.
  This can take a little while for a magnet/torrent-backed source (it's
  resolving live, not instant); a hoster-link-backed one is instant-or-fail.

**Nothing here is Stremio-specific beyond the protocol itself** — no addon URL,
name, or behavior is hardcoded, so any addon you add (today's four, or any
future one) works without touching the app. See
[`docs/PRODUCT.md`](docs/PRODUCT.md#discover-browsesearch-content-via-stremio-protocol-addons)
for exactly how requests are made, how urls stay server-side (opaque tokens,
never sent to the browser), and the host-validation that stops a tampered
token from making the server fetch an arbitrary URL.

## Adding another debrid service

Subclass `Provider` in `src/debrid_hub/providers/`, implement `list_links()` and `resolve()`, and register it in `Aggregator._build()`. The UI and CLI pick it up automatically. Provider-specific data for resolving a link travels inside each link's opaque id, so the server stays stateless. To support deletion, set `capabilities = ("delete",)` and implement `delete(hint)`; carry whatever identifier the delete endpoint needs inside the link's `resolve_hint["del"]`.

## Notes

- The listing is cached for `DEBRID_HUB_CACHE_TTL` seconds (default 60); **Refresh** forces a re-fetch (and bypasses TorBox's own server-side listing cache too, so a just-deleted item doesn't reappear).
- Real-Debrid links come from your `/downloads` history (already direct). AllDebrid saved links + ready magnets and TorBox torrents/web/usenet are resolved when you copy them.
- AllDebrid only exposes file links for magnets whose status is **Ready**.
- Series grouping, quality/language badges, and cross-provider dedup are inferred client-side from filenames/size; they're display conveniences, not metadata from the providers. Files that don't match stay as-is.
- If a provider's listing comes back empty or wrong after they change their API, check `debrid-hub list --debug` (or `?debug=true` / the UI's Debug button) before assuming it's a credentials problem — it shows the exact request and response.
- Discover is independent of the provider/link machinery above — it never touches `secrets.enc` or the debrid provider clients directly. Adding a source there only affects the debrid account the addon itself is configured for; Debrid Hub doesn't choose or override that.
