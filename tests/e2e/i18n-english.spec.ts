import { test, expect, Page, Browser } from '@playwright/test';

/**
 * Die englische Fassung: Sprache steht in localStorage ('karma_language'), die
 * Texte kommen aus TRANSLATIONS im Client. Server-Meldungen sind Schlüssel +
 * Parameter — übersetzt wird erst beim Anzeigen, damit zwei Spieler am selben
 * Tisch verschiedene Sprachen fahren können.
 *
 * Die Sprache wird per addInitScript VOR dem ersten Laden gesetzt: loadSettings()
 * läuft beim Parsen des Skripts, ein späteres localStorage.setItem käme zu spät.
 */
async function useEnglish(page: Page) {
  await page.addInitScript(() => localStorage.setItem('karma_language', 'en'));
}

async function hostSession(page: Page, name: string, mode = 'single'): Promise<string> {
  await useEnglish(page);
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#game-mode').selectOption(mode);
  await page.getByRole('button', { name: 'Create Session' }).click();
  await expect(page.locator('#lobby-waiting')).toBeVisible();
  return (await page.locator('#session-id-display').innerText()).trim();
}

async function addGuest(browser: Browser, code: string, name: string) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await useEnglish(page);
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#join-code').fill(code);
  await page.getByRole('button', { name: 'Join' }).click();
  await expect(page.locator('#session-id-display')).toHaveText(code);
  return { ctx, page };
}

test.describe('Englische Fassung', () => {
  test('Lobby ist vollständig englisch', async ({ page }) => {
    await useEnglish(page);
    await page.goto('/');

    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('.logo-sub')).toHaveText('The Card Game');
    await expect(page.locator('#lobby-home h2')).toHaveText('Player');
    await expect(page.locator('#player-name')).toHaveAttribute('placeholder', 'Your Name');
    await expect(page.locator('#join-code')).toHaveAttribute('placeholder', 'Session code (e.g. 1234)');
    await expect(page.getByRole('button', { name: 'Create Session' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Join' })).toBeVisible();
    await expect(page.locator('#game-mode option').first()).toHaveText('Single Game');
  });

  test('Umschalten in den Einstellungen wirkt sofort, ohne Reload', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.logo-sub')).toHaveText('Das Kartenspiel');

    await page.locator('#lobby-gear').click();
    await page.locator('#lang-en').click();

    await expect(page.locator('.logo-sub')).toHaveText('The Card Game');
    await expect(page.locator('#settings-done-btn')).toHaveText('Done');
    await expect(page.locator('#lang-label')).toHaveText('Language');
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');

    // Und wieder zurück — der Wechsel geht in beide Richtungen.
    await page.locator('#lang-de').click();
    await expect(page.locator('.logo-sub')).toHaveText('Das Kartenspiel');
  });

  test('Fehlermeldung vom Server erscheint englisch', async ({ page }) => {
    await useEnglish(page);
    await page.goto('/');

    const messages: string[] = [];
    page.on('dialog', async (d) => { messages.push(d.message()); await d.dismiss(); });
    await page.getByRole('button', { name: 'Create Session' }).click();
    await expect.poll(() => messages).toEqual(['Please enter a name']);

    await page.locator('#player-name').fill('Stranger');
    await page.locator('#join-code').fill('XXXX');
    await page.getByRole('button', { name: 'Join' }).click();
    await expect(page.locator('#toast-container .toast')).toContainText('Session not found');
  });

  test('Regelwerk ist englisch, Karten heißen Cat und Dog', async ({ page }) => {
    await useEnglish(page);
    await page.goto('/');
    await page.locator('#lobby-help').click();

    const modal = page.locator('#help-modal');
    await expect(modal.locator('h2')).toHaveText('📖 Game Rules – Karma');
    await expect(modal).toContainText('Goal of the Game');
    await expect(modal).toContainText('Snap – React Fast!');
    await expect(modal).toContainText('Penalty points go to');
    // Kartentabelle: die beiden deutschen Namen sind übersetzt, der Rest bleibt.
    await expect(modal.locator('table')).toContainText('🐱 Cat');
    await expect(modal.locator('table')).toContainText('🐕 Dog');
    await expect(modal.locator('table')).toContainText('See an opponent');
    await expect(modal.locator('table')).not.toContainText('Katze');
    await expect(modal.locator('table')).not.toContainText('Hund');
    // Kein Rest-Deutsch im ganzen Regelwerk.
    await expect(modal).not.toContainText('Fähigkeit');
    await expect(modal).not.toContainText('Spieler');
  });

  test('Tisch, Karten und Log laufen englisch', async ({ page, browser }) => {
    const code = await hostSession(page, 'Alice', 'best_of_3');
    const guest = await addGuest(browser, code, 'Bob');

    await expect(page.locator('#players-list')).toContainText('Alice (You)');
    await expect(guest.page.locator('#waiting-msg')).toHaveText('Waiting for the host…');
    await expect(page.locator('#toast-container .toast')).toContainText('Bob joined!');

    await page.locator('#start-btn').click();

    // Peek-Phase
    for (const p of [page, guest.page]) {
      await expect(p.locator('#peek-title')).toHaveText('Look at your cards');
      await expect(p.locator('#peek-count-txt')).toHaveText('0 / 2 selected');
      await expect(p.locator('#deck-count')).toHaveText(/\d+ cards/);
      await expect(p.locator('.peek-slot-lbl').first()).toHaveText('Card 1');
    }
    await expect(page.locator('#tb-mode')).toHaveText('Best of 3 – Round 1/3');
    await expect(page.locator('#tb-phase')).toHaveText('Memorise');

    // Beide überspringen — danach steht der Tisch.
    await page.locator('#peek-done-btn').click();
    await guest.page.locator('#peek-done-btn').click();

    for (const p of [page, guest.page]) {
      await expect(p.locator('#peek-overlay')).toBeHidden();
      await expect(p.locator('.hand-heading')).toHaveText('Your Hand');
      await expect(p.locator('.pile-label').first()).toHaveText('Draw Pile');
      await expect(p.locator('.pile-label').nth(1)).toHaveText('Discard Pile');
      await expect(p.locator('.log-toggle-lbl')).toHaveText('History');
    }

    // Wer am Zug ist, sieht die englische Hinweiszeile und den Beenden-Knopf.
    const onTurn = (await page.locator('#turn-badge').isVisible()) ? page : guest.page;
    const waiting = onTurn === page ? guest.page : page;
    await expect(onTurn.locator('#turn-badge')).toHaveText('Your Turn');
    await expect(onTurn.locator('#instruct')).toHaveText('Draw a card from the draw pile or end the game');
    await expect(onTurn.locator('#action-bar button')).toHaveText('End Game');
    await expect(waiting.locator('#instruct')).toHaveText(/^Waiting for /);

    // Ziehen: Kartenfläche und Entscheidungsansicht sind englisch, die
    // Server-Meldung landet übersetzt im Log des Gegenübers.
    await onTurn.locator('#deck-pile').click();
    await expect(onTurn.locator('.drawn-label')).toHaveText('Drawn Card');
    // Karten ohne Fähigkeit zeigen nur den NORMAL-Chip – keine Überschrift und
    // keinen Erklärsatz. Welche Karte kommt, entscheidet der Stapel, also beide
    // Fälle abdecken.
    const chip = onTurn.locator('#drawn-card-display .tcg-ability-label');
    await expect(chip).toHaveText(/^(NORMAL|ABILITY)$/);
    const abName = onTurn.locator('#drawn-card-display .tcg-ability-name');
    if ((await chip.innerText()) === 'ABILITY') {
      await expect(abName).toHaveText(
        /^(See your own card|See an opponent's card|Swap cards|See & Swap)$/);
    } else {
      await expect(abName).toHaveCount(0);
      await expect(onTurn.locator('#drawn-card-display .tcg-ability-desc')).toHaveCount(0);
    }
    await expect(onTurn.locator('#drawn-discard-btn')).toHaveText(/^(Discard|Discard & use ability)$/);
    await expect(waiting.locator('#log-panel')).toContainText('draws a card');
    await expect(waiting.locator('.opp-thinking')).toContainText('thinking');

    await guest.ctx.close();
  });

  test('Sprachwechsel im laufenden Spiel beschriftet auch das Log um', async ({ page, browser }) => {
    const code = await hostSession(page, 'Alice');
    const guest = await addGuest(browser, code, 'Bob');
    await page.locator('#start-btn').click();

    await page.locator('#peek-done-btn').click();
    await guest.page.locator('#peek-done-btn').click();
    await expect(page.locator('#peek-overlay')).toBeHidden();

    const onTurn = (await page.locator('#turn-badge').isVisible()) ? page : guest.page;
    const other = onTurn === page ? guest.page : page;
    await onTurn.locator('#deck-pile').click();
    await expect(other.locator('#log-panel')).toContainText('draws a card');

    // Umschalten auf Deutsch: die bereits eingetroffene Meldung wird aus den
    // Rohdaten neu gezeichnet, nicht nur die künftigen.
    await other.locator('#topbar .gear-btn').nth(1).click();
    await other.locator('#lang-de').click();
    await other.locator('#settings-done-btn').click();

    await expect(other.locator('#log-panel')).toContainText('zieht eine Karte');
    await expect(other.locator('#log-panel')).not.toContainText('draws a card');
    await expect(other.locator('.hand-heading')).toHaveText('Deine Hand');
    await expect(other.locator('.pile-label').first()).toHaveText('Nachziehstapel');

    // Der andere Spieler bleibt englisch — die Sprache ist pro Browser.
    await expect(onTurn.locator('.hand-heading')).toHaveText('Your Hand');

    await guest.ctx.close();
  });
});
