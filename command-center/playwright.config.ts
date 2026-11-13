import { defineConfig, devices } from '@playwright/test';

import { testWorkers } from './scripts/test-workers.ts';

// Smoke-проверка собранного приложения (`vite build` + `vite preview`).
// API фабрики не нужен: все запросы к /api подменяются в tests/e2e/fixtures.ts,
// а любые запросы за пределы локального сервера обрываются и роняют тест.
const PORT = Number(process.env.CC_E2E_PORT || 4179);
const baseURL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  // CC-0042: половина ядер (CC_TEST_WORKERS — явно; в CI по-прежнему 1, если не задано).
  // Потолки под занятую машину: тест — 60 с вместо 30, expect — 10 с вместо 5; зависание
  // всё равно падает за минуту.
  workers: process.env.CI && !process.env.CC_TEST_WORKERS ? 1 : testWorkers(),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npx vite build && npx vite preview --port ${PORT} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
