import { test, expect } from '@playwright/test';

/**
 * Vollständigkeitswächter für die Übersetzungen.
 *
 * t() fällt bei einem fehlenden Schlüssel absichtlich auf Deutsch zurück, damit
 * ein Vergessen höchstens unübersetzt und nie kaputt aussieht. Der Preis: eine
 * Lücke fällt niemandem auf — der Text steht einfach weiter auf Deutsch da.
 * Dieser Test schließt genau diese Lücke: jede Sprache aus LANGUAGES muss jeden
 * Schlüssel der deutschen Fassung mitbringen.
 *
 * Einzige Ausnahme ist `cardQuote` — Sprüche werden grundsätzlich nicht
 * übersetzt, jede Sprache zeigt den Originalsatz aus Karten.csv. Die
 * Wörterbücher müssen deshalb leer bleiben; genau das prüft der letzte Test.
 */
type Report = {
  languages: string[];
  translationBlocks: string[];
  missing: Record<string, string[]>;
  untranslated: Record<string, string[]>;
};

async function collect(page: import('@playwright/test').Page): Promise<Report> {
  return page.evaluate(() => {
    const TR = eval('TRANSLATIONS') as Record<string, any>;
    const LANGS = eval('LANGUAGES') as { id: string }[];
    const flat = (o: any, p = '', r: Record<string, string> = {}) => {
      for (const k of Object.keys(o)) {
        const v = o[k];
        const key = p ? `${p}.${k}` : k;
        if (v && typeof v === 'object') flat(v, key, r);
        else r[key] = String(v);
      }
      return r;
    };
    const base = flat(TR.de);
    const baseKeys = Object.keys(base).filter((k) => !k.startsWith('cardQuote.'));
    // Bewusst in jeder Sprache wortgleich: fester englischer Schlachtruf zum
    // Snoop-GIF im Endstand – wie die Figurenzitate bleibt er überall stehen.
    // Der Schlüssel muss trotzdem in jeder Sprache vorhanden sein, deshalb
    // greift die Ausnahme nur beim Übersetzungs-, nicht beim Fehlt-Test.
    const fixedPhrases = ['sc.youAreTheBest'];
    const missing: Record<string, string[]> = {};
    const untranslated: Record<string, string[]> = {};
    for (const { id } of LANGS) {
      const own = TR[id] ? flat(TR[id]) : {};
      missing[id] = baseKeys.filter((k) => !(k in own));
      // Wortgleich mit dem Deutschen ist bei Eigennamen (Best of 3, Olli, Onyx)
      // richtig — nur längere Sätze sind ein Zeichen für vergessene Übersetzung.
      untranslated[id] =
        id === 'de'
          ? []
          : baseKeys.filter(
              (k) => !fixedPhrases.includes(k) && own[k] === base[k] && base[k].length > 24,
            );
    }
    return {
      languages: LANGS.map((l) => l.id),
      translationBlocks: Object.keys(TR),
      missing,
      untranslated,
    };
  });
}

test.describe('Übersetzungs-Schlüssel', () => {
  test('jede Sprache aus LANGUAGES hat einen Block in TRANSLATIONS', async ({ page }) => {
    await page.goto('/');
    const rep = await collect(page);

    expect(rep.languages).toEqual(['de', 'en', 'tr']);
    expect(rep.translationBlocks.sort()).toEqual([...rep.languages].sort());
  });

  test('keine Sprache fällt heimlich auf Deutsch zurück', async ({ page }) => {
    await page.goto('/');
    const rep = await collect(page);

    for (const lang of rep.languages) {
      expect(rep.missing[lang], `${lang}: fehlende Schlüssel`).toEqual([]);
      expect(rep.untranslated[lang], `${lang}: noch deutscher Text`).toEqual([]);
    }
  });

  test('Kartenfähigkeiten sind in jeder Sprache übersetzt', async ({ page }) => {
    await page.goto('/');
    // Genau der Weg, den die Karte am Tisch geht: buildCardInner → getAbilityName
    // / getAbilityDesc. Damit prüft der Test die Anzeige, nicht nur das Wörterbuch.
    const rendered = await page.evaluate(() => {
      // 'none' fehlt hier bewusst: solche Karten zeigen gar keinen
      // Fähigkeitstext mehr – das prüft der Test darunter.
      const abilities = ['see_own', 'see_others', 'swap', 'see_swap'];
      const out: Record<string, Record<string, string>> = {};
      for (const { id } of eval('LANGUAGES') as { id: string }[]) {
        (eval('setLanguage') as (l: string) => void)(id);
        out[id] = {};
        for (const ability of abilities) {
          const card = { nr: 12, name: 'Hund', value: 12, ability, quote: 'x', image: '12_Hund.jpg', color: '#2196F3' };
          const el = document.createElement('div');
          el.innerHTML = (eval('buildCardInner') as Function)(card, 130, 190);
          out[id][ability] =
            el.querySelector('.tcg-ability-name')!.textContent + ' | ' +
            el.querySelector('.tcg-ability-desc')!.textContent;
        }
      }
      return out;
    });

    expect(rendered.de.see_swap).toBe('Sehen & Tauschen | Du kannst zwei Karten ansehen und dann tauschen.');
    expect(rendered.en.see_swap).toBe('See & Swap | You may look at two cards and then swap them.');
    expect(rendered.tr.see_swap).toBe('Bak & Takas et | İki karta bakıp sonra takas edebilirsin.');

    // Keine Sprache zeigt die deutsche Fassung einer anderen Fähigkeit.
    for (const lang of ['en', 'tr']) {
      for (const [ability, text] of Object.entries(rendered[lang])) {
        expect(text, `${lang}/${ability}`).not.toBe(rendered.de[ability]);
        expect(text, `${lang}/${ability}`).not.toContain('Fähigkeit');
      }
    }
  });

  test('Karten ohne Fähigkeit tragen keinen Fähigkeitstext', async ({ page }) => {
    await page.goto('/');
    // Statt „Keine Fähigkeiten" + Erklärsatz bleibt nur der NORMAL-Chip stehen –
    // in jeder Sprache, sonst stünde die leere Aussage anderswo doch wieder da.
    const plain = await page.evaluate(() => {
      const out: Record<string, { chip: string; hasName: boolean; hasDesc: boolean; text: string }> = {};
      for (const { id } of eval('LANGUAGES') as { id: string }[]) {
        (eval('setLanguage') as (l: string) => void)(id);
        const card = { nr: 5, name: 'Barbie', value: 5, ability: 'none', quote: 'Ciao bella ciao!', image: 'fotos/05-barbie.webp', color: '#4CAF50' };
        const el = document.createElement('div');
        el.innerHTML = (eval('buildCardInner') as Function)(card, 130, 190);
        out[id] = {
          chip: el.querySelector('.tcg-ability-label')!.textContent!,
          hasName: !!el.querySelector('.tcg-ability-name'),
          hasDesc: !!el.querySelector('.tcg-ability-desc'),
          text: el.textContent!,
        };
      }
      return out;
    });

    for (const [lang, card] of Object.entries(plain)) {
      expect(card.chip, `${lang}: Chip`).toBe('NORMAL');
      expect(card.hasName, `${lang}: Fähigkeitsname`).toBe(false);
      expect(card.hasDesc, `${lang}: Fähigkeitstext`).toBe(false);
      expect(card.text, `${lang}: Resttext`).not.toMatch(/no special ability|Keine Fähigkeiten|No ability|Yetenek yok|yeteneği yok/i);
      // Das Zitat bleibt – nur die leere Fähigkeitsaussage verschwindet.
      expect(card.text, `${lang}: Zitat`).toContain('Ciao bella ciao!');
    }
  });

  test('Sprüche werden nie übersetzt', async ({ page }) => {
    await page.goto('/');
    // Ein Spruch gehört der Figur, nicht der Sprache: „einmal zwei döner" bleibt
    // auch auf Englisch stehen. Deshalb darf kein cardQuote-Wörterbuch gefüllt
    // sein — sobald dort ein Eintrag auftaucht, weicht eine Sprachfassung von
    // Karten.csv ab, ohne dass es jemandem auffällt.
    const quotes = await page.evaluate(() => {
      const TR = eval('TRANSLATIONS') as Record<string, { cardQuote?: Record<string, string> }>;
      const out: Record<string, string[]> = {};
      for (const { id } of eval('LANGUAGES') as { id: string }[]) {
        out[id] = Object.keys(TR[id]?.cardQuote ?? {});
      }
      return out;
    });

    for (const [lang, keys] of Object.entries(quotes)) {
      expect(keys, `${lang}: übersetzte Sprüche`).toEqual([]);
    }

    // Und die Anzeige nimmt wirklich den Servertext, in jeder Sprache.
    const shown = await page.evaluate(() => {
      const card = { nr: 4, name: 'Ugur', value: 4, ability: 'none', quote: 'einmal zwei döner', image: 'fotos/04-ugur.webp', color: '#4CAF50' };
      const out: Record<string, string> = {};
      for (const { id } of eval('LANGUAGES') as { id: string }[]) {
        (eval('setLanguage') as (l: string) => void)(id);
        out[id] = (eval('cardQuote') as (c: unknown) => string)(card);
      }
      return out;
    });

    for (const [lang, text] of Object.entries(shown)) {
      expect(text, `${lang}: Spruch`).toBe('einmal zwei döner');
    }
  });
});
