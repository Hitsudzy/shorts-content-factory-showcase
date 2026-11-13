// Демо-сервер тренировки (CC-0073): подставной API из `src/mocks/*` прямо в браузере — service
// worker MSW (`public/mockServiceWorker.js`) перехватывает запросы страницы, ответы считает этот
// модуль. Кусок ленивый: грузится только во вкладке в тренировке (`./mode.ts`).
//
// Ни один запрос к `/api/…` отсюда не уходит в сеть: единственный обработчик ловит весь `/api/`,
// и на неизвестное отвечает 501 сам; `onUnhandledRequest` ещё и роняет такой запрос (не
// пропускает). Состояние демо — своё на каждую загрузку вкладки, «Начать заново» — свежее.
import { bypass, delay, http, HttpResponse } from 'msw';
import { setupWorker, type SetupWorker } from 'msw/browser';

import clipUrl from '../../tests/e2e/assets/clip.mp4?url';
import contactSheetUrl from '../../tests/e2e/assets/contact-sheet.jpg?url';
import cutUrl from '../../tests/e2e/assets/cut.png?url';
import frameUrl from '../../tests/e2e/assets/frame.jpg?url';
import meme1Url from '../../tests/e2e/assets/meme-1.jpg?url';
import meme2Url from '../../tests/e2e/assets/meme-2.jpg?url';
import meme3Url from '../../tests/e2e/assets/meme-3.jpg?url';
import meme4Url from '../../tests/e2e/assets/meme-4.jpg?url';
import gifUrl from '../../tests/e2e/assets/meme.gif?url';
import sheetUrl from '../../tests/e2e/assets/sheet.png?url';
import { createAnalyticsBackend, routeAnalytics } from '../mocks/analytics';
import { createBatchesBackend, routeBatches } from '../mocks/batches';
import { createChannelsBackend, routeChannels } from '../mocks/channels';
import { fixtures } from '../mocks/fixtures';
import { createMemesBackend, routeMemes, type MemeFile } from '../mocks/memes';
import { createNotifyBackend, routeNotify } from '../mocks/notify';
import { createMaintenanceBackend, routeMaintenance } from '../mocks/maintenance';
import { createOAuthBackend, routeOAuth } from '../mocks/oauth';
import { createPublishBackend, REEL, routePublish } from '../mocks/publish';
import { createQuestionsBackend, routeQuestions } from '../mocks/questions';
import { createRequestsBackend, routeRequests } from '../mocks/requests';
import { createRightsBackend, routeRights } from '../mocks/rights';
import { createScheduleBackend, routeSchedule } from '../mocks/schedule';
import { createGatesBackend, routeGates } from '../mocks/gates';
import { createStudioBackend, routeStudio } from '../mocks/studio';
import { createVersionsBackend, routeVersions } from '../mocks/versions';
import { createDevBackend, routeDev } from '../mocks/dev';
import { createVideosBackend, routeVideos, type MediaFile } from '../mocks/videos';
import { createChecklist, type WriteEvent } from './checklist';
import { unregisterDemoWorker, type DemoHandle } from './mode';

/** Подставная фабрика тренировки: те же моки, что у тестов, — с состоянием. */
export function createWorld() {
  const publish = createPublishBackend();
  // Загрузку на YouTube в демо пробуют сразу: API-загрузка канала уже включена (на живой
  // фабрике её включают после аудита — это отдельное действие на той же карточке).
  publish.writes.state.switches[REEL] = {
    on: true,
    at: '2026-10-09T10:00:00Z',
    by: 'user',
    note: 'включено для тренировки (из центра)',
    history: [],
  };
  // Упавшие батчи (CC-0089): в тренировке видно, где и почему батч упал и как его продолжить.
  const batches = createBatchesBackend();
  batches.strand();
  const rights = createRightsBackend();
  return {
    channels: createChannelsBackend(),
    schedule: createScheduleBackend(),
    batches,
    videos: createVideosBackend(),
    publish,
    questions: createQuestionsBackend(),
    requests: createRequestsBackend(),
    analytics: createAnalyticsBackend(),
    memes: createMemesBackend(),
    rights,
    notify: createNotifyBackend(),
    oauth: createOAuthBackend(),
    studio: createStudioBackend(),
    gates: createGatesBackend(),
    versions: createVersionsBackend(),
    dev: createDevBackend(),
    maintenance: createMaintenanceBackend(),
  };
}

export type World = ReturnType<typeof createWorld>;

/** Демо-«фабрика» в шапке: видно, что это не живая. */
const VERSION = {
  ...fixtures.version,
  factory: { ...fixtures.version.factory, version: 'демо (тренировка)' },
};

/** Рычаги: что сделать со следующим «да». */
export type Levers = {
  /** Следующее «да» опоздает: все выданные планы устареют («промотать время»). */
  expireNext: boolean;
};

type Snapshot = { world: World; levers: Levers; refuseNext: boolean; generation: number };

let world = createWorld();
let levers: Levers = { expireNext: false };
let generation = 0;
let snapshot: Snapshot = { world, levers, refuseNext: false, generation };
const listeners = new Set<() => void>();
const writeListeners = new Set<(ev: WriteEvent) => void>();

function emit() {
  snapshot = {
    world,
    levers,
    refuseNext: world.publish.writes.state.next === 'refused',
    generation,
  };
  listeners.forEach((l) => l());
}

/** Отметки заданий: учитываются на каждый ответ демо-сервера, даже если панель свёрнута. */
export const checklist = createChecklist();

export const demoStore = {
  get: (): Snapshot => snapshot,
  subscribe(l: () => void) {
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  },
  /** Подписка на ответы демо-сервера на записи (для тостов «задание выполнено»). */
  onWrite(l: (ev: WriteEvent) => void) {
    writeListeners.add(l);
    return () => {
      writeListeners.delete(l);
    };
  },
  /** «Промотать время»: следующее «да» получит «план устарел». */
  expireNext() {
    levers = { ...levers, expireNext: true };
    emit();
  },
  /** Следующее «да» в публикации получит отказ фабрики. */
  refuseNext() {
    world.publish.writes.state.next = 'refused';
    emit();
  },
  /** «Начать заново»: свежая демо-фабрика и пустые отметки. */
  reset() {
    world = createWorld();
    levers = { expireNext: false };
    generation += 1;
    checklist.reset();
    emit();
  },
};

const SAFE = new Set(['GET', 'HEAD']);

/** «да» после плана: туда действует «промотать время». */
const isConfirmPath = (p: string) =>
  !p.endsWith('/plan') &&
  (/\/api\/publish\/[^/]+\/./.test(p) ||
    /\/api\/batches\/(launch|[^/]+\/[^/]+\/(stop|resume))$/.test(p) ||
    /\/api\/memes\/[^/]+\/(apply|cutout|trim|add-image|add-gif|sheet|embed)$/.test(p) ||
    /\/api\/analytics\/[^/]+\/studio\/record$/.test(p) ||
    /\/api\/studio\/read$/.test(p) ||
    /\/api\/notify\/reminders$/.test(p) ||
    /\/api\/oauth\/api-data\/purge$/.test(p) ||
    /\/api\/maintenance\/(journals|pool\/release|archive)$/.test(p));

const MEDIA: Record<MediaFile | MemeFile, string> = {
  'clip.mp4': clipUrl,
  'frame.jpg': frameUrl,
  'sheet.png': sheetUrl,
  'meme-1.jpg': meme1Url,
  'meme-2.jpg': meme2Url,
  'meme-3.jpg': meme3Url,
  'meme-4.jpg': meme4Url,
  'meme.gif': gifUrl,
  'cut.png': cutUrl,
  'contact-sheet.jpg': contactSheetUrl,
};
const media = new Map<MediaFile | MemeFile, Promise<ArrayBuffer>>();

/** Учебный файл (ролик, кадр): статикой с того же сервера, мимо демо-сервера. */
function mediaBytes(name: MediaFile | MemeFile): Promise<ArrayBuffer> {
  let p = media.get(name);
  if (!p) {
    const url = new URL(MEDIA[name], window.location.href).toString();
    p = fetch(bypass(url)).then((r) => r.arrayBuffer());
    p.catch(() => media.delete(name));
    media.set(name, p);
  }
  return p;
}

/** Как `FileResponse` фабрики: `Accept-Ranges`, один диапазон — 206, за концом — 416. */
async function serveMedia(name: MediaFile | MemeFile, type: string, range: string | null) {
  const buf = await mediaBytes(name);
  const size = buf.byteLength;
  const head = { 'Content-Type': type, 'Accept-Ranges': 'bytes' };
  const m = /^bytes=(\d*)-(\d*)$/.exec(range ?? '');
  if (!m || (m[1] === '' && m[2] === '')) return new HttpResponse(buf, { headers: head });
  let start = m[1] === '' ? Math.max(0, size - Number(m[2])) : Number(m[1]);
  const end = m[1] === '' || m[2] === '' ? size - 1 : Math.min(Number(m[2]), size - 1);
  if (start >= size)
    return new HttpResponse(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } });
  start = Math.min(start, end);
  return new HttpResponse(buf.slice(start, end + 1), {
    status: 206,
    headers: { ...head, 'Content-Range': `bytes ${start}-${end}/${size}` },
  });
}

type Reply = { status: number; body: unknown };

/** Ответ подставной фабрики — в том же порядке, что у e2e (`tests/e2e/fixtures.ts`). */
function route(
  w: World,
  method: string,
  url: URL,
  body: unknown,
  range: string | null,
): Reply | { file: MediaFile | MemeFile; type: string } | null {
  const law = routeRights(w.rights, method, url, body);
  if (law) return law;
  const ch = routeChannels(w.channels, method, url, body);
  if (ch) return ch;
  const sch = routeSchedule(w.schedule, method, url, body);
  if (sch) return sch;
  const film = routeVideos(w.videos, method, url, { range }, body);
  if (film && 'file' in film) return { file: film.file, type: film.type };
  if (film) return film;
  const going = routeBatches(w.batches, method, url, body);
  if (going) return going;
  const pub = routePublish(w.publish, method, url, body);
  if (pub) return pub;
  const asked = routeQuestions(w.questions, method, url, body);
  if (asked) return asked;
  const asks = routeRequests(w.requests, method, url, body);
  if (asks) return asks;
  const stats = routeAnalytics(w.analytics, method, url, body);
  if (stats) return stats;
  const bell = routeNotify(w.notify, method, url, body);
  if (bell) return bell;
  const keys = routeOAuth(w.oauth, method, url, body);
  if (keys) return keys;
  const pins = routeVersions(w.versions, method, url);
  if (pins) return pins;
  const tasks = routeDev(w.dev, method, url);
  if (tasks) return tasks;
  const care = routeMaintenance(w.maintenance, method, url, body);
  if (care) return care;
  const read = routeStudio(w.studio, method, url, body);
  if (read) return read;
  const gate = routeGates(w.gates, method, url, body);
  if (gate) return gate;
  const meme = routeMemes(w.memes, method, url, body);
  if (meme && 'file' in meme) return { file: meme.file, type: meme.type };
  if (meme) return meme;
  if (method === 'GET' && url.pathname.endsWith('/api/health'))
    return { status: 200, body: fixtures.health };
  if (method === 'GET' && url.pathname.endsWith('/api/version'))
    return { status: 200, body: VERSION };
  if (method === 'GET' && url.pathname.endsWith('/api/session'))
    return { status: 200, body: fixtures.session };
  return null;
}

const codeOf = (body: unknown): string | null => {
  const c = (body as { code?: unknown } | null)?.code;
  return typeof c === 'string' ? c : null;
};

/** Единственный обработчик: весь `/api/` этого сайта отвечает демо-фабрика. */
export const demoHandler = http.all(/\/api(\/|$)/, async ({ request }) => {
  const url = new URL(request.url);
  const method = request.method;
  const body: unknown = SAFE.has(method) ? null : await request.json().catch(() => null);
  const path = url.pathname;
  // Взведённый отказ: «да», что опоздало, его не тратит — он ждёт следующего «да».
  const refusal = world.publish.writes.state.next;
  if (!SAFE.has(method)) {
    // Запись — с паузой, как у фабрики: виден ход «Записываю…».
    await delay(250);
    if (levers.expireNext && isConfirmPath(path)) {
      world.publish.writes.expireTokens();
      world.batches.actions.expireTokens();
      world.memes.expireTokens();
      world.analytics.entry.expireTokens();
      world.notify.expireTokens();
      world.oauth.expireTokens();
      world.rights.lists.expireTokens();
      world.studio.expireTokens();
      world.maintenance.expireTokens();
      levers = { ...levers, expireNext: false };
    }
  }
  const reply = route(world, method, url, body, request.headers.get('range'));
  if (reply && 'file' in reply)
    return serveMedia(reply.file, reply.type, request.headers.get('range'));
  const out: Reply = reply ?? {
    status: 501,
    body: { detail: 'В тренировке у демо-фабрики нет такого ответа.' },
  };
  if (refusal && codeOf(out.body) === 'confirm_expired') world.publish.writes.state.next = refusal;
  if (!SAFE.has(method)) {
    const ev: WriteEvent = { method, path, status: out.status, code: codeOf(out.body) };
    checklist.record(ev);
    writeListeners.forEach((l) => l(ev));
    emit();
  }
  return HttpResponse.json(out.body as object, { status: out.status });
});

/** Дождаться, пока страницу возьмёт под себя service worker демо-сервера. */
async function waitForControl(timeoutMs: number): Promise<boolean> {
  const sw = navigator.serviceWorker;
  const ours = () => !!sw.controller?.scriptURL.endsWith('/mockServiceWorker.js');
  if (ours()) return true;
  await new Promise<void>((resolve) => {
    const done = () => {
      clearTimeout(timer);
      sw.removeEventListener('controllerchange', done);
      resolve();
    };
    const timer = setTimeout(done, timeoutMs);
    sw.addEventListener('controllerchange', done);
  });
  return ours();
}

let running: SetupWorker | null = null;

/** Поднять демо-сервер; бросает, если страницу он под себя не взял. */
export async function startDemo(): Promise<DemoHandle> {
  if (typeof navigator === 'undefined' || !navigator.serviceWorker)
    throw new Error('этот браузер не умеет service worker — тренировка недоступна');
  const base = import.meta.env.BASE_URL;
  const worker = setupWorker(demoHandler);
  await worker.start({
    serviceWorker: { url: `${base}mockServiceWorker.js`, options: { scope: base } },
    quiet: true,
    // Запрос к API мимо обработчика — ошибка, не пропуск в сеть. Статика сайта — как есть.
    onUnhandledRequest(request, print) {
      if (/\/api(\/|$)/.test(new URL(request.url).pathname)) print.error();
    },
  });
  if (!(await waitForControl(5000))) {
    worker.stop();
    throw new Error('демо-сервер не взял страницу под себя');
  }
  running = worker;
  return {
    stop: async () => {
      running?.stop();
      running = null;
      await unregisterDemoWorker();
    },
  };
}
