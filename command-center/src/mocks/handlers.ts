import { http, HttpResponse } from 'msw';

import type { paths } from '@/api/schema.gen';

import { createAuthBackend, guardAuth, routeAuth, type AuthBackend } from './auth';
import { createAnalyticsBackend, routeAnalytics, type AnalyticsBackend } from './analytics';
import { createBatchesBackend, routeBatches, type BatchesBackend } from './batches';
import { createDevBackend, routeDev, type DevBackend } from './dev';
import { createChannelsBackend, isListed, routeChannels, type ChannelsBackend } from './channels';
import { fixtures } from './fixtures';
import { createMaintenanceBackend, routeMaintenance, type MaintenanceBackend } from './maintenance';
import { createMemesBackend, routeMemes, type MemesBackend } from './memes';
import { createNotifyBackend, routeNotify, type NotifyBackend } from './notify';
import { createOAuthBackend, routeOAuth, type OAuthBackend } from './oauth';
import { createPublishBackend, routePublish, type PublishBackend } from './publish';
import { createQuestionsBackend, routeQuestions, type QuestionsBackend } from './questions';
import { createRequestsBackend, routeRequests, type RequestsBackend } from './requests';
import { createRightsBackend, routeRights, type RightsBackend } from './rights';
import { createScheduleBackend, routeSchedule, type ScheduleBackend } from './schedule';
import { createGatesBackend, routeGates, type GatesBackend } from './gates';
import { createStudioBackend, routeStudio, type StudioBackend } from './studio';
import { createVersionsBackend, routeVersions, type VersionsBackend } from './versions';
import { createVideosBackend, routeVideos, type VideosBackend } from './videos';

// Подставной API для тестов. Любой запрос, которого здесь нет, роняет тест
// (onUnhandledRequest: 'error' в src/test/setup.ts) — тесты никогда не ходят в сеть.

/** Пути контракта, у которых есть GET. */
export type GetPath = {
  [P in keyof paths]: paths[P] extends { get: { responses: object } } ? P : never;
}[keyof paths];

type GetResponses<P extends GetPath> = paths[P]['get']['responses'];

/** Тело JSON-ответа `GET path` со статусом `S` — ровно как в контракте. */
export type GetBody<
  P extends GetPath,
  S extends keyof GetResponses<P>,
> = GetResponses<P>[S] extends { content: { 'application/json': infer T } } ? T : never;

/**
 * Хендлер MSW для `GET path`, тело которого проверяется типами контракта: лишнее,
 * недостающее или не того типа поле — ошибка `tsc`, а не тихо зелёный тест.
 */
export function mockGet<P extends GetPath, S extends keyof GetResponses<P> & number = 200>(
  path: P,
  body: GetBody<P, S>,
  status?: S,
) {
  return http.get(`*${path}`, () => HttpResponse.json(body as object, { status: status ?? 200 }));
}

/** Подставная фабрика каналов текущего теста; `resetChannels()` — свежая (src/test/setup.ts). */
export let channels: ChannelsBackend = createChannelsBackend();
export function resetChannels(): void {
  channels = createChannelsBackend();
}

/** Подставное расписание батчей текущего теста; `resetSchedule()` — свежее (src/test/setup.ts). */
export let schedule: ScheduleBackend = createScheduleBackend();
export function resetSchedule(): void {
  schedule = createScheduleBackend();
}

/** Подставные батчи текущего теста; `resetBatches()` — свежие (src/test/setup.ts). */
export let batches: BatchesBackend = createBatchesBackend();
export function resetBatches(): void {
  batches = createBatchesBackend();
}

/** Подставные ролики текущего теста; `resetVideos()` — свежие (src/test/setup.ts). */
export let videos: VideosBackend = createVideosBackend();
export function resetVideos(): void {
  videos = createVideosBackend();
}

/** Подставная публикация текущего теста; `resetPublish()` — свежая (src/test/setup.ts). */
export let publish: PublishBackend = withChannels(createPublishBackend());
export function resetPublish(): void {
  publish = withChannels(createPublishBackend());
}
/** Канал из подставного списка каналов (и только что созданный) — с пустой очередью (CC-0138). */
function withChannels(p: PublishBackend): PublishBackend {
  p.state.elsewhere = (c) => isListed(channels, c);
  return p;
}

/** Подставной журнал вопросов текущего теста; `resetQuestions()` — свежий (src/test/setup.ts). */
export let questions: QuestionsBackend = createQuestionsBackend();
export function resetQuestions(): void {
  questions = createQuestionsBackend();
}

/** Подставная очередь просьб текущего теста; `resetRequests()` — свежая (src/test/setup.ts). */
export let requests: RequestsBackend = createRequestsBackend();
export function resetRequests(): void {
  requests = createRequestsBackend();
}

/** Подставная статистика текущего теста; `resetAnalytics()` — свежая (src/test/setup.ts). */
export let analytics: AnalyticsBackend = createAnalyticsBackend();
export function resetAnalytics(): void {
  analytics = createAnalyticsBackend();
}

/** Подставной стол мемов текущего теста; `resetMemes()` — свежий (src/test/setup.ts). */
export let memes: MemesBackend = createMemesBackend();
export function resetMemes(): void {
  memes = createMemesBackend();
}

/** Подставные списки каналов (правообладатели, происхождение футажа) текущего теста; `resetRights()` — свежие (src/test/setup.ts). */
export let rights: RightsBackend = createRightsBackend();
export function resetRights(): void {
  rights = createRightsBackend();
}

/** Подставные уведомления и напоминания текущего теста; `resetNotify()` — свежие (src/test/setup.ts). */
export let notify: NotifyBackend = createNotifyBackend();
export function resetNotify(): void {
  notify = createNotifyBackend();
}

/** Подставное чтение Studio текущего теста; `resetStudio()` — свежее (src/test/setup.ts). */
export let studio: StudioBackend = createStudioBackend();
export function resetStudio(): void {
  studio = createStudioBackend();
}

/** Подставная цена воротец текущего теста; `resetGates()` — свежая (src/test/setup.ts). */
export let gates: GatesBackend = createGatesBackend();
export function resetGates(): void {
  gates = createGatesBackend();
}

const gatesHandler = http.all('*/api/gate-prices*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeGates(gates, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const studioHandler = http.all('*/api/studio/*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeStudio(studio, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const notifyHandler = http.all('*/api/notify/*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeNotify(notify, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

/** Подставные версии и агенты текущего теста; `resetVersions()` — свежие (src/test/setup.ts). */
export let versions: VersionsBackend = createVersionsBackend();
export function resetVersions(): void {
  versions = createVersionsBackend();
}

const versionsHandler = http.get('*/api/versions', ({ request }) => {
  const reply = routeVersions(versions, request.method, new URL(request.url));
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

/** Подставная «Разработка» текущего теста; `resetDev()` — свежая (src/test/setup.ts). */
export let dev: DevBackend = createDevBackend();
export function resetDev(): void {
  dev = createDevBackend();
}

const devHandler = http.get('*/api/dev/*', ({ request }) => {
  const reply = routeDev(dev, request.method, new URL(request.url));
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

/** Подставное обслуживание текущего теста; `resetMaintenance()` — свежее (src/test/setup.ts). */
export let maintenance: MaintenanceBackend = createMaintenanceBackend();
export function resetMaintenance(): void {
  maintenance = createMaintenanceBackend();
}

const maintenanceHandler = http.all('*/api/maintenance*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeMaintenance(maintenance, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

/** Подставные токен и данные API текущего теста; `resetOAuth()` — свежие (src/test/setup.ts). */
export let oauth: OAuthBackend = createOAuthBackend();
export function resetOAuth(): void {
  oauth = createOAuthBackend();
}

const oauthHandler = http.all('*/api/oauth/*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeOAuth(oauth, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

// Списки канала: чтения `/api/channels/{channel}/(rights-holders|footage-origin)` — раньше каналов.
const rightsHandler = http.all(
  /\/api\/channels\/[^/]+\/(rights-holders|footage-origin)(\/plan)?$/,
  async ({ request }) => {
    const body: unknown = ['GET', 'HEAD'].includes(request.method)
      ? null
      : await request.json().catch(() => null);
    const reply = routeRights(rights, request.method, new URL(request.url), body);
    if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
    return HttpResponse.json(reply.body as object, { status: reply.status });
  },
);

const memesHandler = http.all('*/api/memes*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeMemes(memes, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  // jsdom картинки не грузит: вместо файла-заглушки — пустое тело нужного типа.
  if ('file' in reply)
    return new HttpResponse(new ArrayBuffer(0), { headers: { 'Content-Type': reply.type } });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const analyticsHandler = http.all('*/api/analytics*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeAnalytics(analytics, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const requestsHandler = http.all('*/api/requests*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeRequests(requests, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const questionsHandler = http.all('*/api/questions*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeQuestions(questions, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const publishHandler = http.all('*/api/publish*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routePublish(publish, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const batchesHandler = http.all('*/api/batches*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const film = routeVideos(
    videos,
    request.method,
    new URL(request.url),
    { range: request.headers.get('range') },
    body,
  );
  // jsdom видео не играет: вместо файла-заглушки — пустое тело нужного типа.
  if (film && 'file' in film)
    return new HttpResponse(new ArrayBuffer(0), { headers: { 'Content-Type': film.type } });
  if (film) return HttpResponse.json(film.body as object, { status: film.status });
  const reply = routeBatches(batches, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const scheduleHandler = http.all('*/api/schedule*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeSchedule(schedule, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

const channelsHandler = http.all('*/api/channels*', async ({ request }) => {
  const url = new URL(request.url);
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeChannels(channels, request.method, url, body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  return HttpResponse.json(reply.body as object, { status: reply.status });
});

/** Подставной вход текущего теста (CC-0037): по умолчанию Mac; `resetAuthMock()` — свежий. */
export let auth: AuthBackend = createAuthBackend();
export function resetAuthMock(): void {
  auth = createAuthBackend();
}

// Охрана входа — первой: без входа из сети любой путь API — 401 `auth_required`; иначе
// хендлер ничего не возвращает, и запрос идёт к своему хендлеру дальше по списку.
const authGuardHandler = http.all('*/api/*', ({ request }) => {
  const refused = guardAuth(auth, new URL(request.url));
  if (refused) return HttpResponse.json(refused.body as object, { status: refused.status });
  return undefined;
});

const authHandler = http.all('*/api/auth/*', async ({ request }) => {
  const body: unknown = ['GET', 'HEAD'].includes(request.method)
    ? null
    : await request.json().catch(() => null);
  const reply = routeAuth(auth, request.method, new URL(request.url), body);
  if (!reply) return HttpResponse.json({ detail: 'нет подставного ответа' }, { status: 501 });
  const headers = 'headers' in reply ? reply.headers : undefined;
  return HttpResponse.json(reply.body as object, { status: reply.status, headers });
});

export const handlers = [
  authGuardHandler,
  authHandler,
  mockGet('/api/health', fixtures.health),
  mockGet('/api/version', fixtures.version),
  mockGet('/api/session', fixtures.session),
  rightsHandler,
  channelsHandler,
  scheduleHandler,
  batchesHandler,
  publishHandler,
  questionsHandler,
  requestsHandler,
  analyticsHandler,
  memesHandler,
  notifyHandler,
  oauthHandler,
  versionsHandler,
  devHandler,
  maintenanceHandler,
  studioHandler,
  gatesHandler,
];
