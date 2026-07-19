# Debrid Hub — Product & Architecture

> Machine- and human-readable overview. If you are an AI agent or a new
> contributor, read this first, then [`API.md`](API.md) for the HTTP contract and
> [`openapi.json`](openapi.json) for the exact schema.

## What it is

Debrid Hub is a self-hosted aggregator for **debrid services** (services that turn
torrents/hosters into direct HTTPS downloads). It logs into one or more provider
accounts, presents every downloadable item as a single normalized list, resolves
the final direct URL on demand, lets you **manage** (delete) items, and hands the
URLs to **JDownloader2**.

It is one Python package exposing three surfaces over the same core:

- **Web UI** — a single self-contained `index.html` (no build step).
- **REST API** — FastAPI, documented at `/docs`, schema at `/openapi.json`.
- **CLI** — `debrid-hub …` (Typer).

## Supported providers

| Provider | id | Lists | Resolve | Delete granularity |
|---|---|---|---|---|
| Real-Debrid | `realdebrid` | `/downloads` history (already direct) | none needed (URL is direct) | single download entry |
| AllDebrid | `alldebrid` | saved links + files in completed magnets | `/link/unlock` per link | saved link: that link · magnet file: the **whole magnet** |
| TorBox | `torbox` | torrents / web / usenet items + their files | `requestdl` per file | the **whole item** (all files) |
| Mock | `mock` | built-in fake data (`DEBRID_HUB_MOCK=1`) | echoes a URL | in-memory (safe to test) |

## Core concepts

- **`DebridLink`** (`models.py`) — the normalized item: `provider, name, size, host,
  kind, added, direct_url, resolve_hint, id`. `to_dict()` is what clients see; it
  drops `resolve_hint` and adds `id` + `resolvable`.
- **Opaque `id`** — base64url of `{p: provider, h: resolve_hint}`. The server is
  **stateless**: everything needed to resolve or delete a link is encoded in its id
  and decoded on demand (`decode_id`). Ids are recomputed on every listing.
- **`resolve_hint`** — provider-private data. Never sent to clients. Carries the
  resolve method (`k`) plus, when deletable, a `del` sub-object with the identifier
  the provider's delete endpoint needs.
- **Capabilities** — a provider advertises optional operations via
  `capabilities: tuple[str,...]` (currently `("delete",)`). The UI/CLI/API use this
  to decide which management actions to offer.

## Request flow

```
Browser / CLI / HTTP client
        │
        ▼
FastAPI (api.py)  ──auth (optional Bearer)──►  Aggregator (aggregator.py)
        │                                            │
        │                             ┌──────────────┼───────────────┐
        ▼                             ▼              ▼               ▼
   index.html               RealDebrid        AllDebrid          TorBox / Mock
   (web UI)                 providers/*.py — each wraps one upstream API via httpx
```

- `Aggregator.list_links()` fans out to every provider concurrently
  (`asyncio.gather`), normalizes results, caches for `DEBRID_HUB_CACHE_TTL` s, and
  records per-provider errors instead of failing the whole request.
- `resolve(id)` / `delete(id)` decode the id, pick the provider, and call it.
  `delete` also invalidates the cache so the next listing reflects the removal.

## Series / season grouping

Grouping is a **client-side** view concern (in `index.html`), not stored data.
`parseEp(name)` extracts `{series, season, episode}` from a filename using these
patterns (first match wins), after stripping the file extension:

1. `…S01E02…` (also `S01E02E03` multi-episode → first episode)
2. `…1x02…`
3. `…Season 1 Episode 2…`

The series title is cleaned (dots/underscores → spaces, trailing year like `2015`
or `(2015)` removed). Items are grouped `series → season → episodes`, keyed
**case-insensitively** so e.g. `From` and `FROM` merge into one series (the
display name prefers a non-ALL-CAPS casing when one appears). A "series" that
ends up with a single episode is demoted back to a flat row. Toggle the whole
behaviour with the **group series** switch.

## Configuration & secrets

- Keys come from env vars (`DEBRID_REALDEBRID_TOKEN`, `DEBRID_ALLDEBRID_APIKEY`,
  `DEBRID_TORBOX_APIKEY`) **or** are saved at runtime, **encrypted at rest**
  (Fernet/AES) under `DEBRID_HUB_DATA_DIR` via `store.py`.
- A runtime-saved key overrides the matching env var; deleting it falls back to the
  env var. Providers rebuild live (`Aggregator.reload()`), no restart.
- Optional `DEBRID_HUB_API_KEY` protects the API/UI with a Bearer token.
- Stored key **values are never returned** by any endpoint or CLI command — only
  whether a key is set and where it came from (`stored` vs `env`).

## Settings (env vars)

| Var | Default | Meaning |
|---|---|---|
| `DEBRID_REALDEBRID_TOKEN` / `DEBRID_ALLDEBRID_APIKEY` / `DEBRID_TORBOX_APIKEY` | — | provider credentials |
| `DEBRID_HUB_API_KEY` | — | if set, require `Authorization: Bearer <key>` |
| `DEBRID_HUB_MOCK` | off | inject the demo provider (no keys needed) |
| `DEBRID_HUB_CACHE_TTL` | `60` | seconds to cache the aggregated listing |
| `DEBRID_HUB_TIMEOUT` | `30` | per-request HTTP timeout (s) |
| `DEBRID_HUB_DATA_DIR` | `~/.config/debrid-hub` | encrypted credential store location |
| `DEBRID_HUB_SECRET_KEY` | auto | master key for the store (else a generated `secret.key`) |

## Extending

Add a provider by subclassing `Provider` (`providers/base.py`): implement
`list_links()` and `resolve(hint)`, optionally `delete(hint)` +
`capabilities = ("delete",)` and `health()`, then register it in
`Aggregator._build()`. Everything else (UI, CLI, API, grouping) picks it up with no
further changes.

## Safety notes for automated agents

- **Deletion is destructive and irreversible.** Some providers delete a whole
  torrent/magnet (every file inside), not just the targeted file — see the table
  above. Confirm intent before calling `POST /api/delete` or `debrid-hub rm`.
- The **mock** provider is the safe target for exercising the delete flow; its
  deletions are in-memory only.
