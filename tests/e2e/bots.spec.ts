import { test, expect, Page, Browser } from '@playwright/test';

/**
 * KI-Gegner: Einzelspieler gegen 1–3 Bots, freie Plätze in einer
 * Mehrspieler-Session mit Bots auffüllen, und die drei Stärken.
 *
 * Der Kern der Sache ist nicht die Oberfläche, sondern die Zusage, dass ein Bot
 * NICHT hellsichtig ist: er darf nur Karten kennen, die er gesehen hat. Genau
 * das prüft der letzte Block — direkt gegen die Entscheidungsfunktion des
 * Servers, weil man es einem Spielverlauf von außen nicht ansieht.
 */

async function hostWithBots(page: Page, name: string, bots: string, level: string) {
  await page.goto('/');
  await page.locator('#player-name').fill(name);
  await page.locator('#bot-count').selectOption(bots);
  await page.locator('#bot-level').selectOption(level);
  await page.getByRole('button', { name: 'Session erstellen' }).click();
  await expect(page.locator('#lobby-waiting')).toBeVisible();
  return (await page.locator('#session-id-display').innerText()).trim();
}

test.describe('Bots in der Lobby', () => {
  test('Stärke-Auswahl erscheint erst, wenn Bots mitspielen sollen', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#bot-level')).toBeHidden();
    await page.locator('#bot-count').selectOption('2');
    await expect(page.locator('#bot-level')).toBeVisible();
    await page.locator('#bot-count').selectOption('0');
    await expect(page.locator('#bot-level')).toBeHidden();
  });

  test('Einzelspiel gegen drei Bots: Tisch ist voll und startbereit', async ({ page }) => {
    await hostWithBots(page, 'Solo', '3', 'hard');

    await expect(page.locator('#players-list .player-chip')).toHaveCount(4);
    await expect(page.locator('#players-list .bot-tag')).toHaveCount(3);
    // Die Stärke steht an jedem Bot – auch mitten in der Partie soll man sie
    // nachsehen können.
    for (const tag of await page.locator('#players-list .bot-tag').all()) {
      await expect(tag).toHaveText(/Schwer/);
    }
    // Voller Tisch: kein weiterer Bot mehr, aber Start ist frei.
    await expect(page.locator('#bot-fill')).toBeHidden();
    await expect(page.locator('#start-btn')).toBeVisible();
  });

  test('ein einzelner Bot genügt zum Starten', async ({ page }) => {
    await hostWithBots(page, 'Solo', '1', 'easy');
    await expect(page.locator('#players-list .player-chip')).toHaveCount(2);
    await expect(page.locator('#players-list .bot-tag')).toHaveText(/Leicht/);
    await expect(page.locator('#start-btn')).toBeVisible();
    // Zwei Plätze frei: auffüllen geht weiterhin.
    await expect(page.locator('#bot-fill')).toBeVisible();
  });

  test('der Host kann einen Bot wieder vom Tisch nehmen', async ({ page }) => {
    await hostWithBots(page, 'Solo', '2', 'medium');
    await expect(page.locator('#players-list .player-chip')).toHaveCount(3);

    await page.locator('.bot-kick').first().click();
    await expect(page.locator('#players-list .player-chip')).toHaveCount(2);
    await expect(page.locator('#players-list .bot-tag')).toHaveCount(1);
  });

  test('Mehrspieler: freie Plätze werden mit Bots aufgefüllt', async ({ page, browser }) => {
    // Ganz normale Session ohne Bots – so wie man sie mit Freunden aufmacht.
    await page.goto('/');
    await page.locator('#player-name').fill('Host');
    await page.getByRole('button', { name: 'Session erstellen' }).click();
    // Erst warten, dann den Code lesen: vor dem 'created' des Servers steht da
    // ein leerer String, und ein Beitritt darauf schlägt still fehl.
    await expect(page.locator('#lobby-waiting')).toBeVisible();
    const code = (await page.locator('#session-id-display').innerText()).trim();
    expect(code).toMatch(/^\d{4}$/);

    const ctx = await browser.newContext();
    const guest = await ctx.newPage();
    await guest.goto('/');
    await guest.locator('#player-name').fill('Gast');
    await guest.locator('#join-code').fill(code);
    await guest.getByRole('button', { name: 'Beitreten' }).click();
    await expect(guest.locator('#session-id-display')).toHaveText(code);
    await expect(page.locator('#players-list .player-chip')).toHaveCount(2);

    // Zwei Menschen, zwei freie Plätze -> "Auffüllen" setzt genau zwei Bots.
    await page.locator('#bot-fill-level').selectOption('hard');
    await page.getByRole('button', { name: 'Auffüllen' }).click();
    await expect(page.locator('#players-list .player-chip')).toHaveCount(4);
    await expect(page.locator('#players-list .bot-tag')).toHaveCount(2);

    // Der Gast sieht die Bots auch – und darf sie nicht entfernen.
    await expect(guest.locator('#players-list .player-chip')).toHaveCount(4);
    await expect(guest.locator('#players-list .bot-tag')).toHaveCount(2);
    await expect(guest.locator('.bot-kick')).toHaveCount(0);
    await expect(guest.locator('#bot-fill')).toBeHidden();

    await ctx.close();
  });
});

test.describe('Bots am Tisch', () => {
  test('die Bots spielen von selbst: Peek, Züge und Schnapp laufen ohne Zutun', async ({ page }) => {
    await hostWithBots(page, 'Mensch', '3', 'hard');
    await page.locator('#start-btn').click();

    // Der Mensch prägt sich zwei Karten ein; die Bots erledigen ihre Peek-Phase
    // selbst und warten nicht die vollen 6 Sekunden ab.
    await expect(page.locator('#peek-overlay')).toBeVisible();
    await page.locator('#peek-hand .peek-slot').nth(0).locator('.flip-back').click();
    await page.locator('#peek-hand .peek-slot').nth(1).locator('.flip-back').click();
    await expect(page.locator('#peek-overlay')).toBeHidden({ timeout: 20_000 });

    await expect(page.locator('#opponents .opponent-zone')).toHaveCount(3);
    // Die Bot-Kennzeichnung bleibt während der Partie stehen.
    await expect(page.locator('#opponents .bot-tag')).toHaveCount(3);

    // Der Startspieler wird ausgelost — ist der Mensch dran, muss er ziehen,
    // sonst wartet der Tisch zu Recht auf ihn. Sein Zug läuft hier über das
    // Protokoll statt über Klicks: die Frage ist, ob die BOTS von selbst
    // spielen, nicht ob der Ziehen-Knopf sitzt (das prüfen andere Specs).
    const botNames = await page.evaluate(() =>
      (eval('state') as { players: { name: string; isBot: boolean }[] }).players
        .filter((p) => p.isBot)
        .map((p) => p.name),
    );
    expect(botNames).toHaveLength(3);

    const botLogCount = async () =>
      page.evaluate(
        (names) =>
          (eval('logEntries') as { params?: { name?: string } }[]).filter(
            (e) => e.params && names.includes(e.params.name as string),
          ).length,
        botNames,
      );

    // Ohne Zutun des Menschen müssen die Bots ziehen, ablegen und schnappen.
    for (let i = 0; i < 40 && (await botLogCount()) < 5; i++) {
      await page.evaluate(() => {
        const st = eval('state') as { phase: string; currentPlayerId: string; myId: string; drawnCard: unknown };
        const s = eval('send') as (m: unknown) => void;
        if (st.phase !== 'playing' || st.currentPlayerId !== st.myId) return;
        // Ziehen und auf Slot 1 tauschen: das löst keine Fähigkeit aus und gibt
        // den Zug zuverlässig weiter.
        if (!st.drawnCard) s({ type: 'draw' });
        else s({ type: 'keep', handIndex: 0 });
      });
      await page.waitForTimeout(700);
    }

    expect(await botLogCount(), 'Meldungen, die von einem Bot stammen').toBeGreaterThanOrEqual(5);

    const botKeys = await page.evaluate(
      (names) =>
        (eval('logEntries') as { key: string; params?: { name?: string } }[])
          .filter((e) => e.params && names.includes(e.params.name as string))
          .map((e) => e.key),
      botNames,
    );
    expect(botKeys, 'ein Bot hat gezogen').toContain('log.draw');
  });
});

test.describe('Bots sind nicht hellsichtig', () => {
  test('ein Bot kennt nur Karten, die er gesehen hat — schwer zusätzlich Schnapp-Fehlgriffe', async () => {
    // Direkt gegen den Server: einem Spielverlauf sieht man von außen nicht an,
    // woher ein Bot seine Entscheidung nimmt. bot_value() ist der einzige Weg
    // eines Bots zu einem Kartenwert, also wird genau die Funktion geprüft.
    const { execFileSync } = await import('node:child_process');
    const path = await import('node:path');
    const ROOT = path.join(__dirname, '..', '..');

    const script = `
import sys, asyncio
sys.path.insert(0, ${JSON.stringify(ROOT)})
import server_render as sr

async def setup():
    s = sr.new_session('h', 'Mensch', None, 'single')
    for lvl in ('easy', 'medium', 'hard'):
        sr.add_bot(s, lvl)
    await sr.start_game(s)
    # start_game stösst die Bots nur an; ihre Peek-Phase läuft als eigene Task.
    # Ohne dieses Mitlaufen stünde known_cards noch leer da.
    for _ in range(2000):
        if all(p['peek_done'] for p in s['players'] if p.get('is_bot')):
            break
        await asyncio.sleep(0.01)
    return s

s = asyncio.run(setup())
bots = {p['bot_level']: p for p in s['players'] if p.get('is_bot')}

out = []

# 1. Frisch nach dem Peek: genau die zwei selbst angesehenen Karten sind bekannt,
#    alles andere (eigene wie fremde) liefert None.
for lvl, b in bots.items():
    known = sum(1 for c in b['hand'] if sr.bot_value(b, c) is not None)
    out.append(('own_known', lvl, known))
    foreign = [sr.bot_value(b, c) for p in s['players'] if p is not b for c in p['hand']]
    out.append(('foreign_known', lvl, sum(1 for v in foreign if v is not None)))

# 2. Ein Fehlgriff beim Schnappen dreht eine Karte offen um. Nur "schwer" merkt
#    sie sich; leicht und mittel vergessen sie sofort wieder.
mensch = s['players'][0]
card = mensch['hand'][0]
sr._bot_note_race_reveal(s, card)
for lvl, b in bots.items():
    out.append(('after_miss_reveal', lvl, sr.bot_value(b, card) is not None))

print(repr(out))
`;
    const raw = execFileSync('python3', ['-c', script], { cwd: ROOT }).toString().trim();
    const rows = raw
      .slice(1, -1)
      .split('), (')
      .map((r) => r.replace(/^\(|\)$/g, '').split(', '));

    const get = (kind: string, lvl: string) =>
      rows.find((r) => r[0] === `'${kind}'` && r[1] === `'${lvl}'`)![2];

    for (const lvl of ['easy', 'medium', 'hard']) {
      // Zwei eigene Karten aus dem Peek — nicht mehr, und vor allem keine fremde.
      expect(get('own_known', lvl), `${lvl}: eigene bekannte Karten`).toBe('2');
      expect(get('foreign_known', lvl), `${lvl}: fremde Karten`).toBe('0');
    }

    // Die eine erlaubte Ausnahme nach oben, und nur sie.
    expect(get('after_miss_reveal', 'easy')).toBe('False');
    expect(get('after_miss_reveal', 'medium')).toBe('False');
    expect(get('after_miss_reveal', 'hard')).toBe('True');
  });

  test('die drei Stärken unterscheiden sich beim Schnappen wie vorgegeben', async () => {
    const { execFileSync } = await import('node:child_process');
    const path = await import('node:path');
    const ROOT = path.join(__dirname, '..', '..');

    const script = `
import sys
sys.path.insert(0, ${JSON.stringify(ROOT)})
import server_render as sr
print(repr([(lvl, p['race_delay'], p['race_accuracy'], p['race_others'])
            for lvl, p in sr.BOT_PROFILES.items()]))
`;
    const raw = execFileSync('python3', ['-c', script], { cwd: ROOT }).toString().trim();

    // Reaktionszeit, Trefferquote und ob auch auf gegnerische Karten geschnappt
    // wird — das sind die drei Stellschrauben, an denen man die Stärke merkt.
    expect(raw).toContain("('easy', 4.0, 0.5, False)");
    expect(raw).toContain("('medium', 3.0, 0.65, True)");
    expect(raw).toContain("('hard', 2.5, 0.9, True)");

    // Alle drei müssen ins Schnapp-Fenster passen, sonst käme ein Bot nie zum Zug.
    const raceSeconds = execFileSync('python3', [
      '-c',
      `import sys; sys.path.insert(0, ${JSON.stringify(ROOT)}); import server_render as sr; print(sr.RACE_SECONDS)`,
    ])
      .toString()
      .trim();
    expect(Number(raceSeconds)).toBeGreaterThan(4.0);
  });
});
