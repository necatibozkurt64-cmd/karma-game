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
 * Einzige Ausnahme ist `cardQuote` — das Wörterbuch ist bewusst dünn besetzt
 * und überschreibt nur die Zitate, die nicht schon in der Quelle (Karten.csv)
 * passen; alles andere kommt vom Server.
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
    const missing: Record<string, string[]> = {};
    const untranslated: Record<string, string[]> = {};
    for (const { id } of LANGS) {
      const own = TR[id] ? flat(TR[id]) : {};
      missing[id] = baseKeys.filter((k) => !(k in own));
      // Wortgleich mit dem Deutschen ist bei Eigennamen (Best of 3, Olli, Onyx)
      // richtig — nur längere Sätze sind ein Zeichen für vergessene Übersetzung.
      untranslated[id] =
        id === 'de' ? [] : baseKeys.filter((k) => own[k] === base[k] && base[k].length > 24);
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
      const abilities = ['none', 'see_own', 'see_others', 'swap', 'see_swap'];
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
});
