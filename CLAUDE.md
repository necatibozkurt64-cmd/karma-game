# Karma — project context (read this first)

**Karma** is a 2–4 player multiplayer card game prototype. Python backend (aiohttp / asyncio) + a single-file vanilla-JS frontend, talking over one WebSocket. HTTP and WebSocket are served on the **same port** by aiohttp (`PORT` env, default 3000).

## Run & verify (fast)
- **Dev (use this):** `preview_start name:karma` — the `karma` config already exists in `.claude/launch.json` and runs `server_render.py` on port 3000. Then open `http://localhost:3000`.
- **Fallback:** `python3 server_render.py` (needs `aiohttp>=3.10.0`, already installed).
- To verify a change: open the preview, `read_console_messages` (expect clean), and click through lobby → game.

## ⚠️ The two-server rule (biggest gotcha)
There are **two near-identical server files that must stay in sync**:
| File | Role | Launched by | Image paths |
|------|------|-------------|-------------|
| `server_render.py` (root) | **dev / local** | `.claude/launch.json` | `app/public/...` |
| `app/server_final.py` | **production (Render)** | `Procfile` (`web: cd app && python server_final.py`) | `public/...` |

They differ **only** in the `IMAGES_DIR` / `PUBLIC_DIR` path prefix (lines ~39–40). **Any game-logic change must be made in BOTH.** Confirm they're still in sync:
```bash
diff server_render.py app/server_final.py
```
Expect only those 2 path lines to differ. If more differs, the deploy is out of sync with dev.

## File map
- `server_render.py` — active dev server: game logic + HTTP + WS (~1000 lines).
- `app/server_final.py` — production mirror of the above.
- `app/public/index.html` — **entire frontend**, all CSS + JS inline (~2500 lines). Connects to `ws://<host>/ws`. Card rendering: `buildCardInner(card, w, h)`.
- `.claude/launch.json` — `karma` preview config (points at `server_render.py`).
- `Procfile` — Render deploy entrypoint (points at `app/server_final.py`).
- `Karten/Karten.csv` — source card data (names/quotes). `Karten/Karten.xlsx`, `regeln/*.docx` — design docs.
- `app/public/Bilder/` — card face images (served at `/images/...`). `Bilder/` (root) + `Bilder.zip` are the originals.
- `requirements.txt` — `aiohttp>=3.10.0`. `README.md` is a stub.

## Backend architecture
- Routes (`create_app`): `GET /ws` (WebSocket), `GET /` (index), `GET /{path:.*}` (static; `images/*` → `IMAGES_DIR`, else `PUBLIC_DIR`).
- Sessions are in-memory dicts keyed by a short session id; `sessions` global. Players hold hidden card lists; server tracks turn/phase.
- Message dispatch: `ws_handler` → `dispatch(ws, msg)`. Handled `type`s: `create, join, start, peek, peek_done, call_end, draw, keep, discard_drawn, race, reaction_swap, ability, next_round`. Each maps to a `handle_*` coroutine.
- State push: `send_state(s)` builds per-player views (`card_view` hides opponents' cards) and broadcasts.

## Protocol footgun: camelCase ↔ snake_case
- The **client sends camelCase** (`playerId`, `cardIndex`, `handIndex`, `targetPlayerId`, …).
- Inside `dispatch()`, helpers `g(key, alt)` and `gi(key)` accept **both** camelCase and snake_case (via `_to_snake`).
- State sent **back to clients is camelCase** (`send_state`).
- **Rule when adding a new message field:** read it through `g()`/`gi()` in `dispatch()`/its handler, and if it's part of game state, add it to `send_state()` in camelCase. Miss either side and the field silently disappears.

## Card model
- `CARD_DEFS` (15 cards) lives in both server files: `dict(nr, name, value, ability, quote, count, colors)`.
- Abilities: `none`, `see_own`, `see_others`, `swap`, `see_swap` (handled in `handle_ability`).
- Notable values: Titi = 0, Katze = -1 (lucky), Mr Hankey = 13 (penalty-ish). Quotes must match `Karten/Karten.csv`.
- Image mapping: `IMAGE_FILES` (nr → filename in `Bilder/`).

## Gameplay flow (one glance)
Lobby (host `create`, others `join`, host `start` with ≥2 players) → **peek** phase (each player secretly peeks 2 of their 4 face-down cards) → **turns**: draw → keep (swap into a hand slot) or discard_drawn; special cards trigger abilities → **racing / reaction_swap** phase (snap matching values) → someone `call_end` → **scoring** (lowest total wins, penalties) → `next_round`. Timing constants: `REVEAL_SECONDS`, `FLIGHT_SECONDS` (must match the client's flight animation).
