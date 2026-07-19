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
| AllDebrid | `alldebrid` | saved links (`/v4/user/links`) + files in ready magnets (`/v4.1/magnet/status` + `/v4/magnet/files`) | `/link/unlock` per link | saved link: that link · magnet file: the **whole magnet** |
| TorBox | `torbox` | torrents / web / usenet items + their files | `requestdl` per file | the **whole item** (all files) |
| Mock | `mock` | built-in fake data (`DEBRID_HUB_MOCK=1`) | echoes a URL | in-memory (safe to test) |

> **AllDebrid API note:** the old consolidated `/v4/magnet/status` (which used to
> also carry each magnet's files) was discontinued upstream. It's now two calls:
> `/v4.1/magnet/status` for status only, then `/v4/magnet/files` (batched, `id[]`)
> for files of magnets whose `statusCode == 4` ("Ready"). A magnet's files can
> nest one level (a folder entry with an `e[]` array) — `providers/alldebrid.py`
> flattens that recursively.

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
- **Partial failures aren't swallowed.** A provider's `list_links()` may fetch
  several sections (e.g. AllDebrid: saved links, then magnets); if one section
  fails, the provider records it in `self.warnings` instead of silently dropping
  it, and `Aggregator.list_links()` surfaces that into `errors[provider]` even
  though the provider still returned whatever it could. This is what used to hide
  the AllDebrid magnet-listing breakage entirely — see the debug mode below.

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

## Quality / language badges

Also client-side, also derived purely from the filename (no metadata call, no
external lookup). `parseTags(name)` scans for two independent token sets and
renders them as small pills under the filename:

- **Quality**: resolution (`4K`/`2160p`→`4K`, `1440p`, `1080p`, `1080i`, `720p`,
  `576p`, `480p` — first match wins) plus any of `REMUX`, `DV` (Dolby Vision),
  `HDR10+`, `HDR`, `BluRay`, `WEB-DL`, `WEBRip`, `HDTV` that appear.
- **Language**: `TrueFrench`, `VFF`, `VFI`, `VFQ`, `VOSTFR`, `Multi`, `French`,
  `Italian`, `German`, `Spanish`, `English`.

Both are best-effort display hints, not stored data — a filename that doesn't
match anything just shows no badges.

## Cross-provider dedup

The same release is often cached by more than one debrid service. `current()`
(in `index.html`) collapses items whose normalized filename (lowercased,
non-alphanumerics stripped) **and** exact size match, keeping one per group.
The provider you're left seeing doesn't matter functionally (select/resolve/
delete all operate on whichever copy won), but ties are broken by a fixed
priority — **TorBox, then Real-Debrid, then AllDebrid, then Mock**
(`PROVIDER_PRIORITY`). This only affects the *combined* view: filtering to a
single provider chip shows that provider's raw, undeduped list.

## Debug mode: raw provider requests/responses

`GET /api/links?debug=true` (implies `refresh=true`) makes every provider
record every outbound HTTP call it makes during that listing — method, URL,
query params (secrets like `apikey`/`token`/`authorization` redacted to `***`),
response status, and a truncated response body — and returns it under a
`"debug"` key, `{provider: [call, ...]}`. This is opt-in and per-request; a
provider's `debug_log` is reset at the top of every `list_links()` call so it
never leaks a previous request's calls into the next.

Three ways to see it:
- **Web UI**: the **🐛 Debug** button next to Refresh.
- **API**: `curl "localhost:8080/api/links?debug=true" | jq .debug`.
- **CLI**: `debrid-hub list --debug`.

This exists because a provider changing its upstream API (as AllDebrid did —
see the note above) can otherwise fail *silently*: a caught exception inside
one section of `list_links()` used to just mean "return fewer links," with no
visible error and nothing to grep. Now such failures land in `warnings` →
`errors[provider]`, and `--debug`/`?debug=true` shows the exact request and the
exact response that broke, without needing to hand over an API key to debug it
by hand again.

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
