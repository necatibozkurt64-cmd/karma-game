import { test, expect, Page, Browser } from '@playwright/test';

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

/**
 * Wählt die ersten beiden Handkarten. Die zweite Karte startet serverseitig
 * automatisch die 6-Sekunden-Anzeige (REVEAL_SECONDS) — es ist kein weiterer
 * Klick nötig.
 *
 * Achtung beim Assert danach: sobald der LETZTE Spieler fertig ist, wechselt
 * die Phase auf 'playing' und das Peek-Modal wird nicht mehr neu gerendert.
 * Der Titel "Einprägen abgeschlossen" erscheint deshalb nur bei Spielern, auf
 * die noch gewartet wird. Für den letzten Spieler auf ein verstecktes
 * #peek-overlay prüfen.
 */
async function peekTwoCards(page: Page) {
  await expect(page.locator('#peek-overlay')).toBeVisible();
  await page.locator('#peek-hand .peek-slot').nth(0).locator('.flip-back').click();
  await page.locator('#peek-hand .peek-slot').nth(1).locator('.flip-back').click();
  await expect(page.locator('#peek-timer')).toBeVisible();
}

test.describe('Spielstart', () => {
  test('Host startet — beide Spieler landen in der Peek-Phase', async ({ page, browser }) => {
    const code = await hostSession(page, 'Host', 'best_of_3');
    const guest = await addGuest(browser, code, 'Gast');

    await expect(page.locator('#start-btn')).toBeVisible();
    await page.locator('#start-btn').click();

    for (const p of [page, guest.page]) {
      await expect(p.locator('#game')).toBeVisible();
      await expect(p.locator('#lobby')).toBeHidden();
      await expect(p.locator('#deck-count')).toHaveText(/\d+ Karten/);
      await expect(p.locator('#peek-overlay')).toBeVisible();
      await expect(p.locator('#peek-hand .peek-slot')).toHaveCount(4);
      await expect(p.locator('#peek-count-txt')).toHaveText('0 / 2 ausgewählt');
    }

    // Spielmodus und Punktestand stehen in der Topbar.
    await expect(page.locator('#tb-mode')).toHaveText('Best of 3 – Runde 1/3');
    await expect(page.locator('#tb-scores .score-chip')).toHaveCount(2);

    await guest.ctx.close();
  });

  test('Peek: zwei Karten ansehen, dann sind beide Spieler bereit', async ({ page, browser }) => {
    const code = await hostSession(page, 'Host');
    const guest = await addGuest(browser, code, 'Gast');
    await page.locator('#start-btn').click();

    // Erste Karte: nur Auswahl, noch keine Anzeige.
    await expect(page.locator('#peek-overlay')).toBeVisible();
    await page.locator('#peek-hand .peek-slot').nth(0).locator('.flip-back').click();
    await expect(page.locator('#peek-count-txt')).toHaveText('1 / 2 ausgewählt');
    await expect(page.locator('#peek-timer')).toBeHidden();
    await expect(page.locator('#peek-done-btn')).toHaveText('Diese Karten ansehen');

    // Zweite Karte startet die 6 Sekunden.
    await page.locator('#peek-hand .peek-slot').nth(1).locator('.flip-back').click();
    await expect(page.locator('#peek-timer')).toBeVisible();

    // Host ist fertig, wartet aber noch auf den Gast.
    await expect(page.locator('#peek-title')).toHaveText('Einprägen abgeschlossen', { timeout: 20_000 });
    await expect(page.locator('#peek-count-txt')).toHaveText('1 / 2 Spieler fertig');

    await peekTwoCards(guest.page);

    // Beide fertig -> Peek-Overlay verschwindet, der Tisch ist dran.
    for (const p of [page, guest.page]) {
      await expect(p.locator('#peek-overlay')).toBeHidden({ timeout: 20_000 });
      await expect(p.locator('#deck-pile')).toBeVisible();
      await expect(p.locator('#my-hand .card')).toHaveCount(4);
      await expect(p.locator('#opponents .opponent-zone')).toHaveCount(1);
    }

    await guest.ctx.close();
  });

  test('"Überspringen" beendet die Peek-Phase ohne Kartenauswahl', async ({ page, browser }) => {
    const code = await hostSession(page, 'Host');
    const guest = await addGuest(browser, code, 'Gast');
    await page.locator('#start-btn').click();

    // Ohne Auswahl heißt der Button "Überspringen" und setzt sofort fertig —
    // ohne die 6 Sekunden abzuwarten.
    await expect(page.locator('#peek-done-btn')).toHaveText('Überspringen');
    await page.locator('#peek-done-btn').click();
    await expect(page.locator('#peek-title')).toHaveText('Einprägen abgeschlossen');
    await expect(page.locator('#peek-timer')).toBeHidden();

    await peekTwoCards(guest.page);

    await expect(page.locator('#peek-overlay')).toBeHidden({ timeout: 20_000 });
    await expect(page.locator('#my-hand .card')).toHaveCount(4);

    await guest.ctx.close();
  });

  test('ein dritter Spieler kann nicht in ein laufendes Spiel', async ({ page, browser }) => {
    const code = await hostSession(page, 'Host');
    const guest = await addGuest(browser, code, 'Gast');
    await page.locator('#start-btn').click();
    await expect(page.locator('#game')).toBeVisible();

    const ctx = await browser.newContext();
    const late = await ctx.newPage();
    await late.goto('/');
    await late.locator('#player-name').fill('Zuspät');
    await late.locator('#join-code').fill(code);
    await late.getByRole('button', { name: 'Beitreten' }).click();

    await expect(late.locator('#toast-container .toast')).toContainText('Spiel bereits gestartet');
    await expect(late.locator('#lobby-waiting')).toBeHidden();

    await ctx.close();
    await guest.ctx.close();
  });
});
