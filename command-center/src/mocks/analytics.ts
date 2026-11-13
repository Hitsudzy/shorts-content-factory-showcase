// Подставная статистика (CC-0020 фабрики, договор 0.23.0) — только чтение: каналы со сбором,
// окно «первые N дней» по роликам, дневные строки ролика, сводка аналитика (посчитанная и
// сохранённые), «нужный футаж» (с упакованными — по `packed=true`) и чтение Studio. Общий для
// Vitest (MSW, src/mocks/handlers.ts), Playwright (tests/e2e/fixtures.ts) и тренировки
// (src/training/demo.ts). Данные — ./analyticsData. Состояние — поля бэкенда: тест может сломать
// хранилище (`broken`), убрать сбор или сводки перед открытием. Единственная запись — ввод
// прочитанного в Studio (CC-0074 фабрики, `…/studio/record[/plan]`, ./analyticsStudio): она
// меняет то, что потом читают GET (`…/studio`, метрики, график ролика); прочие не-GET — `null`.
// Импорты — относительные.
import type { components } from '../api/schema.gen';
import { diversityReply, type DiversityLog } from './diversity';
import {
  ANALYTICS_CHANNELS,
  buildSummary,
  dailyRows,
  END_DAY,
  FOOTAGE_ROWS,
  LAST_RUN,
  LAST_VISIT,
  PACKED_ROW,
  REEL_VIDEOS,
  STUDIO_SETTINGS,
  STUDIO_URL,
  studioRow,
  TECH_VIDEOS,
  windowRow,
  type MockVideo,
} from './analyticsData';
import { createStudioEntry } from './analyticsStudio';
import { REEL, SCIENCE, TECH } from './publish';

type S = components['schemas'];
type Code = S['AnalyticsProblem']['code'];

/**
 * Причины нехватки футажа словами фабрики (`reasons_ru` ответа, CC-0113): `funnel.reason_ru`,
 * иначе `footage_wanted.REASONS`. `event_footage_short` без строки — центр покажет сам код.
 */
const FOOTAGE_REASONS_RU: Record<string, string | null> = {
  anchor_no_picture: 'монтажу не хватило кадра для главного героя',
  anchor_short: 'кадров главного героя хватило не на весь блок',
  frame_contradicts: 'в кадре не то, что называет диктор',
  frame_foreign: 'блок закрыт чужим кадром',
  visual_claim_uncovered: 'сценарий показывает то, чего нет в пуле',
  pool_too_thin: 'пул тоньше сценария',
  no_second_source: 'всё из одного источника',
  event_footage_short: null,
  no_source: 'для темы не нашлось футажа',
  rights_exclusion: 'источники темы не взяты по правам: лицензия, которую канал не принимает',
};

export type AnalyticsReply<T> =
  | { status: 200; body: T }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: string; details: string[] } };

const problem = (
  status: 404 | 409 | 422,
  code: Code,
  message: string,
  details: string[] = [],
): AnalyticsReply<never> => ({ status, body: { message, code, details } });

const ok = <T>(body: T): AnalyticsReply<T> => ({ status: 200, body });

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

const copy = (list: MockVideo[]) =>
  list.map((v) => ({ ...v, studio: v.studio ? { ...v.studio } : null }));

export function createAnalyticsBackend() {
  const state = {
    channels: [...ANALYTICS_CHANNELS] as string[],
    videos: { [REEL]: copy(REEL_VIDEOS), [TECH]: copy(TECH_VIDEOS), [SCIENCE]: [] } as Record<
      string,
      MockVideo[]
    >,
    lastRun: { ...LAST_RUN },
    /** Собирает ли фабрика окно «первые 7 дней» для канала. */
    collected: { [REEL]: true, [TECH]: false, [SCIENCE]: true } as Record<string, boolean>,
    summaryDays: {
      [REEL]: ['2026-10-09', '2026-10-08', '2026-10-07'],
      [TECH]: ['2026-10-09'],
      [SCIENCE]: [],
    } as Record<string, string[]>,
    /** Канал, у которого хранилище статистики не читается (409 `store_unreadable`). */
    broken: null as string | null,
    /** Чтение Studio настроено (`analyst.studio_read`); у Tech — нет. */
    studioSettings: { [REEL]: true, [TECH]: false, [SCIENCE]: true } as Record<string, boolean>,
    noPipeline: {
      [SCIENCE]:
        'example-science: конвейера нет (status: no_pipeline) - канал оформлен, ролики не делаются',
    } as Record<string, string>,
    /** Каждый GET: путь с запросом — тесты проверяют, что `packed=true` ушёл только по кнопке. */
    calls: [] as string[],
    /** Последнее посещение Studio (`studio_visits.jsonl`). */
    visits: { [REEL]: LAST_VISIT } as Record<string, Record<string, unknown>>,
    /** Studio прочитали из центра: страховка закрыта («рано»). */
    fresh: {} as Record<string, boolean>,
    /** Чтения Studio, внесённые из центра: канал → ролик → строка `studio.jsonl`. */
    reads: {} as Record<string, Record<string, S['StudioReadRow']>>,
    /** Журнал приёмки для разнообразия ленты (CC-0115): `broken` — `log_error`. */
    diversityLog: 'ok' as DiversityLog,
  };

  const known = (c: string) => state.channels.includes(c);
  const unknown = (c: string) =>
    problem(404, 'unknown_channel', `Канала ${c} нет в журнале загрузок.`, [
      `summary.channels_of: ${state.channels.join(', ')}`,
    ]);
  const broken = (c: string) =>
    problem(409, 'store_unreadable', 'Хранилище статистики канала не читается.', [
      `analytics/${c}/daily.jsonl line 12: Expecting ',' delimiter`,
    ]);
  const guard = (c: string) => (!known(c) ? unknown(c) : state.broken === c ? broken(c) : null);
  const vids = (c: string) => state.videos[c] ?? [];
  /** Последнее чтение Studio ролика: внесённое из центра или из данных. */
  const readOf = (c: string, v: MockVideo) => state.reads[c]?.[v.video_id] ?? studioRow(c, v);
  const entryOf = (c: string, v: MockVideo) => `${c}/${v.batch}/${v.slug}`;

  const entry = createStudioEntry({
    channels: () => state.channels,
    journal: (c) =>
      Object.fromEntries(
        vids(c)
          .filter((v) => v.published <= END_DAY)
          .map((v) => [v.video_id, entryOf(c, v)]),
      ),
    latest: (c, id) => {
      const v = vids(c).find((x) => x.video_id === id);
      return v ? readOf(c, v) : (state.reads[c]?.[id] ?? null);
    },
    store: (c, row) => {
      (state.reads[c] ??= {})[row.video_id] = row;
      const v = vids(c).find((x) => x.video_id === row.video_id);
      if (v)
        v.studio = {
          viewed: (row.viewed_pct as number | null) ?? null,
          swiped: (row.swiped_pct as number | null) ?? null,
          read_at: row.read_at,
          ...(row.note ? { note: row.note } : {}),
        };
    },
    visit: (c, line) => {
      state.visits[c] = line;
      state.fresh[c] = true;
    },
    lastVisitAt: (c) => (state.visits[c]?.read_at as string | undefined) ?? null,
  });

  return {
    state,
    entry,
    diversity(c: string | null, last: number): AnalyticsReply<S['FeedDiversity']> {
      if (c && !known(c)) return unknown(c);
      return { status: 200, body: diversityReply(c, last, state.diversityLog) };
    },

    overview(): AnalyticsReply<S['AnalyticsOverview']> {
      return ok({
        channels: state.channels.map((c) => ({
          channel: c,
          last_run: state.lastRun[c] ?? null,
          summary_days: state.summaryDays[c] ?? [],
        })),
        window_days: [7],
      });
    },
    metrics(c: string, firstDays: number): AnalyticsReply<S['ChannelMetrics']> {
      const bad = guard(c);
      if (bad) return bad;
      const collected = firstDays === 7 && !!state.collected[c];
      return ok({
        channel: c,
        first_days: firstDays,
        collected,
        window_days: [7],
        last_run: state.lastRun[c] ?? null,
        videos: vids(c).map((v) => {
          const daily = dailyRows(c, v);
          return {
            video_id: v.video_id,
            window: collected ? windowRow(c, v) : null,
            daily_rows: daily.length,
            last_daily: daily.at(-1) ?? null,
            studio: readOf(c, v),
          };
        }),
      });
    },
    video(c: string, id: string): AnalyticsReply<S['VideoSeries']> {
      const bad = guard(c);
      if (bad) return bad;
      const v = vids(c).find((x) => x.video_id === id);
      if (!v)
        return problem(404, 'unknown_video', `Ролика ${id} нет в статистике канала ${c}.`, [
          `analytics/${c}/daily.jsonl, windows.jsonl: no rows for ${id}`,
        ]);
      const w = state.collected[c] ? windowRow(c, v) : null;
      const s = readOf(c, v);
      return ok({
        channel: c,
        video_id: id,
        daily: dailyRows(c, v),
        windows: w ? [w] : [],
        studio: s ? [s] : [],
      });
    },
    summary(c: string, day: string | null, firstDays: number): AnalyticsReply<S['AnalystSummary']> {
      const bad = guard(c);
      if (bad) return bad;
      const d = day ?? END_DAY;
      if (!DAY_RE.test(d))
        return problem(422, 'bad_day', `День ${d} не похож на дату ГГГГ-ММ-ДД.`, [`day=${d}`]);
      return ok({
        ...buildSummary(
          c,
          vids(c),
          d,
          firstDays === 7 && !!state.collected[c],
          state.summaryDays[c] ?? [],
        ),
        first_days: firstDays,
      });
    },
    savedSummary(c: string, day: string): AnalyticsReply<S['AnalystSummary']> {
      const bad = guard(c);
      if (bad) return bad;
      if (!DAY_RE.test(day))
        return problem(422, 'bad_day', `День ${day} не похож на дату ГГГГ-ММ-ДД.`, [`day=${day}`]);
      const days = state.summaryDays[c] ?? [];
      if (!days.includes(day))
        return problem(404, 'no_saved_summary', `Сводки за ${day} у канала ${c} не сохранено.`, [
          `analytics/${c}/summary/${day}.json: not found`,
        ]);
      return ok(buildSummary(c, vids(c), day, !!state.collected[c], days));
    },
    footage(c: string, packed: boolean): AnalyticsReply<S['FootageWanted']> {
      const bad = guard(c);
      if (bad) return bad;
      const rows = c === REEL ? [...FOOTAGE_ROWS, ...(packed ? [PACKED_ROW] : [])] : [];
      const byReason: Record<string, number> = {};
      for (const r of rows)
        for (const [k, n] of Object.entries(r.reasons)) byReason[k] = (byReason[k] ?? 0) + n;
      const read = c === REEL ? 9 : c === TECH ? 2 : 0;
      return ok({
        task: 'footage-wanted',
        channel: c,
        built_at: '2026-10-10T07:00:00Z',
        since: null,
        batches: {
          read: read + (packed && c === REEL ? 21 : 0),
          packed: packed && c === REEL ? 21 : 0,
          first: read ? (packed && c === REEL ? '2026-09-10T0200Z' : '2026-10-01T0200Z') : null,
          last: read ? '2026-10-09T0200Z' : null,
        },
        notes:
          c === TECH
            ? [
                "official channels: the footage-origin list of 'example-tech' has no `official_channels` list - «где добыть» without official channels",
              ]
            : [],
        needs: rows.reduce((a, r) => a + r.misses, 0),
        by_reason: byReason,
        rows,
        packed_read: packed,
        reasons_ru: Object.fromEntries(
          [
            ...new Set([...Object.keys(byReason), ...rows.flatMap((r) => Object.keys(r.reasons))]),
          ].map((k) => [k, FOOTAGE_REASONS_RU[k] ?? null]),
        ),
      });
    },
    studio(c: string): AnalyticsReply<S['AnalyticsStudio']> {
      const bad = guard(c);
      if (bad) return bad;
      const set = !!state.studioSettings[c];
      const reads = vids(c)
        .map((v) => readOf(c, v))
        .filter((r): r is S['StudioReadRow'] => !!r);
      const last = [...vids(c)]
        .filter((v) => v.published <= END_DAY)
        .reverse()
        .slice(0, STUDIO_SETTINGS.last_videos);
      const visit = state.visits[c] ?? null;
      return ok({
        channel: c,
        no_pipeline: state.noPipeline[c] ?? null,
        settings: set ? { ...STUDIO_SETTINGS } : null,
        settings_error: set
          ? null
          : `channels/${c}.json has no analyst.studio_read (last_videos, insurance_hours, hook_min_gap_hours)`,
        last_videos: set
          ? last.map((v) => ({
              video_id: v.video_id,
              slug: v.slug,
              entry_id: entryOf(c, v),
              published: `${v.published}T15:00:00Z`,
              studio_url: STUDIO_URL(v.video_id),
            }))
          : [],
        n: set ? STUDIO_SETTINGS.last_videos : null,
        due: !set
          ? null
          : state.fresh[c]
            ? {
                due: false,
                line: `ok ${c}: рано (Studio прочитали только что; страховка — 24 ч)`,
              }
            : visit
              ? {
                  due: true,
                  line: `due ${c}: пора читать (страховка: >24 ч; последнее чтение 08.10 21:40 МСК, 36.3 ч назад)`,
                }
              : {
                  due: true,
                  line: `due ${c}: пора читать (страховка: ни одного чтения)`,
                },
        last_visit: visit,
        latest_reads: reads,
      });
    },
  };
}

export type AnalyticsBackend = ReturnType<typeof createAnalyticsBackend>;

/**
 * Маршрутизация `/api/analytics*`: GET — чтение, POST `…/studio/record[/plan]` — ввод прочитанного
 * в Studio; null — не этот адрес или не тот метод.
 */
export function routeAnalytics(
  backend: AnalyticsBackend,
  method: string,
  url: URL,
  body: unknown = null,
): AnalyticsReply<unknown> | null {
  const m = url.pathname.match(/\/api\/analytics(?:\/(.*))?$/);
  if (!m) return null;
  if (method === 'POST') {
    const w = (m[1] ?? '').split('/').map(decodeURIComponent);
    if (w.length === 4 && w[1] === 'studio' && w[2] === 'record' && w[3] === 'plan')
      return backend.entry.plan(w[0]!, body) as AnalyticsReply<unknown>;
    if (w.length === 3 && w[1] === 'studio' && w[2] === 'record')
      return backend.entry.confirm(w[0]!, body) as AnalyticsReply<unknown>;
    return null;
  }
  if (method !== 'GET') return null;
  backend.state.calls.push(url.pathname + url.search);
  if (!m[1]) return backend.overview();
  const q = url.searchParams;
  const n = Number(q.get('first_days') ?? 7);
  if (m[1] === 'diversity') return backend.diversity(q.get('channel'), Number(q.get('last') ?? 10));
  const rest = m[1].split('/').map(decodeURIComponent);
  const [c, what, arg] = rest as [string, string | undefined, string | undefined];
  if (rest.length === 2) {
    if (what === 'metrics') return backend.metrics(c, n);
    if (what === 'summary') return backend.summary(c, q.get('day'), n);
    if (what === 'footage-wanted') return backend.footage(c, q.get('packed') === 'true');
    if (what === 'studio') return backend.studio(c);
  }
  if (rest.length === 3 && arg) {
    if (what === 'videos') return backend.video(c, arg);
    if (what === 'summary') return backend.savedSummary(c, arg);
  }
  return null;
}
