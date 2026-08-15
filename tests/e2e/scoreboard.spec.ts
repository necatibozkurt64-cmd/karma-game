import { test, expect, type Page } from '@playwright/test';

/**
 * Endstand: Punkte je Runde als Tabelle + Snoop-Kopfzeile.
 *
 * Ein echtes Best-of-3 durchzuspielen dauert im Browser Minuten und hängt am
 * Zufall des Decks. Getestet wird deshalb genau die Stelle, die das Update
 * verändert: renderScoringModal() gegen einen eingesetzten State — derselbe
 * Weg, den auch i18n-keys.spec.ts nimmt. Die Verdrahtung State→Server deckt
 * server-sync.spec.ts ab.
 */

const PLAYERS = [
  { id: 'p1', name: 'Anna' },
  { id: 'p2', name: 'Bert' },
];

// Best of 3. Anna beendet Runde 2 zu früh und kassiert die 30 Strafpunkte:
// 3 Kartenpunkte + 30 = 33. Summen: Anna 12+33+4 = 49, Bert 5+8+21 = 34.
const HISTORY = [
  { round: 1, scores: { p1: 12, p2: 5 }, penalties: {} },
  { round: 2, scores: { p1: 33, p2: 8 }, penalties: { p1: 30 } },
  { round: 3, scores: { p1: 4, p2: 21 }, penalties: {} },
];

type Round = (typeof HISTORY)[number];

async function showFinalScore(page: Page, history: Round[] = HISTORY, lang = 'de') {
  await page.goto('/');
  await page.evaluate(
    ({ history, lang, players }) => {
      // Sprache umstellen, solange state noch null ist – setLanguage() würde
      // sonst render() auf dem eingesetzten Teil-State auslösen.
      (eval('setLanguage') as (l: string) => void)(lang);

      const totals: Record<string, number> = {};
      for (const r of history)
        for (const [pid, v] of Object.entries(r.scores)) totals[pid] = (totals[pid] ?? 0) + v;
      const last = history[history.length - 1];

      const fake = {
        phase: 'done',
        myId: 'p1',
        roundNumber: history.length,
        totalRounds: history.length,
        endCalledBy: 'p1',
        players: players.map((p) => ({ ...p, hand: [] })),
        roundScores: last.scores,
        matchScores: totals,
        scoreBreakdown: Object.fromEntries(
          players.map((p) => [
            p.id,
            {
              cards: [],
              card_total: last.scores[p.id as 'p1' | 'p2'] - (last.penalties[p.id] ?? 0),
              penalties: last.penalties[p.id]
                ? [{ amount: last.penalties[p.id], reasons: ['notWon', 'over7'] }]
                : [],
            },
          ]),
        ),
        roundHistory: history,
      };
      eval('state = ' + JSON.stringify(fake));
      (eval('renderScoringModal') as () => void)();
    },
    { history, lang, players: PLAYERS },
  );
}

/** Tabelleninhalt als Zeilen von Zellen-Texten. */
async function tableGrid(page: Page) {
  return page.$$eval('#scoring-modal .round-table tr', (rows) =>
    rows.map((r) => [...r.querySelectorAll('th,td')].map((c) => c.textContent!.trim())),
  );
}

test.describe('Endstand', () => {
  test('zeigt die Punkte je Runde mit Summenzeile', async ({ page }) => {
    await showFinalScore(page);

    await expect(page.locator('#scoring-modal .round-table')).toBeVisible();
    expect(await tableGrid(page)).toEqual([
      ['Runde', 'Anna', 'Bert'],
      ['1', '12', '5'],
      ['2', '33*', '8'],
      ['3', '4', '21'],
      ['Gesamt', '49', '34'],
    ]);
  });

  test('markiert nur die Strafrunde mit * und hebt sie farblich ab', async ({ page }) => {
    await showFinalScore(page);

    const starred = page.locator('#scoring-modal .round-table td.pen');
    await expect(starred).toHaveCount(1);
    await expect(starred).toHaveText('33*');

    // Kein anderes Feld trägt versehentlich einen Stern.
    const withStar = await page.$$eval('#scoring-modal .round-table td', (tds) =>
      tds.filter((td) => td.textContent!.includes('*')).length,
    );
    expect(withStar).toBe(1);

    await expect(page.locator('#scoring-modal .round-legend')).toHaveText(
      '* enthält Strafpunkte',
    );
  });

  test('die Gesamtsumme ist die Summe der Rundenspalte', async ({ page }) => {
    await showFinalScore(page);
    const grid = await tableGrid(page);
    const rounds = grid.slice(1, -1);
    const totals = grid[grid.length - 1];

    for (let col = 1; col < totals.length; col++) {
      const sum = rounds.reduce((acc, row) => acc + parseInt(row[col], 10), 0);
      expect(parseInt(totals[col], 10), `Spalte ${grid[0][col]}`).toBe(sum);
    }
  });

  test('der Sieger steht in der Summenzeile hervorgehoben', async ({ page }) => {
    await showFinalScore(page);
    const win = page.locator('#scoring-modal .round-table tfoot td.win');
    await expect(win).toHaveCount(1);
    await expect(win).toHaveText('34'); // Bert, die kleinere Summe gewinnt
  });

  test('Snoop-GIF und Gewinnerzeile stehen ganz oben', async ({ page }) => {
    await showFinalScore(page);

    const hero = page.locator('#scoring-hero');
    await expect(hero).toBeVisible();
    await expect(hero.locator('img')).toHaveAttribute('src', '/snoop-dogg-dancing.gif');
    await expect(hero.locator('.hero-line')).toHaveText('You are the best, Bert');

    // Das GIF kommt aus dem eigenen Repo, nicht von einem fremden CDN – und es
    // muss tatsächlich ankommen, sonst nimmt onerror es still aus dem Layout.
    await expect
      .poll(
        () =>
          hero
            .locator('img')
            .evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
        { message: 'GIF wurde geladen' },
      )
      .toBe(true);

    // "Ganz oben" heißt: vor der Überschrift im Modal.
    const heroBeforeTitle = await page.evaluate(() => {
      const h = document.getElementById('scoring-hero')!;
      const title = document.getElementById('scoring-title')!;
      return !!(h.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(heroBeforeTitle).toBe(true);
  });

  test('der Server liefert das GIF aus dem Repo aus', async ({ page }) => {
    const res = await page.request.get('/snoop-dogg-dancing.gif');
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toBe('image/gif');
    // GIF89a-Signatur – die Datei ist wirklich ein GIF, keine 404-Seite.
    expect((await res.body()).subarray(0, 6).toString('latin1')).toBe('GIF89a');
  });

  test('nach einer einzelnen Runde gibt es keine Tabelle', async ({ page }) => {
    await showFinalScore(page, [HISTORY[0]]);

    await expect(page.locator('#scoring-modal .round-table')).toHaveCount(0);
    // Der Endstands-Kopf erscheint trotzdem.
    await expect(page.locator('#scoring-hero .hero-line')).toHaveText('You are the best, Bert');
  });

  test('ohne Strafpunkte fehlt die Sternchen-Legende', async ({ page }) => {
    const clean = HISTORY.map((r) => ({ ...r, penalties: {} }));
    await showFinalScore(page, clean);

    await expect(page.locator('#scoring-modal .round-table')).toBeVisible();
    await expect(page.locator('#scoring-modal .round-legend')).toHaveCount(0);
    await expect(page.locator('#scoring-modal .round-table td.pen')).toHaveCount(0);
  });

  test('Tabellenköpfe folgen der Sprache, der Schlachtruf bleibt englisch', async ({ page }) => {
    await showFinalScore(page, HISTORY, 'en');
    expect((await tableGrid(page))[0]).toEqual(['Round', 'Anna', 'Bert']);
    await expect(page.locator('#scoring-modal .round-legend')).toHaveText(
      '* includes penalty points',
    );
    await expect(page.locator('#scoring-hero .hero-line')).toHaveText('You are the best, Bert');

    await showFinalScore(page, HISTORY, 'tr');
    expect((await tableGrid(page))[0]).toEqual(['Tur', 'Anna', 'Bert']);
    await expect(page.locator('#scoring-modal .round-legend')).toHaveText(
      '* ceza puanı içerir',
    );
    await expect(page.locator('#scoring-hero .hero-line')).toHaveText('You are the best, Bert');
  });

  test('am Rundenende (noch nicht fertig) bleibt der Snoop-Kopf verborgen', async ({ page }) => {
    await showFinalScore(page);
    await page.evaluate(() => {
      eval('state.phase = "scoring"');
      eval('state.roundNumber = 2');
      eval('state.totalRounds = 3');
      (eval('renderScoringModal') as () => void)();
    });

    await expect(page.locator('#scoring-hero')).toBeHidden();
    // Die Tabelle bleibt – sie beantwortet dieselbe Frage auch zwischendurch.
    await expect(page.locator('#scoring-modal .round-table')).toBeVisible();
  });
});
