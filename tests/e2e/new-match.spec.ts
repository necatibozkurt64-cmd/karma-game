import { test, expect, type Browser, type Page } from '@playwright/test';

/**
 * Zwei Regeln, die vorher gebrochen waren:
 *
 *  1. "Neues Spiel" im Endstand startete keine neue Partie. Der Knopf schickt
 *     `next_round`, und der Server fiel bei phase='done' sofort wieder in den
 *     'done'-Zweig zurück – sichtbar tat der Klick gar nichts.
 *  2. Wer anfängt, wird ausgelost. Das passierte serverseitig schon, war aber
 *     nirgends zu sehen; jetzt sagt es eine Log-Meldung an.
 *
 * Der Auslos-Test läuft über rohe WebSockets im Browser statt über die
 * Oberfläche: 16 Partien durchzuklicken dauert Minuten, das Protokoll
 * beantwortet dieselbe Frage in Sekunden.
 */

type Starter = { starter: string; announced: string | null; hostId: string };

/**
 * Spielt `runs` Partien bis zur Peek-Phase – nur über das Protokoll – und
 * meldet je Partie, wer am Zug ist und wen die Ansage nennt.
 */
async function drawStarters(page: Page, runs: number): Promise<Starter[]> {
  await page.goto('/');
  return page.evaluate(async (n: number) => {
    /** Minimaler WS-Client: puffert alle Meldungen, damit zwischen zwei
     *  await-Schritten keine verloren geht. */
    class Conn {
      msgs: any[] = [];
      ws: WebSocket;
      ready: Promise<unknown>;
      constructor(url: string) {
        this.ws = new WebSocket(url);
        this.ready = new Promise((r) => (this.ws.onopen = r));
        this.ws.onmessage = (e) => this.msgs.push(JSON.parse(e.data));
      }
      async send(o: unknown) {
        await this.ready;
        this.ws.send(JSON.stringify(o));
      }
      async wait(pred: (m: any) => boolean, ms = 10000) {
        const t0 = Date.now();
        for (;;) {
          const i = this.msgs.findIndex(pred);
          if (i >= 0) return this.msgs.splice(0, i + 1).pop();
          if (Date.now() - t0 > ms) throw new Error('Timeout beim Warten auf eine Meldung');
          await new Promise((r) => setTimeout(r, 20));
        }
      }
      close() {
        this.ws.close();
      }
    }

    const url = 'ws://' + location.host + '/ws';
    const out: { starter: string; announced: string | null; hostId: string }[] = [];

    for (let i = 0; i < n; i++) {
      const hostId = 'h' + Date.now() + '_' + i;
      const guestId = 'g' + Date.now() + '_' + i;
      const host = new Conn(url);
      const guest = new Conn(url);

      await host.send({ type: 'create', playerId: hostId, playerName: 'Host', gameMode: 'single' });
      const created = await host.wait((m) => m.type === 'created');
      await guest.send({
        type: 'join',
        playerId: guestId,
        playerName: 'Gast',
        sessionId: created.sessionId,
      });
      await host.wait((m) => m.type === 'state' && m.players.length === 2);
      await host.send({ type: 'start' });

      const st = await host.wait((m) => m.type === 'state' && m.phase === 'peek');
      const toast = await host.wait((m) => m.type === 'toast' && m.key === 'log.startPlayer');
      out.push({ starter: st.currentPlayerId, announced: toast?.params?.name ?? null, hostId });

      host.close();
      guest.close();
    }
    return out;
  }, runs);
}

async function hostSession(page: Page, name: string, mode = 'single'): Promise<string> {
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#game-mode').selectOption(mode);
  await page.getByRole('button', { name: 'Session erstellen' }).click();
  await expect(page.locator('#lobby-waiting')).toBeVisible();
  return (await page.locator('#session-id-display').innerText()).trim();
}

async function addGuest(browser: Browser, code: string, name: string) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#join-code').fill(code);
  await page.getByRole('button', { name: 'Beitreten' }).click();
  await expect(page.locator('#session-id-display')).toHaveText(code);
  return { ctx, page };
}

/** Wer am Zug ist, ist ausgelost – der Tisch muss danach gefragt werden. */
async function splitByTurn(pages: Page[]): Promise<[Page, Page]> {
  const visible = () => Promise.all(pages.map((p) => p.locator('#turn-badge').isVisible()));
  await expect
    .poll(async () => (await visible()).filter(Boolean).length, {
      message: 'genau ein Spieler ist am Zug',
      timeout: 20_000,
    })
    .toBe(1);
  const active = (await visible()).indexOf(true);
  return [pages[active], pages[1 - active]];
}

test.describe('Startspieler wird ausgelost', () => {
  test('über viele Partien fängt nicht immer derselbe an', async ({ page }) => {
    const runs = await drawStarters(page, 16);
    const hostStarts = runs.filter((r) => r.starter === r.hostId).length;

    // Bei fairem Los ist "16x dieselbe Seite" praktisch ausgeschlossen (~1:32000).
    expect(hostStarts, 'der Host fängt nicht jedes Mal an').toBeLessThan(16);
    expect(hostStarts, 'der Gast fängt nicht jedes Mal an').toBeGreaterThan(0);
  });

  test('die Ansage nennt den Spieler, der wirklich anfängt', async ({ page }) => {
    const runs = await drawStarters(page, 6);
    for (const r of runs) {
      expect(r.announced).toBe(r.starter === r.hostId ? 'Host' : 'Gast');
    }
  });
});

test.describe('Neues Spiel', () => {
  // Eine ganze Runde inklusive Schnapp-Fenster – deshalb großzügig.
  test.setTimeout(120_000);

  test('der Knopf im Endstand startet eine neue Partie bei null', async ({ page, browser }) => {
    const code = await hostSession(page, 'Host');
    const guest = await addGuest(browser, code, 'Gast');
    await page.locator('#start-btn').click();

    // Peek überspringen – die Karten interessieren hier nicht.
    for (const p of [page, guest.page]) await p.locator('#peek-done-btn').click();
    for (const p of [page, guest.page]) {
      await expect(p.locator('#peek-overlay')).toBeHidden({ timeout: 20_000 });
    }

    // Kürzester Weg zum Rundenende: der Spieler am Zug beendet, der andere macht
    // seinen einen Schlusszug. Dabei "Handkarte ersetzen" statt ablegen – Ablegen
    // würde bei einer Fähigkeitskarte in die Fähigkeitsphase führen und den
    // Testablauf vom Deck abhängig machen.
    const [active, other] = await splitByTurn([page, guest.page]);
    await active.locator('#action-bar button', { hasText: 'Spiel beenden' }).click();

    await expect(other.locator('#turn-badge')).toBeVisible({ timeout: 20_000 });
    await other.locator('#deck-pile').click();
    await expect(other.locator('#drawn-hand .card')).toHaveCount(4, { timeout: 20_000 });
    await other.locator('#drawn-hand .card').nth(0).click();

    // Schnapp-Fenster läuft ab (RACE_SECONDS), dann kommt die Abrechnung.
    const btn = page.locator('#next-round-btn');
    await expect(page.locator('#scoring-overlay')).toBeVisible({ timeout: 40_000 });
    await expect(btn).toHaveText('Endergebnis');
    await btn.click();

    // Erst im Endstand heißt der Knopf "Neues Spiel".
    await expect(page.locator('#scoring-title')).toHaveText('Spiel beendet!');
    await expect(btn).toHaveText('Neues Spiel');
    await btn.click();

    // Der Klick muss eine komplette neue Partie starten: Modal zu, Peek offen,
    // Runde 1, Punktestand zurück auf null.
    for (const p of [page, guest.page]) {
      await expect(p.locator('#scoring-overlay')).toBeHidden({ timeout: 20_000 });
      await expect(p.locator('#peek-overlay')).toBeVisible();
      await expect(p.locator('#peek-hand .peek-slot')).toHaveCount(4);
      await expect(p.locator('#tb-mode')).toHaveText('Einzelspiel – Runde 1/1');
      await expect(p.locator('#tb-scores .score-chip')).toHaveText(['Host: 0', 'Gast: 0']);
    }

    await guest.ctx.close();
  });
});
