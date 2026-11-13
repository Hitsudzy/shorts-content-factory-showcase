// Подставной случай CC-0137 для e2e и screens: последний батч истории — без роликов (EMPTY),
// как второй батч Tech на фабрике 2.5 (0 тем).
import type { Page } from '@playwright/test';

import { EMPTY } from '../../src/mocks/videos';

/** Батч EMPTY (0 роликов) — последний в истории прогонов. */
export async function latestIsEmpty(page: Page) {
  await page.route(
    (url) => url.pathname === '/api/batches/history',
    (route) =>
      route.fulfill({
        json: {
          channel: null,
          runs: [
            {
              batch: EMPTY,
              id: '2026-10-07T0200Z',
              channel: 'example-tech',
              date: '2026-10-07',
              started: '2026-10-07T02:00:00Z',
              ended: '2026-10-07T02:40:00Z',
              videos: 0,
              wall_s: 2400,
              outcome: 'no_videos',
              launch: null,
            },
          ],
          launches: [],
        },
      }),
  );
}
