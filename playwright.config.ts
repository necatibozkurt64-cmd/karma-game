import { defineConfig, devices } from '@playwright/test';

/**
 * E2E-Setup für den Karma-Server (aiohttp, HTTP + WebSocket auf einem Port).
 *
 * Playwright startet eine eigene Instanz auf E2E_PORT, damit ein laufender
 * Dev-Server auf 3000 nicht gestört wird. Sessions liegen nur im RAM des
 * Servers — jeder Lauf startet also ohnehin bei null, es gibt nichts
 * zurückzusetzen.
 */
const TEST_PORT = Number(process.env.E2E_PORT ?? 3100);
const BASE_URL = `http://127.0.0.1:${TEST_PORT}`;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Ein Mehrspieler-Test öffnet 2–3 Browser-Kontexte. Mit der Playwright-
  // Voreinstellung (= halbe CPU-Zahl) laufen dann >15 Kontexte gleichzeitig,
  // und Tests kippen in Timeouts, ohne dass am Code etwas falsch ist.
  workers: process.env.CI ? 1 : 3,
  // Die Peek-Phase hat 6 Sekunden Zwangsanzeige — 30 s Default sind zu knapp.
  timeout: 60_000,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    locale: 'de-DE',
    timezoneId: 'Europe/Berlin',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 7'] } },
  ],

  webServer: {
    // Dev-Server (siehe CLAUDE.md). Dass app/server_final.py dazu synchron
    // bleibt, prüft tests/e2e/server-sync.spec.ts.
    command: `python3 server_render.py`,
    url: BASE_URL,
    cwd: __dirname,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: 'pipe',
    stderr: 'pipe',
    env: { PORT: String(TEST_PORT) },
  },
});
