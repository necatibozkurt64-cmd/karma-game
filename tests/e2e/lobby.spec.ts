import { test, expect, Page } from '@playwright/test';

/** Erstellt eine Session und gibt den vierstelligen Zahlencode zurück. */
async function hostSession(page: Page, name: string, mode = 'single'): Promise<string> {
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#game-mode').selectOption(mode);
  await page.getByRole('button', { name: 'Session erstellen' }).click();

  await expect(page.locator('#lobby-waiting')).toBeVisible();
  const code = (await page.locator('#session-id-display').innerText()).trim();
  expect(code).toMatch(/^[0-9]{4}$/);
  return code;
}

async function joinSession(page: Page, name: string, code: string) {
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#join-code').fill(code);
  await page.getByRole('button', { name: 'Beitreten' }).click();
}

test.describe('Lobby', () => {
  test('startet in der Lobby, nicht im Spiel', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#lobby-home')).toBeVisible();
    await expect(page.locator('#lobby-waiting')).toBeHidden();
    await expect(page.locator('#player-name')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Session erstellen' })).toBeVisible();
  });

  test('ohne Namen erscheint ein Hinweis statt einer Session', async ({ page }) => {
    await page.goto('/');

    // alert() blockiert den Renderer. Der Dialog muss im Listener selbst
    // geschlossen werden — ein reines waitForEvent('dialog') würde den Klick
    // hängen lassen, weil ein registrierter Listener das Auto-Dismiss abschaltet.
    const messages: string[] = [];
    page.on('dialog', async (d) => {
      messages.push(d.message());
      await d.dismiss();
    });

    await page.getByRole('button', { name: 'Session erstellen' }).click();
    await expect.poll(() => messages).toEqual(['Bitte Namen eingeben']);
    await expect(page.locator('#lobby-waiting')).toBeHidden();
  });

  test('Host bekommt einen Session-Code und sieht sich selbst mit Krone', async ({ page }) => {
    await hostSession(page, 'Necati');

    const chips = page.locator('#players-list .player-chip');
    await expect(chips).toHaveCount(1);
    await expect(chips.first()).toContainText('Necati (Du)');
    await expect(chips.first().locator('.crown')).toBeVisible();

    // Allein kann nicht gestartet werden.
    await expect(page.locator('#start-btn')).toBeHidden();
  });

  test('unbekannter Code liefert eine Fehlermeldung', async ({ page }) => {
    // Buchstaben statt Ziffern: Codes sind vierstellig numerisch, 'XXXX' kann
    // also nie vergeben sein. Eine Zahl wie '0000' könnte dagegen zufällig zu
    // einer Session eines parallel laufenden Tests gehören.
    await joinSession(page, 'Fremder', 'XXXX');
    await expect(page.locator('#toast-container .toast')).toContainText('Session nicht gefunden');
    await expect(page.locator('#lobby-waiting')).toBeHidden();
  });

  test('zweiter Spieler tritt bei — beide sehen die Runde', async ({ page, browser }) => {
    const code = await hostSession(page, 'Host');

    const guestCtx = await browser.newContext();
    const guest = await guestCtx.newPage();
    await joinSession(guest, 'Gast', code);

    await expect(guest.locator('#session-id-display')).toHaveText(code);
    await expect(guest.locator('#players-list .player-chip')).toHaveCount(2);
    await expect(guest.locator('#players-list')).toContainText('Gast (Du)');
    // Gast ist nicht Host.
    await expect(guest.locator('#start-btn')).toBeHidden();
    await expect(guest.locator('#waiting-msg')).toBeVisible();

    // Host sieht den Beitritt live per WebSocket-Broadcast.
    await expect(page.locator('#players-list .player-chip')).toHaveCount(2);
    await expect(page.locator('#players-list')).toContainText('Gast');
    await expect(page.locator('#toast-container .toast')).toContainText('Gast ist beigetreten');
    await expect(page.locator('#start-btn')).toBeVisible();

    await guestCtx.close();
  });

  // Hier stand einmal "Beitritt zu kleingeschriebenem Code": bei reinen Ziffern
  // prüft das nichts mehr, und Leerzeichen o.ä. lässt maxlength="4" gar nicht
  // erst ins Feld. Der normale Beitritt oben deckt den Weg ab.
});
