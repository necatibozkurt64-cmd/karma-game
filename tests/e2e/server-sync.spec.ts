import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

/**
 * Der dokumentierte Haupt-Stolperstein des Projekts (siehe CLAUDE.md):
 * server_render.py (dev) und app/server_final.py (Railway/Prod) sind
 * Kopien voneinander und dürfen sich NUR in den beiden Pfadzeilen
 * unterscheiden. Läuft die E2E-Suite grün, aber Prod ist eine andere
 * Codebasis, ist die Suite wertlos — deshalb steht der Check hier drin.
 */
const ROOT = path.join(__dirname, '..', '..');

const ALLOWED_DIFF = new Set([
  "IMAGES_DIR = Path(__file__).parent / 'app' / 'public' / 'Bilder'",
  "PUBLIC_DIR = Path(__file__).parent / 'app' / 'public'",
  "IMAGES_DIR = Path(__file__).parent / 'public' / 'Bilder'",
  "PUBLIC_DIR = Path(__file__).parent / 'public'",
]);

test('dev- und prod-Server unterscheiden sich nur in den Pfadzeilen', () => {
  const dev = fs.readFileSync(path.join(ROOT, 'server_render.py'), 'utf8').split('\n');
  const prod = fs.readFileSync(path.join(ROOT, 'app', 'server_final.py'), 'utf8').split('\n');

  expect(dev.length, 'Zeilenzahl weicht ab — die Dateien sind auseinandergelaufen').toBe(prod.length);

  const drift: string[] = [];
  for (let i = 0; i < dev.length; i++) {
    if (dev[i] === prod[i]) continue;
    if (ALLOWED_DIFF.has(dev[i].trim()) && ALLOWED_DIFF.has(prod[i].trim())) continue;
    drift.push(`Zeile ${i + 1}:\n  dev : ${dev[i]}\n  prod: ${prod[i]}`);
  }

  expect(drift, 'Game-Logik muss in BEIDEN Server-Dateien geändert werden').toEqual([]);
});
