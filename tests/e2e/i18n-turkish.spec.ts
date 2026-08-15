import { test, expect, Page, Browser } from '@playwright/test';

/**
 * Die türkische Fassung. Aufbau wie i18n-english.spec.ts: die Sprache steht in
 * localStorage ('karma_language') und wird per addInitScript VOR dem ersten
 * Laden gesetzt — loadSettings() läuft beim Parsen des Skripts, ein späteres
 * localStorage.setItem käme zu spät.
 */
async function useTurkish(page: Page) {
  await page.addInitScript(() => localStorage.setItem('karma_language', 'tr'));
}

async function hostSession(page: Page, name: string, mode = 'single'): Promise<string> {
  await useTurkish(page);
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#game-mode').selectOption(mode);
  await page.getByRole('button', { name: 'Oturum oluştur' }).click();
  await expect(page.locator('#lobby-waiting')).toBeVisible();
  return (await page.locator('#session-id-display').innerText()).trim();
}

async function addGuest(browser: Browser, code: string, name: string) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await useTurkish(page);
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#join-code').fill(code);
  await page.getByRole('button', { name: 'Katıl' }).click();
  await expect(page.locator('#session-id-display')).toHaveText(code);
  return { ctx, page };
}

test.describe('Türkische Fassung', () => {
  test('Lobby ist vollständig türkisch', async ({ page }) => {
    await useTurkish(page);
    await page.goto('/');

    await expect(page.locator('html')).toHaveAttribute('lang', 'tr');
    await expect(page.locator('.logo-sub')).toHaveText('Kart Oyunu');
    await expect(page.locator('#lobby-home h2')).toHaveText('Oyuncu');
    await expect(page.locator('#player-name')).toHaveAttribute('placeholder', 'Adın');
    await expect(page.locator('#join-code')).toHaveAttribute('placeholder', 'Oturum kodu (örn. ABC123)');
    await expect(page.getByRole('button', { name: 'Oturum oluştur' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Katıl' })).toBeVisible();
    await expect(page.locator('#game-mode option').first()).toHaveText('Tek oyun');
  });

  test('Umschalten in den Einstellungen wirkt sofort, ohne Reload', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.logo-sub')).toHaveText('Das Kartenspiel');

    await page.locator('#lobby-gear').click();
    await expect(page.locator('#lang-grid button')).toHaveCount(3);
    await page.locator('#lang-tr').click();

    await expect(page.locator('.logo-sub')).toHaveText('Kart Oyunu');
    await expect(page.locator('#settings-done-btn')).toHaveText('Tamam');
    await expect(page.locator('#lang-label')).toHaveText('Dil');
    await expect(page.locator('html')).toHaveAttribute('lang', 'tr');
    await expect(page.locator('#lang-tr')).toHaveClass(/active/);

    // Und wieder zurück — der Wechsel geht in jede Richtung.
    await page.locator('#lang-en').click();
    await expect(page.locator('.logo-sub')).toHaveText('The Card Game');
    await page.locator('#lang-de').click();
    await expect(page.locator('.logo-sub')).toHaveText('Das Kartenspiel');
  });

  test('Fehlermeldung vom Server erscheint türkisch', async ({ page }) => {
    await useTurkish(page);
    await page.goto('/');

    const messages: string[] = [];
    page.on('dialog', async (d) => { messages.push(d.message()); await d.dismiss(); });
    await page.getByRole('button', { name: 'Oturum oluştur' }).click();
    await expect.poll(() => messages).toEqual(['Lütfen bir ad gir']);

    await page.locator('#player-name').fill('Yabancı');
    await page.locator('#join-code').fill('ZZZZZZ');
    await page.getByRole('button', { name: 'Katıl' }).click();
    await expect(page.locator('#toast-container .toast')).toContainText('Oturum bulunamadı');
  });

  test('Regelwerk ist türkisch, Karten heißen Kedi und Köpek', async ({ page }) => {
    await useTurkish(page);
    await page.goto('/');
    await page.locator('#lobby-help').click();

    const modal = page.locator('#help-modal');
    await expect(modal.locator('h2')).toHaveText('📖 Oyun kuralları – Karma');
    await expect(modal).toContainText('Oyunun amacı');
    await expect(modal).toContainText('Kap – Hızlı tepki ver!');
    await expect(modal).toContainText('Ceza puanını');
    // Kartentabelle: die beiden übersetzbaren Namen sind türkisch, der Rest bleibt.
    await expect(modal.locator('table')).toContainText('🐱 Kedi');
    await expect(modal.locator('table')).toContainText('🐕 Köpek');
    await expect(modal.locator('table')).toContainText('Rakibin kartına bak');
    await expect(modal.locator('table')).toContainText('Bak & Takas et');
    await expect(modal.locator('table')).not.toContainText('Katze');
    await expect(modal.locator('table')).not.toContainText('Hund');
    // Kein Rest-Deutsch und kein Rest-Englisch im Regelwerk.
    await expect(modal).not.toContainText('Fähigkeit');
    await expect(modal).not.toContainText('Spieler');
    await expect(modal).not.toContainText('Ability');
  });

  test('Tisch, Karten und Log laufen türkisch', async ({ page, browser }) => {
    const code = await hostSession(page, 'Ayse', 'best_of_3');
    const guest = await addGuest(browser, code, 'Mehmet');

    await expect(page.locator('#players-list')).toContainText('Ayse (Sen)');
    await expect(guest.page.locator('#waiting-msg')).toHaveText('Kurucu bekleniyor…');
    await expect(page.locator('#toast-container .toast')).toContainText('Mehmet katıldı!');

    await page.locator('#start-btn').click();

    // Ezberleme-Phase
    for (const p of [page, guest.page]) {
      await expect(p.locator('#peek-title')).toHaveText('Kartlarına bak');
      await expect(p.locator('#peek-count-txt')).toHaveText('0 / 2 seçildi');
      await expect(p.locator('#deck-count')).toHaveText(/\d+ kart/);
      await expect(p.locator('.peek-slot-lbl').first()).toHaveText('Kart 1');
    }
    await expect(page.locator('#tb-mode')).toHaveText('3 turluk seri – Tur 1/3');
    await expect(page.locator('#tb-phase')).toHaveText('Kartlara bak');

    // Beide überspringen — danach steht der Tisch.
    await page.locator('#peek-done-btn').click();
    await guest.page.locator('#peek-done-btn').click();

    for (const p of [page, guest.page]) {
      await expect(p.locator('#peek-overlay')).toBeHidden();
      await expect(p.locator('.hand-heading')).toHaveText('Elin');
      await expect(p.locator('.pile-label').first()).toHaveText('Çekme destesi');
      await expect(p.locator('.pile-label').nth(1)).toHaveText('Iskarta destesi');
      await expect(p.locator('.log-toggle-lbl')).toHaveText('Geçmiş');
    }

    const onTurn = (await page.locator('#turn-badge').isVisible()) ? page : guest.page;
    const waiting = onTurn === page ? guest.page : page;
    await expect(onTurn.locator('#turn-badge')).toHaveText('Sıra sende');
    await expect(onTurn.locator('#instruct')).toHaveText('Çekme destesinden bir kart çek ya da oyunu bitir');
    await expect(onTurn.locator('#action-bar button')).toHaveText('Oyunu bitir');
    await expect(waiting.locator('#instruct')).toHaveText(/ bekleniyor…$/);

    // Ziehen: Kartenfläche samt Fähigkeit ist türkisch, die Server-Meldung
    // landet übersetzt im Log des Gegenübers.
    await onTurn.locator('#deck-pile').click();
    await expect(onTurn.locator('.drawn-label')).toHaveText('Çekilen kart');
    await expect(onTurn.locator('#drawn-card-display .tcg-ability-label')).toHaveText(/^(NORMAL|YETENEK)$/);
    await expect(onTurn.locator('#drawn-card-display .tcg-ability-name')).toHaveText(
      /^(Yetenek yok|Kendi kartına bak|Rakibin kartına bak|Kartları takas et|Bak & Takas et)$/);
    await expect(onTurn.locator('#drawn-discard-btn')).toHaveText(/^(At|At & yeteneği kullan)$/);
    await expect(waiting.locator('#log-panel')).toContainText('bir kart çekiyor');
    await expect(waiting.locator('.opp-thinking')).toContainText('düşünüyor');

    await guest.ctx.close();
  });

  test('Sprachwechsel im laufenden Spiel beschriftet auch das Log um', async ({ page, browser }) => {
    const code = await hostSession(page, 'Ayse');
    const guest = await addGuest(browser, code, 'Mehmet');
    await page.locator('#start-btn').click();

    await page.locator('#peek-done-btn').click();
    await guest.page.locator('#peek-done-btn').click();
    await expect(page.locator('#peek-overlay')).toBeHidden();

    const onTurn = (await page.locator('#turn-badge').isVisible()) ? page : guest.page;
    const other = onTurn === page ? guest.page : page;
    await onTurn.locator('#deck-pile').click();
    await expect(other.locator('#log-panel')).toContainText('bir kart çekiyor');

    // Umschalten auf Deutsch: die bereits eingetroffene Meldung wird aus den
    // Rohdaten neu gezeichnet, nicht nur die künftigen.
    await other.locator('#topbar .gear-btn').nth(1).click();
    await other.locator('#lang-de').click();
    await other.locator('#settings-done-btn').click();

    await expect(other.locator('#log-panel')).toContainText('zieht eine Karte');
    await expect(other.locator('#log-panel')).not.toContainText('bir kart çekiyor');
    await expect(other.locator('.hand-heading')).toHaveText('Deine Hand');

    // Der andere Spieler bleibt türkisch — die Sprache ist pro Browser.
    await expect(onTurn.locator('.hand-heading')).toHaveText('Elin');

    await guest.ctx.close();
  });
});
