# Debrid Hub

One place to see every link across your debrid accounts — **Real-Debrid, AllDebrid, TorBox** — search and sort them, and copy direct URLs straight into **JDownloader2**. Ships a **CLI**, a **REST API**, and a **web UI** from a single container.

## What it does

- Aggregates links from every configured provider into one normalized list.
- Cross-debrid: you don't pick a service, it just shows everything.
- Search by filename/host, sort by name/size/date/host/provider/kind.
- Resolves the actual direct download URL on demand (links are metered/locked on some services, so this happens when you copy, not when you browse).
- **JD2 tray**: tick several links, hit *Copy for JD2*, and every direct URL lands on your clipboard newline-separated. JDownloader2 monitors the clipboard by default, so it auto-catches them into the LinkGrabber — or just paste.

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

Set only the ones you use; empty vars disable that provider.

## CLI

```bash
debrid-hub providers                 # credential health per service
debrid-hub list                      # table of everything
debrid-hub list -s ubuntu --sort size --order desc
debrid-hub list -p torbox -k torrent
debrid-hub list --urls               # direct URLs only, one per line
debrid-hub list -s 1080p --urls | xclip -selection clipboard   # → paste into JD2
debrid-hub list --json               # machine-readable
debrid-hub resolve <link-id>         # id comes from `list --json`
debrid-hub serve --port 8080
```

## REST API

Base URL `http://host:8080`. If `DEBRID_HUB_API_KEY` is set, send `Authorization: Bearer <key>`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/providers` | configured providers + health |
| GET | `/api/links` | aggregated list; query: `search, provider, kind, sort, order, refresh` |
| POST | `/api/resolve` | body `{"ids":["…"]}` (or `{"id":"…"}`) → direct URLs |
| GET | `/health` | liveness |

```bash
curl -s localhost:8080/api/links?search=ubuntu | jq '.links[0]'
curl -s -X POST localhost:8080/api/resolve \
  -H 'content-type: application/json' -d '{"ids":["<id>"]}'
```

Interactive docs at `/docs` (FastAPI/OpenAPI), so you can wire this into other tools.

## Exposing it safely

Behind Cloudflare Tunnel or Tailscale, no extra auth is strictly needed. If it's reachable from the internet, set `DEBRID_HUB_API_KEY`; the UI will prompt for it once and remember it in your browser.

## Adding another debrid service

Subclass `Provider` in `src/debrid_hub/providers/`, implement `list_links()` and `resolve()`, and register it in `Aggregator._build()`. The UI and CLI pick it up automatically. Provider-specific data for resolving a link travels inside each link's opaque id, so the server stays stateless.

## Notes

- The listing is cached for `DEBRID_HUB_CACHE_TTL` seconds (default 60); **Refresh** forces a re-fetch.
- Real-Debrid links come from your `/downloads` history (already direct). AllDebrid saved links + completed magnets and TorBox torrents/web/usenet are resolved when you copy them.
- AllDebrid only exposes file links for *completed* magnets.
