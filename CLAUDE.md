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
- `Karten/Karten.csv` — source card data (names/quotes). `Karten/*.xlsx`, `regeln/*.docx` — design docs.
- `tools/make_avatars.py` — erzeugt `app/public/Bilder/avatare/` aus den Motiven. Reproduzierbar: zweimal laufen lassen gibt byte-gleiche Dateien.
- `requirements.txt` — `aiohttp>=3.10.0`. `AGENTS.md` ist nur ein Zeiger hierher.

### Wo die Bilder liegen
Alles unter `app/public/Bilder/` wird als `/images/...` **ausgeliefert**, alles unter `Bilder/` bleibt **lokal** (gitignored).

| Ort | Inhalt | Im Repo? |
|---|---|---|
| `app/public/Bilder/*.jpg\|jpeg` | die 6 Kartenmotive, die noch als Original-Datei dienen | ja |
| `app/public/Bilder/fotos/*.webp` | die 10 optimierten Kartenmotive | ja |
| `app/public/Bilder/legacy/` | 9 Motive, die **früher** auf Karten standen — heute nur noch Quelle für die Legacy-Avatare | ja |
| `app/public/Bilder/avatare/*.webp` | die 25 Profilbilder, 160×160 | ja |
| `Bilder/originale/karten/` | hochauflösende Quellfotos (HEIC/PNG/JPG, mehrere MB) | **nein** |
| `Bilder/originale/legalpics/` | lizenziertes Fremdmaterial | **nein** |

Die Regel dahinter: **ins Repo geht nur, was der Browser wirklich lädt.** Ein 5-MB-Handyfoto gehört nach `Bilder/originale/`, der daraus erzeugte WebP-Streifen nach `app/public/Bilder/fotos/`. Ausgeliefert wird nie ein Original.

## Backend architecture
- Routes (`create_app`): `GET /ws` (WebSocket), `GET /` (index), `GET /{path:.*}` (static; `images/*` → `IMAGES_DIR`, else `PUBLIC_DIR`).
- Sessions are in-memory dicts keyed by a short session id; `sessions` global. Players hold hidden card lists; server tracks turn/phase.
- **Session-Code = vier Ziffern** (`0000`–`9999`, `gen_session_id()`) — vorlesbar und auf der Handy-Tastatur tippbar; das Feld `#join-code` ist entsprechend `maxlength="4"` + `inputmode="numeric"`. Der Preis: nur 10 000 Codes, und Sessions werden nie aufgeräumt. `gen_session_id()` gibt deshalb einen *freien* Code zurück bzw. `None`, wenn alle vergeben sind (→ `err.noFreeCode`); ein `while sid in sessions`-Retry wäre bei erschöpftem Vorrat ein Server-Hänger.
- Message dispatch: `ws_handler` → `dispatch(ws, msg)`. Handled `type`s: `create, join, start, peek, peek_done, call_end, draw, keep, discard_drawn, race, reaction_swap, ability, next_round`. Each maps to a `handle_*` coroutine.
- State push: `send_state(s)` builds per-player views (`card_view` hides opponents' cards) and broadcasts.

## Endstand: Punkte je Runde
`match_scores` ist nur die Summe und verrät nicht, welche Runde teuer war — bei Best of 3/5/10 ist genau das die Frage. Deshalb führt die Session zusätzlich **`round_history`**: eine Zeile je beendeter Runde, angelegt in `new_session()`, gefüllt am Ende von `end_round()`, nie geleert (eine Session spielt genau ein Match). Format: `{'round': n, 'scores': {pid: punkte}, 'penalties': {pid: summe}}` — `penalties` enthält nur Spieler, die welche kassiert haben, und nur die Summe; die Begründung im Klartext bleibt in `score_breakdown`. Der Eintrag ist gegen einen Doppelaufruf von `end_round()` abgesichert, sonst stünde die Runde zweimal in der Tabelle.

Im Client baut `renderRoundTable()` daraus die Tabelle (Runden als Zeilen, Spieler als Spalten, Summenzeile unten); eine Runde mit Strafpunkten trägt ein rotes `*` plus Legende. Sie erscheint ab **zwei** gespielten Runden — also auch schon am Rundenende, nicht erst im Endstand. `renderScoringHero()` setzt darüber das Snoop-Dogg-GIF und die Gewinnerzeile; nur bei `phase === 'done'`. Das GIF liegt als `app/public/snoop-dogg-dancing.gif` **im Repo** (498×371, 668 KB) und wird über `SNOOP_GIF_URL = '/snoop-dogg-dancing.gif'` vom eigenen Server ausgeliefert — kein fremdes CDN, damit der Endstand auch offline steht. Beide Server lesen dasselbe `app/public/`, die eine Datei genügt für dev und prod. Der `onerror`-Rückfall bleibt: fehlt die Datei, verschwindet nur das Bild. Abgedeckt von `tests/e2e/scoreboard.spec.ts`, das `renderScoringModal()` gegen einen eingesetzten State prüft, statt ein ganzes Best-of-3 durchzuspielen.

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
- **Kartennamen** kommen über die Kartennummer, nicht über `card.name`: `cardName(card)` → `t('cardName.<nr>')` (nur `Hund→Dog/Köpek`, `Katze→Cat/Kedi` unterscheiden sich). Deshalb schickt jede Log-Meldung mit Karte ein `cardNr`, keinen Namen. Die deutsche Fassung bleibt damit deckungsgleich mit `Karten/Karten.csv`.
- **Die Kartenfähigkeit ist ein Schlüssel, kein Text:** der Server schickt `ability: 'see_swap'`, `getAbilityName()`/`getAbilityDesc()` machen daraus `t('abName.<ability>')` / `t('abDesc.<ability>')`. Auch der Chip (`chip.ability`) und die Fähigkeitsspalte im Regelwerk (`CARD_TABLE`) hängen an denselben Schlüsseln.
- **`ability: 'none'` hat keinen Text und keine Schlüssel.** Karten ohne Fähigkeit zeigen nur den `chip.normal`-Chip — kein „Keine Fähigkeiten", kein Erklärsatz; `abName`/`abDesc` haben deshalb bewusst keinen `none`-Eintrag und `cardHasAbility()` schneidet den Block in `buildCardInner()` ab. Wer den Satz zurückholen will, braucht Einträge in **allen drei** Dicts.
- **Sprüche werden NIE übersetzt.** Ein Spruch gehört der Figur, nicht der Sprache: „einmal zwei döner" und „guys, I lost my phone.." stehen in jeder Sprachfassung genau so da wie in `Karten/Karten.csv`. Der Weg über `cardQuote(card)` → `t('cardQuote.<nr>')` bleibt zwar bestehen, aber **alle drei `cardQuote`-Wörterbücher sind leer** und der Fallback auf den Servertext ist der Normalfall. Der Vollständigkeitstest nimmt den Zweig aus; dafür prüft „Sprüche werden nie übersetzt" in `tests/e2e/i18n-keys.spec.ts`, dass dort nichts nachwächst.
- **Feste Schlachtrufe stehen überall gleich da.** `sc.youAreTheBest` („You are the best, {name}", zum Snoop-GIF im Endstand) ist in allen drei Sprachen wortgleich — gewollt, wie die Figurenzitate. Der Wächter kennt dafür die Liste `fixedPhrases` in `tests/e2e/i18n-keys.spec.ts`: sie hebelt nur den Übersetzungs-, nie den Fehlt-Test aus. Weitere solche Zeilen gehören dort hinein, statt die Längenschwelle zu umgehen.
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
- Notable values: Titi = 0, Katze = -1 (lucky), Murat Abi = 13 (penalty-ish). Quotes must match `Karten/Karten.csv` — that CSV is the source of truth for names *and* quotes, so update it in the same breath as `CARD_DEFS`.
- Image mapping: `IMAGE_FILES` (nr → filename in `Bilder/`). **Neues Motiv ⇒ drei Schritte:** Bild als verkleinertes WebP nach `app/public/Bilder/fotos/NN-name.webp` (lange Kante ≤ 900px, `quality=82` — die Handy-Originale sind mehrere MB groß und der Kartenstreifen ist ein paar hundert Pixel breit), Eintrag in `IMAGE_FILES` in **beiden** Servern, Eintrag in `CARD_IMAGE_FOCUS` im Client (ohne den landet der Ausschnitt auf `FACE_FALLBACK` und schneidet Köpfe ab). **HEIC geht nicht** — kein Browser zeigt es an; per `sips -s format png` umwandeln. Schwarze Balken von Screenshots/abfotografierten Bildschirmen vorher wegschneiden, sie stehen sonst als Streifen auf der Karte. Das Originalfoto wandert dabei nach `Bilder/originale/karten/` und bleibt lokal. Soll die Figur auch als Profilbild wählbar sein, kommt ein vierter Schritt dazu: Eintrag in `FIGURES` in `tools/make_avatars.py` und einmal laufen lassen — das schreibt `app/public/Bilder/avatare/card-<nr>.webp` — plus ein Eintrag in `AVATAR_CARD_NRS` (siehe „Profilbilder"). **Ein Motiv, das von einer Karte verschwindet**, wird nicht gelöscht: es zieht nach `app/public/Bilder/legacy/` und bleibt über `AVATAR_LEGACY` als Profilbild wählbar.

## Gameplay flow (one glance)
Lobby (host `create`, others `join`, host `start` with ≥2 players) → **peek** phase (each player secretly peeks 2 of their 4 face-down cards) → **turns**: draw → keep (swap into a hand slot) or discard_drawn; special cards trigger abilities → **racing / reaction_swap** phase (snap matching values) → someone `call_end` → **scoring** (lowest total wins, penalties) → `next_round`. Timing constants: `REVEAL_SECONDS`, `FLIGHT_SECONDS` (must match the client's flight animation).

### Joker (11) und Hund (12) laufen am Tisch, nicht im Fenster
Die beiden Tauschkarten haben **kein Fähigkeitsfenster mehr** — Auswahl, Aufdecken und Tauschfrage passieren auf der globalen Tischansicht. Grund: das Fenster zeigte die Hände in einer eigenen Reihenfolge (wer dort „Platz 2" traf, meinte am Tisch etwas anderes), und nach dem Aufdecken verdeckte es genau den Tisch, über den zu entscheiden war. Das Fenster bleibt den Guck-Karten (`see_own`/`see_others`) vorbehalten.

- **`abilityRunsOnTable()`** ist der Schalter: `swap`/`see_swap` + eigener Auslöser ⇒ `renderAbilityModal()` steigt sofort aus. Darunter `canPickForAbility()` (Schritt `select1`/`select2`) und `isDecidingSwap()` (Schritt `decide_swap`).
- **Anklickbar** sind alle Tischkarten über `.ability-target` (lila), gesetzt in `renderOpponents()` und `renderMyZone()`. Die schon gewählte Karte bekommt die Klasse **nicht** — `applyAbilityHighlights()` entfernt sie wieder, weil `.tbl-swap-sel` weiter oben im Stylesheet steht und die Ziel-Umrandung ihn bei gleicher Spezifität sonst überschreibt.
- **Auswahl zurücknehmen:** ein zweiter Klick auf eine bereits gewählte Karte schickt `{type:'ability', undo:true}`; derselbe Weg hängt als Knopf in `#action-bar`. Der Server nimmt `undo` **nur** in `select1`/`select2` an — ab `decide_swap` sind die Karten gesehen, ein „zurück" wäre dort ein zweiter Gratis-Blick auf ein neues Paar.
- **Aufgedeckt wird am Tisch:** `abilityRevealAt()` liest `abilityState.revealedCards` und rendert die Vorderseite in den Slot (`.tbl-flip`, halbe Y-Drehung). Dass **nur der Auslöser** sie sieht, entscheidet der Server: `send_state()` hängt `revealedCards` ausschließlich an den Auslöser-View. Wer das Feld nicht bekommt, sieht Rückseiten — im Client wird nichts gefiltert, also auch nichts vergessen.
- Die Knöpfe „Tauschen"/„Nicht tauschen" und der Rückgängig-Knopf sitzen in `#action-bar`. Der ist **nicht** Teil von `fixedRowsHeight()`, verhält sich aber wie die normale „Spiel beenden"-Zeile — eine Knopfreihe passt, mehr nicht.

### Handtausch aus dem Nachziehstapel ist sichtbar
`handle_keep()` endet in **`start_keep_flight()`** statt direkt in `start_racing()`: Phase `swap_flight` für `KEEP_FLIGHT_SECONDS`, davor die Nachricht `keep_anim` (Slot + abgegebene Karte, aufgedeckt). Ohne das lief der häufigste Zug des Spiels bei allen anderen **stumm** ab — die ersetzte Karte verschwindet vom Tisch, die neue trägt eine frische uid, und `runTableFlip()` findet damit weder Vorher- noch Nachher-Position. Im Client zeichnet `animateKeep()` zwei gleichzeitige Flüge (Slot → Ablage als Klon, gezogene Karte → Slot per Inverse-FLIP). Es läuft **vor** der FLIP-Schleife, weil es die noch liegende `#draw-hold` als Startpunkt braucht — `syncDrawHold()` räumt sie direkt danach weg.

**Flugdauern hängen zusammen:** Client `SWAP_FLIGHT_MS` (1170 ms) muss in die Server-Fenster `FLIGHT_SECONDS` (1.8) bzw. `KEEP_FLIGHT_SECONDS` (1.5) passen. Wer eins ändert, prüft die anderen. `flyCard()`/`replayFlight()` schicken ihre Skalierung durch `finiteScale()`: ein Slot kann im Moment der Messung 0 breit sein, und ein einziger `Infinity`-Wert lässt den Browser das **ganze** Keyframe verwerfen — die Karte springt dann ohne Flug an ihren Platz.

### Profilbilder
Kleine runde Bilder neben dem Namen (Tisch, Lobby), gewählt in den Einstellungen — **pro Browser**, wie die Sprache, in `localStorage['karma_avatar']`.
- Katalog im Client: `AVATAR_CARD_NRS` (die 15 Kartenfiguren) + `AVATAR_LEGACY` (die Motive, die früher auf den Karten standen). Dateien: `app/public/Bilder/avatare/<id>.webp`, 160×160, quadratisch ums Gesicht geschnitten — der Kartenausschnitt ist ein breiter Streifen und taugt im Kreis nicht. Ausgeliefert über `/images/avatare/…`.
- **Der Server prüft die ID nicht**, er reicht sie nur durch (`_clean_avatar`, nur längenbegrenzt) — sonst müsste der Katalog in drei Dateien gepflegt werden. Geprüft wird im Client (`avatarKnown()`); eine unbekannte ID fällt auf den Namens-Initial zurück (Farbe aus dem Namen, damit sie pro Spieler stabil bleibt).
- Übertragen bei `create`/`join` und jederzeit per `set_avatar`; in `send_state()` als `avatar` je Spieler. **Figurennamen werden nicht übersetzt** (wie die Sprüche); die Kartenfiguren ziehen ihren Namen trotzdem aus `cardName.<nr>`, damit Hund/Katze in der Sprache des Spielers stehen.

### Startspieler und „Neues Spiel"
- **Wer anfängt, wird jede Runde ausgelost** — `start_game()` setzt `current_player_index` per `random.randrange()`, der Host hat kein Vorrecht. Weil die Runde mit der Peek-Phase beginnt und man erst danach sieht, wer dran ist, sagt `start_game()` es zusätzlich im Log an (`log.startPlayer`, „{name} fängt an"). Ohne diese Zeile wirkt das Los unsichtbar und es sieht aus, als finge immer der Host an — genau das war die Bugmeldung.
- **`next_round` bedeutet zwei verschiedene Dinge**, je nach Phase: bei `scoring` die nächste Runde (`start_next_round()`), bei `done` eine komplett neue Partie (`start_new_match()`). Der Knopf im Endstand heißt „Neues Spiel" und schickt dieselbe Nachricht. Vorher liefen beide Phasen in `start_next_round()`, das bei `round_number >= total_rounds` sofort wieder in den `done`-Zweig fällt — der Knopf tat sichtbar gar nichts. `start_new_match()` setzt `round_number`, `match_scores`, `round_history` und `score_breakdown` zurück; wer das vergisst, zählt die alte Partie weiter und die Rundentabelle wächst über zwei Matches.

## KI-Gegner (Bots)
Einzelspieler gegen 1–3 Bots (Auswahl im Lobby-Home, `create` trägt `bots` + `botLevel`), und in einer laufenden Mehrspieler-Lobby kann der Host freie Plätze auffüllen (`add_bot` / `remove_bot`, beides nur Host + nur Phase `lobby` — ein Bot, der mitten in der Runde dazukäme, hätte weder Hand noch Peek).

- **Ein Bot ist ein normaler Eintrag in `s['players']`** mit `ws=None` und `is_bot`/`bot_level`. `send()` steigt bei `ws is None` sofort aus, `send_state()` überspringt solche Spieler ganz — ein Bot bekommt nie eine Sicht gebaut. Namen und Gesichter kommen aus `BOT_PERSONAS` und zeigen auf die Legacy-Avatare des Clients.
- **Bots spielen ausschließlich über dieselben `handle_*`-Funktionen wie Menschen.** Sie haben keinen eigenen Regelpfad, können also auch nicht versehentlich an einer Prüfung vorbeispielen, und `known_cards` wird für sie an genau denselben Stellen gefüllt.
- **⚠️ Keine Hellsicht — das ist die Zusage, an der die Bots hängen.** Der einzige Zugang eines Bots zu einem Kartenwert ist `bot_value(bot, card)`; die Funktion liest nur `known_cards`. Im Bot-Code darf `card['value']` **nirgends** direkt gelesen werden. Erlaubte Ausnahmen, die auch ein Mensch offen vor sich hat: die selbst gezogene Karte (`s['drawn_card']`) und die oberste Ablagekarte. Wer eine neue Heuristik schreibt, geht durch `bot_value()` — sonst ist die Zusage still gebrochen und niemand merkt es.
- **Die eine erlaubte Erweiterung:** der **schwere** Bot merkt sich zusätzlich Karten, die ein *Fehlgriff* beim Schnappen für alle sichtbar umgedreht und zurückgelegt hat (`_bot_note_race_reveal`, gerufen im Miss-Zweig von `handle_race`). Öffentliche Information — nur merkt sie sich nicht jeder. **Treffer zählen nicht dazu:** die Karte wandert in die Ablage und `_forget_uid` löscht das Wissen ohnehin.
- **Alle Stellschrauben stehen als Zahl in `BOT_PROFILES`**, die Entscheidungsfunktionen sind für alle drei Stärken dieselben. Am deutlichsten trennt das **Schnappen**, weil man es unmittelbar merkt: leicht 4,0 s / 50 % Treffer / nur eigene Karten · mittel 3,0 s / 65 % / auch gegnerische · schwer 2,5 s / 90 % / auch gegnerische. Ein verfehlter Versuch ist bewusst gewollt und kostet den Bot eine Strafkarte (`_bot_race_wrong` greift dafür eine Karte, von der der Bot *weiß*, dass sie nicht passt — sonst würde die Quote durch zufällige Blindtreffer nach oben rutschen). Alle Reaktionszeiten müssen unter `RACE_SECONDS` (5.0) bleiben.
- **Denkpausen laufen immer über `_bot_pause(bot, factor)`**, nie über feste Sekunden — sonst grübelt ein starker Bot an einzelnen Stellen doch so lange wie ein schwacher.
- **Geduldsventil in `_bot_should_call_end()`:** eine Hand mit fünf Karten kommt nie unter die 7-Punkte-Schwelle, ab der „beenden" ohne Strafe möglich ist. Ohne das Ventil würde eine Runde, in der kein Mensch ruft, schlicht nie enden. Ab `prof['patience']` Zügen (gezählt in `s['round_turns']`) genügt deshalb ein klarer Vorsprung, ab dem Doppelten ruft der Bot notfalls auch mit mittelmäßiger Hand.
- **Treiber:** `bot_kick(s)` am Ende von `send_state()` startet `_bot_loop`, davon läuft höchstens einer je Session (`s['bot_task']`). Die Schleife ruft selbst `send_state` — der Wächter in `bot_kick` verhindert die zweite Schleife. `_bot_step()` macht **einen** Schritt und meldet, ob es noch etwas zu tun gab; in `swap_flight`/`scoring`/`done` gibt es das nicht, dort endet die Schleife und der nächste `send_state` weckt sie wieder.

## E2E tests (Playwright)
Run them after any change to the server logic or `app/public/index.html`:
```bash
npx playwright test
```
- Config: `playwright.config.ts`. Playwright boots its **own** `server_render.py` on port **3100** (`E2E_PORT`), so a dev server on 3000 is untouched. Sessions are in-memory — nothing to reset between runs.
- Specs in `tests/e2e/`: `lobby.spec.ts` (create/join/errors), `game-start.spec.ts` (2 players → peek → table), `server-sync.spec.ts` (**guards the two-server rule above**), `card-artwork.spec.ts` (card data + images), `scoreboard.spec.ts` (Endstand), `new-match.spec.ts` (Startspieler-Los + „Neues Spiel"; der Los-Test fährt rohe WebSockets aus `page.evaluate()`, weil 16 Partien durchzuklicken Minuten dauern würde), `i18n-english.spec.ts` / `i18n-turkish.spec.ts` / `i18n-keys.spec.ts` (see the i18n section), `bots.spec.ts` (KI-Gegner).
- `card-artwork.spec.ts` pinnt einen SHA-256 über `CARD_DEFS` — jede *gewollte* Änderung an Namen, Sprüchen oder Werten muss ihn neu setzen; der Einzeiler dafür steht im Kopf der Spec. Das ist Absicht: so kann keine Kartendatei nebenbei verrutschen.
- Multiplayer tests drive a second player through `browser.newContext()`. `workers` is pinned to 3 — the Playwright default opens too many contexts at once here and tests fall over on timeouts.
- Two traps worth knowing:
  - The client uses `alert()`. Handle the dialog **inside** a `page.on('dialog', …)` listener; a bare `waitForEvent('dialog')` disables auto-dismiss and hangs the click.
  - When the **last** player finishes peeking, the phase flips to `playing` and the peek modal stops re-rendering — its title never reaches "Einprägen abgeschlossen". Assert on a hidden `#peek-overlay` for the last player instead.
  - Den Session-Code **erst nach** `await expect(page.locator('#lobby-waiting')).toBeVisible()` auslesen. Davor steht dort ein leerer String, der Beitritt schlägt still fehl — und ein `toHaveText('')` auf der Gastseite geht dabei fröhlich durch, sodass der Test erst drei Zeilen später und an ganz anderer Stelle scheitert.
  - `logEntries`, `state`, `send` sind top-level `let`/`function` im Skript und stehen **nicht** an `window` — in `page.evaluate()` über `eval('logEntries')` holen.
  - Bots-Tests: der Startspieler wird ausgelost. Ist der Mensch dran, wartet der Tisch zu Recht auf ihn — ein Test, der nur zusieht, läuft in den Timeout. `bots.spec.ts` schiebt den eigenen Zug deshalb über das Protokoll weiter (`draw` + `keep`, keine Fähigkeitskarte im Weg) und prüft dann, dass Log-Meldungen mit *Bot-Namen* auflaufen.
