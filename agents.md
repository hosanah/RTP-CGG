# RTP-CGG2 - Agents Guide

This file summarizes the system behavior and architecture so we can work
together quickly. It is based on the current codebase in `C:\dev\RTP-CGG2`.

## What this app does
- Flask app that pulls live RTP data from `cgg.bet.br` using protobuf.
- Pushes realtime updates to the browser over Socket.IO.
- Persists RTP history in Postgres for analytics and history views.
- Provides multiple dashboard pages and a few data APIs.

## High-level flow
1) `background_fetch()` in `app.py` runs forever.
2) It calls `fetch_games_data()` which hits two endpoints:
   - daily RTP (data = `\x08\x01\x10\x02`)
   - weekly RTP (data = `\x08\x02\x10\x02`)
3) The protobuf response is decoded into JSON-like dicts.
4) `latest_games` is updated; new data is inserted into Postgres.
5) Socket.IO emits `games_update` to all connected clients.
6) Frontend (`static/script.js`) re-renders cards and triggers alerts.

## Data source and protocol
- Base host: `https://cgg.bet.br`
- Live RTP endpoints:
  - `POST /casinogo/widgets/v2/live-rtp`
  - `POST /casinogo/widgets/v2/live-rtp/search`
- The code builds a protobuf schema at runtime in `get_protobuf_message()`
  and decodes messages using `google.protobuf`.
- RTP values are reported as integers. The UI shows `rtp / 100`.
- The `extra` field is treated as a signed 64-bit integer and decoded
  via `decode_signed()`; used for status and priority.

## Server entrypoints
- `app.py` is the main server for local dev:
  - Starts Socket.IO background task.
  - Runs Flask app with eventlet.
- `wsgi.py` is the entrypoint for gunicorn:
  - Starts background task and exposes `app`.
- `Dockerfile` runs: `gunicorn -k eventlet -b 0.0.0.0:5000 wsgi:app`.

## Database
Schema in `schema.sql` and auto-init in `db.py`:
- Table `rtp_history`:
  - `game_id BIGINT`
  - `name TEXT`
  - `provider TEXT`
  - `rtp REAL`
  - `extra BIGINT`
  - `rtp_status TEXT` (down/up/neutral)
  - `casa TEXT DEFAULT 'cgg'`
  - `timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP`

`db.insert_games()`:
- For each game, pulls the last 4 rows for that `game_id`.
- Skips insert if any recent row has the same `rtp` and `extra`.

## Backend endpoints
HTML pages:
- `/` -> `templates/index.html` (main realtime grid).
- `/melhores` -> `templates/melhores.html` (priority view).
- `/historico` -> `templates/historico.html` (chart + table by game).
- `/historico-registros` -> `templates/historico_grid.html` (raw records).
- `/registro-extra` -> `templates/registro_extra.html` (avg extra filter).

JSON APIs:
- `/api/games` -> latest RTP list (daily + weekly).
- `/api/melhores` -> sorted by lowest `extra`.
- `/api/search-rtp` -> POST `{"names":["..."]}` to fetch current RTP.
  - Falls back to local cache if search returns empty.
- `/api/history` -> aggregated history by period (daily/weekly/monthly).
- `/api/history/games` -> distinct games in history table.
- `/api/game-history` -> all records for one game id.
- `/api/history/records` -> raw records with filters.
- `/api/registro-extra` -> avg extra filter in a date range.
- `/api/last-winners` -> proxy to `cgg.bet.br` winners JSON.
- `/imagens/<game_id>.webp` -> cached image fetcher.

Websocket:
- Socket.IO event: `games_update` (same shape as `/api/games`).

## Frontend behavior
Main UI logic lives in `static/script.js`:
- Connects to Socket.IO and listens for `games_update`.
- Renders game cards into `#games-container`.
- Filters by name, provider, RTP range, extra range, and status.
- Sorts by name or RTP.
- Local alerts:
  - Per-game RTP threshold alerts (saved in localStorage).
  - Global extra threshold alerts (positive and negative).
  - Plays a base64-embedded alert sound.
- Search behavior:
  - Uses live data while typing; if not found locally, calls
    `/api/search-rtp` and keeps refreshing while query is active.
- Game modal:
  - Click a card image to open a modal.
  - While open, it refreshes that game every 1s via `/api/search-rtp`.
- Winners modal:
  - Optional overlay with `/api/last-winners` polling every 3s.

Styles live in `static/style.css`, focused on a dark theme and card grid.

## Config and env vars
Read via `.env` or environment:
- `VERIFY_SSL` (default true) controls SSL verification.
- `REQUEST_TIMEOUT` (default 3 seconds).
- `WINNERS_TIMEOUT` (default = REQUEST_TIMEOUT).
- `RTP_UPDATE_INTERVAL` (default 3 seconds).
- `DATABASE_URL` Postgres DSN.
- `DEBUG_REQUESTS` prints HTTP request/response info.
- `FLASK_DEBUG` enables Flask debug mode.
- `PORT` server port (used by Docker and Flask).

## Known quirks to keep in mind
- The protobuf schema is defined inline; if the upstream schema changes,
  decoding may break.
- `/api/search-rtp` uses 1-byte length encoding for the name; very long
  names could overflow that length.
- `image_cache/` is created on startup and stores cached `.webp` files.

## How to extend safely
- Backend changes: update both `/api/games` flow and DB inserts if new
  fields are added.
- Frontend changes: keep `script.js` in sync with any new API fields.
- For new analytics: prefer adding DB queries in `db.py` and new endpoints
  in `app.py`, then wire a new template.

## Quick commands
- Run locally: `python app.py`
- Docker build: `docker build -t rtp-cgg .`
- Docker run: `docker run -e PORT=5000 -p 5000:5000 rtp-cgg`

If you want a deeper map (diagrams, tests, or linting), tell me what you
need and I will add it.
