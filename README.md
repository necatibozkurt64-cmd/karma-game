# Karma

Ein Kartenspiel für 2–4 Spieler im Browser. Python-Backend (aiohttp) und ein
Single-File-Frontend aus reinem JavaScript, verbunden über einen WebSocket.
HTTP und WebSocket laufen auf demselben Port.

Wer am Spiel arbeitet, liest zuerst **[CLAUDE.md](CLAUDE.md)** — dort stehen
Architektur, Fallstricke und Konventionen.

## Lokal starten

```bash
python3 server_render.py
```

Dann `http://localhost:3000` öffnen. Braucht `aiohttp>=3.10.0` (`pip install -r requirements.txt`).
Ein Spieler erstellt eine Session und gibt den vierstelligen Code weiter, die
anderen treten damit bei. Wer allein spielen will, füllt die Plätze mit KI-Gegnern.

## Tests

```bash
npx playwright test
```

Playwright startet sich dafür einen eigenen Server auf Port 3100 — ein laufender
Dev-Server auf 3000 bleibt unberührt.

## Deploy

Railway baut aus diesem Repo; ein Push auf `main` löst den Deploy aus.
Einstiegspunkt ist das `Procfile` → `app/server_final.py`.

> **Achtung:** `server_render.py` (Entwicklung) und `app/server_final.py`
> (Produktion) sind zwei fast identische Dateien und müssen synchron bleiben.
> Sie dürfen sich nur in zwei Pfadzeilen unterscheiden; `tests/e2e/server-sync.spec.ts`
> wacht darüber.

## Spielregeln

`regeln/PlayCards – Regelbuch.docx`, im Spiel auch über das Fragezeichen oben rechts.
Die Kartendaten (Namen, Sprüche, Werte) stehen in `Karten/Karten.csv`.
