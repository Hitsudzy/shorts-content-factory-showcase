import { readFileSync } from 'node:fs';

import { test as base, expect, type Locator, type Page, type Route } from '@playwright/test';

import {
  authPreset,
  createAuthBackend,
  guardAuth,
  routeAuth,
  type AuthBackend,
  type AuthPreset,
} from '../../src/mocks/auth';
import {
  createAnalyticsBackend,
  routeAnalytics,
  type AnalyticsBackend,
} from '../../src/mocks/analytics';
import { createBatchesBackend, routeBatches, type BatchesBackend } from '../../src/mocks/batches';
import {
  createChannelsBackend,
  isListed,
  routeChannels,
  type ChannelsBackend,
} from '../../src/mocks/channels';
import { createDevBackend, routeDev, type DevBackend } from '../../src/mocks/dev';
import { fixtures } from '../../src/mocks/fixtures';
import {
  createMemesBackend,
  routeMemes,
  type MemeFile,
  type MemesBackend,
} from '../../src/mocks/memes';
import {
  createMaintenanceBackend,
  routeMaintenance,
  type MaintenanceBackend,
} from '../../src/mocks/maintenance';
import { createNotifyBackend, routeNotify, type NotifyBackend } from '../../src/mocks/notify';
import { createOAuthBackend, routeOAuth, type OAuthBackend } from '../../src/mocks/oauth';
import { createPublishBackend, routePublish, type PublishBackend } from '../../src/mocks/publish';
import {
  createVersionsBackend,
  routeVersions,
  type VersionsBackend,
} from '../../src/mocks/versions';
import {
  createQuestionsBackend,
  routeQuestions,
  type QuestionsBackend,
} from '../../src/mocks/questions';
import {
  createRequestsBackend,
  routeRequests,
  type RequestsBackend,
} from '../../src/mocks/requests';
import { createRightsBackend, routeRights, type RightsBackend } from '../../src/mocks/rights';
import {
  createScheduleBackend,
  routeSchedule,
  type ScheduleBackend,
} from '../../src/mocks/schedule';
import { createGatesBackend, routeGates, type GatesBackend } from '../../src/mocks/gates';
import { createStudioBackend, routeStudio, type StudioBackend } from '../../src/mocks/studio';
import {
  createVideosBackend,
  routeVideos,
  type MediaFile,
  type VideosBackend,
} from '../../src/mocks/videos';

type Fixtures = {
  /** Состояние входа подставного API (src/mocks/auth.ts): по умолчанию `mac` — входа нет. */
  authMode: AuthPreset;
  /** Подставной вход этого теста (src/mocks/auth.ts): с состоянием. */
  auth: AuthBackend;
  /** Подставная фабрика каналов этого теста (src/mocks/channels.ts): с состоянием. */
  channels: ChannelsBackend;
  /** Подставное расписание батчей этого теста (src/mocks/schedule.ts): с состоянием. */
  schedule: ScheduleBackend;
  /** Подставные батчи этого теста (src/mocks/batches.ts): с состоянием. */
  batches: BatchesBackend;
  /** Подставные ролики этого теста (src/mocks/videos.ts): с состоянием, mp4 — с Range. */
  videos: VideosBackend;
  /** Подставная публикация этого теста (src/mocks/publish.ts): чтение и записи без сети. */
  publish: PublishBackend;
  /** Подставной журнал вопросов этого теста (src/mocks/questions.ts): с состоянием. */
  questions: QuestionsBackend;
  /** Подставная очередь просьб оператору этого теста (src/mocks/requests.ts): с состоянием. */
  requests: RequestsBackend;
  /** Подставная статистика этого теста (src/mocks/analytics.ts): только чтение. */
  analytics: AnalyticsBackend;
  /** Подставной стол мемов этого теста (src/mocks/memes.ts): с состоянием, картинки — файлами. */
  memes: MemesBackend;
  /** Подставные права и нарушение этого теста (src/mocks/rights.ts): только чтение. */
  rights: RightsBackend;
  /** Подставные уведомления и напоминания этого теста (src/mocks/notify.ts): с состоянием. */
  notify: NotifyBackend;
  /** Подставные токен и данные API этого теста (src/mocks/oauth.ts): с состоянием. */
  oauth: OAuthBackend;
  /** Подставные версии и агенты этого теста (src/mocks/versions.ts): только чтение. */
  versions: VersionsBackend;
  /** Подставное обслуживание и расход этого теста (src/mocks/maintenance.ts): с состоянием. */
  maintenance: MaintenanceBackend;
  /** Подставная «Разработка» этого теста (src/mocks/dev.ts): только чтение. */
  dev: DevBackend;
  /** Подставное чтение Studio этого теста (src/mocks/studio.ts): запуск выключен, как на проде. */
  studio: StudioBackend;
  /** Подставная цена воротец этого теста (src/mocks/gates.ts). */
  gates: GatesBackend;
  /** Задержка ответа на запись (PUT, revert), мс: чтобы был виден ход сохранения. */
  writeDelay: number;
  /**
   * Запросы к `/api/…`, дошедшие до подставного «живого» API этого теста: «МЕТОД путь». Ответ
   * service worker тренировки (CC-0073) сюда не попадает — он отвечает раньше сети.
   */
  apiHits: string[];
  /** URL запросов, которые пытались уйти мимо локального сервера и были оборваны. */
  blockedRequests: string[];
  /** Ошибки консоли и необработанные исключения страницы за тест. */
  consoleErrors: string[];
  /** false — тест сам ломает API и ждёт ошибок загрузки в консоли. */
  expectCleanConsole: boolean;
  /**
   * CC-0162: замедление процессора страницы во столько раз (Chromium, CDP
   * `Emulation.setCPUThrottlingRate`). По умолчанию — `CC_THROTTLE` из окружения, без него
   * выключено (0 или 1 — без вызова CDP). Тест гонки задаёт своё: `test.use({ cpuThrottle: 4 })`.
   */
  cpuThrottle: number;
};

/** `CC_THROTTLE=4` — весь прогон e2e на замедленном в 4 раза процессоре; иначе — без замедления. */
const envThrottle = (() => {
  const n = Number(process.env.CC_THROTTLE);
  return Number.isFinite(n) && n > 1 ? n : 0;
})();

const MOCKED = [
  ['/api/health', fixtures.health],
  ['/api/version', fixtures.version],
  ['/api/session', fixtures.session],
] as const;

// Подставной API для e2e: /api/* отвечает отсюда, всё остальное вне локального
// сервера обрывается. После каждого теста проверяем, что в сеть не ушло ничего.
// Тест может перекрыть ответ своим `page.route(...)` — маршруты страницы главнее.
export const test = base.extend<Fixtures>({
  expectCleanConsole: [true, { option: true }],
  writeDelay: [300, { option: true }],
  authMode: ['mac', { option: true }],
  cpuThrottle: [envThrottle, { option: true }],
  // Замедление — до первого действия теста; не Chromium (CDP нет) — молча без него.
  page: async ({ page, cpuThrottle, browserName }, use) => {
    if (cpuThrottle > 1 && browserName === 'chromium') {
      const cdp = await page.context().newCDPSession(page);
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: cpuThrottle });
    }
    await use(page);
  },
  auth: async ({ authMode }, use) => {
    await use(authPreset(createAuthBackend(), authMode));
  },
  // eslint-disable-next-line no-empty-pattern
  channels: async ({}, use) => {
    await use(createChannelsBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  schedule: async ({}, use) => {
    await use(createScheduleBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  batches: async ({}, use) => {
    await use(createBatchesBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  videos: async ({}, use) => {
    await use(createVideosBackend());
  },
  publish: async ({ channels }, use) => {
    const publish = createPublishBackend();
    // Канал из списка каналов (и только что созданный) — с пустой очередью, как у фабрики.
    publish.state.elsewhere = (c) => isListed(channels, c);
    await use(publish);
  },
  // eslint-disable-next-line no-empty-pattern
  questions: async ({}, use) => {
    await use(createQuestionsBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  requests: async ({}, use) => {
    await use(createRequestsBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  analytics: async ({}, use) => {
    await use(createAnalyticsBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  memes: async ({}, use) => {
    await use(createMemesBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  rights: async ({}, use) => {
    await use(createRightsBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  notify: async ({}, use) => {
    await use(createNotifyBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  oauth: async ({}, use) => {
    await use(createOAuthBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  versions: async ({}, use) => {
    await use(createVersionsBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  maintenance: async ({}, use) => {
    await use(createMaintenanceBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  dev: async ({}, use) => {
    await use(createDevBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  studio: async ({}, use) => {
    await use(createStudioBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  gates: async ({}, use) => {
    await use(createGatesBackend());
  },
  // eslint-disable-next-line no-empty-pattern
  apiHits: async ({}, use) => {
    await use([]);
  },
  blockedRequests: [
    async (
      {
        apiHits,
        auth,
        context,
        baseURL,
        channels,
        schedule,
        batches,
        videos,
        publish,
        questions,
        requests,
        analytics,
        memes,
        rights,
        notify,
        oauth,
        studio,
        gates,
        versions,
        maintenance,
        dev,
        writeDelay,
      },
      use,
    ) => {
      const blocked: string[] = [];
      const origin = new URL(baseURL ?? 'http://127.0.0.1').origin;

      await context.route('**/*', async (route) => {
        const url = new URL(route.request().url());
        if (url.origin !== origin) {
          blocked.push(url.toString());
          return route.abort('blockedbyclient');
        }
        // Те же ответы, что у MSW в Vitest, — типизированы сгенерированными типами контракта.
        const req = route.request();
        if (url.pathname.includes('/api/')) apiHits.push(`${req.method()} ${url.pathname}`);
        const body: unknown = req.postData() ? req.postDataJSON() : null;
        // CC-0037: охрана входа — раньше всех; без входа из сети API закрыто (кроме /api/auth/*).
        const refused = url.pathname.includes('/api/') ? guardAuth(auth, url) : null;
        if (refused) return route.fulfill({ status: refused.status, json: refused.body });
        const door = routeAuth(auth, req.method(), url, body);
        if (door) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          const headers = 'headers' in door ? door.headers : undefined;
          return route.fulfill({ status: door.status, json: door.body, headers });
        }
        const law = routeRights(rights, req.method(), url, body);
        if (law) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: law.status, json: law.body });
        }
        const reply = routeChannels(channels, req.method(), url, body);
        if (reply) {
          const creating =
            req.method() === 'POST' &&
            url.pathname.endsWith('/api/channels') &&
            (body as { dry_run?: boolean } | null)?.dry_run !== true;
          if (req.method() === 'PUT' || url.pathname.endsWith('/revert') || creating) {
            await new Promise((r) => setTimeout(r, writeDelay));
          }
          return route.fulfill({ status: reply.status, json: reply.body });
        }
        const planned = routeSchedule(schedule, req.method(), url, body);
        if (planned) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: planned.status, json: planned.body });
        }
        const film = routeVideos(
          videos,
          req.method(),
          url,
          { range: req.headers()['range'] },
          body,
        );
        if (film && 'file' in film) return serveFile(route, film.file, film.type);
        if (film) {
          if (req.method() === 'POST') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: film.status, json: film.body });
        }
        const going = routeBatches(batches, req.method(), url, body);
        if (going) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: going.status, json: going.body });
        }
        const pub = routePublish(publish, req.method(), url, body);
        if (pub) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: pub.status, json: pub.body });
        }
        const asked = routeQuestions(questions, req.method(), url, body);
        if (asked) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: asked.status, json: asked.body });
        }
        const asks = routeRequests(requests, req.method(), url, body);
        if (asks) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: asks.status, json: asks.body });
        }
        const meme = routeMemes(memes, req.method(), url, body);
        if (meme && 'file' in meme) return serveFile(route, meme.file, meme.type);
        if (meme) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: meme.status, json: meme.body });
        }
        const bell = routeNotify(notify, req.method(), url, body);
        if (bell) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: bell.status, json: bell.body });
        }
        const keys = routeOAuth(oauth, req.method(), url, body);
        if (keys) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: keys.status, json: keys.body });
        }
        const pins = routeVersions(versions, req.method(), url);
        if (pins) return route.fulfill({ status: pins.status, json: pins.body });
        const tasks = routeDev(dev, req.method(), url);
        if (tasks) return route.fulfill({ status: tasks.status, json: tasks.body });
        const care = routeMaintenance(maintenance, req.method(), url, body);
        if (care) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: care.status, json: care.body });
        }
        const stats = routeAnalytics(analytics, req.method(), url, body);
        if (stats) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: stats.status, json: stats.body });
        }
        const read = routeStudio(studio, req.method(), url, body);
        if (read) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: read.status, json: read.body });
        }
        const gate = routeGates(gates, req.method(), url, body);
        if (gate) {
          if (req.method() !== 'GET') await new Promise((r) => setTimeout(r, writeDelay));
          return route.fulfill({ status: gate.status, json: gate.body });
        }
        const mocked = MOCKED.find(([path]) => url.pathname.endsWith(path));
        if (mocked) return route.fulfill({ json: mocked[1] });
        if (url.pathname.includes('/api/')) {
          return route.fulfill({ status: 501, json: { detail: 'нет подставного ответа' } });
        }
        return route.continue();
      });

      await use(blocked);
      expect(blocked, 'запросы в сеть из e2e запрещены').toEqual([]);
    },
    { auto: true },
  ],
  consoleErrors: [
    async ({ page, expectCleanConsole }, use) => {
      const errors: string[] = [];
      page.on('console', (m) => {
        if (m.type() === 'error') errors.push(m.text());
      });
      page.on('pageerror', (e) => errors.push(e.message));
      await use(errors);
      if (expectCleanConsole) expect(errors, 'ошибки в консоли').toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

const ASSETS = new URL('./assets/', import.meta.url);
const files = new Map<MediaFile | MemeFile, Buffer>();

/**
 * Файл-заглушка из tests/e2e/assets — как `FileResponse` фабрики: `Accept-Ranges`, один
 * диапазон — 206 с `Content-Range`, начало за концом — 416 (так браузер перематывает).
 */
async function serveFile(route: Route, name: MediaFile | MemeFile, type: string) {
  let buf = files.get(name);
  if (!buf) files.set(name, (buf = readFileSync(new URL(name, ASSETS))));
  const size = buf.length;
  const head = { 'Content-Type': type, 'Accept-Ranges': 'bytes' };
  const m = /^bytes=(\d*)-(\d*)$/.exec(route.request().headers()['range'] ?? '');
  if (!m || (m[1] === '' && m[2] === ''))
    return route.fulfill({ status: 200, headers: head, body: buf });
  let start = m[1] === '' ? Math.max(0, size - Number(m[2])) : Number(m[1]);
  const end = m[1] === '' || m[2] === '' ? size - 1 : Math.min(Number(m[2]), size - 1);
  if (start >= size)
    return route.fulfill({ status: 416, headers: { 'Content-Range': `bytes */${size}` } });
  start = Math.min(start, end);
  return route.fulfill({
    status: 206,
    headers: { ...head, 'Content-Range': `bytes ${start}-${end}/${size}` },
    body: buf.subarray(start, end + 1),
  });
}

/** Отказ API браузер сам пишет в консоль («status of 422»); других ошибок быть не должно. */
export const onlyHttp = (errors: string[], status: number) =>
  expect(errors.filter((e) => !e.includes(`status of ${status}`))).toEqual([]);

/**
 * Открыть тултип `trigger` (фокусом или наведением) и дождаться в нём `text`.
 * Radix закрывает открытый тултип на любой прокрутке страницы, а `focus()`/`hover()` сами
 * докручивают элемент в вид — под нагрузкой событие прокрутки приходит уже после открытия,
 * и тултип тут же закрывается. Поэтому: сначала докрутить и дать странице встать, потом
 * открывать, а открытие повторять, пока подсказка не появится.
 */
export async function openTip(
  page: Page,
  trigger: Locator,
  text: string | RegExp,
  how: 'focus' | 'hover' = 'focus',
): Promise<Locator> {
  await trigger.scrollIntoViewIfNeeded();
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );
  const tip = page.getByRole('tooltip');
  await expect(async () => {
    if (how === 'hover') {
      await page.mouse.move(0, 0);
      await trigger.hover();
    } else {
      await trigger.blur();
      await trigger.focus();
    }
    await expect(tip).toContainText(text, { timeout: 1500 });
  }).toPass({ timeout: 15_000 });
  return tip;
}

/** Телефон: ничего не вылезает за край (кроме своей прокрутки), страница вбок не едет. */
export async function noSideScroll(page: Page) {
  const wide = await page.evaluate(() => {
    const w = document.documentElement.clientWidth;
    const clipped = (e: Element | null): boolean =>
      !!e && (getComputedStyle(e).overflowX !== 'visible' || clipped(e.parentElement));
    return [...document.querySelectorAll('body *')]
      .filter((e) => e.getBoundingClientRect().right > w + 1 && !clipped(e.parentElement))
      .slice(0, 5)
      .map(
        (e) => `${e.tagName} ${e.getAttribute('data-testid') ?? ''} ${e.textContent?.slice(0, 40)}`,
      );
  });
  expect(wide).toEqual([]);
  const { scroll, client } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(scroll).toBeLessThanOrEqual(client);
}
