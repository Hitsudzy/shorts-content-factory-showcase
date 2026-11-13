// Токены, OAuth и данные API (CC-0028 фабрики, договор 0.28.0; экран — CC-0029). Только чтения и
// одна запись. Чтения: состояние токена (`GET /api/oauth/token` — `publisher_auth.py status` и
// файл состояния рядом с токеном; **значения токена в ответе нет никогда**), данные API, которые
// хранит фабрика (`GET /api/oauth/api-data` — строка `api_data.py status`, отметка отзыва, `held` —
// что удалила бы `purge --all`, `due` — что удалил бы авто-прогон сейчас), и сухой прогон отзыва
// (`GET /api/oauth/revoke` — `api_data.py revoke` без `--yes`; `confirm_available` — отзывает ли
// фабрика из центра). Записи (экраны отзыва и «по сроку» — CC-0087): отозвать доступ —
// `…/revoke/plan` (сухой прогон данными, токен) и `…/revoke {confirm}` (структурный итог: ответ
// Google, удалён ли файл токена, строка журнала удалений; Google не ответил — `ok: false`, ничего не
// изменилось); удалить по сроку — `…/api-data/auto/plan` (что подлежит авто-удалению сейчас) и
// `…/api-data/auto {confirm}`. И удалить данные API по просьбе
// владельца, в два вызова, как записи публикации: `…/purge/plan {scope, channels}` ничего не
// удаляет и показывает, что удалится, с токеном на `expires_in_s` (нечего удалять — `ok: false`,
// токена нет); `…/purge {confirm}` удаляет (`apply(by=user, via=center)`), токен YouTube остаётся.
// Отказы — `OAuthProblem {message, code, details}` (разбирает `takeBatch`), словами —
// `oauthProblemText`. Переключатель загрузки по API — на экране «Публикация» (CC-0066).
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { BatchError, takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { writeProblemText } from './publishWrites';

export type OAuthToken = Schemas['OAuthToken'];
export type OAuthScopes = Schemas['OAuthScopes'];
export type OAuthState = Schemas['OAuthState'];
export type ApiDataState = Schemas['ApiDataState'];
export type ApiDataPlan = Schemas['ApiDataPlan'];
export type ApiDataRow = Schemas['ApiDataRow'];
export type ApiDataRevocation = Schemas['ApiDataRevocation'];
export type OAuthRevokePreview = Schemas['OAuthRevokePreview'];
export type ApiDataPurgeIn = Schemas['ApiDataPurgeIn'];
export type ApiDataPurgePlan = Schemas['ApiDataPurgePlan'];
export type ApiDataPurgeResult = Schemas['ApiDataPurgeResult'];
export type OAuthProblem = Schemas['OAuthProblem'];
export type OAuthRevokePlan = Schemas['OAuthRevokePlan'];
export type OAuthRevokeResult = Schemas['OAuthRevokeResult'];
export type OAuthRevokeOutcome = Schemas['OAuthRevokeOutcome'];
export type ApiDataAutoPlan = Schemas['ApiDataAutoPlan'];
export type ApiDataAutoResult = Schemas['ApiDataAutoResult'];
export type TokenKind = OAuthToken['kind'];

/** Код отказа API токенов, если ошибка — его отказ (`OAuthProblem`). */
export function oauthCode(e: unknown): OAuthProblem['code'] | null {
  return e instanceof BatchError
    ? ((e.problem?.code as OAuthProblem['code'] | undefined) ?? null)
    : null;
}

export async function getToken(signal?: AbortSignal): Promise<OAuthToken> {
  return takeBatch(await api.GET('/api/oauth/token', { signal }));
}

export async function getApiData(signal?: AbortSignal): Promise<ApiDataState> {
  return takeBatch(await api.GET('/api/oauth/api-data', { signal }));
}

export async function getRevoke(signal?: AbortSignal): Promise<OAuthRevokePreview> {
  return takeBatch(await api.GET('/api/oauth/revoke', { signal }));
}

const call = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

export const planPurge = (body: ApiDataPurgeIn) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/oauth/api-data/purge/plan', { body, signal })),
  );

export const purgeApiData = (confirm: string) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/oauth/api-data/purge', { body: { confirm }, signal })),
  );

export const planRevoke = () =>
  call(async (signal) => takeBatch(await api.POST('/api/oauth/revoke/plan', { signal })));

export const revokeAccess = (confirm: string) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/oauth/revoke', { body: { confirm }, signal })),
  );

export const planAuto = () =>
  call(async (signal) => takeBatch(await api.POST('/api/oauth/api-data/auto/plan', { signal })));

export const runAuto = (confirm: string) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/oauth/api-data/auto', { body: { confirm }, signal })),
  );

export const oauthKeys = {
  all: ['api', 'oauth'] as const,
  token: ['api', 'oauth', 'token'] as const,
  apiData: ['api', 'oauth', 'api-data'] as const,
  revoke: ['api', 'oauth', 'revoke'] as const,
};

/** Отказ 4xx (вид неизвестен) повтором не лечится; сеть и 5xx — до трёх раз. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Срок токена идёт по часам: перечитываем раз в минуту и при возврате на вкладку. */
const minute = { refetchInterval: 60_000, refetchIntervalInBackground: false, retry } as const;

export function useToken() {
  return useQuery({
    queryKey: oauthKeys.token,
    queryFn: ({ signal }) => getToken(signal),
    ...minute,
  });
}

export function useApiData() {
  return useQuery({
    queryKey: oauthKeys.apiData,
    queryFn: ({ signal }) => getApiData(signal),
    ...minute,
  });
}

/** Сухой прогон отзыва: без опроса — меняется, только когда меняются данные API или токен. */
export function useRevoke() {
  return useQuery({
    queryKey: oauthKeys.revoke,
    queryFn: ({ signal }) => getRevoke(signal),
    staleTime: 60_000,
    retry,
  });
}

/** После удаления (и отказа «да») перечитать всё про токен и данные API. */
export function useAfterPurge() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: oauthKeys.all });
}

// ---------------------------------------------------------------- слова
const OAUTH_PROBLEM_TEXT: Record<string, string> = {
  config_broken: 'Настройки публикатора не читаются — состояние токена не узнать',
  unknown_channel: 'Такого канала нет',
  no_channels: 'Выберите каналы, данные API которых удалить',
  refused: 'Удалять уже нечего — данные API этих каналов кто-то удалил',
  check_changed: 'Данные API изменились с момента плана — посмотрите план заново',
  busy: 'Идёт другая запись публикации — подождите и нажмите ещё раз',
  factory_broken:
    'Фабрика ответила ошибкой — посмотрите состояние данных API, прежде чем повторять',
};

export const oauthProblemText = (code: string | null | undefined): string =>
  (code && OAUTH_PROBLEM_TEXT[code]) || writeProblemText(code);

// ---------------------------------------------------------------- данные API по каналам
/** Что из плана удаления относится к одному каналу. */
export type ChannelShare = {
  /** id канала; `null` — общее, не привязанное к каналу. */
  channel: string | null;
  files: string[];
  dirs: string[];
  rows: ApiDataRow[];
  texts: ApiDataPlan['texts'];
};

const ANALYTICS = /^analytics\/([^/]+)\//;

/**
 * План удаления по каналам: файлы и папки метрик — по пути `analytics/<канал>/…`, строки журнала —
 * по своему каналу, упоминания id в текстах — по строке журнала с тем же id (не нашлась — общее).
 * Каналы — в порядке `plan.channels`, общее — последним.
 */
export function byChannel(plan: ApiDataPlan): ChannelShare[] {
  const out = new Map<string | null, ChannelShare>();
  const of = (ch: string | null) => {
    let s = out.get(ch);
    if (!s) {
      s = { channel: ch, files: [], dirs: [], rows: [], texts: [] };
      out.set(ch, s);
    }
    return s;
  };
  for (const ch of plan.channels) of(ch);
  for (const f of plan.files) of(ANALYTICS.exec(f)?.[1] ?? null).files.push(f);
  for (const d of plan.dirs) of(ANALYTICS.exec(`${d}/`)?.[1] ?? null).dirs.push(d);
  for (const r of plan.rows) of(r.channel ?? null).rows.push(r);
  const idChannel = new Map(plan.rows.map((r) => [r.video_id, r.channel ?? null] as const));
  for (const t of plan.texts) of(idChannel.get(t.video_id) ?? null).texts.push(t);
  const shares = [...out.values()].filter(
    (s) => s.files.length || s.dirs.length || s.rows.length || s.texts.length,
  );
  return [...shares.filter((s) => s.channel !== null), ...shares.filter((s) => s.channel === null)];
}

/** Сколько всего удалится (как «N item(s)» у фабрики). */
export const planSize = (p: ApiDataPlan) =>
  p.files.length + p.dirs.length + p.rows.length + p.texts.length;
