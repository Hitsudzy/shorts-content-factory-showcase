// Подставная копилка каналов (CC-0122; фабрика CF-0738/CF-0746, договор 0.54.0): принятые
// ролики без слота в `publish/<канал>/_queue/` с подробностями (батч, когда принят, давность и
// «устарел» — старше 14 дней от даты новости, у вечнозелёных — от принятия, карточка, холд,
// превью) и `not_queued` — принятые, что в копилку не легли. Записи — как у фабрики: план ничего
// не пишет и даёт одноразовый токен на `life` секунд (120) только когда разложится каждый ролик;
// «да» берёт только `{confirm}`, токен сгорает при любом исходе, кроме `busy`. Размещение пачкой —
// по порядку на ближайшие свободные слоты ленты (`world.freeDays`), отказы по ролику — коды
// `publish_stash` (`duplicate`, `not_in_queue`, `held`, `no_card`, `card_not_ready`, `no_slot`).
// `state.next` — исход на выбор теста: `dirty` / `batch_open` (план без токена с отказом
// строкой), `commit_refused` (разложено, коммит не прошёл — 409), `busy`, `check_changed`.
// Импорты — относительные (общий для Vitest и Playwright).
// CC-0180 (договор 0.78.0, фабрика CF-0918/CF-0919): новостные и бессрочные, запас (снятые из ленты
// с `video_id`, `bucket: _reserve`), горизонт; план `{auto, force?}` — порядок фабрики (сначала свежие
// новости, потом бессрочные, столько, сколько берут свободные слоты в горизонте), что ждёт — в
// `skipped` с причиной, в том числе ролики без готовой карточки. По умолчанию ответ — как у прежней
// фабрики (всё бессрочное, горизонта нет); политика ленты включается `feedPolicy` — экраны прошлых
// задач видят прежний мир.
// CC-0183 (фабрика CC-0182, CF-0920): `namesakes` — два ролика одного имени в копилке (файл
// `<имя>~<батч>`): порядок `<батч>/<имя>`; голое имя двух роликов — `not_in_queue` с названными батчами.
// Ответы без этого вызова — прежние.
// CC-0187 (фабрика CC-0186, CF-0921): `otherVersion` — принятые, которых правило не отличило от версии
// уже размещённого ролика (`other_version`, `queue_code: other_version_placed`); без вызова — `[]`.
import type { components } from '../api/schema.gen';

type S = components['schemas'];

/** ExampleFilm: ждёт слота и держит холд (тот же ролик, что `WAITING` в ./publish). */
export const STASH_HELD = 'rapid-reckless-11';
/** ExampleFilm: устарел — новости 20 дней. */
export const STASH_STALE = 'skyman-sequel';
/** ExampleFilm: карточка не готова. */
export const STASH_NOT_READY = 'wicked-for-good';
/** ExampleFilm: принят, но в копилку не лёг. */
export const NOT_QUEUED = 'the-nightwatch-part-ii';
/** ExampleFilm (CC-0127): карточка собирается сама после приёмки — готова через два опроса. */
export const STASH_BUILDING = 'zootopia-2';
/** Политика ленты (CC-0180): новость по словам сценария — ещё свежая. */
export const STASH_FRESH_NEWS = 'gta-6-trailer';
/** Политика ленты (CC-0180): бессрочный, принят раньше других. */
export const STASH_EVERGREEN = 'cinema-history';
/** Политика ленты (CC-0180): бессрочный, снят из ленты — в запасе, уже в Studio. */
export const STASH_RESERVE = 'sandfall-three';
export const STASH_RESERVE_ID = 'Rs3rveV1d0x';
/** Политика ленты (CC-0180): свежая новость без карточки — авто-раскладка её пропускает. */
export const STASH_NO_CARD = 'avatar-four';

/** CC-0183: тёзки в `_queue/`: два ролика одного имени. */
export const TWIN = 'neon-rift';
/** CC-0183: тёзки в `_reserve/`: оба уже в Studio и в «Снято из ленты». */
export const TWIN_RESERVE = 'iron-tide';
export const TWIN_RESERVE_OLD_ID = 'Tw1nR3s0ld0';
export const TWIN_RESERVE_NEW_ID = 'Tw1nR3sn3w0';
/** CC-0183: батч старшего тёзки. */
export const TWIN_OLD = '2026-09-24T0200Z';
/** CC-0183: батч младшего тёзки. */
export const TWIN_NEW = '2026-10-09T0200Z';
/** CC-0183: батч тёзки в копилке у ролика, что стоит в ленте. */
export const TWIN_OF_PLACED = '2026-10-08T0200Z';
/** CC-0183: названия тёзок разные — тест видит, какой из них открылся. */
export const TWIN_TITLES: Record<string, string> = {
  [`${TWIN_OLD}/${TWIN}`]: 'Neon Rift: The First Cut #shorts',
  [`${TWIN_NEW}/${TWIN}`]: 'Neon Rift: The Studio Recut #shorts',
  [`${TWIN_OLD}/${TWIN_RESERVE}`]: 'Iron Tide: Part One #shorts',
  [`${TWIN_NEW}/${TWIN_RESERVE}`]: 'Iron Tide: Part Two #shorts',
};

/** CC-0187: причины правила фабрики (`acceptance.VERSION_UNSURE`). */
export const UNSURE_NO_TOPIC = 'темы нет в записи - новый ролик от версии не отличить';
export const UNSURE_NO_FACT = 'факта нет в записи - новый ролик от версии не отличить';
/** CC-0187: строка не положенной другой версии — что знает о ней ответ копилки. */
export type OtherVersionSeed = {
  slug: string;
  batch: string;
  title: string;
  accepted_at: string;
  other_entry: string;
  other_path: string | null;
  other_why: string | null;
};
/** CC-0187: `queue_text_ru` фабрики (`acceptance.QUEUE_RU[other_version_placed]`) — с командой. */
export const otherVersionText = (o: OtherVersionSeed, entry: string) =>
  `другая версия этого ролика уже размещена (${o.other_entry}; ${o.other_why ?? 'тот же сценарий'}) - эта в копилку не идёт (CF-0463). Если это новый ролик под старым именем: runlog acceptance --enqueue-accepted --entry ${entry} --other-version-ok --apply`;

/** CC-0183: сообщение отказа `namesakes` — по-русски, с названными батчами. */
export const namesakesMessage = (slug: string, batches: readonly string[]) =>
  `Под именем ${slug} в копилке два ролика: батчи ${batches.join(' и ')}. Назовите батч.`;

export type StashOutcome = 'dirty' | 'batch_open' | 'commit_refused' | 'busy' | 'check_changed';

export type StashReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: string; details: string[] } };

/** Что копилке нужно от остальной подставной публикации. */
export type StashWorld = {
  channels: readonly string[];
  now: () => string;
  /** Ближайшие свободные слоты канала впереди, по порядку: день, метка, ISO. */
  freeDays: (c: string) => { day: string; label: string; at: string }[];
  paused: (c: string) => boolean;
  hasSlot: (c: string) => boolean;
  /** Поставить ролик в день ленты (папка дня и карточка с её состоянием). */
  place: (
    c: string,
    slug: string,
    day: string,
    title: string,
    ready: boolean,
    card: S['CardState'] | null,
    /** CC-0183: батч тёзки; без него — батч подставной карточки по умолчанию. */
    batch?: string,
  ) => void;
  readOnly: () => boolean;
  /** CC-0127: состояние карточки ролика по учёту карточек (./cards); null — из готовности. */
  cardOf?: (c: string, slug: string) => S['CardState'] | null;
  /** CC-0180: ролик запаса разложен — строка журнала снова на дне, новой загрузки нет. */
  returned?: (c: string, slug: string, day: string, videoId: string, batch?: string) => void;
};

const STALENESS: S['StashStaleness'] = {
  rule: 'CF-0746',
  decided: '2026-10-13, пользователь',
  threshold_days: 14,
  stale_when: 'days > 14',
  basis:
    'от даты новости темы (самый свежий датированный источник); у вечнозелёных — от даты принятия',
  only_marks: true,
  note: 'устаревший ролик только помечается — разместить его можно',
};

const DAY_MS = 86_400_000;

/** Название без хвоста хэштегов (« #shorts») — как `title_clean` фабрики (CF-0750). */
export const cleanTitle = (t: string) => t.replace(/(?:\s+#[^\s#]+)+\s*$/u, '').trim();
const daysSince = (iso: string | null | undefined, now: string) =>
  iso ? Math.floor((Date.parse(now) - Date.parse(iso)) / DAY_MS) : null;

type Seed = {
  slug: string;
  batch: string;
  title: string;
  accepted_at: string;
  news_at: string | null;
  card: { present: boolean; ready: boolean | null; why_not: string | null };
  held?: string | null;
  in_queue?: boolean;
  queue_code?: string;
  queue_text_ru?: string;
  feed_kind?: 'news' | 'evergreen';
  news_why?: string | null;
  stale_at?: string | null;
  reserve?: boolean;
  video_id?: string | null;
  kind_mark?: S['StashKindMark'] | null;
  /** CC-0183: тёзка: файл в копилке называется `<имя>~<батч>`. */
  tilde?: boolean;
};

/** Название ролика (из карточки батча) — для карточки дня, когда его разложат. */
export const STASH_TITLES: Record<string, string> = {
  [STASH_HELD]: 'Rapid & Reckless 11 Lost Its Date Again — Here Is Why #shorts',
  [STASH_STALE]: 'Skyman Sequel: What Gunn Actually Confirmed #shorts',
  [STASH_NOT_READY]: 'Charmed: For Good — The Number Behind the Two-Part Plan #shorts',
  [NOT_QUEUED]: 'The Nightwatch Part II Slipped Again — The Real Reason #shorts',
  [STASH_BUILDING]: 'Zootopia 2: The Box Office Number Nobody Expected #shorts',
  [STASH_FRESH_NEWS]: 'GTA 6: The Trailer Date Everyone Is Waiting For #shorts',
  [STASH_EVERGREEN]: 'Why Cinemas Sell Popcorn: The Old Trick Still Works #shorts',
  [STASH_RESERVE]: 'Sandfall Three: How Villeneuve Shot the Desert Twice #shorts',
  [STASH_NO_CARD]: 'Avatar Four Moved Again: What Changed #shorts',
};

const REEL = 'example-film';

function seeds(): Record<string, { videos: Seed[]; notQueued: Seed[] }> {
  return {
    [REEL]: {
      videos: [
        {
          slug: STASH_HELD,
          batch: '2026-10-09T0200Z',
          title: STASH_TITLES[STASH_HELD]!,
          accepted_at: '2026-10-09T15:00:00Z',
          news_at: '2026-10-05T09:00:00Z',
          card: { present: true, ready: true, why_not: null },
          held: `${REEL}/2026-10-09T0200Z/lf-2026-10-09-003`,
        },
        {
          slug: STASH_STALE,
          batch: '2026-09-24T0200Z',
          title: STASH_TITLES[STASH_STALE]!,
          accepted_at: '2026-09-25T10:00:00Z',
          news_at: '2026-09-20T06:00:00Z',
          card: { present: true, ready: true, why_not: null },
        },
        {
          slug: STASH_NOT_READY,
          batch: '2026-10-09T0200Z',
          title: STASH_TITLES[STASH_NOT_READY]!,
          accepted_at: '2026-10-09T16:00:00Z',
          news_at: null,
          card: { present: true, ready: false, why_not: 'описание без источника факта' },
        },
        {
          slug: STASH_BUILDING,
          batch: '2026-10-09T0200Z',
          title: STASH_TITLES[STASH_BUILDING]!,
          accepted_at: '2026-10-10T06:50:00Z',
          news_at: null,
          card: { present: true, ready: false, why_not: null },
        },
      ],
      notQueued: [
        {
          slug: NOT_QUEUED,
          batch: '2026-10-08T0200Z',
          title: STASH_TITLES[NOT_QUEUED]!,
          accepted_at: '2026-10-08T12:00:00Z',
          news_at: '2026-10-07T08:00:00Z',
          card: { present: true, ready: true, why_not: null },
          in_queue: false,
          queue_code: 'placed',
          queue_text_ru: `Будет положен в копилку: publish/${REEL}/_queue/${NOT_QUEUED}.mp4`,
        },
      ],
    },
  };
}

function videoOf(
  c: string,
  s: Seed,
  now: string,
  st: S['CardState'] | null = null,
): S['StashVideo'] {
  const accepted_days = daysSince(s.accepted_at, now);
  const news_days = daysSince(s.news_at, now);
  const basis = s.news_at ? 'news' : s.accepted_at ? 'accepted' : null;
  const days = basis === 'news' ? news_days : basis === 'accepted' ? accepted_days : null;
  const dir = `${c}/${s.batch}`;
  const inQueue = s.in_queue !== false;
  const file = s.tilde ? `${s.slug}~${s.batch}` : s.slug;
  const folder = s.tilde && s.reserve ? '_reserve' : '_queue';
  return {
    slug: s.slug,
    channel: c,
    // CF-0750 (0.58.0): название карточки как есть (с « #shorts») и для показа — без хэштегов.
    title: s.title,
    title_source: 'card',
    title_clean: cleanTitle(s.title),
    entry_id: `${c}:${s.batch}:${s.slug}`,
    batch_id: s.batch,
    verdict: 'yes',
    kind: 'batch',
    batch_dir: `pipeline/${dir}`,
    accepted_at: s.accepted_at,
    recorded_at: s.accepted_at,
    pending: false,
    in_queue: inQueue,
    mp4: inQueue ? `publish/${c}/${folder}/${file}.mp4` : null,
    mp4_present: inQueue,
    source_mp4: `pipeline/${dir}/videos/${s.slug}.mp4`,
    thumbnail: `pipeline/${dir}/videos/${s.slug}.jpg`,
    card: {
      present: s.card.present,
      where: s.card.present ? (inQueue ? 'publish' : 'batch') : null,
      path: s.card.present
        ? inQueue
          ? `publish/${c}/${folder}/${file}.md`
          : `pipeline/${dir}/publish/${s.slug}.md`
        : null,
      // CC-0127: `ready` строгий (machine-ready), у ruled — false; решает `placeable`.
      ready: st ? st.state === 'ready' : s.card.ready,
      why_not: st ? (st.placeable ? null : (s.card.why_not ?? st.why ?? null)) : s.card.why_not,
      batch: dir,
      title: s.card.present ? s.title : null,
      title_clean: s.card.present ? cleanTitle(s.title) : null,
      ...(st
        ? {
            state: st.state,
            state_ru: st.state_ru ?? null,
            placeable: st.placeable,
            reasons: st.reasons ?? [],
            ruling: st.ruling ?? null,
            build: st.build ?? null,
          }
        : {
            state: !s.card.present ? 'none' : s.card.ready ? 'ready' : 'not_ready',
            placeable: s.card.ready === true,
          }),
    },
    feed_kind: s.feed_kind ?? 'evergreen',
    news_why: s.news_why ?? null,
    stale_at: s.stale_at ?? null,
    reserve: !!s.reserve,
    video_id: s.video_id ?? null,
    // CF-0919: папка ролика; `null` — ролика в копилке уже нет (`not_queued`).
    bucket: inQueue ? (s.reserve ? '_reserve' : '_queue') : null,
    kind_mark: s.kind_mark ?? null,
    held: !!s.held,
    hold_id: s.held ?? null,
    topic_id: null,
    age: {
      accepted_days,
      news_at: s.news_at,
      news_days,
      news_source: s.news_at ? '01 evidence.sources[].published_at' : 'нет датированных новостей',
      basis,
      days,
      stale: days == null ? null : days > 14,
    },
    mp4_url: `/api/batches/${dir}/videos/${s.slug}/mp4`,
    preview_url: `/api/batches/${dir}/videos/${s.slug}/preview`,
    videos_url: `/api/batches/${dir}/videos`,
    ...(inQueue
      ? {}
      : {
          queue_code: s.queue_code ?? null,
          queue_text_ru: s.queue_text_ru ?? null,
          repair: `python3 scripts/acceptance.py repair-queue --only ${c}:${s.batch}:${s.slug} --apply`,
        }),
  };
}

class Fault extends Error {
  readonly status: 404 | 409 | 422 | 500;
  readonly code: string;
  readonly details: string[];
  constructor(
    status: 404 | 409 | 422 | 500,
    code: string,
    message: string,
    details: string[] = [],
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const PLACE_RU: Record<string, string> = {
  duplicate: 'Ролик выбран дважды — второй раз пропущен.',
  not_in_queue: 'Ролика нет в копилке канала.',
  held: 'Ролик держит холд публикации — сначала его надо снять.',
  no_card: 'У ролика нет карточки к публикации.',
  card_building: 'Карточка ролика ещё собирается — разложить можно после сборки.',
  card_not_ready: 'Карточка ролика не готова',
  no_slot: 'Свободных слотов впереди не хватило.',
  dirty: 'В publish/ есть незакоммиченные правки — центр не смешивает их со своим коммитом.',
  batch_open: 'Идёт батч — копилку раскладывают, когда он закончится.',
};

/** Почему авто-раскладка оставила ролик ждать — сообщения центра (`SKIP_RU`). */
const SKIP_RU: Record<string, string> = {
  stale_news:
    'Новость устарела — сама в слот не идёт; поставить можно руками или авто-раскладкой с force.',
  beyond_horizon: 'В горизонте ленты не осталось свободных слотов — ролик ждёт в копилке.',
  no_card: 'У ролика нет карточки — соберите её, потом разложите.',
  card_building: 'Карточка ролика ещё собирается.',
  card_not_ready: 'Карточка ролика не готова.',
  note_differs: 'Карточка в копилке расходится с карточкой батча.',
};
const AUTO_EMPTY_RU =
  'Ставить нечего: подходящих роликов в копилке нет или в горизонте ленты нет свободных слотов (см. skipped).';

type Token = {
  action: 'place' | 'repair';
  channel: string;
  bound: unknown;
  fp: string;
  expires: number;
};

export function createStash(world: StashWorld) {
  const all = seeds();
  const piles = new Map<string, { videos: Seed[]; notQueued: Seed[] }>(
    world.channels.map((c) => [c, all[c] ?? { videos: [], notQueued: [] }]),
  );
  const tokens = new Map<string, Token>();
  let n = 0;
  const view = (c: string, s: Seed, now: string) =>
    videoOf(c, s, now, world.cardOf?.(c, s.slug) ?? null);
  const state = {
    piles,
    /** Исход следующего плана или «да» (одноразово). */
    next: null as StashOutcome | null,
    life: 120,
    /** CC-0180: горизонт канала; null — ответ прежней фабрики. */
    horizon: null as S['StashHorizon'] | null,
    /** CC-0187: не положенные как другая версия, по каналу. */
    other: new Map<string, OtherVersionSeed[]>(),
    calls: [] as {
      kind: 'get' | 'plan' | 'confirm';
      action: string;
      channel: string;
      body: unknown;
    }[],
    written: [] as { action: string; channel: string; order: unknown }[],
  };

  const pile = (c: string) => {
    if (!world.channels.includes(c)) throw new Fault(404, 'unknown_channel', `Канала ${c} нет.`);
    return piles.get(c)!;
  };

  function stash(c: string): StashReply {
    state.calls.push({ kind: 'get', action: 'stash', channel: c, body: null });
    try {
      const p = pile(c);
      const now = world.now();
      const videos = p.videos.map((s) => view(c, s, now));
      const body: S['PublishStash'] = {
        channel: c,
        task: 'CF-0738',
        now,
        count: videos.length,
        stale: videos.filter((v) => v.age.stale).length,
        news: videos.filter((v) => v.feed_kind === 'news').length,
        reserve: videos.filter((v) => v.reserve).length,
        horizon: state.horizon,
        videos,
        not_queued: p.notQueued.map((s) => view(c, s, now)),
        other_version: (state.other.get(c) ?? []).map((o) => otherOf(c, o, now)),
        staleness: STALENESS,
      };
      return { status: 200, body };
    } catch (e) {
      return fail(e);
    }
  }

  /** CC-0187: строка `other_version` — поля `StashVideo` не положенного ролика плюс версия. */
  function otherOf(c: string, o: OtherVersionSeed, now: string): S['StashOtherVersion'] {
    const v = videoOf(
      c,
      {
        slug: o.slug,
        batch: o.batch,
        title: o.title,
        accepted_at: o.accepted_at,
        news_at: null,
        card: { present: true, ready: true, why_not: null },
        in_queue: false,
      },
      now,
    );
    const entry = `${c}/${o.batch}/${o.slug}`;
    return {
      ...v,
      entry_id: entry,
      queue_code: 'other_version_placed',
      queue_text_ru: otherVersionText(o, entry),
      repair: `runlog acceptance --enqueue-accepted --entry ${entry} --other-version-ok --apply`,
      other_entry: o.other_entry,
      other_path: o.other_path,
      other_why: o.other_why,
    };
  }

  /** CC-0187: строки «похоже на другую версию» у канала. */
  const otherVersion = (c: string, rows: OtherVersionSeed[]) => {
    state.other.set(c, [...(state.other.get(c) ?? []), ...rows]);
  };

  function fail(e: unknown): StashReply {
    if (e instanceof Fault)
      return { status: e.status, body: { message: e.message, code: e.code, details: e.details } };
    throw e;
  }

  const refusal = (code: string, slug: string | null, line: string): S['StashRefusal'] => ({
    code,
    slug,
    line,
    message: PLACE_RU[code] ?? code,
  });

  const withinHorizon = (day: string) => !state.horizon || day <= state.horizon.last_day;

  /** Карточка не даёт поставить ролик (CF-0919): причина пропуска; null — можно. */
  const cardBlock = (v: S['StashVideo']) => {
    if (v.reserve) return null;
    if (!v.card.present) return 'no_card';
    if (v.card.state === 'building') return 'card_building';
    return v.card.placeable ? null : 'card_not_ready';
  };

  /** `choose` фабрики: свежие новости, затем бессрочные; что не влезло или без карточки — ждёт. */
  function choose(c: string, force: boolean) {
    const now = world.now();
    const all = pile(c).videos.map((s) => view(c, s, now));
    const stale = (v: S['StashVideo']) => v.feed_kind === 'news' && v.age.stale === true;
    const accepted = (v: S['StashVideo']) => String(v.accepted_at ?? '');
    const able = all.filter((v) => !cardBlock(v));
    const news = able
      .filter((v) => v.feed_kind === 'news' && (force || !stale(v)))
      .sort((a, b) => (a.age.news_at ?? accepted(a)).localeCompare(b.age.news_at ?? accepted(b)));
    const evergreen = able
      .filter((v) => v.feed_kind !== 'news')
      .sort((a, b) => accepted(a).localeCompare(accepted(b)));
    const picks = [...news, ...evergreen];
    // CC-0183: фабрика называет тёзку с батчем, остальных — как раньше, по имени.
    const twin = (v: S['StashVideo']) => all.filter((x) => x.slug === v.slug).length > 1;
    const orderOf = (v: S['StashVideo']) => (twin(v) ? `${v.batch_id}/${v.slug}` : v.slug);
    const room = world.freeDays(c).filter((d) => withinHorizon(d.day)).length;
    const skipped: S['StashSkipped'][] = [
      ...all.flatMap((v) => {
        const reason = cardBlock(v);
        return reason
          ? [
              {
                slug: v.slug,
                batch_id: v.batch_id,
                reason,
                line: `${v.slug}: ${reason} - ждёт в копилке`,
                message: SKIP_RU[reason]!,
              },
            ]
          : [];
      }),
      ...able
        .filter((v) => stale(v) && !force)
        .map((v) => ({
          slug: v.slug,
          batch_id: v.batch_id,
          reason: 'stale_news',
          line: `${v.slug}: новость устарела (${v.age.days} дн., CF-0741) - в слот только руками или с --force`,
          message: SKIP_RU.stale_news!,
        })),
      ...picks.slice(room).map((v) => ({
        slug: v.slug,
        batch_id: v.batch_id,
        reason: 'beyond_horizon',
        line: `${v.slug}: свободных слотов в горизонте ${state.horizon?.days} дн. (до ${state.horizon?.last_day}) не осталось - ждёт в копилке`,
        message: SKIP_RU.beyond_horizon!,
      })),
    ];
    return { order: picks.slice(0, room).map(orderOf), skipped };
  }

  /** `place_plan` фабрики: по порядку на ближайшие свободные слоты. */
  function placeCheck(c: string, order: string[]) {
    const p = pile(c);
    const now = world.now();
    const later = world.freeDays(c);
    const free = later.filter((d) => withinHorizon(d.day));
    const seen = new Set<string>();
    let taken = 0;
    const items: S['StashPlaceItem'][] = order.map((raw) => {
      const parts = raw.split('/');
      const slug = parts.at(-1)!;
      const batch = parts.at(-2);
      const twins = p.videos.filter((s) => s.slug === slug);
      const seed = twins.find((s) => !batch || s.batch === batch);
      const v = seed ? view(c, seed, now) : null;
      const base = {
        slug,
        batch_id: v?.batch_id ?? null,
        entry_id: v?.entry_id ?? null,
        stale: v?.age.stale ?? null,
        age_days: v?.age.days ?? null,
        age_basis: v?.age.basis ?? null,
        beyond_horizon: false,
        feed_kind: v?.feed_kind ?? null,
        stale_at: v?.stale_at ?? null,
        reserve: !!v?.reserve,
        video_id: v?.video_id ?? null,
        warnings: [] as string[],
      };
      if (v?.feed_kind === 'news' && v.age.stale)
        base.warnings.push(
          `STALE ${slug}: новость устарела (${v.age.days} дн., CF-0741) - ставится, потому что названа руками (CF-0918)`,
        );
      if (v?.reserve)
        base.warnings.push(
          `STUDIO ${slug} (${v.video_id}) comes back from the копилка: in Studio set «Отложенная публикация» on its slot (it stands at «Ограниченный доступ») - no new upload (CF-0918)`,
        );
      const no = (code: string, line: string) => ({
        ...base,
        ok: false,
        slot: null,
        day: null,
        label: null,
        refusals: [
          {
            ...refusal(code, slug, line),
            message:
              code === 'card_not_ready' && v?.card.why_not
                ? `${PLACE_RU[code]}: ${v.card.why_not}.`
                : (PLACE_RU[code] ?? code),
          },
        ],
      });
      // CC-0183: голое имя двух роликов не годится: `not_in_queue` с названными батчами.
      if (!batch && twins.length > 1) {
        const named = twins.map((s) => s.batch);
        const out = no('not_in_queue', `${slug}: two videos of the name: ${named.join(', ')}`);
        out.refusals[0]!.message = namesakesMessage(slug, named);
        return out;
      }
      const seenKey = seed ? `${seed.batch}/${slug}` : slug;
      if (seen.has(seenKey)) return no('duplicate', `${slug}: duplicate in the order`);
      seen.add(seenKey);
      if (!v) return no('not_in_queue', `${slug}: not in publish/${c}/_queue/`);
      if (v.held) return no('held', `${slug}: held by ${v.hold_id}`);
      if (!v.card.present) return no('no_card', `${slug}: no card`);
      if (v.card.state === 'building') return no('card_building', `${slug}: the card is building`);
      if (!v.card.placeable)
        return no('card_not_ready', `${slug}: card not_ready - ${v.card.why_not}`);
      const slot = free.shift();
      if (!slot && later.length > taken)
        return {
          ...no(
            'no_slot',
            `beyond_horizon: ${slug} - ближайший свободный слот ${later[taken]!.label} дальше горизонта канала`,
          ),
          beyond_horizon: true,
        };
      if (!slot) return no('no_slot', `${slug}: no free slot ahead`);
      taken += 1;
      return { ...base, ok: true, slot: slot.at, day: slot.day, label: slot.label, refusals: [] };
    });
    const refusals: S['StashRefusal'][] = [];
    if (state.next === 'dirty' || state.next === 'batch_open') {
      const code = state.next;
      refusals.push(
        refusal(
          code,
          null,
          code === 'dirty'
            ? ` M publish/${c}/_queue/${STASH_HELD}.md`
            : `pipeline/${c}/2026-10-10T0200Z: batch is running`,
        ),
      );
    }
    const lines = items.map((it) => {
      const tail = it.stale ? ` (устарел: ${it.age_days} дн.)` : '';
      return it.ok
        ? `${it.slug} -> ${it.label}${tail}`
        : `${it.slug}: REFUSED ${it.refusals[0]!.code}${tail}`;
    });
    const placed = items.filter((i) => i.ok).length;
    const ok = items.every((i) => i.ok) && !refusals.length;
    const why = refusals.length
      ? refusals[0]!.message
      : ok
        ? null
        : `Разложить можно ${placed} из ${items.length}: у остальных отказ — уберите их из выбора.`;
    return { ok, items, refusals, lines, placed, why };
  }

  /** План по названным или, с `auto`, по выбору фабрики; выбирать нечего — `empty_order`. */
  function placing(c: string, named: string[], auto: boolean, force: boolean) {
    const chosen = auto ? choose(c, force) : { order: named, skipped: [] };
    const out = placeCheck(c, chosen.order);
    const empty = auto && !chosen.order.length;
    const refusals = empty
      ? [{ code: 'empty_order', line: 'nothing to place', slug: null, message: AUTO_EMPTY_RU }]
      : out.refusals;
    return {
      auto,
      force: auto && force,
      order: chosen.order,
      skipped: chosen.skipped,
      ...out,
      refusals,
      ok: out.ok && !empty,
      why: empty ? AUTO_EMPTY_RU : out.why,
      lines: [...out.lines, ...chosen.skipped.map((x) => `ждёт: ${x.line}`)],
    };
  }

  function repairCheck(c: string, entries: string[] | null) {
    const p = pile(c);
    const rows = p.notQueued.filter(
      (s) => !entries || entries.includes(`${c}:${s.batch}:${s.slug}`),
    );
    const items: S['StashRepairItem'][] = rows.map((s) => ({
      entry_id: `${c}:${s.batch}:${s.slug}`,
      slug: s.slug,
      batch_id: s.batch,
      code: s.queue_code ?? 'placed',
      text_ru: s.queue_text_ru ?? null,
      ok: true,
      skipped: false,
      refused: false,
      changed: true,
      publish_path: `publish/${c}/_queue/${s.slug}.mp4`,
    }));
    const ok = items.length > 0;
    return {
      ok,
      entries: items.map((i) => i.entry_id!),
      items,
      refusals: [] as Record<string, unknown>[],
      lines: items.map((i) => `${i.slug}: ${i.code}`),
      sha256: 'sha256:acceptance-log',
      log: 'publish/acceptance-log.json',
      why: ok ? null : 'Докладывать нечего: все принятые ролики уже в копилке.',
    };
  }

  const fingerprint = (x: unknown) => JSON.stringify(x);

  const readOnly = () =>
    new Fault(
      409,
      'not_working_factory',
      'Только смотреть: рабочая копия на ветке cc-api, а не main',
      ['CC_API_WRITES is off'],
    );

  function plan(action: 'place' | 'repair', c: string, raw: unknown): StashReply {
    state.calls.push({ kind: 'plan', action, channel: c, body: raw });
    try {
      if (world.readOnly()) throw readOnly();
      pile(c);
      const b = (raw ?? {}) as {
        order?: string[];
        entries?: string[] | null;
        auto?: boolean;
        force?: boolean;
      };
      let out: Record<string, unknown> & { ok: boolean };
      if (action === 'place') {
        const named = b.order ?? [];
        const auto = b.auto === true;
        const force = b.force === true;
        if (auto && named.length)
          throw new Fault(422, 'invalid', 'Авто-раскладка выбирает сама: order должен быть пуст.', [
            'auto with a named order',
          ]);
        if (force && !auto)
          throw new Fault(422, 'invalid', 'force — только для авто-раскладки.', [
            'force without auto',
          ]);
        if (!auto && !named.length)
          throw new Fault(422, 'empty_order', 'Не выбран ни один ролик.', ['order is empty']);
        if (!world.hasSlot(c))
          throw new Fault(409, 'no_queue', `У канала ${c} нет слота публикации.`, []);
        if (world.paused(c))
          throw new Fault(409, 'paused', 'Публикации канала на паузе.', [`publish pause on ${c}`]);
        out = { ...placing(c, named, auto, force), base_sha256: `sha256:${c}-${n}` };
      } else out = repairCheck(c, b.entries ?? null);
      if (state.next === 'dirty' || state.next === 'batch_open') state.next = null;
      const fp = fingerprint(out.items);
      let confirm: string | null = null;
      if (out.ok) {
        confirm = `stash-${action}-${++n}`;
        tokens.set(confirm, {
          action,
          channel: c,
          bound: b,
          fp,
          expires: Date.now() + state.life * 1000,
        });
      }
      return {
        status: 200,
        body: {
          action: action === 'place' ? 'stash_place' : 'stash_repair',
          channel: c,
          dry_run: true,
          ...out,
          fingerprint: `sha256:${fp.length}-${n}`,
          confirm,
          expires_in_s: confirm ? state.life : null,
        },
      };
    } catch (e) {
      return fail(e);
    }
  }

  function confirm(action: 'place' | 'repair', c: string, raw: unknown): StashReply {
    state.calls.push({ kind: 'confirm', action, channel: c, body: raw });
    try {
      if (world.readOnly()) throw readOnly();
      const token = ((raw ?? {}) as { confirm?: string }).confirm ?? '';
      const got = tokens.get(token);
      if (!got)
        throw new Fault(409, 'confirm_unknown', 'Подтверждение не найдено или уже использовано.', [
          'no such confirm token',
        ]);
      const next = state.next;
      state.next = null;
      if (next === 'busy')
        throw new Fault(409, 'busy', 'Идёт другая запись публикации — подождите.', [
          'the publication write lock was not free in 30.0 s; the token is not spent',
        ]);
      tokens.delete(token);
      if (got.action !== action || got.channel !== c)
        throw new Fault(409, 'confirm_mismatch', 'Подтверждение выдано другому действию.', [
          `token of ${got.action} ${got.channel}`,
        ]);
      if (got.expires <= Date.now())
        throw new Fault(409, 'confirm_expired', 'Подтверждение устарело (живёт 120 с).', [
          'expired',
        ]);
      const b = got.bound as {
        order?: string[];
        entries?: string[] | null;
        auto?: boolean;
        force?: boolean;
      };
      if (action === 'repair') {
        const out = repairCheck(c, b.entries ?? null);
        if (next === 'check_changed' || fingerprint(out.items) !== got.fp)
          throw new Fault(409, 'check_changed', 'Записи приёмки изменились с момента плана.', []);
        const p = pile(c);
        const moved = p.notQueued.filter((s) => out.entries.includes(`${c}:${s.batch}:${s.slug}`));
        p.notQueued = p.notQueued.filter((s) => !moved.includes(s));
        p.videos.push(...moved.map((s) => ({ ...s, in_queue: true })));
        state.written.push({ action, channel: c, order: out.entries });
        const body: S['StashRepairResult'] = {
          action: 'stash_repair',
          channel: c,
          dry_run: false,
          ...out,
          ok: true,
          items: out.items.map((i) => ({ ...i, text_ru: `Положен в копилку: ${i.publish_path}` })),
          written: true,
          new_sha256: 'sha256:acceptance-log-2',
          commit: 'b7e1c0d4a9f2',
          by: 'user',
          via: 'center',
        };
        return { status: 200, body };
      }
      const out = placing(c, b.order ?? [], b.auto === true, b.force === true);
      const order = out.order;
      if (next === 'check_changed' || fingerprint(out.items) !== got.fp)
        throw new Fault(409, 'check_changed', 'Копилка или слоты изменились с момента плана.', [
          'the fingerprint of the plan differs',
        ]);
      const p = pile(c);
      const touched: string[] = [];
      for (const it of out.items) {
        const seed = p.videos.find((s) => s.slug === it.slug && s.batch === it.batch_id)!;
        const st = world.cardOf?.(c, it.slug) ?? null;
        p.videos = p.videos.filter((s) => s !== seed);
        world.place(
          c,
          it.slug,
          it.day!,
          seed.title,
          st ? st.placeable : seed.card.ready === true,
          st,
          seed.tilde ? seed.batch : undefined,
        );
        if (seed.reserve && world.returned) {
          world.returned(c, it.slug, it.day!, seed.video_id!, seed.tilde ? seed.batch : undefined);
          touched.push('publish/uploads.json');
        }
        touched.push(
          `publish/${c}/${it.day}/${it.slug}.md`,
          `publish/${c}/${it.day}/${it.slug}.mp4`,
          `publish/${c}/_queue/${it.slug}.md`,
          `publish/${c}/_queue/${it.slug}.mp4`,
        );
      }
      state.written.push({ action, channel: c, order });
      if (next === 'commit_refused')
        throw new Fault(
          409,
          'commit_refused',
          `Разложено ${out.placed}, но коммит не прошёл: правки остались в publish/${c}/ незакоммиченными.`,
          ['git commit: pre-commit hook refused (exit 1)', ...touched],
        );
      const body: S['StashPlaceResult'] = {
        action: 'stash_place',
        channel: c,
        ok: true,
        dry_run: false,
        auto: out.auto,
        force: out.force,
        order,
        skipped: out.skipped,
        items: out.items.map((i) => ({
          ...i,
          placed: true,
          path: `publish/${c}/${i.day}/${i.slug}.md`,
          report: [`${i.slug} -> ${i.label}`],
        })),
        refusals: [],
        lines: out.lines,
        base_sha256: `sha256:${c}`,
        placed: out.placed,
        written: true,
        new_sha256: `sha256:${c}-2`,
        touched,
        touched_from: 'factory',
        committed: touched,
        commit: '3f9a1c27e0b4d5a6',
        by: 'user',
        via: 'center',
      };
      return { status: 200, body };
    } catch (e) {
      return fail(e);
    }
  }

  /** Все токены устарели (как будто прошло 120 с). */
  const expireTokens = () => {
    for (const t of tokens.values()) t.expires = 0;
  };

  /** CC-0166: ролик вернули из папки дня в копилку — он снова ждёт слота. */
  const receive = (
    c: string,
    v: { slug: string; batch: string; title: string; ready: boolean; videoId?: string },
  ) => {
    const p = pile(c);
    p.videos = p.videos.filter((s) => s.slug !== v.slug || s.batch !== v.batch);
    const tilde = p.videos.some((s) => s.slug === v.slug);
    p.videos.push({
      ...(tilde ? { tilde } : {}),
      slug: v.slug,
      batch: v.batch,
      title: v.title,
      accepted_at: world.now(),
      news_at: null,
      card: {
        present: true,
        ready: v.ready,
        why_not: v.ready ? null : 'описание без источника факта',
      },
      // CC-0180: снятый из ленты — в запасе, уже в Studio.
      ...(v.videoId ? { reserve: true, video_id: v.videoId } : {}),
    });
  };

  /** CC-0180: ролик запаса вернулся переносом на день — из копилки уходит, название остаётся. */
  const take = (c: string, slug: string, batch?: string | null) => {
    const p = pile(c);
    const seed = p.videos.find((s) => s.slug === slug && (!batch || s.batch === batch));
    p.videos = p.videos.filter((s) => s !== seed);
    return seed;
  };

  /**
   * CC-0180: мир политики ленты 04.11 для тестов: горизонт на `days` дней от сегодня; новостные
   * (устаревшая и свежая, с `noCard` — ещё свежая без карточки), бессрочный и ролик запаса.
   * Вид — по словам заметки (CF-0919), `news_why` — эти слова как есть.
   */
  const feedPolicy = (
    c: string,
    { days = 3, lastDay, noCard = false }: { days?: number; lastDay: string; noCard?: boolean },
  ) => {
    state.horizon = { days, last_day: lastDay, source: `channels/${c}.json` };
    const seed = (s: Omit<Seed, 'card' | 'title'> & { card?: Seed['card'] }): Seed => ({
      card: { present: true, ready: true, why_not: null },
      title: STASH_TITLES[s.slug]!,
      ...s,
    });
    pile(c).videos = [
      seed({
        slug: STASH_STALE,
        batch: '2026-09-24T0200Z',
        accepted_at: '2026-09-25T10:00:00Z',
        news_at: '2026-09-20T06:00:00Z',
        feed_kind: 'news',
        news_why: '«сиквел покажут на следующей неделе»',
        stale_at: '2026-10-04',
      }),
      seed({
        slug: STASH_FRESH_NEWS,
        batch: '2026-10-09T0200Z',
        accepted_at: '2026-10-09T15:00:00Z',
        news_at: null,
        feed_kind: 'news',
        news_why: '«трейлер выйдет в ноябре»',
        stale_at: '2026-10-23',
      }),
      ...(noCard
        ? [
            seed({
              slug: STASH_NO_CARD,
              batch: '2026-10-08T0200Z',
              accepted_at: '2026-10-08T15:00:00Z',
              news_at: null,
              card: { present: false, ready: null, why_not: null },
              feed_kind: 'news',
              news_why: '«студия объявит дату на этой неделе»',
              stale_at: '2026-10-22',
            }),
          ]
        : []),
      seed({
        slug: STASH_EVERGREEN,
        batch: '2026-09-24T0200Z',
        accepted_at: '2026-10-02T10:00:00Z',
        news_at: null,
        kind_mark: { kind: 'evergreen', by: 'driver', at: '2026-10-02T11:00:00Z', task: 'CF-0919' },
      }),
      seed({
        slug: STASH_RESERVE,
        batch: '2026-09-24T0200Z',
        accepted_at: '2026-10-03T10:00:00Z',
        news_at: null,
        reserve: true,
        video_id: STASH_RESERVE_ID,
      }),
    ];
  };

  /**
   * CC-0183: тёзки: `TWIN` дважды в `_queue/` (старший — с не готовой карточкой), `TWIN_RESERVE`
   * дважды в `_reserve/`, а у `placed` (ролик ленты) — тёзка в `_queue/`.
   */
  const namesakes = (c: string, placed: string, placedTitle: string) => {
    const seed = (s: Omit<Seed, 'card' | 'news_at' | 'tilde'> & { card?: Seed['card'] }): Seed => ({
      card: { present: true, ready: true, why_not: null },
      news_at: null,
      tilde: true,
      ...s,
    });
    pile(c).videos.push(
      seed({
        slug: TWIN,
        batch: TWIN_OLD,
        title: TWIN_TITLES[`${TWIN_OLD}/${TWIN}`]!,
        accepted_at: '2026-09-26T10:00:00Z',
        card: { present: true, ready: false, why_not: 'описание без источника факта' },
      }),
      seed({
        slug: TWIN,
        batch: TWIN_NEW,
        title: TWIN_TITLES[`${TWIN_NEW}/${TWIN}`]!,
        accepted_at: '2026-10-09T17:00:00Z',
      }),
      seed({
        slug: TWIN_RESERVE,
        batch: TWIN_OLD,
        title: TWIN_TITLES[`${TWIN_OLD}/${TWIN_RESERVE}`]!,
        accepted_at: '2026-09-27T10:00:00Z',
        reserve: true,
        video_id: TWIN_RESERVE_OLD_ID,
      }),
      seed({
        slug: TWIN_RESERVE,
        batch: TWIN_NEW,
        title: TWIN_TITLES[`${TWIN_NEW}/${TWIN_RESERVE}`]!,
        accepted_at: '2026-10-09T18:00:00Z',
        reserve: true,
        video_id: TWIN_RESERVE_NEW_ID,
      }),
      seed({
        slug: placed,
        batch: TWIN_OF_PLACED,
        title: placedTitle,
        accepted_at: '2026-10-08T17:00:00Z',
      }),
    );
  };

  /** CC-0183: тёзки копилки дают `waiting` одно имя: мир отдаёт их, пока лежит хоть один. */
  const twinNames = (c: string) =>
    pile(c)
      .videos.filter((s) => s.tilde)
      .map((s) => s.slug);

  return {
    state,
    stash,
    plan,
    confirm,
    expireTokens,
    receive,
    take,
    feedPolicy,
    namesakes,
    twinNames,
    otherVersion,
  };
}

export type StashBackend = ReturnType<typeof createStash>;

/** `GET …/{c}/stash`, `POST …/{c}/stash/{place|repair}[/plan]`; null — не адрес копилки. */
export function routeStash(
  s: StashBackend,
  method: string,
  rest: string[],
  body: unknown,
): StashReply | null {
  const [c, what, action, last] = rest;
  if (!c || what !== 'stash') return null;
  if (method === 'GET' && rest.length === 2) return s.stash(c);
  if (method !== 'POST' || (action !== 'place' && action !== 'repair')) return null;
  if (rest.length === 4 && last === 'plan') return s.plan(action, c, body);
  if (rest.length === 3) return s.confirm(action, c, body);
  return null;
}
