// Подставные ролики батчей (CC-0012/0057 фабрики, договор 0.17.0) — с состоянием: ролики
// батча с пересборками рядом, превью (кадр монтажа / лист судьи / нет), карточки публикации,
// что журнал приёмки знает о ролике (вердикт, очередь под батчем). Общий для Vitest (MSW,
// src/mocks/handlers.ts) и Playwright (tests/e2e/fixtures.ts). mp4 и картинки — файлы-заглушки
// из tests/e2e/assets (их отдаёт фикстура e2e, с HTTP Range); здесь — только какой файл.
// Данные выдуманные, но по форме как у живой фабрики. Импорты — относительные.
import type { components } from '../api/schema.gen';
import { PAST, PAST_REBUILD } from './batches';
import { ACCEPT_BUILD_REFUSED, AUTO_RUN, plainState, seedState } from './cards';
import { createRebuild } from './rebuild';
import { MOCK_NOW, type BatchReply } from './schedule';
import { SCORE_MODEL, scoreOf, scoreShort } from './score';
import { createWithdraw } from './withdraw';
import {
  NOT_QUEUED,
  STASH_BUILDING,
  STASH_HELD,
  STASH_NOT_READY,
  STASH_STALE,
  STASH_TITLES,
} from './stash';

type S = components['schemas'];

/** Пересборка последнего батча истории (только у роликов: в истории прогонов её нет). */
export const PAST_REDO = 'rebuilds/2026-10-09T1500Z';
/** Источник пересборки PAST_REBUILD из истории. */
export const OLDER = 'example-film/2026-10-06T0210Z';
/**
 * CF-0821 (CC-0152): принятый ролик, что в копилку не лёг, — «да» ролику `usb-c-myths` батча OLDER.
 * Под этим именем в publish/example-film/ лежит ролик другого батча (`slug_taken`), и это другой
 * ролик — тёзка с другой темой и фактом (`namesake`).
 */
export const LEFT_OUT_SLUG = 'usb-c-myths';
export const LEFT_OUT_ALERT =
  'Ролик usb-c-myths (2026-10-06T0210Z) принят, но в копилку publish/example-film/_queue/ не попал: имя занято файлом другого батча в publish/';
export const LEFT_OUT_NAMESAKE = {
  entry_id: 'example-film:2026-09-24T0200Z:usb-c-myths',
  publish_path: 'publish/example-film/usb-c-myths.mp4',
  why: 'другая тема (usb-c-myths / usb-c-charging-myths) и другой факт',
};
const LEFT_OUT_QUEUED: S['AcceptQueued'] = {
  code: 'slug_taken',
  text_ru:
    'НЕ В КОПИЛКЕ: в publish/example-film/ под именем usb-c-myths лежит ролик другого батча - копия не положена, нужен человек',
  publish_path: null,
  ok: false,
  skipped: false,
  refused: true,
  changed: false,
  left_out: true,
  alert_ru: LEFT_OUT_ALERT,
  namesake: LEFT_OUT_NAMESAKE,
  notified: { status: 'sent', kind: 'needs_human' },
};
/** Источник пересборки ExampleTech, что стоит в «Идёт сейчас» (src/mocks/batches.ts). */
export const TECH_REBUILD_SRC = 'example-tech/2026-10-08T0200Z';
/** Батч без роликов (нет `05-video-editor.json`). */
export const EMPTY = 'example-tech/2026-10-07T0200Z';
/**
 * Настоящий случай CC-0088 (12.10): первые версии rink-rivals и delver без строки журнала
 * приёмки — отказ 09.10 оформили пересборкой, — а их пересборку вы приняли и залили в Studio.
 * Последним батчем истории батч становится только в тестах (`REPLACED_RUN`).
 */
export const REPLACED_SRC = 'example-film/2026-10-08T1824Z';
export const REPLACED_REDO = 'rebuilds/2026-10-09T1208Z';
/** Загрузки пересборки (как в `publish/uploads.json`): для подставной ленты публикации. */
export const REPLACED_UPLOADS = [
  {
    slug: 'rink-rivals',
    day: '2026-10-13',
    videoId: 'X66dFJ80XgA',
    batch: REPLACED_REDO,
    title: 'Rink Rivals Season 2: The Casting Call That Broke the Fandom #shorts',
  },
  {
    slug: 'delver',
    day: '2026-10-15',
    videoId: 'jHGkh2Zo0zw',
    batch: REPLACED_REDO,
    title: 'Delver: The One-Take Mine Scene Nobody Believed Was Real #shorts',
  },
] as const;
/** Прогон истории для батча REPLACED_SRC: тест ставит его последним (`/api/batches/history`). */
export const REPLACED_RUN: S['BatchRun'] = {
  batch: REPLACED_SRC,
  id: '2026-10-08T1824Z',
  channel: 'example-film',
  date: '2026-10-08',
  started: '2026-10-08T18:24:00Z',
  ended: '2026-10-08T20:41:00Z',
  videos: 3,
  wall_s: 8220,
  outcome: 'videos',
  launch: null,
};

/**
 * Настоящий случай CC-0116 (13.10): батч Science 2001Z — sophie-adenot отрендерен и отказан
 * проверкой качества (24 < 40), его mp4 в папке есть; второй отказанный после монтажа — без
 * файла. Оба лежат в `05.refusals`, API отдаёт их в `videos[]` с `refused`. В истории прогонов
 * батча нет — открывается по адресу (`?batch=…`), как и в тренировке.
 */
export const SCIENCE = 'example-science/2026-10-12T2001Z';

/**
 * CC-0175: «Да» положило ролик в копилку, а автосборка карточки не запустилась — с причиной
 * `card_build.why` (подставить через `setQueued`; `publish_path` — копилка `channel`).
 */
export const queuedBuildRefused = (channel: string, slug: string): S['AcceptQueued'] => ({
  code: 'placed',
  text_ru: `ролик положен в копилку: publish/${channel}/_queue/${slug}.mp4`,
  publish_path: `publish/${channel}/_queue/${slug}.mp4`,
  ok: true,
  skipped: false,
  refused: false,
  left_out: false,
  changed: true,
  card_build: { ...ACCEPT_BUILD_REFUSED, refusals: [...(ACCEPT_BUILD_REFUSED.refusals ?? [])] },
});

/** Файл-заглушка: что отдать на `mp4` и `preview`. */
export type MediaFile = 'clip.mp4' | 'frame.jpg' | 'sheet.png';
export type VideoReply =
  | BatchReply<unknown>
  | { status: 200; file: MediaFile; type: 'video/mp4' | 'image/jpeg' | 'image/png' };

type PreviewKind = 'frame' | 'sheet' | 'none';
type Seed = {
  slug: string;
  title: string | null;
  duration: number;
  preview: PreviewKind;
  score: string | null;
  qc?: boolean;
  card?: 'ready' | 'not_ready' | 'none';
  acceptance?: Partial<S['VideoAcceptance']>;
  /** Отказан после монтажа (05 `refusals[]`, CC-0116). */
  refused?: S['VideoRefusal'];
  /** false — mp4 в папке батча нет. */
  mp4?: boolean;
};

const base = (batch: string, slug: string) => `/api/batches/${batch}/videos/${slug}`;

function preview(batch: string, slug: string, kind: PreviewKind): S['Preview'] {
  if (kind === 'none')
    return {
      available: false,
      kind: null,
      media_type: null,
      url: null,
      path: null,
      tile: null,
      grid: null,
      reason: 'Монтаж не сохранил кадр, а судья кадров ролик не смотрел.',
    };
  const url = `${base(batch, slug)}/preview`;
  const dir = `pipeline/${batch}`;
  return kind === 'frame'
    ? {
        available: true,
        kind: 'frame',
        media_type: 'image/jpeg',
        url,
        path: `${dir}/videos/${slug}.jpg`,
        tile: null,
        grid: null,
        reason: null,
      }
    : {
        available: true,
        kind: 'sheet',
        media_type: 'image/png',
        url,
        path: `${dir}/work/${slug}/frame-judge/sheet-1.png`,
        tile: { width: 360, height: 640 },
        grid: { columns: 3, rows: 2 },
        reason: null,
      };
}

function acceptance(slug: string, batchId: string, a: Partial<S['VideoAcceptance']> = {}) {
  return {
    entry_id: `example-film:${batchId}:${slug}`,
    slug,
    recorded: false,
    verdict: null,
    accepted: null,
    reason: null,
    reason_code: null,
    answer: null,
    answered_at: null,
    recorded_at: null,
    note: null,
    amended_because: null,
    history: [],
    held: false,
    hold_id: null,
    publishable: false,
    pending: false,
    queued_at: null,
    queued_by: null,
    queued_verdicts: null,
    state_error: null,
    ...a,
  } satisfies S['VideoAcceptance'];
}

const channelOf = (batch: string) => {
  const dir = batch.split('/')[0]!;
  return dir === 'rebuilds' ? 'example-film' : dir;
};

function cardState(batch: string, s: Seed): S['CardState'] {
  const card = s.card ?? 'ready';
  return (
    seedState(channelOf(batch), batch.split('/')[1]!, s.slug) ??
    plainState(card === 'ready', card !== 'none')
  );
}

function video(batch: string, s: Seed, rebuiltIn: string[] = []): S['Video'] {
  const id = batch.split('/')[1]!;
  const card = s.card ?? 'ready';
  return {
    slug: s.slug,
    script_id: `${s.slug}-s1`,
    qc_passed: s.qc ?? true,
    score_line: s.score,
    duration: s.duration,
    mp4:
      s.mp4 === false
        ? { url: `${base(batch, s.slug)}/mp4`, exists: false, bytes: null, path: null }
        : {
            url: `${base(batch, s.slug)}/mp4`,
            exists: true,
            bytes: 22459,
            path: `pipeline/${batch}/videos/${s.slug}.mp4`,
          },
    preview: preview(batch, s.slug, s.preview),
    card: {
      exists: card !== 'none',
      ready: card === 'ready',
      why: card === 'not_ready' ? 'В карточке нет раздела «## Публикация».' : null,
      title: card === 'none' ? null : s.title,
      url: `${base(batch, s.slug)}/card`,
      // CC-0127: состояние карточки — по учёту карточек (./cards), иначе по готовности.
      card: cardState(batch, s),
    },
    acceptance: acceptance(s.slug, id, s.acceptance),
    accept_url: `${base(batch, s.slug)}/acceptance`,
    rebuilt_in: rebuiltIn,
    ...(s.refused ? { refused: s.refused } : {}),
    // CC-0172 (договор 0.75.0): ремонта после судьи кадров нет — null (`setRepair`).
    repair: null,
    // CC-0125 (договор 0.55): баллы и тир — из строки оценки; у отказанного — из 05.
    score: scoreShort(batch, s.slug, s.score, !!s.refused),
  };
}

const DELVER: Seed = {
  slug: 'delver',
  title: 'Delver: the one-take mine scene nobody believed was real',
  duration: 44.9,
  preview: 'sheet',
  score: 'B · 74 — хук держит, середина проседает',
};
const RIVALRY: Seed = {
  slug: 'rink-rivals',
  title: 'Rink Rivals: the casting call that broke the fandom',
  duration: 41.2,
  preview: 'frame',
  score: 'A · 82 — сильный хук',
  acceptance: {
    recorded: true,
    verdict: 'accepted',
    accepted: true,
    answer: 'rink-rivals — да, берём',
    answered_at: '2026-10-09',
    recorded_at: '2026-10-09T09:12:00Z',
    publishable: true,
  },
};
const VANGUARDS: Seed = {
  slug: 'vanguards-doomsday',
  title: 'Vanguards: Doomsday — the release date shift explained',
  duration: 38.4,
  preview: 'none',
  score: 'C · 58 — тема слабая',
  card: 'not_ready',
  acceptance: {
    recorded: true,
    verdict: 'rejected',
    accepted: false,
    reason: 'хук про дату скучный, нужен кадр со студией',
    reason_code: 'weak_hook',
    answer: 'vanguards-doomsday — переделать: хук скучный',
    note: 'переделать',
    pending: true,
    queued_at: '2026-10-10T06:40:00Z',
    queued_by: 'user (центр)',
    queued_verdicts: 1,
  },
};

type Stored = { list: S['BatchVideos']; cards: Map<string, S['Card']> };

function card(batch: string, s: Seed): S['Card'] {
  const title = s.title ?? s.slug;
  const about = `Почему эту сцену из «${title.split(':')[0]}» до сих пор пересматривают — за ${Math.round(s.duration)} секунд.`;
  const source = 'Источник: интервью режиссёра, Variety, 2026.';
  const hashtags = '#shorts #кино #example-film';
  const ready = (s.card ?? 'ready') === 'ready';
  const sections: S['CardSection'][] = [
    { name: 'Название', text: title },
    { name: 'Описание', text: [about, source, hashtags].join('\n\n') },
    { name: 'Теги', text: 'кино, съёмки, закулисье, факты' },
    ...(ready ? [{ name: 'Публикация', text: '2026-10-11 18:00 MSK' }] : []),
    { name: 'Факты', text: '1. Сцену сняли одним дублем — Variety, 2026.' },
  ];
  const raw = sections.map((x) => `## ${x.name}\n\n${x.text}\n`).join('\n');
  return {
    batch,
    slug: s.slug,
    path: `pipeline/${batch}/work/publish-card/${s.slug}.md`,
    ready,
    why: ready ? null : 'В карточке нет раздела «## Публикация».',
    status: ready ? 'ready' : 'not_ready',
    title,
    description: [about, source, hashtags].join('\n\n'),
    description_blocks: [about, source, hashtags],
    tags: ['кино', 'съёмки', 'закулисье', 'факты'],
    tags_raw: 'кино, съёмки, закулисье, факты',
    publish_at: ready ? '2026-10-11T15:00:00Z' : null,
    publish_section: ready ? '2026-10-11 18:00 MSK' : null,
    contains_synthetic: false,
    note_error: null,
    sections,
    problems: ready ? [] : ['нет раздела «## Публикация» — слот не назначен'],
    source: { url: 'https://example.invalid/variety', title: 'Variety' },
    fact_checks: [],
    claims: null,
    mark: { status: ready ? 'ready' : 'not_ready', agent: 'publisher' },
    raw,
    card: cardState(batch, s),
  };
}

function batchOf(
  batch: string,
  seeds: Seed[],
  opts: {
    rebuilds?: { batch: string; seeds: Seed[] }[];
    of?: string;
    editorError?: string;
  } = {},
): Stored {
  const [dir, id] = batch.split('/') as [string, string];
  const rebuilds = (opts.rebuilds ?? []).map((rb) => ({
    batch: rb.batch,
    batch_id: rb.batch.split('/')[1]!,
    dir: `pipeline/${rb.batch}`,
    editor_error: null,
    videos: rb.seeds.map((s) => video(rb.batch, s)),
  }));
  const list: S['BatchVideos'] = {
    batch,
    channel: dir === 'rebuilds' ? 'example-film' : dir,
    batch_id: id,
    dir: `pipeline/${batch}`,
    editor_error: opts.editorError ?? null,
    rebuild_of: opts.of
      ? { channel: 'example-film', batch_id: opts.of.split('/')[1]!, batch: opts.of }
      : null,
    videos: seeds.map((s) =>
      video(
        batch,
        s,
        rebuilds.filter((rb) => rb.videos.some((v) => v.slug === s.slug)).map((rb) => rb.batch),
      ),
    ),
    rebuilds,
    reason_codes: [
      { code: 'weak_hook', count: 4, phrases: ['хук скучный', 'хук не цепляет'] },
      { code: 'off_topic', count: 1, phrases: ['не по теме канала'] },
    ],
    acceptance_error: null,
    score_model: SCORE_MODEL,
  };
  const cards = new Map<string, S['Card']>();
  const all = [
    ...seeds.map((s) => [batch, s] as const),
    ...(opts.rebuilds ?? []).flatMap((rb) => rb.seeds.map((s) => [rb.batch, s] as const)),
  ];
  for (const [b, s] of all)
    if ((s.card ?? 'ready') !== 'none') cards.set(`${b}|${s.slug}`, card(b, s));
  return { list, cards };
}

const REDO_DELVER: Seed = {
  ...DELVER,
  title: 'Delver: the one-take mine scene — new hook',
  duration: 43.1,
  preview: 'frame',
  score: 'B · 79 — хук сильнее',
};
const OLD_A: Seed = {
  slug: 'quiet-keyboards',
  title: 'Why quiet keyboards cost twice as much',
  duration: 39,
  preview: 'frame',
  score: 'S · 93 — сильный хук, ровный темп',
  acceptance: {
    recorded: true,
    verdict: 'rejected',
    accepted: false,
    reason: 'звук тихий',
    reason_code: 'bad_audio',
    answer: 'quiet-keyboards — нет, звук тихий',
    answered_at: '2026-10-06',
    recorded_at: '2026-10-06T10:00:00Z',
  },
};
const OLD_B: Seed = {
  slug: 'usb-c-myths',
  title: 'Three USB-C myths that refuse to die',
  duration: 42,
  preview: 'sheet',
  score: 'D · 44 — середина проседает, кадр мелкий',
  card: 'none',
};

const ACCEPTED_REDO = (slug: string, day: string): Partial<S['VideoAcceptance']> => ({
  recorded: true,
  verdict: 'accepted',
  accepted: true,
  answer: `${slug} — да, берём`,
  answered_at: day,
  recorded_at: `${day}T17:40:00Z`,
  publishable: true,
});
const SRC_RIVALRY: Seed = {
  slug: 'rink-rivals',
  title: 'Rink Rivals Season 2: the casting call that broke the fandom',
  duration: 41.2,
  preview: 'frame',
  score: 'B · 72 — хук держит',
};
const SRC_DELVER: Seed = {
  slug: 'delver',
  title: 'Delver: the one-take mine scene nobody believed was real',
  duration: 44.9,
  preview: 'frame',
  score: 'B · 70 — середина проседает',
};
const SRC_VANGUARDS: Seed = {
  slug: 'vanguards-doomsday',
  title: 'Vanguards: Doomsday moved again — the date Zenith picked',
  duration: 38.4,
  preview: 'frame',
  score: 'B · 75',
  acceptance: ACCEPTED_REDO('vanguards-doomsday', '2026-10-09'),
};
const REDO_SEEDS: Seed[] = [
  {
    slug: 'mudform',
    title: 'Mudform: the DC villain getting his own film',
    duration: 40.3,
    preview: 'frame',
    score: 'B · 77',
    acceptance: ACCEPTED_REDO('mudform', '2026-10-09'),
  },
  {
    ...SRC_DELVER,
    title: 'Delver: the one-take mine scene — new hook',
    score: 'B · 79 — хук сильнее',
    acceptance: ACCEPTED_REDO('delver', '2026-10-09'),
  },
  {
    ...SRC_RIVALRY,
    title: 'Rink Rivals Season 2: the casting call — new cut',
    score: 'A · 81 — сильный хук',
    acceptance: ACCEPTED_REDO('rink-rivals', '2026-10-09'),
  },
];

/** Science 2001Z (CC-0116): один ролик ждёт решения, два отказаны после монтажа. */
const MARS: Seed = {
  slug: 'mars-sample-return',
  title: 'Mars Sample Return: why NASA is rethinking the whole plan',
  duration: 42.6,
  preview: 'frame',
  score: 'B · 68 — хук держит',
};
/** Пул клипов живой фабрики: в журнале оценки пути абсолютные — экран их не показывает. */
const CLIPS = '~/factory/pool/example-science/clips';
/** Строка оценки sophie-adenot — дословно как в 05 `refusals[]` живого батча 2001Z. */
export const ADENOT_SCORE_LINE =
  'F · 24 — −6 полоса удержания (3 блока), −3 кадрирование (1 шот), −4 разрешение (2 шота), −1 подача: размытый фон (1 шот), −62 зависший кадр (1 блок, хук)';
export const ADENOT: Seed = {
  slug: 'sophie-adenot',
  title: 'Sophie Adenot: the second French woman heading to space',
  duration: 44.1,
  preview: 'frame',
  score: ADENOT_SCORE_LINE,
  qc: false,
  refused: {
    reason_code: 'score_below_threshold',
    reason_ru: 'оценка ниже порога после штрафов',
    reason: 'SCORE UNDER THE THRESHOLD after qc: 24 < 40',
    gate: 'score_below_threshold',
    score_line: ADENOT_SCORE_LINE,
    score: {
      score: 24,
      threshold: 40,
      tier: 'F',
      log: [
        { rule: 'score.retention_strip', price: -6, hook: false, where: { blocks: [3, 4, 5] } },
        {
          rule: 'score.framing',
          price: -3,
          hook: false,
          where: { shot: `${CLIPS}/a03_iss-cupola.mp4` },
          note: `subject off-center: ${CLIPS}/a03_iss-cupola.mp4`,
        },
        {
          rule: 'score.resolution',
          price: -4,
          hook: false,
          where: { shot: `${CLIPS}/a06_esa-adenot-training.mp4` },
          note: `source 640x360 under 1080p (${CLIPS}/a06_esa-adenot-training.mp4)`,
        },
        { rule: 'score.blurry_background', price: -1, hook: false },
        {
          rule: 'score.frozen_block',
          price: -62,
          hook: true,
          note: 'clip block rendered as a still (qc_render frozen_blocks)',
        },
      ],
    },
    at: '2026-10-12T23:41:00Z',
  },
};
export const DOTS: Seed = {
  slug: 'jwst-little-red-dots',
  title: 'The little red dots: what JWST found at the edge of time',
  duration: 39.8,
  preview: 'none',
  score: null,
  qc: false,
  mp4: false,
  refused: {
    reason_code: 'no_second_source',
    reason_ru: 'всё из одного источника',
    reason: 'fact 2 has a single source - two independent sources are required',
    gate: null,
    score_line: null,
    score: null,
    at: '2026-10-12T23:55:00Z',
  },
};

/** Батчи роликов копилки ExampleFilm (CC-0122, ./stash): их ролики приняты. */
export const STASH_BATCH = 'example-film/2026-10-09T0200Z';
export const STASH_OLD_BATCH = 'example-film/2026-09-24T0200Z';
export const NOT_QUEUED_BATCH = 'example-film/2026-10-08T0200Z';
const stashSeed = (slug: string, score: string, day: string): Seed => ({
  slug,
  title: STASH_TITLES[slug]!,
  duration: 40.5,
  preview: 'frame',
  score,
  acceptance: {
    recorded: true,
    verdict: 'accepted',
    accepted: true,
    answer: `${slug} — да`,
    answered_at: day,
    recorded_at: `${day}T15:00:00Z`,
    publishable: true,
  },
});

function seed(): Map<string, Stored> {
  const m = new Map<string, Stored>();
  const add = (s: Stored) => m.set(s.list.batch, s);
  add(
    batchOf(PAST, [DELVER, RIVALRY, VANGUARDS], {
      rebuilds: [{ batch: PAST_REDO, seeds: [REDO_DELVER] }],
    }),
  );
  add(batchOf(PAST_REDO, [REDO_DELVER], { of: PAST }));
  add(
    batchOf(OLDER, [OLD_A, OLD_B], {
      rebuilds: [
        { batch: PAST_REBUILD, seeds: [{ ...OLD_A, acceptance: {}, score: 'B · 76' }, OLD_B] },
      ],
    }),
  );
  add(batchOf(PAST_REBUILD, [{ ...OLD_A, acceptance: {}, score: 'B · 76' }, OLD_B], { of: OLDER }));
  add(
    batchOf(REPLACED_SRC, [SRC_DELVER, SRC_VANGUARDS, SRC_RIVALRY], {
      rebuilds: [{ batch: REPLACED_REDO, seeds: REDO_SEEDS }],
    }),
  );
  add(batchOf(REPLACED_REDO, REDO_SEEDS, { of: REPLACED_SRC }));
  add(batchOf(SCIENCE, [MARS, ADENOT, DOTS]));
  // Источник остановленной пересборки ExampleTech (src/mocks/batches.ts, `rebuild.of`): у её
  // карточки названия роликов — отсюда.
  add(batchOf(TECH_REBUILD_SRC, [{ ...OLD_A, acceptance: {} }, OLD_B]));
  add(
    batchOf(STASH_BATCH, [
      stashSeed(STASH_HELD, 'A · 84 — сильный хук', '2026-10-09'),
      stashSeed(STASH_NOT_READY, 'C · 55 — середина проседает', '2026-10-09'),
      stashSeed(STASH_BUILDING, 'B · 69 — хук держит', '2026-10-10'),
    ]),
  );
  add(batchOf(STASH_OLD_BATCH, [stashSeed(STASH_STALE, 'B · 71 — тема свежая', '2026-09-25')]));
  add(batchOf(NOT_QUEUED_BATCH, [stashSeed(NOT_QUEUED, 'B · 66 — хук держит', '2026-10-08')]));
  add(batchOf(EMPTY, [], { editorError: 'Нет 05-video-editor.json: монтаж в этом батче не шёл.' }));
  return m;
}

/** Строки фабрики (`acceptance.REFUSALS_RU`, CF-0676) — те отказы, что знает мок. */
const REFUSALS_RU = {
  answer_missing: (slug: string) =>
    `У вердикта по ролику «${slug}» нет ответа пользователя - вердикт берётся только из его слов.`,
  answer_without_name: (slug: string) =>
    `В ответе нет имени ролика «${slug}» - вердикт привязывается к ролику по имени. Впишите имя ролика в ответ.`,
  rejection_without_reason: () => 'Отказ без причины не записывается - нужна причина одной фразой.',
  rejection_without_code: () =>
    'Для отказа нужен код причины (латиница, цифры, подчёркивание: blurry_footage) - по нему фабрика считает повторы причин.',
  acceptance_with_code: () => 'У «принят» не бывает кода причины - уберите его.',
  verdict_already_given: (slug: string) =>
    `У ролика «${slug}» уже есть вердикт. Заменить его можно, только сказав, почему пользователь передумал (поле «почему меняем»).`,
} as const;

/** Пометки строки журнала — как у API (`api/videos.py`). */
export const REDO_NOTE =
  'из центра (CC-0012): «переделать» - просьба переделать ждёт очереди просьб оператору (CC-0018)';
const YES_NO_NOTE = 'из центра (CC-0012)';
export const REDO_NOT_YET =
  'очереди просьб оператору ещё нет (CC-0018) - просьба переделать записана только в журнал приёмки';

/** Как `acceptance.names_video`: имя в любом регистре и с любыми разделителями. */
const norm = (x: string) =>
  x
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim();
export function namesVideo(answer: string, slug: string): boolean {
  const a = norm(answer);
  const s = norm(slug);
  if (!s) return false;
  return ` ${a} `.includes(` ${s} `) || a.replaceAll(' ', '').includes(s.replaceAll(' ', ''));
}

const CODE_RE = /^[a-z][a-z0-9_]*$/;
const VERDICT = { yes: 'accepted', no: 'rejected', redo: 'rejected' } as const;

export function createVideosBackend() {
  const store = seed();
  /** Каждый запрос mp4: Range (null — без него). Тесты проверяют перемотку. */
  const mp4Calls: (string | null)[] = [];
  const unknown = (batch: string): BatchReply<never> => ({
    status: 404,
    body: { message: `Батча «${batch}» нет.`, code: 'unknown_batch', details: [] },
  });
  const noVideo = (batch: string, slug: string): BatchReply<never> => ({
    status: 404,
    body: { message: `Ролика «${slug}» в батче ${batch} нет.`, code: 'unknown_video', details: [] },
  });
  const find = (batch: string, slug: string) => {
    const s = store.get(batch);
    if (!s) return null;
    return (
      s.list.videos.find((v) => v.slug === slug) ??
      s.list.rebuilds.flatMap((r) => r.videos).find((v) => v.slug === slug) ??
      null
    );
  };
  /** Все копии ролика (в своём батче и в списке источника) — правка состояния в одном месте. */
  const everywhere = (batch: string, slug: string) =>
    [...store.values()].flatMap((s) => [
      ...(s.list.batch === batch ? s.list.videos.filter((v) => v.slug === slug) : []),
      ...s.list.rebuilds
        .filter((r) => r.batch === batch)
        .flatMap((r) => r.videos.filter((v) => v.slug === slug)),
    ]);

  /** Идущие батчи (`runlog.open_batches`): пока они есть, вердикт ждёт в очереди. */
  let going: S['BlockingBatch'][] = [];
  /** Каждый принятый мок-фабрикой вердикт (тесты проверяют тело запроса). */
  const accepted: { batch: string; slug: string; body: S['AcceptIn'] }[] = [];
  let commits = 0;
  const refuse = (
    code: keyof typeof REFUSALS_RU,
    slug: string,
    detail: string,
  ): BatchReply<never> => ({
    status: 422,
    body: { message: REFUSALS_RU[code](slug), code, details: [detail] },
  });

  /** Пересборка роликов батча (./rebuild): режимы, секунды → блоки, план и «да». */
  const rebuild = createRebuild((batch) => {
    const s = store.get(batch);
    return s
      ? {
          batch,
          channel: s.list.channel ?? null,
          batch_id: s.list.batch_id,
          videos: s.list.videos,
        }
      : null;
  });

  let queuedNext: S['AcceptQueued'] | null | undefined = undefined;
  const takeQueued = () => {
    const q = queuedNext ?? null;
    queuedNext = undefined;
    return q;
  };

  /** «Снять окончательно» (CC-0107): план и «да» с ответом пользователя. */
  const withdrawal = createWithdraw({
    videoOf: (batch, slug) => {
      const v = find(batch, slug);
      return v ? { verdict: v.acceptance?.verdict ?? null } : null;
    },
    now: () => MOCK_NOW,
  });

  return {
    mp4Calls,
    accepted,
    rebuild,
    withdrawal,
    /** Ответ `queued` следующего «принять» (одноразово; CC-0122): почему не в копилке. */
    setQueued(q: S['AcceptQueued'] | null) {
      queuedNext = q;
    },
    /** CC-0172: ремонт ролика после судьи кадров (null — не было), во всех его копиях. */
    setRepair(batch: string, slug: string, repair: S['VideoRepair'] | null) {
      for (const v of everywhere(batch, slug)) v.repair = repair;
    },
    /** Пустить «идущие батчи» (вердикт — в очередь до конца батча) или убрать их ([]). */
    setGoing(list: S['BlockingBatch'][]) {
      going = list;
    },
    /** `POST …/acceptance`: проверки фабрики по порядку, запись — в журнал или в очередь. */
    accept(batch: string, slug: string, body: unknown): BatchReply<S['AcceptResult']> {
      const b = (body ?? {}) as Partial<S['AcceptIn']>;
      const verdict = b.verdict;
      if (!verdict || !(verdict in VERDICT))
        return {
          status: 422,
          body: {
            message: 'Вердикт - «yes», «no» или «redo».',
            code: 'invalid',
            details: [`verdict ${JSON.stringify(verdict)}: not one of ['no', 'redo', 'yes']`],
          },
        };
      if (!store.has(batch)) return unknown(batch);
      const v = find(batch, slug);
      if (!v) return noVideo(batch, slug);
      // CC-0116 (договор 0.42.0): ролику, отказанному после монтажа, вердикт не дают.
      if (v.refused)
        return {
          status: 409,
          body: {
            message: `Ролик «${slug}» отказан после монтажа - вердикт ему не дают, его можно только пересобрать.`,
            code: 'video_refused',
            details: [`${slug}: in 05 refusals[] (${v.refused.gate ?? '?'}), not videos[]`],
          },
        };
      const words = (b.words ?? '').trim();
      if (!words) return refuse('answer_missing', slug, `${slug}: no answer behind the verdict`);
      if (!namesVideo(words, slug))
        return refuse(
          'answer_without_name',
          slug,
          `${slug}: the answer ${JSON.stringify(words)} does not name this video`,
        );
      const reason = (b.reason ?? '').trim();
      if (verdict !== 'yes') {
        if (!reason)
          return refuse('rejection_without_reason', slug, `${slug}: a rejection with no reason`);
        if (!CODE_RE.test(b.reason_code ?? ''))
          return refuse(
            'rejection_without_code',
            slug,
            `${slug}: a rejection needs a \`reason_code\` ([a-z][a-z0-9_]*), got ${JSON.stringify(b.reason_code ?? null)}`,
          );
      } else if (b.reason_code) {
        return refuse(
          'acceptance_with_code',
          slug,
          `${slug}: an acceptance carries no reason_code`,
        );
      }
      const prev = v.acceptance;
      const amend = (b.amend ?? '').trim();
      if (prev?.verdict && !amend)
        return refuse(
          'verdict_already_given',
          slug,
          `${prev.entry_id} already carries a verdict (${prev.verdict}, ${prev.answered_at}). A verdict is replaced only by the user changing it: pass \`amend\``,
        );
      accepted.push({ batch, slug, body: b as S['AcceptIn'] });
      const now = new Date().toISOString();
      const pending = going.length > 0;
      const id = batch.split('/')[1]!;
      const history = prev?.verdict
        ? [
            ...(prev.history ?? []),
            { verdict: prev.verdict, answer: prev.answer, at: prev.recorded_at },
          ]
        : (prev?.history ?? []);
      const state: Partial<S['VideoAcceptance']> = {
        recorded: true,
        verdict: VERDICT[verdict],
        accepted: verdict === 'yes',
        reason: verdict === 'yes' ? null : reason,
        reason_code: verdict === 'yes' ? null : b.reason_code!,
        answer: b.words!,
        answered_at: now.slice(0, 10),
        recorded_at: now,
        note: verdict === 'redo' ? REDO_NOTE : YES_NO_NOTE,
        amended_because: amend || null,
        history,
        publishable: verdict === 'yes',
        pending,
        queued_at: pending ? now : null,
        queued_by: pending ? 'user (центр)' : null,
        queued_verdicts: pending ? 1 : null,
      };
      for (const x of everywhere(batch, slug)) x.acceptance = acceptance(slug, id, state);
      const row = { entry_id: `example-film:${id}:${slug}`, slug, ...state };
      const subject = `Приёмка: ${slug} ${verdict === 'yes' ? 'принят' : 'отклонён'} (user (центр))`;
      const leftOut =
        queuedNext === undefined &&
        verdict === 'yes' &&
        !pending &&
        batch === OLDER &&
        slug === LEFT_OUT_SLUG;
      const sha = pending ? null : `c0ffee${String(++commits).padStart(2, '0')}`.padEnd(40, '0');
      return {
        status: 200,
        body: {
          batch,
          slug,
          verdict,
          row,
          log: 'publish/acceptance-log.json',
          pending,
          committed: !pending,
          commit: sha,
          subject: pending ? null : subject,
          queue: pending ? 'publish/acceptance-pending.jsonl' : null,
          batches: going,
          flushed: null,
          redo: verdict === 'redo' ? { queued: false, reason: REDO_NOT_YET, request: null } : null,
          acceptance: find(batch, slug)?.acceptance ?? null,
          // CC-0122 (договор 0.54): принятый и записанный ролик фабрика кладёт в копилку канала.
          // CF-0821: принятый, но не легший в копилку ролик — и в `queued`, и верхним `left_out`.
          left_out: leftOut
            ? {
                entry_id: row.entry_id,
                slug,
                batch_id: id,
                code: LEFT_OUT_QUEUED.code,
                text_ru: LEFT_OUT_QUEUED.text_ru,
                alert_ru: LEFT_OUT_ALERT,
                namesake: LEFT_OUT_NAMESAKE,
                notified: LEFT_OUT_QUEUED.notified,
              }
            : null,
          queued:
            queuedNext !== undefined
              ? takeQueued()
              : leftOut
                ? { ...LEFT_OUT_QUEUED }
                : verdict === 'yes' && !pending
                  ? {
                      code: 'placed',
                      text_ru: `ролик положен в копилку: publish/${batch.split('/')[0]}/_queue/${slug}.mp4`,
                      publish_path: `publish/${batch.split('/')[0]}/_queue/${slug}.mp4`,
                      ok: true,
                      skipped: false,
                      refused: false,
                      left_out: false,
                      changed: true,
                      // CC-0127: приёмка сама запускает сборку карточки (отдельным процессом).
                      card_build: {
                        ok: true,
                        launched: true,
                        skipped: null,
                        run_id: AUTO_RUN(slug),
                        log: `logs/publish-card/${slug}.log`,
                        refusals: [],
                        error: null,
                        why: null,
                      },
                    }
                  : null,
        },
      };
    },
    /** Подменить состояние приёмки ролика (тесты; CC-0062 — запись вердикта). */
    setAcceptance(batch: string, slug: string, a: Partial<S['VideoAcceptance']> | null) {
      const id = batch.split('/')[1]!;
      for (const v of everywhere(batch, slug)) v.acceptance = a ? acceptance(slug, id, a) : null;
    },
    /** Подменить превью ролика (тесты: кадр / лист / нет). */
    setPreview(batch: string, slug: string, kind: PreviewKind) {
      for (const v of everywhere(batch, slug)) v.preview = preview(batch, slug, kind);
    },
    list(batch: string): BatchReply<S['BatchVideos']> {
      const s = store.get(batch);
      return s ? { status: 200, body: s.list } : unknown(batch);
    },
    card(batch: string, slug: string): BatchReply<S['Card']> {
      if (!store.has(batch)) return unknown(batch);
      const c = store.get(batch)!.cards.get(`${batch}|${slug}`);
      if (c) return { status: 200, body: c };
      return find(batch, slug)
        ? {
            status: 404,
            body: {
              message: `У ролика «${slug}» нет карточки публикации.`,
              code: 'no_card',
              details: [],
            },
          }
        : noVideo(batch, slug);
    },
    mp4(batch: string, slug: string, range: string | null): VideoReply {
      mp4Calls.push(range);
      if (!store.has(batch)) return unknown(batch);
      if (!find(batch, slug)) return noVideo(batch, slug);
      return { status: 200, file: 'clip.mp4', type: 'video/mp4' };
    },
    /** `GET …/videos/{slug}/score` (CC-0125): разбор оценки; без неё — 404 `no_score`. */
    score(batch: string, slug: string): BatchReply<S['VideoScore']> {
      if (!store.has(batch)) return unknown(batch);
      const v = find(batch, slug);
      if (!v) return noVideo(batch, slug);
      const body = scoreOf(batch, v);
      return body
        ? { status: 200, body }
        : {
            status: 404,
            body: {
              message: `У ролика «${slug}» нет оценки: ни журнала plan.score.json, ни блока в 05.`,
              code: 'no_score',
              details: [`pipeline/${batch}/work/${slug}/plan.score.json: missing`],
            },
          };
    },
    preview(batch: string, slug: string): VideoReply {
      if (!store.has(batch)) return unknown(batch);
      const v = find(batch, slug);
      if (!v) return noVideo(batch, slug);
      if (!v.preview.available)
        return {
          status: 404,
          body: { message: v.preview.reason ?? 'Превью нет.', code: 'no_preview', details: [] },
        };
      return v.preview.kind === 'sheet'
        ? { status: 200, file: 'sheet.png', type: 'image/png' }
        : { status: 200, file: 'frame.jpg', type: 'image/jpeg' };
    },
  };
}

export type VideosBackend = ReturnType<typeof createVideosBackend>;

/** Ответ подставных роликов на запрос, null — адрес не их. */
export function routeVideos(
  backend: VideosBackend,
  method: string,
  url: URL,
  headers: { range?: string | null } = {},
  body: unknown = null,
): VideoReply | null {
  const rb = url.pathname.match(/\/api\/batches\/([^/]+)\/([^/]+)\/rebuild(?:\/(modes|plan))?$/);
  if (rb) {
    const batch = `${decodeURIComponent(rb[1]!)}/${decodeURIComponent(rb[2]!)}`;
    if (rb[3] === 'modes') return method === 'GET' ? backend.rebuild.modes(batch) : null;
    if (method !== 'POST') return null;
    return rb[3] === 'plan'
      ? backend.rebuild.plan(batch, body)
      : backend.rebuild.confirm(batch, body);
  }
  const wd = url.pathname.match(
    /\/api\/batches\/([^/]+)\/([^/]+)\/videos\/([^/]+)\/withdraw(\/plan)?$/,
  );
  if (wd) {
    if (method !== 'POST') return null;
    const batch = `${decodeURIComponent(wd[1]!)}/${decodeURIComponent(wd[2]!)}`;
    const slug = decodeURIComponent(wd[3]!);
    return wd[4]
      ? backend.withdrawal.plan(batch, slug)
      : backend.withdrawal.confirm(batch, slug, body);
  }
  const m = url.pathname.match(
    /\/api\/batches\/([^/]+)\/([^/]+)\/videos(?:\/([^/]+)\/(mp4|preview|card|acceptance|blocks|score))?$/,
  );
  if (!m) return null;
  const [, dir, id, slug, sub] = m;
  const batch = `${decodeURIComponent(dir!)}/${decodeURIComponent(id!)}`;
  if (sub === 'acceptance')
    return method === 'POST' ? backend.accept(batch, decodeURIComponent(slug!), body) : null;
  if (method !== 'GET' && method !== 'HEAD') return null;
  if (!slug) return backend.list(batch);
  const s = decodeURIComponent(slug);
  if (sub === 'card') return backend.card(batch, s);
  if (sub === 'score') return backend.score(batch, s);
  if (sub === 'blocks') return backend.rebuild.blocks(batch, s, url.searchParams.get('at') ?? '');
  if (sub === 'mp4') return backend.mp4(batch, s, headers.range ?? null);
  return backend.preview(batch, s);
}
