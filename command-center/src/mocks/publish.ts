// Подставная публикация (CC-0064 фабрики, чтение; договор 0.20.0): очереди каналов, лента слотов
// на N дней с занявшими их роликами, пауза, переключатель API-загрузки, ротация, серия Studio,
// холды и карточки роликов в папках дней с полями для Studio. Общий для Vitest (MSW,
// src/mocks/handlers.ts) и Playwright (tests/e2e/fixtures.ts). Тела типизированы контрактом;
// строки — как у `publish_queue.py` / `channel_pause` / `api_switch` / `studio_fields`. Данные
// выдуманные, но по форме как у живой фабрики. Записи (пауза, карточка, ротация — CC-0068;
// переключатель API-загрузки, загрузка на YouTube, запись Studio — CC-0069) — `./publishWrites`
// поверх этого же состояния. Состояние — поля бэкенда: тест может поломать очередь, холды или
// карточку перед открытием.
// Импорты — относительные.
import type { components } from '../api/schema.gen';
import {
  API_WARNINGS,
  SWITCH_PATH,
  createPublishWrites,
  holdSignInfo,
  routePublishWrite,
  studioStreak,
  type BatchCard,
  type RotationRow,
  type UploadRow,
  type WriteReply,
} from './publishWrites';
import { MOCK_NOW } from './schedule';
import { createCards, plainState, routeCards, type CardsReply } from './cards';
import { createMove, routeMove, type MoveReply } from './publishMove';
import {
  createStash,
  routeStash,
  STASH_RESERVE,
  STASH_RESERVE_ID,
  STASH_TITLES,
  TWIN,
  TWIN_NEW,
  TWIN_OF_PLACED,
  TWIN_OLD,
  TWIN_RESERVE,
  TWIN_RESERVE_NEW_ID,
  TWIN_RESERVE_OLD_ID,
  TWIN_TITLES,
  UNSURE_NO_TOPIC,
  cleanTitle,
  namesakesMessage,
  type StashReply,
} from './stash';

type S = components['schemas'];

export type PublishReply<T> =
  { status: 200; body: T } | { status: 404 | 409 | 500; body: S['PublishProblem'] };

const problem = (
  status: 404 | 409 | 500,
  code: S['PublishProblem']['code'],
  message: string,
  details: string[] = [],
): PublishReply<never> => ({ status, body: { message, code, details } });

const ok = <T>(body: T): PublishReply<T> => ({ status: 200, body });

export const REEL = 'example-film';
export const TECH = 'example-tech';
export const SCIENCE = 'example-science';
const CHANNELS = [REEL, SCIENCE, TECH] as const;

/** Ролики ленты ExampleFilm: загружен, загружен и в папке дня, готов, не готов. */
export const UPLOADED = 'rink-rivals';
export const PLACED = 'delver';
/** CC-0187: батч новых версий, что правило не отличило от размещённых. */
export const OTHER_BATCH = '2026-10-09T0200Z';
/** CC-0187: название новой версии `PLACED`. */
export const OTHER_TITLE = 'Delver: The Director Speaks #shorts';
/** CC-0187: другая версия без пути размещённой — центр называет её по имени и батчу. */
export const OTHER_UNLINKED = 'night-shift';
export const OTHER_UNLINKED_TITLE = 'Night Shift: Second Look #shorts';
/** CC-0187: батч размещённой версии `OTHER_UNLINKED`. */
export const OTHER_UNLINKED_PLACED = '2026-09-30T0200Z';
export const READY = 'vanguards-doomsday';
export const NOT_READY = 'wren-hollow-casting';
/** Ждёт слота в `_queue/` и держит холд. */
export const WAITING = 'rapid-reckless-11';

/** Очередь ExampleTech с завтрашнего дня (как на фабрике 16.10: 17, 18 и 19.10), дальше — свободно. */
export const TECH_QUEUE = ['homepod', 'homeview', 'chatgpt'] as const;
const TECH_VIDEO_IDS = ['Hp0dT3chA1x', 'Hv1ewT3chB2', 'Cg9tT3chC3z'];

const MSK_H = 3;
const pad = (n: number) => String(n).padStart(2, '0');

/** Слот дня `day` (московский) в `hh:mm` МСК: UTC, местное, подпись фабрики. */
function slotAt(day: string, hh: number, mm = 0): S['SlotAt'] {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  const at = new Date(Date.UTC(y, m - 1, d, hh - MSK_H, mm));
  return {
    at: at.toISOString().replace('.000Z', 'Z'),
    local: `${day}T${pad(hh)}:${pad(mm)}:00+03:00`,
    label: `${day} ${pad(hh)}:${pad(mm)} МСК`,
    day,
  };
}

function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** «Сегодня» подставной фабрики по Москве (MOCK_NOW — 10.10 10:00 МСК). */
export const TODAY = '2026-10-10';

type ChannelSeed = {
  slot: S['SlotRule'] | null;
  /** День (от завтра, 0…) → кто занимает слот. */
  taken: Record<number, string>;
  occupants: S['Occupant'][];
  waiting: string[];
  pause: S['PauseRow'] | null;
  /** CC-0180: строки журнала, снятые из ленты в запас копилки. */
  withdrawn?: S['WithdrawnRow'][];
  /** CC-0180: строка журнала без пары в папке дня (`not_placed`). */
  journalOnly?: string[];
};

const reelDay = (n: number) => addDays(TODAY, n + 1);

/** «skyman-sequel» → «Skyman sequel» (тег карточки разложенного ролика). */
const readable = (slug: string) => {
  const t = slug.replace(/-/g, ' ');
  return t[0]!.toUpperCase() + t.slice(1);
};

function seeds(): Record<string, ChannelSeed> {
  return {
    [REEL]: {
      slot: { channel: REEL, times: ['01:00'], tz: 'Europe/Moscow', per_day: 1, lead_hours: 12 },
      taken: { 0: UPLOADED, 1: PLACED, 2: READY, 4: NOT_READY },
      occupants: [
        {
          slug: UPLOADED,
          day: reelDay(0),
          at: slotAt(reelDay(0), 1).at,
          sources: ['uploads.json:Qx7rT2mVb0c'],
        },
        {
          slug: PLACED,
          day: reelDay(1),
          at: slotAt(reelDay(1), 1).at,
          sources: [`publish/${REEL}/${reelDay(1)}/`, 'uploads.json:rJSXkLVswSs'],
        },
        { slug: READY, day: reelDay(2), at: null, sources: [`publish/${REEL}/${reelDay(2)}/`] },
        {
          slug: NOT_READY,
          day: reelDay(4),
          at: null,
          sources: [`publish/${REEL}/${reelDay(4)}/`],
        },
      ],
      waiting: [WAITING],
      pause: null,
    },
    [SCIENCE]: {
      // Как у живой фабрики 16.10: у ExampleScience слота публикации нет (и пауза с запуска).
      slot: null,
      taken: {},
      occupants: [],
      waiting: [],
      pause: {
        pause_id: 'pause-2026-10-08T1200Z',
        channel: SCIENCE,
        by: 'user',
        reason: 'канал ещё не запущен: оформление и первые ролики впереди',
        set_at: '2026-10-08T12:00:00Z',
        until: null,
        cleared_at: null,
        cleared_by: null,
        clear_note: null,
      },
    },
    // Как у живой фабрики 16.10: слот 01:00 МСК раз в день, три ролика подряд уже в YouTube
    // (загружены программой и ждут своего времени), четвёртый день свободен.
    [TECH]: {
      slot: { channel: TECH, times: ['01:00'], tz: 'Europe/Moscow', per_day: 1, lead_hours: 12 },
      taken: Object.fromEntries(TECH_QUEUE.map((slug, i) => [i, slug])),
      occupants: TECH_QUEUE.map((slug, i) => ({
        slug,
        day: reelDay(i),
        at: slotAt(reelDay(i), 1).at,
        sources: [`uploads.json:${TECH_VIDEO_IDS[i]}`],
      })),
      waiting: [],
      pause: null,
    },
  };
}

const describePause = (r: S['PauseRow']) =>
  `${r.by} ${r.set_at.slice(0, 16).replace('T', ' ')}: ${r.reason}` +
  (r.until ? ` (до ${r.until})` : ' (бессрочно)');

function settings(withLanguage: boolean) {
  return `- Не для детей.${withLanguage ? ' Язык: английский.' : ''} ИИ/синтетический контент: нет. Прямой рекламы нет. Снять «Автоматическое объяснение понятий».`;
}

function formOf(withLanguage: boolean): Record<string, S['FormField']> {
  const src = '## Настройки (publisher.settings)';
  return {
    made_for_kids: {
      value: false,
      studio: 'Нет, это видео не для детей',
      label: 'Аудитория',
      source: src,
    },
    altered_content: {
      value: false,
      studio: 'Нет',
      label: 'Использование ИИ / изменённый контент (в «Развернуть»)',
      source: src,
    },
    paid_promotion: {
      value: false,
      studio: 'Нет, в видео нет прямой рекламы',
      label: 'Платная реклама (в «Развернуть»)',
      source: src,
    },
    auto_concepts: {
      value: false,
      studio: 'снять галочку',
      label: '«Автоматическое объяснение понятий» (эксперимент, в «Развернуть»)',
      source: src,
    },
    language: withLanguage
      ? {
          value: 'английский',
          studio: null,
          label: 'Язык видео (в «Развернуть»)',
          source: src,
        }
      : {
          value: null,
          studio: null,
          label: 'Язык видео (в «Развернуть»)',
          source: src,
          ask_user: 'язык не назван в настройках канала — спросить пользователя',
        },
  };
}

const MONTHS = ['янв.', 'февр.', 'мар.', 'апр.', 'мая', 'июн.', 'июл.', 'авг.', 'сент.', 'окт.'];
const MONTHS_TAIL = ['нояб.', 'дек.'];

function schedule(day: string) {
  const at = slotAt(day, 1);
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  const month = [...MONTHS, ...MONTHS_TAIL][m - 1];
  return {
    publish_at: at.local,
    publish_at_utc: at.at,
    zone: 'Europe/Moscow',
    zone_offset: 'GMT+03:00',
    zone_label: '(GMT+03:00) Москва',
    date: day,
    date_picker_text: `${d} ${month} ${y} г.`,
    time: '01:00',
    msk: at.label,
    msk_day: day,
  };
}

type NoteSeed = {
  slug: string;
  day: string;
  title: string;
  description: string;
  tags: string[];
  ready: boolean;
  batch: string;
  /** CC-0127: состояние карточки (ruled — принята решением); нет — по `ready`. */
  card?: S['CardState'] | null;
  language?: boolean;
  uploaded?: string;
};

/** Батч, из которого ExampleFilm берёт ролики очереди (и карточку ждущего слота). */
export const REEL_BATCH = 'example-film/2026-10-09T0200Z';
/** Готовый к дефициту файл планировщика (отказ за нехваткой материала). */
export const DEFICIT = `pipeline/${REEL_BATCH}/plan.assetless-rung.json`;
/** Сценарии ротации ExampleFilm: стоит пара; уже был отказ; ждёт материала. */
export const SCRIPT_STANDING = 'lf-2026-10-09-001-script1';
export const SCRIPT_REJECTED = 'lf-2026-10-09-002-script1';
export const SCRIPT_HELD = 'lf-2026-10-07-002-script1';

/** Карточка ждущего слота ролика — какой она станет, когда ролик встанет в слот. */
const WAITING_SEED: Omit<NoteSeed, 'day'> = {
  slug: WAITING,
  title: 'Rapid & Reckless 11 Lost Its Date Again — Here Is Why #shorts',
  description:
    'Example Pictures moved Rapid & Reckless 11 to 2028 after the script was rewritten.\n\n#RapidAndReckless #ExamplePictures',
  tags: ['Rapid and Reckless', 'Example Pictures', 'release date'],
  ready: true,
  batch: REEL_BATCH,
};

const NOTE_SEEDS: NoteSeed[] = [
  {
    slug: PLACED,
    day: reelDay(1),
    title: 'Delver Was a $160 Million Bet on Tom Carver — It Opened to $8M #shorts',
    description:
      "Delver opened to just $8 million domestic and $20 million worldwide against a reported $160 million budget — Tom Carver's lowest opening in nineteen years, with a C+ CinemaScore.\n\nThe fact in this video comes from: Wikipedia, Delver (2026 film) — Casting: https://en.wikipedia.org/wiki/Delver_(2026_film)#Casting\n\n#Delver #TomCarver #BoxOffice",
    tags: ['Delver', 'Tom Carver', 'Alejandro G. Iñárritu', 'box office', 'CinemaScore'],
    ready: true,
    batch: 'rebuilds/2026-10-05T1427Z',
    uploaded: 'rJSXkLVswSs',
  },
  {
    slug: READY,
    day: reelDay(2),
    title: 'Vanguards: Doomsday Moved Again — The Date Zenith Picked Says a Lot #shorts',
    description:
      'Zenith moved Vanguards: Doomsday to December 18, 2026, five months later than first announced — the second shift for the film in a year.\n\nThe fact in this video comes from: Variety, «Vanguards: Doomsday» release date: https://variety.com/\n\n#Vanguards #Zenith #MCU',
    tags: ['Vanguards Doomsday', 'Zenith', 'MCU', 'release date', 'Russo brothers'],
    ready: true,
    batch: 'example-film/2026-10-09T0200Z',
    language: false,
  },
  {
    slug: NOT_READY,
    day: reelDay(4),
    title: 'Wren Hollow Series: The Casting Number Nobody Quoted #shorts',
    description:
      'Example Network saw over 32,000 audition tapes for the three leads of its Wren Hollow series.\n\n#WrenHollow #Example Network',
    tags: ['Wren Hollow', 'Example Network', 'casting'],
    ready: false,
    batch: 'example-film/2026-10-09T0200Z',
  },
];

function noteOf(seed: NoteSeed): S['PublishNote'] {
  const path = `publish/${REEL}/${seed.day}/${seed.slug}.md`;
  const [dir, id] = seed.batch.split('/') as [string, string];
  const form = formOf(seed.language !== false);
  const ask = seed.language === false ? ['language'] : [];
  const raw = [
    `# ${seed.slug} — к публикации`,
    '',
    `Файл: \`publish/${REEL}/${seed.day}/${seed.slug}.mp4\` (1080×1920) — батч \`pipeline/${seed.batch}\`.`,
    '',
    '## Название',
    seed.title,
    '',
    '## Описание',
    seed.description,
    '',
    '## Теги',
    seed.tags.join(', '),
    '',
    '## Публикация',
    `**${seed.day} 01:00 МСК**`,
    '',
    '## Настройки',
    settings(seed.language !== false),
    seed.ready ? '' : '\n<!-- publish-card: not_ready - описание без источника факта -->',
  ].join('\n');
  const studio: S['StudioFields'] | null = seed.ready
    ? {
        channel: REEL,
        slug: seed.slug,
        entry_id: `${REEL}:${id}:${seed.slug}`,
        note: path,
        video_file: `publish/${REEL}/${seed.day}/${seed.slug}.mp4`,
        file_name: `${seed.slug}.mp4`,
        title: seed.title,
        description: seed.description,
        tags: seed.tags,
        tags_input: seed.tags.join(', '),
        visibility: 'scheduled',
        visibility_studio: 'Запланировать',
        schedule: schedule(seed.day),
        form,
        ask_user: ask,
        notices: seed.uploaded
          ? [
              `уже загружен: uploads.json:${seed.uploaded} (youtube.com/shorts/${seed.uploaded}) - поля для сверки`,
            ]
          : [],
      }
    : null;
  return {
    channel: REEL,
    day: seed.day,
    slug: seed.slug,
    path,
    ready: seed.ready,
    card: seed.card ?? plainState(seed.ready),
    why: seed.ready ? null : 'описание без источника факта (CF-0412)',
    status: seed.ready ? 'ready' : 'not_ready',
    title: seed.title,
    description: seed.description,
    view: `${path}\n  ${seed.ready ? 'READY' : 'NOT READY'}  ${seed.title}\n  теги: ${seed.tags.length}`,
    form,
    ask_user: ask,
    studio,
    studio_refusal: seed.ready
      ? null
      : `${path}: карточка не готова (not_ready: описание без источника факта) - поля Studio не готовятся`,
    batch: {
      path: seed.batch,
      dir,
      batch_id: id,
      channel: REEL,
      slug: seed.slug,
      script_id: `lf-${id.slice(0, 10)}-001-script1`,
      topic_id: `lf-${id.slice(0, 10)}-001`,
      card_url: `/api/batches/${seed.batch}/videos/${seed.slug}/card`,
      videos_url: `/api/batches/${seed.batch}/videos`,
      error: null,
    },
    mark: seed.ready
      ? { status: 'ready' }
      : { status: 'not_ready', why: 'описание без источника факта' },
    raw,
  };
}

/** Холд content-sensitivity, который центр подписывает (`signable: true`): ролик delver из PAST. */
export const HOLD_SENSITIVE = { batch_id: '2026-10-09T0215Z', topic_id: 'lf-2026-10-09-007' };
/** Холд прав (`rights_check`): центр его не подписывает (`not_signable`). */
export const HOLD_RIGHTS = { batch_id: '2026-10-09T0200Z', topic_id: 'lf-2026-10-09-003' };
/** Холд, снятый раньше. */
export const HOLD_RESOLVED = { batch_id: '2026-10-02T0200Z', topic_id: 'lf-2026-10-02-001' };
/** CC-0170: Tech — снят правилом сцен (флаг на s2, в ролике s1). */
export const SCENE_RELEASED = { batch_id: '2026-10-08T0200Z', topic_id: 'tvtc-2026-10-08-006' };
/** CC-0170: Tech — снят правилом сцен и поставлен обратно (открыт, нужна подпись). */
export const SCENE_REOPENED = { batch_id: '2026-10-08T0200Z', topic_id: 'tvtc-2026-10-08-004' };
/** CC-0170: Tech — флаг на всей теме, снят подписью. */
export const WHOLE_TOPIC_HOLD = { batch_id: '2026-10-07T0200Z', topic_id: 'tvtc-2026-10-07-002' };

const HOLDS: S['HoldRow'][] = [
  {
    hold_id: 'hold-2026-10-09T0415Z-delver',
    channel: REEL,
    batch_id: '2026-10-09T0215Z',
    topic_id: 'lf-2026-10-09-007',
    script_id: 'delver-s1',
    verdict: 'hold',
    reason_code: 'content_sensitivity',
    reason_ru: null,
    reason: 'обвал в шахте: кадры с пострадавшими — посмотреть, не шокирует ли',
    raised_at: '2026-10-09T04:15:00Z',
    resolved_at: null,
    resolved_reason: null,
    signature: null,
    // CC-0170 (CF-0846): флаг стоит на двух сценах темы.
    content_sensitivity_check: {
      flagged: true,
      notes: 'кадры обвала с пострадавшими',
      scenes: ['lf-2026-10-09-007-s2', 'lf-2026-10-09-007-s3'],
    },
    sensitivity_scenes: ['lf-2026-10-09-007-s2', 'lf-2026-10-09-007-s3'],
  },
  {
    hold_id: 'hold-2026-10-09T0400Z-rapid-reckless-11',
    channel: REEL,
    batch_id: '2026-10-09T0200Z',
    topic_id: 'lf-2026-10-09-003',
    script_id: 'lf-2026-10-09-003-script1',
    verdict: 'hold',
    reason_code: 'rights_check',
    reason_ru: null,
    reason: 'клип студии в блоке 2: права на трейлер не подтверждены',
    raised_at: '2026-10-09T04:00:00Z',
    resolved_at: null,
    resolved_reason: null,
    signature: null,
  },
  {
    hold_id: 'hold-2026-10-02T0400Z-skyman-sequel',
    channel: REEL,
    batch_id: '2026-10-02T0200Z',
    topic_id: 'lf-2026-10-02-001',
    script_id: 'lf-2026-10-02-001-script1',
    verdict: 'hold',
    reason_code: 'fact_check',
    reason_ru: null,
    reason: 'дата выхода расходится у двух источников',
    raised_at: '2026-10-02T04:00:00Z',
    resolved_at: '2026-10-03T09:12:00Z',
    resolved_reason: 'источники сверены пользователем: дата верная',
    signature: { by: 'user', at: '2026-10-03T09:12:00Z' },
  },
  // CC-0170 (CF-0846): холды Tech, которые трогало правило сцен фабрики 2.29.
  {
    // Снят правилом сцен: флаг на s2, а ролик взял s1 — подпись не нужна.
    hold_id: 'hold-2026-10-08T0400Z-homepod',
    channel: TECH,
    batch_id: '2026-10-08T0200Z',
    topic_id: SCENE_RELEASED.topic_id,
    script_id: `${SCENE_RELEASED.topic_id}-script1`,
    verdict: 'hold',
    reason_code: 'content_sensitivity',
    reason_ru: null,
    reason: 'в сцене 2 — кадры пожара на складе',
    raised_at: '2026-10-08T04:00:00Z',
    resolved_at: '2026-10-09T03:00:00Z',
    resolved_reason: `flag on ${SCENE_RELEASED.topic_id}-s2; the video takes ${SCENE_RELEASED.topic_id}-s1 - no signature needed`,
    resolved_reason_code: 'flagged_scene_not_in_script',
    scene_release: {
      task: 'CF-0846',
      script_scenes: [`${SCENE_RELEASED.topic_id}-s1`],
      scripts: [`${SCENE_RELEASED.topic_id}-script1`],
      flagged_scenes: [`${SCENE_RELEASED.topic_id}-s2`],
      by: 'runlog scene-holds',
      batch_dir: 'pipeline/example-tech/2026-10-08T0200Z',
    },
    content_sensitivity_check: { flagged: true, scenes: [`${SCENE_RELEASED.topic_id}-s2`] },
    sensitivity_scenes: [`${SCENE_RELEASED.topic_id}-s2`],
    signature: null,
  },
  {
    // Снят правилом сцен и поставлен обратно: новый сценарий взял сцену с флагом — снова открыт.
    hold_id: 'hold-2026-10-08T0410Z-homeview',
    channel: TECH,
    batch_id: '2026-10-08T0200Z',
    topic_id: SCENE_REOPENED.topic_id,
    script_id: `${SCENE_REOPENED.topic_id}-script2`,
    verdict: 'hold',
    reason_code: 'content_sensitivity',
    reason_ru: null,
    reason: 'в сцене 2 — крупно лицо пострадавшего в ДТП',
    raised_at: '2026-10-08T04:10:00Z',
    resolved_at: null,
    resolved_reason: null,
    resolved_reason_code: null,
    scene_release: null,
    scene_release_reopened: {
      at: '2026-10-09T05:30:00Z',
      task: 'CF-0846',
      was: {
        task: 'CF-0846',
        script_scenes: [`${SCENE_REOPENED.topic_id}-s1`],
        scripts: [`${SCENE_REOPENED.topic_id}-script1`],
        flagged_scenes: [`${SCENE_REOPENED.topic_id}-s2`],
        by: 'runlog scene-holds',
        batch_dir: 'pipeline/example-tech/2026-10-08T0200Z',
      },
      why: 'a later round wrote a script on the flagged scene',
      script_scenes: [`${SCENE_REOPENED.topic_id}-s2`],
    },
    content_sensitivity_check: { flagged: true, scenes: [`${SCENE_REOPENED.topic_id}-s2`] },
    sensitivity_scenes: [`${SCENE_REOPENED.topic_id}-s2`],
    signature: null,
  },
  {
    // Флаг на всей теме: снят подписью из центра.
    hold_id: 'hold-2026-10-07T0400Z-chatgpt',
    channel: TECH,
    batch_id: '2026-10-07T0200Z',
    topic_id: WHOLE_TOPIC_HOLD.topic_id,
    script_id: `${WHOLE_TOPIC_HOLD.topic_id}-script1`,
    verdict: 'hold',
    reason_code: 'content_sensitivity',
    reason_ru: null,
    reason: 'тема о самоубийстве подростка после переписки с чат-ботом',
    raised_at: '2026-10-07T04:00:00Z',
    resolved_at: '2026-10-08T10:20:00Z',
    resolved_reason: 'посмотрел: без подробностей, источники — новости',
    content_sensitivity_check: { flagged: true },
    sensitivity_scenes: 'whole_topic',
    signature: {
      user: 'user',
      date: '2026-10-08T10:20:00Z',
      note: 'посмотрел: без подробностей, источники — новости',
      via: 'center',
    },
  },
];

/** `scene_holds.short_scene`: `<тема>-s2` → `s2`. */
const short = (scene: string, topic: string | null | undefined) =>
  topic && scene.startsWith(`${topic}-`) && scene.length > topic.length + 1
    ? scene.slice(topic.length + 1)
    : scene;

const strs = (v: unknown) =>
  Array.isArray(v) ? v.filter((x) => x != null).map((x) => String(x)) : [];

/** `publish._release`: что сняло холд или поставило обратно; null — ни то ни другое. */
function releaseOf(row: S['HoldRow']): S['HoldRelease'] | null {
  const topic = row.topic_id;
  const sr = row.scene_release ?? null;
  const ro = row.scene_release_reopened ?? null;
  const sig = (row.signature ?? null) as Record<string, unknown> | null;
  let base: Omit<
    S['HoldRelease'],
    'flagged_short' | 'script_short' | 'signature_needed' | 'line_ru'
  >;
  if (row.resolved_at) {
    base = {
      state: 'released',
      at: row.resolved_at,
      reason: row.resolved_reason ?? null,
      code: row.resolved_reason_code ?? null,
      by: sr?.by ?? null,
      task: sr?.task ?? null,
      flagged_scenes: strs(sr?.flagged_scenes),
      script_scenes: strs(sr?.script_scenes),
      scripts: strs(sr?.scripts),
    };
  } else if (ro && !sig?.user) {
    const now = row.sensitivity_scenes;
    base = {
      state: 'reopened',
      at: ro.at ?? null,
      reason: ro.why ?? null,
      code: null,
      by: ro.was?.by ?? null,
      task: ro.task ?? ro.was?.task ?? null,
      flagged_scenes: Array.isArray(now)
        ? [...now]
        : now === 'whole_topic'
          ? []
          : strs(ro.was?.flagged_scenes),
      script_scenes: strs(ro.script_scenes),
      scripts: strs(ro.was?.scripts),
    };
  } else return null;
  const fl = base.flagged_scenes.map((x) => short(x, topic));
  const sc = base.script_scenes.map((x) => short(x, topic));
  const line_ru =
    base.state === 'reopened'
      ? `Удержание снова стоит: флаг на ${fl.join(', ') || 'всей теме'}, в ролике ${sc.join(', ') || '?'}, нужна подпись`
      : base.code === 'flagged_scene_not_in_script'
        ? `Удержание снято: флаг на ${fl.join(', ') || '?'}, в ролике ${sc.join(', ') || '?'}, подпись не нужна`
        : `Удержание снято${base.reason ? `: ${base.reason}` : ''}`;
  return {
    ...base,
    flagged_short: fl,
    script_short: sc,
    signature_needed: base.state === 'reopened',
    line_ru,
  };
}

function rotationOf(channel: string): S['RotationReport'] {
  return {
    channel,
    eligible_pairs: ['moment-breakdown/hold', 'number-reveal/build', 'myth-check/turn'],
    blocked_pairs: { 'cast-reveal/hold': 'недостаточно материала (3 из 5 нужных шотов)' },
    blocked_by: ['cast-reveal/hold'],
    k_configured: 4,
    k_effective: 3,
    constrained: true,
    window: 12,
    assignments_total: 27,
    standing_total: 9,
    counts_in_window: {
      'moment-breakdown/hold': 4,
      'number-reveal/build': 5,
      'myth-check/turn': 3,
    },
    counts_outside_vocabulary: {},
    spread: 2,
    no_repeat_violations: [],
    rejections_upheld: 2,
    rejections_denied: 1,
    awaiting_material: [
      {
        script_id: 'lf-2026-10-07-002-script1',
        batch_id: '2026-10-07T0200Z',
        refused_at: '2026-10-07T05:30:00Z',
        state: 'waiting',
        assignable: false,
        retry_when: 'когда в пуле появятся шоты нового трейлера',
      },
    ],
    production_recoverable: {},
    production_awaiting: {},
    production_unrecorded: {},
  };
}

const CARDS = (): BatchCard[] => [
  {
    batch: REEL_BATCH,
    slug: WAITING,
    script_id: 'lf-2026-10-09-003-script1',
    ready: true,
    bucket: '_queue',
    placed: false,
  },
  {
    batch: REEL_BATCH,
    slug: READY,
    script_id: SCRIPT_STANDING,
    ready: true,
    bucket: reelDay(2),
    placed: true,
  },
  {
    batch: REEL_BATCH,
    slug: NOT_READY,
    script_id: SCRIPT_REJECTED,
    ready: false,
    bucket: reelDay(4),
    placed: true,
  },
  {
    batch: 'rebuilds/2026-10-05T1427Z',
    slug: PLACED,
    script_id: 'lf-2026-10-05-001-script1',
    ready: true,
    bucket: reelDay(1),
    placed: true,
  },
];

/** Журнал загрузок: ExampleFilm — один ролик через API (до аудита), один через Studio. */
/** Ролики Studio до серии (CC-0115 шаг 3): последний из них правили руками — серия с него. */
export const EDITED_VIDEO = 'pL0aWm1kQx2';
const studioRow = (slug: string, video_id: string, day: string): UploadRow => ({
  channel: REEL,
  slug,
  video_id,
  source: 'studio',
  publish_at: `${day}T15:00:00Z`,
  entry_id: null,
  recorded_at: `${day}T08:00:00Z`,
});

const UPLOADS = (): UploadRow[] => [
  studioRow('lost-city-trailer', 'aB3cD4eF5gH', '2026-09-20'),
  studioRow('monarch-legacy', 'kL6mN7oP8qR', '2026-09-25'),
  studioRow('sandfall-messiah-cast', 'sT9uV0wX1yZ', '2026-10-01'),
  {
    ...studioRow('last-of-us-s3', EDITED_VIDEO, '2026-10-03'),
    user_edited: true,
    user_edited_at: '2026-10-04T08:20:00Z',
    user_edit_note: 'поправил тег вручную',
  },
  {
    channel: REEL,
    slug: UPLOADED,
    video_id: 'Qx7rT2mVb0c',
    source: 'studio',
    publish_at: slotAt(reelDay(0), 1).at,
    entry_id: `${REEL}:2026-10-08T0200Z:${UPLOADED}`,
    recorded_at: '2026-10-09T08:00:00Z',
  },
  {
    channel: REEL,
    slug: PLACED,
    video_id: 'rJSXkLVswSs',
    source: 'studio',
    publish_at: slotAt(reelDay(1), 1).at,
    entry_id: `${REEL}:2026-10-05T1427Z:${PLACED}`,
    recorded_at: '2026-10-09T09:00:00Z',
  },
];

const ROWS = (): RotationRow[] => [
  {
    script_id: SCRIPT_STANDING,
    batch_id: '2026-10-09T0200Z',
    pattern_id: 'myth-check',
    rhythm_id: 'turn',
    seq: 25,
    rejection_verdict: null,
  },
  {
    script_id: SCRIPT_REJECTED,
    batch_id: '2026-10-09T0200Z',
    pattern_id: 'number-reveal',
    rhythm_id: 'build',
    seq: 27,
    rejection_verdict: null,
  },
];

/**
 * Батч ролика, вернувшегося в подставную копилку. Папка строки там всегда `<канал>/<батч>`, а карточка
 * может быть с пересборки (`rebuilds/…`, у `delver`), которой нет в подставных роликах: строка просила
 * бы несуществующий `example-film/<батч>` — на него берём батч канала.
 */
function pileBatch(note: S['PublishNote'] | undefined): string {
  const b = note?.batch;
  return b?.batch_id && b.dir !== 'rebuilds' ? b.batch_id : REEL_BATCH.split('/')[1]!;
}

/** Строка журнала, снятая из ленты (`upload_records.withdraw`, CF-0918). */
function withdrawnRow(
  c: string,
  w: { slug: string; day: string; at: string; videoId: string },
  batch: string,
  at: string,
): S['WithdrawnRow'] {
  return {
    slug: w.slug,
    video_id: w.videoId,
    url: `https://youtube.com/shorts/${w.videoId}`,
    batch_id: batch,
    note: `publish/${c}/_reserve/${w.slug}.md`,
    withdrawn: {
      at,
      by: 'user',
      via: 'center',
      task: 'CF-0918',
      from_at: w.at,
      from_day: w.day,
      from_note: `publish/${c}/${w.day}/${w.slug}.md`,
      studio: 'Ограниченный доступ',
    },
  };
}

export function createPublishBackend() {
  const ch = seeds();
  const notes = new Map(NOTE_SEEDS.map((s) => [`${s.day}/${s.slug}`, noteOf(s)]));
  /** CC-0183: батчи тёзок: заметки одного имени в одной папке; пусто — голого имени хватает. */
  const noteTwins = (c: string, slug: string, day: string | null) => {
    const hits = [...notes.values()].filter(
      (n) => n.channel === c && n.slug === slug && (!day || n.day === day),
    );
    return hits.length > 1 && new Set(hits.map((n) => n.day)).size === 1
      ? hits.map((n) => n.batch?.batch_id ?? '?')
      : [];
  };
  const state = {
    asOf: MOCK_NOW,
    /** Канал → строка отказа очереди (`publish_queue` не читается): 409 `queue_broken`. */
    queueBroken: {} as Record<string, string>,
    /** Отказ реестра холдов (`problem`): тогда списки пусты, каждый ролик держится. */
    holdsProblem: null as string | null,
    /** Снятые холды не читаются (`GET /holds/released` → `problem`), CC-0170. */
    releasedProblem: null as string | null,
    /** Журнала загрузок (publish/uploads.json) нет: `studio.journal_exists` — false (CC-0142). */
    journalMissing: false,
    holds: HOLDS.map((h) => ({ ...h })),
    notes,
    /** Какие адреса спрашивали (путь с запросом): тест видит, что экран ничего не пишет. */
    calls: [] as string[],
    /**
     * Канал есть в `channels/` (подставной список каналов — его подключают Vitest и Playwright),
     * но не в очередях публикации — например, только что созданный. Живая фабрика отвечает на
     * его ленту и паузу 200: слота нет, паузы нет, пусто (CC-0138).
     */
    elsewhere: (() => false) as (channel: string) => boolean,
  };
  function place(c: string, slug: string, day: string) {
    const s = ch[c]!;
    for (let i = 0; i < 14; i++) if (addDays(TODAY, i + 1) === day) s.taken[i] = slug;
    // CC-0183: `waiting` называет имя, пока в копилке лежит его тёзка.
    s.waiting = s.waiting.filter((x) => x !== slug || stash.twinNames(c).includes(x));
    s.occupants.push({ slug, day, at: null, sources: [`publish/${c}/${day}/`] });
    if (slug === WAITING) notes.set(`${day}/${slug}`, noteOf({ ...WAITING_SEED, day }));
  }
  /** Ролик копилки — в день ленты: папка дня и карточка с её состоянием. */
  function placeCard(
    c: string,
    slug: string,
    day: string,
    title: string,
    ready: boolean,
    card: S['CardState'] | null,
    batch?: string,
  ) {
    place(c, slug, day);
    if (batch) notes.delete(`_queue/${slug}~${batch}`);
    if (slug !== WAITING)
      notes.set(
        `${day}/${slug}`,
        noteOf({
          slug,
          day,
          title,
          description: `${title.replace(/ #shorts$/, '')}.\n\n#shorts`,
          tags: [readable(slug)],
          ready,
          batch: batch ? `batches/${batch}` : REEL_BATCH,
          card,
        }),
      );
  }
  const writes = createPublishWrites(
    {
      channels: CHANNELS,
      noRotation: [TECH],
      pauseOf: (c) => ch[c]?.pause ?? null,
      setPause: (c, row) => {
        ch[c]!.pause = row;
      },
      nextFree: (c) => {
        const s = slotsOf(c).find((x) => x.next_free);
        return s ? { at: s.at, label: s.label, day: s.day } : null;
      },
      place,
      now: () => state.asOf,
      // Как у живой фабрики: ExampleScience — канал-заглушка, пайплайна у него ещё нет.
      noPipeline: (c) =>
        c === SCIENCE ? 'канал-заглушка (channels/example-science.json: stub)' : null,
      noteOf: (c, slug, day, batch) =>
        [...notes.values()]
          .filter(
            (n) =>
              n.channel === c &&
              n.slug === slug &&
              (!day || n.day === day) &&
              (!batch || n.batch?.batch_id === batch),
          )
          .sort((a, b) => b.day.localeCompare(a.day))[0] ?? null,
      twinsOf: (c, slug, day) => noteTwins(c, slug, day),
      holds: () => state.holds,
      holdsProblem: () => state.holdsProblem,
      holdsOf: (c) => backendHolds(c),
      recorded: (row) => streakOf(row.channel),
    },
    { cards: CARDS(), rows: ROWS(), uploads: UPLOADS() },
  );
  // CC-0127: карточки без оператора — состояние, «Собрать заново», решение пользователя.
  const cards = createCards({ now: () => state.asOf, readOnly: () => writes.state.readOnly });
  /** CC-0180: ролик запаса снова на дне: строка журнала без `withdrawn`, журнал — в источниках. */
  const backOnDay = (c: string, slug: string, day: string, videoId: string, batch?: string) => {
    const s = ch[c]!;
    s.withdrawn = (s.withdrawn ?? []).filter(
      (w) => w.slug !== slug || (batch && w.batch_id !== batch),
    );
    s.waiting = s.waiting.filter((x) => x !== slug || stash.twinNames(c).includes(x));
    notes.delete(`_reserve/${slug}`);
    if (batch) notes.delete(`_reserve/${slug}~${batch}`);
    const o = s.occupants.find((x) => x.slug === slug && x.day === day);
    if (o) {
      o.at = slotAt(day, 1).at;
      o.sources.push(`uploads.json:${videoId}`);
    }
  };
  // CC-0122: копилка каналов — поверх той же ленты (разложенный ролик занимает день и карточку).
  const stash = createStash({
    cardOf: cards.cardOf,
    channels: CHANNELS,
    now: () => state.asOf,
    freeDays: (c) =>
      slotsOf(c)
        .filter((x) => !x.taken_by && Date.parse(x.at) >= Date.parse(state.asOf))
        .map((x) => ({ day: x.day, label: x.label, at: x.at })),
    paused: (c) => !!ch[c]?.pause,
    hasSlot: (c) => !!ch[c]?.slot,
    place: (c, slug, day, title, ready, card, batch) =>
      placeCard(c, slug, day, title, ready, card, batch),
    readOnly: () => writes.state.readOnly,
    returned: (c, slug, day, videoId, batch) => backOnDay(c, slug, day, videoId, batch),
  });
  // CC-0166: перенос размещённых роликов и возврат в копилку — поверх той же ленты и копилки.
  const dayIndex = (day: string) => {
    for (let i = 0; i < 400; i++) if (addDays(TODAY, i + 1) === day) return i;
    return -1;
  };
  const move = createMove({
    channels: CHANNELS,
    now: () => state.asOf,
    readOnly: () => writes.state.readOnly,
    hasSlot: (c) => !!ch[c]?.slot,
    placed: (c) =>
      Object.entries(ch[c]?.taken ?? {})
        .map(([i, slug]) => {
          const day = addDays(TODAY, Number(i) + 1);
          const o = ch[c]!.occupants.find((x) => x.slug === slug && x.day === day);
          const id = o?.sources.find((x) => x.startsWith('uploads.json:'));
          const note = notes.get(`${day}/${slug}`);
          const slot = slotAt(day, 1);
          return {
            slug,
            day,
            at: slot.at,
            label: slot.label,
            videoId: id ? id.slice('uploads.json:'.length) : null,
            batch: note?.batch?.batch_id ?? null,
          };
        })
        .sort((a, b) => a.day.localeCompare(b.day)),
    reserve: (c) =>
      (ch[c]?.withdrawn ?? []).map((w) => ({
        slug: w.slug!,
        videoId: w.video_id!,
        batch: w.batch_id ?? null,
      })),
    journalOnly: (c) => ch[c]?.journalOnly ?? [],
    horizon: () => stash.state.horizon,
    slotOf: (_c, day) => {
      const at = slotAt(day, 1);
      return { at: at.at, label: at.label };
    },
    apply: (c, moves, unplace, withdraw) => {
      const s = ch[c]!;
      const touched: string[] = [];
      const lifted = new Map<string, S['PublishNote'] | undefined>();
      const leaving = [
        ...unplace.map((u) => ({ slug: u.slug, from: u.day })),
        ...withdraw.map((w) => ({ slug: w.slug, from: w.day })),
        ...moves.flatMap((m) => (m.from ? [{ slug: m.slug, from: m.from }] : [])),
      ];
      for (const e of leaving) {
        const i = dayIndex(e.from);
        if (s.taken[i] === e.slug) delete s.taken[i];
        const key = `${e.from}/${e.slug}`;
        lifted.set(e.slug, notes.get(key));
        if (notes.delete(key))
          touched.push(
            `publish/${c}/${e.from}/${e.slug}.md`,
            `publish/${c}/${e.from}/${e.slug}.mp4`,
          );
      }
      for (const u of unplace) {
        const note = lifted.get(u.slug);
        s.occupants = s.occupants.filter((o) => !(o.slug === u.slug && o.day === u.day));
        stash.receive(c, {
          slug: u.slug,
          batch: pileBatch(note),
          title: note?.title ?? readable(u.slug),
          ready: note?.ready ?? true,
        });
        touched.push(`publish/${c}/_queue/${u.slug}.md`, `publish/${c}/_queue/${u.slug}.mp4`);
      }
      for (const w of withdraw) {
        const note = lifted.get(w.slug);
        const batch = pileBatch(note);
        s.occupants = s.occupants.filter((o) => !(o.slug === w.slug && o.day === w.day));
        stash.receive(c, {
          slug: w.slug,
          batch,
          title: note?.title ?? readable(w.slug),
          ready: note?.ready ?? true,
          videoId: w.videoId,
        });
        s.withdrawn = [...(s.withdrawn ?? []), withdrawnRow(c, w, batch, state.asOf)];
        if (note)
          notes.set(`_reserve/${w.slug}`, {
            ...note,
            day: '_reserve',
            // Строка журнала и заметка запаса называют один батч: адрес тёзки находит заметку.
            batch: note.batch ? { ...note.batch, batch_id: batch } : note.batch,
          });
        touched.push(
          'publish/uploads.json',
          `publish/${c}/_reserve/${w.slug}.md`,
          `publish/${c}/_reserve/${w.slug}.mp4`,
        );
      }
      for (const m of moves) {
        if (!m.from) {
          // CC-0180: из запаса — новой загрузки нет, журнал снова держит день.
          const seed = stash.take(c, m.slug, m.batch);
          const twin = seed?.tilde ? seed.batch : undefined;
          placeCard(c, m.slug, m.to, seed?.title ?? readable(m.slug), true, null, twin);
          backOnDay(c, m.slug, m.to, m.videoId!, twin);
          touched.push(
            'publish/uploads.json',
            `publish/${c}/${m.to}/${m.slug}.md`,
            `publish/${c}/${m.to}/${m.slug}.mp4`,
            `publish/${c}/_reserve/${m.slug}.md`,
            `publish/${c}/_reserve/${m.slug}.mp4`,
          );
          continue;
        }
        s.taken[dayIndex(m.to)] = m.slug;
        const o = s.occupants.find((x) => x.slug === m.slug && x.day === m.from);
        if (o) {
          o.day = m.to;
          if (o.at) o.at = slotAt(m.to, 1).at;
          o.sources = o.sources.map((x) => x.split(`/${m.from}/`).join(`/${m.to}/`));
          if (o.sources.some((x) => x.startsWith('uploads.json:')))
            touched.push('publish/uploads.json');
        }
        const note = lifted.get(m.slug);
        if (note) {
          const moved = JSON.parse(
            JSON.stringify(note).split(m.from).join(m.to),
          ) as S['PublishNote'];
          if (moved.studio) moved.studio.schedule = schedule(m.to);
          notes.set(`${m.to}/${m.slug}`, moved);
          touched.push(`publish/${c}/${m.to}/${m.slug}.md`, `publish/${c}/${m.to}/${m.slug}.mp4`);
        }
      }
      return [...new Set(touched)];
    },
  });
  // История переключателя API-загрузки (CC-0141): у ExampleFilm — три строки (сейчас выключена),
  // у ExampleScience и ExampleTech переключений не было.
  const reelSwitches = [
    {
      on: false,
      at: '2026-09-28T07:30:00Z',
      by: 'system',
      note: 'создан выключенным до аудита YouTube\u00a0API',
    },
    {
      on: true,
      at: '2026-10-02T09:12:00Z',
      by: 'user',
      note: 'пробная загрузка одного ролика',
      warnings: [...API_WARNINGS],
    },
    {
      on: false,
      at: '2026-10-03T16:45:00Z',
      by: 'user (центр)',
      note: 'вернул загрузку через Studio до аудита',
    },
  ];
  writes.state.switches[REEL] = { ...reelSwitches[2]!, history: reelSwitches };
  writes.state.deficits.add(DEFICIT);
  writes.state.awaiting.push({ script_id: SCRIPT_HELD, batch_id: '2026-10-07T0200Z' });
  writes.state.rejected.add(SCRIPT_REJECTED);

  /** Серия Studio без правок — из журнала загрузок, как `studio_fields.streak`. */
  const streakOf = (c: string): S['StudioStreak'] => studioStreak(writes.state.uploads, c);
  /**
   * Строки журнала загрузок этого канала (`studio.rows`, CC-0149): записи `state.uploads` и ролики
   * очереди, взятые из журнала (`uploads.json:<id>`). У подставной ExampleScience их нет — ноль.
   */
  const rowsOf = (c: string): number => {
    const ids = new Set(writes.state.uploads.filter((u) => u.channel === c).map((u) => u.video_id));
    for (const o of ch[c]?.occupants ?? [])
      for (const src of o.sources)
        if (src.startsWith('uploads.json:')) ids.add(src.slice('uploads.json:'.length));
    return ids.size;
  };

  /** Холды канала (null — всех), как их отдаёт GET: со `signable` и `sign_refusal`. */
  function backendHolds(c: string | null): S['PublicationHolds'] {
    const rows = state.holdsProblem
      ? []
      : state.holds.filter((h) => !c || h.channel === c).map((h) => ({ ...h, ...holdSignInfo(h) }));
    return {
      channel: c,
      path: 'publish/publication-holds.json',
      exists: true,
      problem: state.holdsProblem,
      open: rows.filter((h) => !h.resolved_at && !h.signature),
      rows,
    };
  }

  /** `publish.released_holds`: снятые (и снова поставленные) за `days` дней, новые первыми. */
  function backendReleased(c: string | null, days: number, limit: number): S['ReleasedHolds'] {
    const problem = state.holdsProblem ?? state.releasedProblem;
    const now = Date.parse(state.asOf);
    const since = now - days * 86_400_000;
    const found = (problem ? [] : state.holds)
      .filter((h) => !c || h.channel === c)
      .flatMap((h) => {
        const release = releaseOf(h);
        if (!release) return [];
        const at = release.at ? Date.parse(release.at) : NaN;
        if (!Number.isNaN(at) && at < since) return [];
        const row: S['ReleasedHold'] = { ...h, ...holdSignInfo(h), release };
        return [{ at, row }];
      })
      .sort((a, b) => (Number.isNaN(b.at) ? -1 : Number.isNaN(a.at) ? 1 : b.at - a.at));
    const iso = (t: number) => new Date(t).toISOString().replace('.000Z', 'Z');
    return {
      channel: c,
      path: 'publish/publication-holds.json',
      exists: true,
      problem,
      as_of: iso(now),
      since: iso(since),
      days,
      limit,
      total: found.length,
      released: found.filter((f) => f.row.release.state === 'released').length,
      reopened: found.filter((f) => f.row.release.state === 'reopened').length,
      holds: found.slice(0, limit).map((f) => f.row),
    };
  }

  const known = (raw: string) => (CHANNELS as readonly string[]).includes(raw);
  /** Канал из списка каналов, которого нет в очередях: пустая очередь без слота и паузы. */
  const adopted = (c: string) => {
    if (ch[c]) return true;
    if (!state.elsewhere(c)) return false;
    ch[c] = { slot: null, taken: {}, occupants: [], waiting: [], pause: null };
    return true;
  };
  const unknown = (c: string) =>
    problem(404, 'unknown_channel', `канала ${c} нет: channels/${c}.json не найден`);

  function head(c: string) {
    const s = ch[c]!;
    const pausedLine = s.pause ? describePause(s.pause) : null;
    const slots = slotsOf(c);
    const nextFree = slots.find((x) => x.next_free);
    const tomorrowSlot = slots[1];
    const tomorrow: S['Tomorrow'] = !s.slot
      ? {
          code: 2,
          state: 'error',
          line: `PUBLISH QUEUE ${c}: no publisher.slot - the channel has no queue`,
        }
      : s.pause
        ? {
            code: 3,
            state: 'paused',
            line: `PUBLISH QUEUE ${c}: PAUSED - ${pausedLine}; nothing is placed and tomorrow's slot stays empty`,
          }
        : tomorrowSlot?.taken_by
          ? {
              code: 0,
              state: 'ok',
              line: `ok   ${c}: ${tomorrowSlot.label} ${tomorrowSlot.taken_by}`,
            }
          : {
              code: 1,
              state: 'empty',
              line: `PUBLISH QUEUE ${c}: EMPTY SLOT ${tomorrowSlot?.label ?? ''}`,
            };
    return {
      channel: c,
      slot: s.slot,
      paused: pausedLine,
      pause_notices: [],
      tomorrow,
      next_free:
        s.slot && nextFree && !s.pause
          ? { at: nextFree.at, local: nextFree.local, label: nextFree.label, day: nextFree.day }
          : null,
      next_free_error: s.slot && s.pause ? `${c}: на паузе - свободный слот не ищется` : null,
      waiting: [...s.waiting],
    };
  }

  function slotsOf(c: string, days = 14): S['QueueSlot'][] {
    const s = ch[c]!;
    if (!s.slot) return [];
    const [hh, mm] = s.slot.times[0]!.split(':').map(Number) as [number, number];
    const out: S['QueueSlot'][] = [];
    let marked = false;
    // Как `publish_queue.table`: с сегодняшнего дня, и сегодняшний слот (уже прошедший) в ленте есть.
    for (let i = 0; i < days; i++) {
      const day = addDays(TODAY, i);
      const taken = i === 0 ? null : (s.taken[i - 1] ?? null);
      const slot = slotAt(day, hh, mm);
      const ahead = Date.parse(slot.at) >= Date.parse(state.asOf);
      const free = !taken && ahead && !s.pause && !marked;
      if (free) marked = true;
      out.push({ ...slot, taken_by: taken, next_free: free });
    }
    return out;
  }

  return {
    state,
    channels: ch,
    /** Записи без сети (CC-0068): токены, исходы «да», что записано. */
    writes,
    /** Копилка каналов (CC-0122): ролики, `not_queued`, токены и исходы её записей. */
    stash,
    /** Карточки без оператора (CC-0127): состояния, сборки, решения, токены. */
    cards,
    /** Перенос размещённых роликов и возврат в копилку (CC-0166): токены, исходы, что записано. */
    move,

    /**
     * Все свободные слоты ExampleFilm впереди заняты готовыми роликами-заполнителями с карточкой
     * в папке дня (тесты CC-0142: «пустых дней нет» без 404 на карточки). Возвращает их слаги.
     */
    fillReelDays(): string[] {
      const free = slotsOf(REEL).filter(
        (x) => !x.taken_by && Date.parse(x.at) >= Date.parse(state.asOf),
      );
      return free.map((x, i) => {
        const slug = `filler-${i + 1}`;
        place(REEL, slug, x.day);
        notes.set(
          `${x.day}/${slug}`,
          noteOf({
            slug,
            day: x.day,
            title: `Filler ${i + 1} #shorts`,
            description: `Filler ${i + 1}.\n\n#shorts`,
            tags: [readable(slug)],
            ready: true,
            batch: REEL_BATCH,
          }),
        );
        return slug;
      });
    },

    /**
     * Политика ленты 04.11 у ExampleFilm (CC-0180): горизонт на `days` дней (`READY` освобождает
     * последний день горизонта по умолчанию — есть куда раскладывать), новостные и бессрочные в
     * копилке, один ролик в запасе и его строка «Снято из ленты»; `noCard` — ещё свежая новость без
     * карточки, авто-раскладка её пропускает. Без этого вызова ответы — как у прежней фабрики.
     */
    feedPolicy({ days = 3, noCard = false }: { days?: number; noCard?: boolean } = {}) {
      const s = ch[REEL]!;
      stash.feedPolicy(REEL, { days, lastDay: addDays(TODAY, days), noCard });
      const freed = reelDay(2);
      delete s.taken[2];
      s.occupants = s.occupants.filter((o) => o.slug !== READY);
      notes.delete(`${freed}/${READY}`);
      // CF-0919: `waiting` называет и ролики запаса; заметка запаса читается с `day=_reserve`.
      if (!s.waiting.includes(STASH_RESERVE)) s.waiting = [...s.waiting, STASH_RESERVE];
      notes.set(`_reserve/${STASH_RESERVE}`, {
        ...noteOf({
          slug: STASH_RESERVE,
          day: '2026-10-09',
          title: STASH_TITLES[STASH_RESERVE]!,
          description: 'Sandfall Three.\n\n#shorts',
          tags: ['Sandfall Three'],
          ready: true,
          batch: 'batches/2026-09-24T0200Z',
        }),
        day: '_reserve',
      });
      s.withdrawn = [
        withdrawnRow(
          REEL,
          {
            slug: STASH_RESERVE,
            day: '2026-10-09',
            at: slotAt('2026-10-09', 1).at,
            videoId: STASH_RESERVE_ID,
          },
          '2026-09-24T0200Z',
          '2026-10-08T09:30:00Z',
        ),
      ];
    },

    /**
     * CC-0183 (фабрика CC-0182, CF-0920): поверх `feedPolicy` — тёзки: `TWIN` дважды в `_queue/`,
     * `TWIN_RESERVE` дважды в `_reserve/` (оба в «Снято из ленты»), у `PLACED` в ленте — тёзка в
     * `_queue/`. Заметки и карточки на голое имя тёзок в одной папке отвечают 409 `namesakes`, файлы
     * — `<имя>~<батч>`: забытый батч виден в тестах. Без этого вызова ответы — прежние.
     */
    /**
     * CC-0187 (фабрика CC-0186, CF-0921): в копилке ExampleFilm — два принятых, которых правило не
     * отличило от версии уже размещённого: новая версия `PLACED` (её прежняя — в ленте на завтра,
     * `other_why` «темы нет») и `OTHER_UNLINKED` (прежняя версия без `other_path`, причины нет —
     * только `queue_text_ru` с командой). Без вызова `other_version` пуст.
     */
    otherVersion() {
      stash.otherVersion(REEL, [
        {
          slug: PLACED,
          batch: OTHER_BATCH,
          title: OTHER_TITLE,
          accepted_at: '2026-10-09T19:00:00Z',
          other_entry: `${REEL}/2026-10-05T1427Z/${PLACED}`,
          other_path: `publish/${REEL}/${reelDay(1)}/${PLACED}.mp4`,
          other_why: UNSURE_NO_TOPIC,
        },
        {
          slug: OTHER_UNLINKED,
          batch: OTHER_BATCH,
          title: OTHER_UNLINKED_TITLE,
          accepted_at: '2026-10-09T19:30:00Z',
          other_entry: `${REEL}/${OTHER_UNLINKED_PLACED}/${OTHER_UNLINKED}`,
          other_path: null,
          other_why: null,
        },
      ]);
    },

    namesakes() {
      const s = ch[REEL]!;
      this.feedPolicy({ days: 5 });
      const placedTitle = notes.get(`${reelDay(1)}/${PLACED}`)!.title;
      stash.namesakes(REEL, PLACED, placedTitle);
      cards.state.twins.set(`${REEL}|${TWIN}`, [TWIN_OLD, TWIN_NEW]);
      s.waiting = [...new Set([...s.waiting, TWIN, TWIN_RESERVE, PLACED])];
      const pileNote = (
        slug: string,
        batch: string,
        folder: '_queue' | '_reserve',
        title: string,
      ) =>
        notes.set(`${folder}/${slug}~${batch}`, {
          ...noteOf({
            slug,
            day: '2026-10-09',
            title,
            description: `${cleanTitle(title)}.\n\n#shorts`,
            tags: [readable(slug)],
            ready: true,
            batch: `batches/${batch}`,
          }),
          day: folder,
          path: `publish/${REEL}/${folder}/${slug}~${batch}.md`,
        });
      for (const batch of [TWIN_OLD, TWIN_NEW]) {
        pileNote(TWIN, batch, '_queue', TWIN_TITLES[`${batch}/${TWIN}`]!);
        pileNote(TWIN_RESERVE, batch, '_reserve', TWIN_TITLES[`${batch}/${TWIN_RESERVE}`]!);
      }
      pileNote(PLACED, TWIN_OF_PLACED, '_queue', placedTitle);
      const twinRow = (batch: string, videoId: string, day: string): S['WithdrawnRow'] => ({
        ...withdrawnRow(
          REEL,
          { slug: TWIN_RESERVE, day, at: slotAt(day, 1).at, videoId },
          batch,
          '2026-10-08T09:30:00Z',
        ),
        note: `publish/${REEL}/_reserve/${TWIN_RESERVE}~${batch}.md`,
      });
      s.withdrawn = [
        ...(s.withdrawn ?? []),
        twinRow(TWIN_OLD, TWIN_RESERVE_OLD_ID, '2026-10-07'),
        twinRow(TWIN_NEW, TWIN_RESERVE_NEW_ID, '2026-10-08'),
      ];
    },

    /**
     * Ролик залит из батча `batch` (тесты CC-0088): строка ленты (папка дня и журнал загрузок)
     * и карточка дня, чей «Батч» — этот батч. Слоты ленты не трогает.
     */
    addUpload(
      c: string,
      u: { slug: string; day: string; videoId: string; batch: string; title: string },
    ) {
      ch[c]!.occupants.push({
        slug: u.slug,
        day: u.day,
        at: slotAt(u.day, 1).at,
        sources: [`publish/${c}/${u.day}/`, `uploads.json:${u.videoId}`],
      });
      notes.set(
        `${u.day}/${u.slug}`,
        noteOf({
          slug: u.slug,
          day: u.day,
          title: u.title,
          description: `${u.title}\n\n#shorts`,
          tags: ['shorts'],
          ready: true,
          batch: u.batch,
          uploaded: u.videoId,
        }),
      );
    },

    overview(): PublishReply<S['PublishOverview']> {
      return ok({
        as_of: state.asOf,
        channels: CHANNELS.map((c): S['QueueLine'] =>
          state.queueBroken[c]
            ? {
                channel: c,
                slot: null,
                paused: null,
                pause_notices: [],
                tomorrow: null,
                next_free: null,
                next_free_error: null,
                waiting: [],
                error: state.queueBroken[c],
              }
            : { ...head(c), error: null },
        ),
      });
    },

    queue(c: string, days = 14): PublishReply<S['ChannelQueue']> {
      if (!known(c) && !adopted(c)) return unknown(c);
      if (state.queueBroken[c])
        return problem(409, 'queue_broken', state.queueBroken[c], [
          `QueueError: ${state.queueBroken[c]}`,
        ]);
      return ok({
        ...head(c),
        as_of: state.asOf,
        days,
        journal: 'publish/uploads.json',
        slots: slotsOf(c, days),
        occupants: ch[c]!.occupants.map((o) => ({ ...o })),
        withdrawn: ch[c]!.withdrawn ?? [],
      });
    },

    pause(c: string): PublishReply<S['ChannelPause']> {
      if (!known(c) && !adopted(c)) return unknown(c);
      const row = ch[c]!.pause;
      return ok({
        channel: c,
        as_of: state.asOf,
        state: row ? 'paused' : 'free',
        line: row
          ? `${c}: публикации НА ПАУЗЕ - ${describePause(row)} (CF-0569)`
          : `${c}: публикации идут (паузы нет)`,
        row,
        open_row: row,
        history: row ? [row] : [],
        registry: 'publish/channel-pauses.json',
      });
    },

    apiUpload(c: string | null): PublishReply<S['ApiUpload']> {
      if (c && !known(c)) return unknown(c);
      const list = c ? [c] : [...CHANNELS];
      // Переключатель — тот же, что пишет запись (`writes.state.switches`).
      const views = writes.channelsSwitch(list);
      return ok({
        channel: c,
        path: SWITCH_PATH,
        channels: views,
        warnings: [...API_WARNINGS],
        warnings_error: null,
      });
    },

    rotation(c: string): PublishReply<S['ChannelRotation']> {
      if (!known(c)) return unknown(c);
      // Как у живой фабрики: у ExampleTech ротация не настроена — `rotate` отказывает.
      if (c === TECH)
        return problem(
          409,
          'rotation_broken',
          `channel '${TECH}': patterns.rotation is missing - K and the distribution window are channel settings`,
          ['RotationError: patterns.rotation is missing'],
        );
      return ok({ channel: c, ledger: 'rotation/ledger', report: rotationOf(c) });
    },

    studio(c: string): PublishReply<S['ChannelStudio']> {
      if (!known(c)) return unknown(c);
      return ok({
        channel: c,
        journal: 'publish/uploads.json',
        journal_exists: !state.journalMissing,
        rows: state.journalMissing ? 0 : rowsOf(c),
        streak: streakOf(c),
        withdrawn: ch[c]?.withdrawn ?? [],
      });
    },

    holds(c: string | null): PublishReply<S['PublicationHolds']> {
      if (c && !known(c)) return unknown(c);
      return ok(backendHolds(c));
    },

    released(c: string | null, days = 14, limit = 50): PublishReply<S['ReleasedHolds']> {
      if (c && !known(c)) return unknown(c);
      return ok(backendReleased(c, days, limit));
    },

    note(
      c: string,
      slug: string,
      day: string | null,
      batch: string | null = null,
    ): PublishReply<S['PublishNote']> {
      if (!known(c)) return unknown(c);
      // CC-0183 (CF-0920): два ролика одного имени в одной папке: голое имя — 409 с названными батчами.
      const twins = batch ? [] : noteTwins(c, slug, day);
      if (twins.length)
        return problem(409, 'namesakes', namesakesMessage(slug, twins), [
          `${slug}: ${twins.join(', ')}`,
        ]);
      const hits = [...state.notes.values()].filter(
        (n) =>
          n.channel === c &&
          n.slug === slug &&
          (!day || n.day === day) &&
          (!batch || n.batch?.batch_id === batch),
      );
      // CC-0167 (CF-0857): без дня у имени два места и больше — 404 с просьбой назвать день.
      if (!day && hits.length > 1)
        return problem(
          404,
          'unknown_note',
          `'${slug}': ${hits.length} places in publish/${c}/ (${hits
            .map((n) => n.day)
            .sort()
            .join(
              ', ',
            )}) not in the upload journal - name one (--day) - укажите день: папку, где лежит заметка (YYYY-MM-DD или _queue; в запросе поле day)`,
          [`publish/${c}/<day>/${slug}.md`],
        );
      const hit = hits[0];
      if (!hit)
        return problem(
          404,
          'unknown_note',
          `${slug}: no note in publish/${c}/${day ?? '<day>'}/ - name the note's path or its slug`,
          [`publish/${c}/${day ?? '<day>'}/${slug}.md`],
        );
      return ok(hit);
    },
  };
}

export type PublishBackend = ReturnType<typeof createPublishBackend>;

/**
 * Маршрутизация `/api/publish*`: чтение (GET) и записи (POST, `./publishWrites`); null — не
 * этот адрес или метод.
 */
export function routePublish(
  backend: PublishBackend,
  method: string,
  url: URL,
  body: unknown = null,
): PublishReply<unknown> | WriteReply | StashReply | CardsReply | MoveReply | null {
  const m = url.pathname.match(/\/api\/publish(?:\/(.*))?$/);
  if (!m) return null;
  const rest = (m[1] ?? '').split('/').map(decodeURIComponent);
  if (rest[1] === 'stash') return routeStash(backend.stash, method, rest, body);
  if (rest[1] === 'move') return routeMove(backend.move, method, rest, body);
  if (rest[1] === 'cards') return routeCards(backend.cards, method, rest, url.searchParams, body);
  if (method === 'POST') return routePublishWrite(backend.writes, rest, body);
  if (method !== 'GET') return null;
  backend.state.calls.push(url.pathname + url.search);
  const q = url.searchParams;
  if (!m[1]) return backend.overview();
  if (rest.length === 1 && rest[0] === 'holds') return backend.holds(q.get('channel'));
  if (rest.length === 2 && rest[0] === 'holds' && rest[1] === 'released')
    return backend.released(
      q.get('channel'),
      Number(q.get('days') ?? 14),
      Number(q.get('limit') ?? 50),
    );
  if (rest.length === 1 && rest[0] === 'api-upload') return backend.apiUpload(null);
  const [c, what, slug] = rest as [string, string | undefined, string | undefined];
  if (rest.length === 2) {
    if (what === 'queue') return backend.queue(c, Number(q.get('days') ?? 14));
    if (what === 'pause') return backend.pause(c);
    if (what === 'api-upload') return backend.apiUpload(c);
    if (what === 'rotation') return backend.rotation(c);
    if (what === 'studio') return backend.studio(c);
  }
  if (rest.length === 3 && what === 'notes' && slug)
    return backend.note(c, slug, q.get('day'), q.get('batch_id'));
  return null;
}
