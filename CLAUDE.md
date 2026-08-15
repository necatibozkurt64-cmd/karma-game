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
| `app/server_final.py` | **production (Railway)** | `Procfile` (`web: cd app && python server_final.py`) | `public/...` |

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
- `Procfile` — Railway deploy entrypoint (points at `app/server_final.py`). Railway builds from the GitHub repo; pushing `main` triggers the deploy. There is no `railway.json`/`railway.toml` in the repo — the service is configured in the Railway dashboard.
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

## i18n (Deutsch / English / Türkçe)
Die Sprache ist **pro Browser**, nicht pro Session — zwei Spieler am selben Tisch dürfen unterschiedliche Sprachen fahren. Gespeichert in `localStorage['karma_language']` (`'de'` Default, `'en'`, `'tr'`), umgeschaltet über `setLanguage()` in den Einstellungen.

- **Alle Texte stehen in `TRANSLATIONS = { de: {…}, en: {…}, tr: {…} }`** in `app/public/index.html`. `t('a.b', {n: 3})` liest den Schlüssel der aktuellen Sprache und ersetzt `{platzhalter}`; fehlt ein Schlüssel, fällt `t()` auf Deutsch zurück. **Neuer Text ⇒ Eintrag in ALLE Dicts.**
- **Eine neue Sprache braucht genau zwei Schritte:** einen Block in `TRANSLATIONS` und eine Zeile in `LANGUAGES` (`{id, flag, label}`, direkt darunter). Der Umschalter in den Einstellungen (`updateLanguageUI()` baut `#lang-grid`) und die Gültigkeitsprüfung in `loadSettings()` lesen beide aus dieser Liste — kein Markup und keine Sonderbehandlung nötig.
- **Statisches Markup** trägt `data-i18n` (innerHTML), `data-i18n-ph` (placeholder), `data-i18n-title` (Tooltip) — `applyStaticI18n()` setzt sie. Kein deutscher Text darf hart im JS stehen.
- **Server-Meldungen sind Schlüssel, kein fertiger Satz:** `dict(type='toast', key='log.draw', params={'name': …})` bzw. `type='error', key='err.sessionFull'`. Übersetzt wird erst beim Anzeigen (`entryText()`), sonst bekäme ein englischer Spieler deutsche Log-Zeilen. Dasselbe bei Strafpunkten: `score_breakdown[…]['penalties']` trägt `reasons: ['notWon','over7']`, den Satz baut `penaltyReason()` im Client.
- **Kartennamen und -zitate** kommen über die Kartennummer, nicht über `card.name`: `cardName(card)` → `t('cardName.<nr>')` (nur `Hund→Dog/Köpek`, `Katze→Cat/Kedi` unterscheiden sich), `cardQuote(card)` → `t('cardQuote.<nr>')` mit Fallback auf den Servertext. Deshalb schickt jede Log-Meldung mit Karte ein `cardNr`, keinen Namen. Die deutsche Fassung bleibt damit deckungsgleich mit `Karten/Karten.csv`.
- **Die Kartenfähigkeit ist ein Schlüssel, kein Text:** der Server schickt `ability: 'see_swap'`, `getAbilityName()`/`getAbilityDesc()` machen daraus `t('abName.<ability>')` / `t('abDesc.<ability>')`. Auch der Chip (`chip.ability`) und die Fähigkeitsspalte im Regelwerk (`CARD_TABLE`) hängen an denselben Schlüsseln.
- **`cardQuote` ist bewusst dünn besetzt** — überschrieben wird nur, was in der Zielsprache nicht schon passt; feste Figurenzitate („Eier, we need Eier", „Ciao bella ciao!") bleiben in jeder Sprache stehen. Der Vollständigkeitstest nimmt diesen Zweig deshalb aus.
- **Das Regelwerk wird gerendert, nicht dupliziert:** `renderHelp()` baut `#help-content` aus `help.*`; die Kartentabelle kommt aus `CARD_TABLE` und zieht Namen/Fähigkeiten aus denselben Schlüsseln wie die Karten am Tisch.
- **Das Log speichert Rohdaten** (`logEntries` = `{key, params, color, anim, time}`), nicht fertige Zeilen — `renderLogPanel()` zeichnet nach einem Sprachwechsel auch alte Meldungen neu. `showToast()` nimmt entweder ein solches Objekt oder (für rein lokale Meldungen) einen String.
- Abgedeckt von `tests/e2e/i18n-english.spec.ts` und `tests/e2e/i18n-turkish.spec.ts`. **`tests/e2e/i18n-keys.spec.ts` ist der Wächter:** er prüft, dass jede Sprache aus `LANGUAGES` jeden Schlüssel der deutschen Fassung hat und keinen längeren Satz unübersetzt stehen lässt — sonst fällt `t()` still auf Deutsch zurück und niemand merkt es.

## Handy-Layout (compact view)
Der Tisch ist ein `100dvh`-Block ohne Scrollen — auf dem Handy müssen alle vier Hände, beide Stapel **und** die Aktionsleiste („Spiel beenden") gleichzeitig sichtbar sein. Deshalb:
- **Kartenmaße kommen aus dem JS**, nicht aus dem CSS: `handMetrics(oppCount)` (Gegner-/eigene Karten, bei 3 Gegnern 2×2-Raster via `data-cols`), `pileMetrics()` (Stapel — misst die Resthöhe von `#center`), `drawnCardSize()`, `abilityPickSize()`. Alle setzen Inline-`width`/`height` **und** geben dieselben Zahlen an `buildCardInner()`; Box und Inhalt müssen zusammenpassen.
- **`isCompactView()` (≤760px breit oder ≤620px hoch) muss zur Media Query `@media (max-width: 760px), (max-height: 620px)` passen** — beide zusammen ändern. Dito `isShortView()` (≤460px hoch) ↔ `@media (max-height: 460px)`, wo der Tisch ausnahmsweise scrollen darf.
- **Reihenfolge in `render()`:** `renderCenter()` läuft als Letztes, weil `pileMetrics()` die Resthöhe misst. `fixedRowsHeight()` misst nur *stabile* Zeilen (Topbar, Laufband, Log-Kopf) — Hinweiszeile, Endrunden-Banner und Schnapp-Leiste bewusst nicht, sonst wechseln die Karten mitten im Schnapp-Fenster ihre Größe.
- `#log-panel` sitzt in `#log-box` und ist ein-/ausklappbar (`toggleLog()`, Zustand in `localStorage['karma_log_open']`, auf dem Handy standardmäßig zu). Zugeklappt zeigt die Kopfzeile die letzte Meldung + Zähler; ausgeklappt legt sie sich auf dem Handy **über** den Tisch, statt ihn zu stauchen.
- `buildCardInner()` schaltet unter 100px Breite auf `.tcg-mini` (ohne Chip/Beschreibung/Zitat) und unter 62px ganz ohne Info-Panel.
- `#instruct`/`#end-banner` liegen im DOM in `#game`: am Desktop `position: fixed`, auf dem Handy im Fluss (sonst verdecken sie die Gegnerkarten).

## Card model
- `CARD_DEFS` (15 cards) lives in both server files: `dict(nr, name, value, ability, quote, count, colors)`.
- Abilities: `none`, `see_own`, `see_others`, `swap`, `see_swap` (handled in `handle_ability`).
- Notable values: Titi = 0, Katze = -1 (lucky), Mr Hankey = 13 (penalty-ish). Quotes must match `Karten/Karten.csv`.
- Image mapping: `IMAGE_FILES` (nr → filename in `Bilder/`).

## Gameplay flow (one glance)
Lobby (host `create`, others `join`, host `start` with ≥2 players) → **peek** phase (each player secretly peeks 2 of their 4 face-down cards) → **turns**: draw → keep (swap into a hand slot) or discard_drawn; special cards trigger abilities → **racing / reaction_swap** phase (snap matching values) → someone `call_end` → **scoring** (lowest total wins, penalties) → `next_round`. Timing constants: `REVEAL_SECONDS`, `FLIGHT_SECONDS` (must match the client's flight animation).

## E2E tests (Playwright)
Run them after any change to the server logic or `app/public/index.html`:
```bash
npx playwright test
```
- Config: `playwright.config.ts`. Playwright boots its **own** `server_render.py` on port **3100** (`E2E_PORT`), so a dev server on 3000 is untouched. Sessions are in-memory — nothing to reset between runs.
- Specs in `tests/e2e/`: `lobby.spec.ts` (create/join/errors), `game-start.spec.ts` (2 players → peek → table), `server-sync.spec.ts` (**guards the two-server rule above**), `card-artwork.spec.ts` (card data + images), `i18n-english.spec.ts` / `i18n-turkish.spec.ts` / `i18n-keys.spec.ts` (see the i18n section).
- Multiplayer tests drive a second player through `browser.newContext()`. `workers` is pinned to 3 — the Playwright default opens too many contexts at once here and tests fall over on timeouts.
- Two traps worth knowing:
  - The client uses `alert()`. Handle the dialog **inside** a `page.on('dialog', …)` listener; a bare `waitForEvent('dialog')` disables auto-dismiss and hangs the click.
  - When the **last** player finishes peeking, the phase flips to `playing` and the peek modal stops re-rendering — its title never reaches "Einprägen abgeschlossen". Assert on a hidden `#peek-overlay` for the last player instead.
