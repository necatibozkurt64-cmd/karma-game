import { test, expect } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const ROOT = path.join(__dirname, '..', '..');
// Nach jeder gewollten Änderung an CARD_DEFS neu setzen:
//   python3 -c "import hashlib,json,runpy;c=runpy.run_path('server_render.py')['CARD_DEFS'];\
//     print(hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest())"
const CARD_DEFS_SHA256 = '435bcf571297478c25077c7e2a973b12291bb63601d51decf10e1bcb8402f6d4';

type ArtworkManifest = {
  cardDefsHash: string;
  cardCount: number;
  deckSize: number;
  images: string[];
};

function artworkManifest(): ArtworkManifest {
  // Load the runtime constants rather than trying to parse Python source. This
  // makes the check sensitive to accidental game-data edits as well as broken
  // image mappings, while keeping the game implementation untouched.
  const script = [
    'import hashlib, json, runpy',
    "state = runpy.run_path('server_render.py')",
    "cards = state['CARD_DEFS']",
    "images = state['IMAGE_FILES']",
    "digest = hashlib.sha256(json.dumps(cards, sort_keys=True, separators=(',', ':')).encode()).hexdigest()",
    "print(json.dumps({'cardDefsHash': digest, 'cardCount': len(cards), 'deckSize': sum(card['count'] for card in cards), 'images': [images[nr] for nr in sorted(images)]}))",
  ].join('\n');
  const result = spawnSync('python3', ['-c', script], { cwd: ROOT, encoding: 'utf8' });

  expect(result.status, result.stderr).toBe(0);
  return JSON.parse(result.stdout) as ArtworkManifest;
}

test('Kartendaten unverändert und alle 15 Kartenbilder werden ausgeliefert', async ({ request }) => {
  const manifest = artworkManifest();

  expect(manifest.cardDefsHash).toBe(CARD_DEFS_SHA256);
  expect(manifest.cardCount).toBe(15);
  expect(manifest.deckSize).toBe(52);
  expect(manifest.images).toHaveLength(15);
  expect(new Set(manifest.images).size).toBe(15);
  // Die vier ausgetauschten Karten (Barbie 5, Hawk Tuah Girl 6, Penny 9,
  // Merkel 10) liegen als optimiertes WebP unter fotos/; der Rest sind die
  // Originalbilder im Wurzelverzeichnis von Bilder/.
  for (const nr of [5, 6, 9, 10]) {
    expect(manifest.images[nr - 1], `Karte ${nr}`).toMatch(/^fotos\/\d{2}-[a-z0-9-]+\.webp$/);
  }

  for (const image of manifest.images) {
    const response = await request.get(`/images/${encodeURIComponent(image)}`);
    expect(response.ok(), image).toBeTruthy();
    expect(response.headers()['content-type'], image).toMatch(/^image\/(webp|jpeg|png)$/);
  }
});
