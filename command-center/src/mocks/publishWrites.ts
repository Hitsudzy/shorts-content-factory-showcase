// Подставные записи публикации без сети (CC-0065 фабрики; договор 0.20.0): пауза (поставить,
// снять), карточка (разместить в слот, собрать из черновика) и ротация (назначить, отклонить,
// отказаться). Как у фабрики: план ничего не пишет и при «можно» даёт одноразовый токен на
// `life` секунд (120), «да» берёт только `{confirm}` — токен сгорает при любом исходе, кроме
// `busy`; токен другого действия или канала — `confirm_mismatch` (и тоже сгорел); план
// пересчитывается и сверяется с отпечатком (`check_changed`, или `refused`, если теперь нельзя).
// `state.next` — исход следующего «да» на выбор теста: `busy`, `check_changed`, `refused`,
// `factory_broken`. Записи меняют то, что потом читают GET-маршруты (пауза, лента, карточки).
//
// Записи за пределы машины (CC-0066 фабрики; экран — CC-0069): переключатель API-загрузки
// (включение — заметка в плане, иначе 422 `note_required`, и фраза «аудит подтверждаю» в «да»,
// иначе 422 `audit_unconfirmed` — токен уже сгорел), загрузка на YouTube (выключен
// переключатель — `why` строкой фабрики, токена нет; «да» — `{confirm, answer}`, ответ не «да» —
// 422 `answer_required` до траты токена; `state.uploadNext` — `reauthorize`, `upload_failed`,
// `uploaded_unrecorded`) и запись загрузки из Studio (сверка с карточкой — `mismatches`,
// `would-add|exists`). Ручки: `switchBroken` (409 `switch_unreadable`), `channelId` (пусто — нет
// токена), `readme` (нет `publish/README.md` — нет токена). Журнал загрузок — `state.uploads`.
//
// Подпись холда (CC-0070 фабрики; экран — CC-0071): `holds/{batch}/{topic}/sign[/plan]`. Как
// `publication_hold.check_sign`: подписать можно только открытый холд content-sensitivity,
// иначе план — 4xx с кодом (`no_such_hold`, `already_signed`, `already_resolved`,
// `not_signable`, `ledger_unreadable`; без заметки — 422 `empty_note`). «да» проверяет ещё раз
// (холд подписали в терминале — `already_signed`) и пишет `signature {user, date, note, via}`.
// Строки GET холдов несут `signable` и `sign_refusal` из той же проверки (`holdSignInfo`).
// Импорты — относительные (общий для Vitest и Playwright).
import type { components } from '../api/schema.gen';
import { namesakesMessage } from './stash';

type S = components['schemas'];

/** `<тема>-s2` → `s2` (`factory.short_scene`). */
export const shortScene = (scene: string, topic: string | null | undefined) =>
  topic && scene.startsWith(`${topic}-`) && scene.length > topic.length + 1
    ? scene.slice(topic.length + 1)
    : scene;
type Problem = S['PublishWriteProblem'];
type Code = Problem['code'] | 'not_working_factory';

export type WriteReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: Code; details: string[] } };

export type WriteAction =
  | 'pause_set'
  | 'pause_clear'
  | 'card_place'
  | 'card_build'
  | 'rotation_assign'
  | 'rotation_reject'
  | 'rotation_refuse'
  | 'api_upload_switch'
  | 'api_upload'
  | 'studio_record'
  | 'studio_edited'
  | 'studio_edited_undo'
  | 'hold_sign';

export type WriteOutcome = 'busy' | 'check_changed' | 'refused' | 'factory_broken';

/** Исход следующей загрузки на YouTube (одноразово): как отказывает `upload.run`. */
export type UploadOutcome = 'reauthorize' | 'upload_failed' | 'uploaded_unrecorded';

/** Слова, что включают API-загрузку (`publish_net.AUDIT_PHRASE`). */
export const AUDIT_PHRASE = 'аудит подтверждаю';
/** Вопрос перед ответом (`publish_net.QUESTION`). */
export const UPLOAD_QUESTION = 'Загрузить этот ролик? Введите «да»';
/** Условия YouTube перед ответом (`upload_gate.TOS_NOTICE`, CF-0618) — по смыслу, не дословно. */
export const TOS_NOTICE =
  'Загружая ролик, вы подтверждаете, что у вас есть права на всё, что в нём есть, и что он соблюдает Условия использования YouTube и правила сообщества.';

/** Строка журнала загрузок (`publish/uploads.json`): чем грузили и какой id дал YouTube. */
export type UploadRow = {
  channel: string;
  slug: string;
  video_id: string;
  source: 'api' | 'studio';
  publish_at: string | null;
  entry_id: string | null;
  recorded_at: string;
  /** Ручная правка в Studio (`upload_records.mark_user_edited`, CF-0018). */
  user_edited?: boolean;
  user_edited_at?: string;
  user_edit_note?: string;
  user_edited_by?: string;
  user_edited_via?: string;
  /** Строка снята (замена ролика): по slug её не ищут. */
  removed_at?: string | null;
};

/** Цель серии Studio без правок (`studio_fields.STREAK_GOAL`). */
export const STREAK_GOAL = 5;

/** `studio_fields.streak`: ролики Studio по порядку записи и сколько последних подряд без правок. */
export function studioStreak(rows: readonly UploadRow[], c: string): S['StudioStreak'] {
  const mine = rows
    .filter((r) => r.source === 'studio' && r.channel === c)
    .sort((a, b) =>
      a.recorded_at === b.recorded_at
        ? a.slug.localeCompare(b.slug)
        : a.recorded_at.localeCompare(b.recorded_at),
    );
  let n = 0;
  for (let i = mine.length - 1; i >= 0 && !mine[i]!.user_edited; i--) n++;
  const last = [...mine].reverse().find((r) => r.user_edited);
  return {
    streak: n,
    goal: STREAK_GOAL,
    studio_videos: mine.length,
    done: n >= STREAK_GOAL,
    run: mine.slice(mine.length - n).map((r) => r.slug),
    last_edited: last
      ? {
          slug: last.slug,
          video_id: last.video_id,
          at: last.user_edited_at ?? null,
          note: last.user_edit_note ?? null,
        }
      : null,
  };
}

/** Переключатель API-загрузки канала — то, что пишет `api_switch.set_switch`. */
export type SwitchRow = { on: boolean; at: string | null; by: string | null; note: string | null };
/** Строка истории переключателя: с тем, о чём предупредило включение. */
export type SwitchHistoryRow = SwitchRow & { warnings?: string[] };

class Fault extends Error {
  readonly status: 404 | 409 | 422 | 500;
  readonly code: Code;
  readonly details: string[];
  constructor(status: 404 | 409 | 422 | 500, code: Code, message: string, details: string[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const fault = (e: Fault): WriteReply => ({
  status: e.status,
  body: { message: e.message, code: e.code, details: e.details },
});

/** Карточка ролика в батче (`work/publish-card/<slug>.md`) и где лежит сам ролик в publish/. */
export type BatchCard = {
  batch: string;
  slug: string;
  script_id: string;
  /** null — карточки в батче нет. */
  ready: boolean | null;
  /** Папка ролика в publish/<channel>/: день или `_queue`; null — ролика там нет. */
  bucket: string | null;
  /** Заметка уже лежит рядом с роликом. */
  placed: boolean;
};

export type RotationRow = {
  script_id: string;
  batch_id: string;
  pattern_id: string;
  rhythm_id: string;
  seq: number;
  rejection_verdict: string | null;
};

/** Что бэкенд публикации отдаёт записям: каналы, ленту и как поставить ролик в слот. */
export type WriteWorld = {
  channels: readonly string[];
  /** Канал без ротации (`patterns.rotation` нет): любой план ротации — 409 `rotation_broken`. */
  noRotation: readonly string[];
  pauseOf: (c: string) => S['PauseRow'] | null;
  setPause: (c: string, row: S['PauseRow'] | null) => void;
  /** Ближайший свободный слот канала: `{at, label, day}` или null. */
  nextFree: (c: string) => { at: string; label: string; day: string } | null;
  /** Ролик из `_queue/` встал в слот дня `day`. */
  place: (c: string, slug: string, day: string) => void;
  now: () => string;
  /** Канал-заглушка без пайплайна (`api_switch.no_pipeline`): строка почему, иначе null. */
  noPipeline: (c: string) => string | null;
  /** Заметка к публикации (`studio_fields.locate`): последняя по имени или за день `day`. */
  noteOf: (
    c: string,
    slug: string,
    day: string | null,
    batch?: string | null,
  ) => S['PublishNote'] | null;
  /** CC-0183: батчи тёзок одной папки; пусто — голого имени хватает. */
  twinsOf?: (c: string, slug: string, day: string | null) => string[];
  /** Строка журнала из Studio легла: серия канала после неё. */
  recorded: (row: UploadRow) => S['StudioStreak'];
  /** Строки реестра холдов (живой массив: подпись пишется в строку). */
  holds: () => S['HoldRow'][];
  /** Реестр холдов не читается: строка ошибки, иначе null. */
  holdsProblem: () => string | null;
  /** Холды канала, как их отдаёт GET (со `signable`). */
  holdsOf: (c: string) => S['PublicationHolds'];
};

/** Причина холда, который центр может подписать (`publication_hold.SIGNABLE_REASONS`). */
export const SIGNABLE_REASON = 'content_sensitivity';

/** Отказы подписи (`HoldSignError`, CF-0687): строка фабрики по-русски и по-английски. */
const SIGN_REFUSALS = {
  no_such_hold: [
    404,
    'Такого холда в реестре нет — может, его id набран с ошибкой.',
    'no such hold',
  ],
  already_signed: [
    409,
    'Холд уже подписан — второй раз подписывать нечего.',
    'the hold is already signed',
  ],
  already_resolved: [409, 'Холд уже снят — подписывать нечего.', 'the hold is already resolved'],
  not_signable: [
    409,
    'Этот холд — не про чувствительность контента: центр его не подписывает, снимает человек в терминале.',
    'only a content-sensitivity hold is signed from the center',
  ],
  empty_user: [422, 'Не записано, кто подписывает.', 'empty user'],
  empty_note: [
    422,
    'Подпись — с заметкой: напишите, почему ролик можно публиковать.',
    'a signature needs a note',
  ],
  ledger_unreadable: [
    409,
    'Реестр холдов не читается — пока его не починят, подписывать нельзя.',
    'the hold ledger does not read',
  ],
} as const satisfies Record<
  S['HoldSignRefusal']['code'],
  readonly [404 | 409 | 422, string, string]
>;

type SignCode = keyof typeof SIGN_REFUSALS;

const signRefusal = (code: SignCode): S['HoldSignRefusal'] => ({
  code,
  text_ru: SIGN_REFUSALS[code][1],
  text: SIGN_REFUSALS[code][2],
});

/** Почему строку холда центр не подпишет (без заметки), или null — подпишет. */
function signCodeOf(row: S['HoldRow'] | undefined, problem: string | null): SignCode | null {
  if (problem) return 'ledger_unreadable';
  if (!row) return 'no_such_hold';
  if (row.signature) return 'already_signed';
  if (row.resolved_at) return 'already_resolved';
  if (row.reason_code !== SIGNABLE_REASON) return 'not_signable';
  return null;
}

/** `signable` и `sign_refusal` строки холда — как их добавляет GET `/api/publish/holds`. */
export function holdSignInfo(row: S['HoldRow'], problem: string | null = null) {
  const code = signCodeOf(row, problem);
  return { signable: code == null, sign_refusal: code ? signRefusal(code) : null };
}

/** Что отметил compliance-checker в строке ролика (у подставного — по причине холда). */
const COMPLIANCE: Record<string, { sensitivity: string; rights: string }> = {
  content_sensitivity: {
    sensitivity: 'отмечено: в блоке 3 — кадры обвала с пострадавшими, крупно',
    rights: 'права подтверждены: кадры из пресс-кита студии',
  },
};

/** Что не готово, если включить API-загрузку (`api_switch.warnings`); не отказ. */
export const API_WARNINGS = [
  'OAuth-приложение в режиме Testing (PUBLISHER_OAUTH_MODE=testing): пока аудит не пройден, загруженные ролики видны только владельцу',
  'токен: refresh-токен истекает 2026-10-15 (через 5 дней) - обновить: python3 agents/publisher/oauth.py refresh',
];
export const SWITCH_PATH = 'schedule/api-upload.json';

const words = (t: unknown) =>
  String(t ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/ё/g, 'е');

/** Строка `api_switch.channel_state`. */
export function switchLine(c: string, row: SwitchRow | undefined, broken: string | null): string {
  if (broken) return `API-загрузка: ${SWITCH_PATH} не читается (${broken}) - считаю ВЫКЛЮЧЕННОЙ`;
  if (row?.on)
    return `API-загрузка ${c} ВКЛЮЧЕНА (${row.by} ${row.at?.slice(0, 16)}Z): upload.py грузит после «да»; Studio-путь - запасной`;
  const was = row?.at ? `${row.by} ${row.at.slice(0, 16)}Z` : 'не включалась';
  return `API-загрузка ${c} ВЫКЛЮЧЕНА (${was}): ждёт аудита YouTube API (CF-0470); публикация - через Studio`;
}

const normTitle = (t: unknown) =>
  String(t ?? '')
    .replace(/\s+/g, ' ')
    .trim();
const normText = (t: unknown) =>
  String(t ?? '')
    .normalize('NFC')
    .replace(/\r\n?/g, '\n')
    .replace(/[\u00a0\u202f\u2007]/g, ' ')
    .replace(/[\u200b-\u200d\u2060\ufeff]/g, '')
    .split('\n')
    .map((l) => l.trimEnd())
    .join('\n')
    .trim()
    .replace(/\n{3,}/g, '\n\n');
const normTags = (t: unknown) =>
  (Array.isArray(t) ? t.map(String) : String(t ?? '').split(','))
    .map((x) => x.trim())
    .filter(Boolean);
const SCHEDULED = new Set(['scheduled', 'schedule', 'запланировать', 'запланировано']);
const mskOf = (ms: number) =>
  new Date(ms + 3 * 3600_000).toISOString().slice(0, 16).replace('T', ' ') + ' МСК';

export type StudioMismatch = { field: string; expected: unknown; read: unknown };

/** `studio_fields.compare`: что Studio показывает не так, как в карточке. */
export function compareStudio(
  f: S['StudioFields'],
  read: Record<string, unknown>,
): StudioMismatch[] {
  const out: StudioMismatch[] = [];
  const miss = (field: string, expected: unknown, got: unknown) =>
    out.push({ field, expected, read: got });
  if (normTitle(read.title) !== normTitle(f.title)) miss('title', f.title, read.title ?? null);
  const exp = normText(f.description);
  const got = normText(read.description);
  if (got !== exp) miss('description', exp.slice(0, 60), got.slice(0, 60));
  if (!('tags' in read)) miss('tags', f.tags, null);
  else {
    const e = normTags(f.tags);
    const g = normTags(read.tags);
    if (e.join('\n') !== g.join('\n'))
      miss(
        'tags',
        {
          missing: e.filter((t) => !g.includes(t)),
          extra: g.filter((t) => !e.includes(t)),
          order: e,
        },
        g,
      );
  }
  if (!SCHEDULED.has(normTitle(read.visibility).toLowerCase()))
    miss('visibility', f.visibility_studio, read.visibility ?? null);
  const sched = f.schedule as { publish_at: string; msk: string };
  const at = typeof read.publish_at === 'string' ? Date.parse(read.publish_at) : NaN;
  if (Number.isNaN(at)) miss('publish_at', sched.msk, 'время не прочитано (нет publish_at)');
  else if (at !== Date.parse(sched.publish_at)) miss('publish_at', sched.msk, mskOf(at));
  return out;
}

const MIN_REASON = 25;
const FROM_CENTER = 'из центра';
const marked = (t: string | null | undefined) => {
  const s = (t ?? '').trim();
  return s ? `${s} (${FROM_CENTER})` : FROM_CENTER;
};

export function createPublishWrites(
  world: WriteWorld,
  seed: { cards: BatchCard[]; rows: RotationRow[]; uploads?: UploadRow[] },
) {
  const tokens = new Map<
    string,
    { action: WriteAction; channel: string; bound: unknown; fp: string; expires: number }
  >();
  let n = 0;
  const state = {
    /** Срок жизни токена, секунд (у фабрики — 120). */
    life: 120,
    /** Исход следующего «да» (одноразово). */
    next: null as WriteOutcome | null,
    /** API не на рабочей фабрике: каждый POST — 409 `not_working_factory`. */
    readOnly: false,
    /** План выкладки сдвигает соседний ролик (`moves`) — показать сдвиги. */
    placeMoves: false,
    cards: seed.cards.map((c) => ({ ...c })),
    rows: seed.rows.map((r) => ({ ...r })),
    /** Файлы дефицита, которые «есть» под pipeline/. */
    deficits: new Set<string>(),
    awaiting: [] as { script_id: string; batch_id: string }[],
    /** Журнал ротации сломался после чтения: планы ротации — 409 `rotation_broken`. */
    rotationBroken: false,
    /** Сценарии, от пары которых уже отказывались (R3: один отказ на сценарий). */
    rejected: new Set<string>(),
    /** Что спрашивали: план или «да», действие, канал, тело. */
    calls: [] as {
      kind: 'plan' | 'confirm';
      action: WriteAction;
      channel: string;
      body: unknown;
    }[],
    /** Что записано (после «да»). */
    written: [] as { action: WriteAction; channel: string; bound: unknown }[],
    /** Переключатель API-загрузки по каналам (нет строки — не включался). */
    switches: {} as Record<string, SwitchRow & { history: SwitchHistoryRow[] }>,
    /** Файл переключателя не читается: строка ошибки (план — 409 `switch_unreadable`). */
    switchBroken: null as string | null,
    /** `PUBLISHER_CHANNEL_ID`: пусто — план загрузки без токена. */
    channelId: 'UCexample_film000000000',
    /** `publish/README.md` есть: нет — план загрузки без токена. */
    readme: true,
    /** Исход следующей загрузки (одноразово); null — загрузилось. */
    uploadNext: null as UploadOutcome | null,
    /** Журнал загрузок `publish/uploads.json`. */
    uploads: (seed.uploads ?? []).map((u) => ({ ...u })),
  };

  // ------------------------------------------------------------ переключатель API-загрузки
  function switchState(c: string): S['ApiSwitchState'] {
    const row = state.switches[c];
    const on = !state.switchBroken && !!row?.on;
    return {
      channel: c,
      on,
      line: switchLine(c, row, state.switchBroken),
      at: row?.at ?? null,
      by: row?.by ?? null,
      note: row?.note ?? null,
      warnings: [],
      history: (row?.history ?? []).map((h): S['ApiSwitchRow'] => ({
        channel: c,
        action: h.on ? 'on' : 'off',
        ...h,
        warnings: h.warnings ?? [],
      })),
      error: state.switchBroken,
    };
  }

  function switchCheck(c: string, b: { on?: boolean; note?: string | null }) {
    const on = !!b.on;
    const note = (b.note ?? '').trim();
    if (on && !note)
      throw new Fault(
        422,
        'note_required',
        'Включение API-загрузки - с заметкой: где и когда вы так решили (после аудита YouTube API, CF-0470).',
        ['api_switch.set_switch: --note is required to turn it on'],
      );
    const st = switchState(c);
    if (state.switchBroken)
      throw new Fault(409, 'switch_unreadable', st.line, [`${SWITCH_PATH}: ${state.switchBroken}`]);
    const stub = world.noPipeline(c);
    let why: string | null = null;
    if (on && stub) why = `${c}: ${stub} - API-загрузке нечего грузить (CF-0562).`;
    else if (st.on === on)
      why = `API-загрузка ${c} уже ${on ? 'включена' : 'выключена'} - менять нечего.`;
    return {
      ok: why == null,
      why,
      on,
      state: st,
      line: st.line,
      row: { channel: c, on, by: 'user', note: marked(note) },
      warnings: on && why == null ? [...API_WARNINGS] : null,
      audit_phrase: on ? AUDIT_PHRASE : null,
      path: SWITCH_PATH,
    };
  }

  // ------------------------------------------------------------ загрузка на YouTube
  function noteOrFault(c: string, slug: unknown, day: unknown, batch?: unknown) {
    const s = typeof slug === 'string' ? slug : '';
    const d = typeof day === 'string' && day ? day : null;
    const named = typeof batch === 'string' && batch ? batch : null;
    const twins = named ? [] : (world.twinsOf?.(c, s, d) ?? []);
    if (twins.length)
      throw new Fault(409, 'namesakes', namesakesMessage(s, twins), [`${s}: ${twins.join(', ')}`]);
    const note = world.noteOf(c, s, d, named);
    if (!note)
      throw new Fault(
        404,
        'unknown_note',
        `${s}: no note in publish/${c}/${d ?? '<day>'}/ - name the note's path or its slug`,
        [`publish/${c}/${d ?? '<day>'}/${s}.md`],
      );
    return note;
  }

  const uploadedOf = (c: string, slug: string) =>
    state.uploads.find((u) => u.channel === c && u.slug === slug) ?? null;

  function uploadCheck(
    c: string,
    b: { slug?: string; batch_id?: string | null; day?: string | null; entry?: string | null },
  ) {
    const note = noteOrFault(c, b.slug, b.day, b.batch_id);
    const st = switchState(c);
    const video = note.path.replace(/\.md$/, '.mp4');
    const sched = (note.studio?.schedule ?? null) as {
      publish_at_utc?: string;
      msk?: string;
    } | null;
    const out = {
      ok: false,
      why: null as string | null,
      slug: note.slug,
      day: note.day,
      note: note.path,
      video,
      entry_id: null as string | null,
      switch: st,
      dry_run: [] as string[],
      summary: null as string | null,
      body: null as Record<string, unknown> | null,
      tos_notice: null as string | null,
      question: null as string | null,
      channel_id: null as string | null,
      token: null as string | null,
      publish_at: null as string | null,
    };
    if (!st.on) {
      out.why = `${c}: API-загрузка выключена (${SWITCH_PATH}) - upload.py не грузит; ролик грузите через Studio или включите загрузку после аудита YouTube API (CF-0470).`;
      return out;
    }
    const done = uploadedOf(c, note.slug);
    const dry = [`DRY RUN ${note.path}`, '  switch: on', `  card: ${note.status}`];
    if (!note.ready || !note.studio) {
      out.why = `${note.path}: карточка не готова (${note.why ?? 'not_ready'}) - загрузка не начинается.`;
      out.dry_run = [...dry, `REFUSED card_gate: ${note.why ?? 'not_ready'}`];
      return out;
    }
    if (done) {
      out.why = `${note.slug}: уже загружен (uploads.json:${done.video_id}, ${done.source}) - второй раз не грузится.`;
      out.dry_run = [...dry, `REFUSED journal: ${done.video_id}`];
      return out;
    }
    const pause = world.pauseOf(c);
    if (pause) {
      out.why = `${c}: публикации на паузе (${pause.reason}) - загрузка не начинается.`;
      out.dry_run = [...dry, 'REFUSED pause'];
      return out;
    }
    const f = note.studio;
    const publishAt = sched?.publish_at_utc ?? null;
    const body = {
      snippet: { title: f.title, description: f.description, tags: f.tags, categoryId: '24' },
      status: { privacyStatus: 'private', publishAt, selfDeclaredMadeForKids: false },
    };
    let why: string | null = null;
    if (!state.channelId)
      why =
        'PUBLISHER_CHANNEL_ID пуст - загрузка должна знать, для какого канала она (agents/publisher/.env).';
    else if (!state.readme)
      why = 'publish/README.md нет - запись загрузки туда не ляжет; загрузка не начинается.';
    Object.assign(out, {
      ok: why == null,
      why,
      entry_id: f.entry_id,
      dry_run: [
        ...dry,
        `  slot: ${sched?.msk ?? '—'}`,
        `  file: ${video} (1080x1920)`,
        'DRY RUN ok - nothing sent',
      ],
      summary: [
        `Канал: ${c} (${state.channelId || '—'})`,
        `Ролик: ${f.file_name}`,
        `Название: ${f.title}`,
        `Теги: ${f.tags.join(', ')}`,
        `Выход: ${sched?.msk ?? '—'} (до этого — приватный)`,
      ].join('\n'),
      body,
      tos_notice: TOS_NOTICE,
      question: UPLOAD_QUESTION,
      channel_id: state.channelId || null,
      token: 'токен: годен до 2026-10-15 (agents/publisher/token.json)',
      publish_at: publishAt,
    });
    return out;
  }

  // ------------------------------------------------------------ запись загрузки из Studio
  function recordCheck(
    c: string,
    b: {
      slug?: string;
      batch_id?: string | null;
      day?: string | null;
      video_id?: string;
      read?: unknown;
      replaces?: string | null;
    },
  ) {
    const note = noteOrFault(c, b.slug, b.day, b.batch_id);
    if (!b.read || typeof b.read !== 'object' || Array.isArray(b.read))
      throw new Fault(
        422,
        'invalid',
        'Прочитанное из Studio - объект JSON (title, description, tags, visibility, schedule ...).',
        [`read is ${Array.isArray(b.read) ? 'list' : typeof b.read}`],
      );
    const read = b.read as Record<string, unknown>;
    const vid = String(b.video_id ?? '').trim();
    let why: string | null = null;
    let mismatches: StudioMismatch[] = [];
    let status: 'would-add' | 'exists' | null = null;
    let row: Record<string, unknown> | null = null;
    if (!note.studio) why = note.studio_refusal ?? `${note.path}: карточка не готова`;
    else if (!/^[A-Za-z0-9_-]{11}$/.test(vid))
      why = `video id ${JSON.stringify(vid)} - не 11 знаков, как его показывает Studio`;
    else {
      mismatches = compareStudio(note.studio, read);
      if (!mismatches.length) {
        const has = state.uploads.find((u) => u.channel === c && u.video_id === vid);
        status = has ? 'exists' : 'would-add';
        row = {
          entry_id: note.studio.entry_id,
          channel: c,
          slug: note.slug,
          video_id: vid,
          url: `https://youtube.com/shorts/${vid}`,
          source: 'studio',
          user_edited: false,
          publish_at: (note.studio.schedule as { publish_at_utc?: string }).publish_at_utc ?? null,
          replaces: b.replaces ?? null,
        };
      }
    }
    if (mismatches.length)
      why = `Studio показывает не то, что в карточке - ничего не записано: ${mismatches.map((m) => m.field).join('; ')}. Скажите пользователю до слота.`;
    else if (why == null && status !== 'would-add')
      why = `${note.slug}: ${vid} уже в журнале (${status}) - записывать нечего.`;
    return {
      ok: why == null,
      why,
      slug: note.slug,
      day: note.day,
      note: note.path,
      video_id: vid,
      replaces: b.replaces ?? null,
      mismatches,
      status,
      row,
    };
  }

  // ------------------------------------------------------------ ручная правка в Studio
  /** Как `upload_records.mark_user_edited(dry_run=True)`: строка до и после, или строка отказа. */
  function editedRow(
    c: string,
    vid: string | null,
    slug: string | null,
    edited: boolean,
    note: string | null,
  ) {
    const mine = vid
      ? state.uploads.filter((u) => u.video_id === vid)
      : state.uploads.filter((u) => u.slug === slug && !u.removed_at && u.channel === c);
    if (!mine.length) return { why: `no journal row for ${vid ?? slug}` } as const;
    if (mine.length > 1)
      return {
        why: `${slug}: ${mine.length} live rows (${mine.map((u) => u.video_id).join(', ')}) - name the video with --video-id`,
      } as const;
    const before = mine[0]!;
    if (before.source !== 'studio')
      return {
        why: `${before.video_id} is a \`${before.source}\` row - only the Studio path (CF-0018) keeps the no-edit count`,
      } as const;
    const after: UploadRow = {
      ...before,
      user_edited: edited,
      user_edited_by: 'user',
      user_edited_via: 'center',
    };
    if (note) after.user_edit_note = note;
    else if (!edited) delete after.user_edit_note;
    return { before, after } as const;
  }

  function editedCheck(edited: boolean) {
    return (
      c: string,
      b: { video_id?: string | null; slug?: string | null; note?: string | null },
    ) => {
      const vid = (b.video_id ?? '').trim();
      const slug = (b.slug ?? '').trim();
      if (!vid === !slug)
        throw new Fault(
          422,
          'invalid',
          'Назовите ролик: его id в Studio (video_id) или slug - одно из двух.',
          ['mark_user_edited: --video-id ID or --slug SLUG, exactly one'],
        );
      const note = (b.note ?? '').trim() || null;
      const got = editedRow(c, vid || null, slug || null, edited, note);
      let why: string | null = 'why' in got ? (got.why ?? null) : null;
      const after = 'after' in got ? got.after : null;
      const before = 'before' in got ? got.before : null;
      if (!why && after && after.channel !== c)
        why = `${after.video_id} - ролик канала ${after.channel}, а не ${c} - отмечать его отсюда нельзя.`;
      else if (!why && !!before?.user_edited === edited)
        why = `${after!.slug} (${after!.video_id}): ${edited ? 'ручная правка уже отмечена' : 'отметки ручной правки нет'} - менять нечего.`;
      const ok = why == null;
      const rows = ok ? state.uploads.map((u) => (u === before ? after! : u)) : [];
      return {
        ok,
        why,
        edited,
        video_id: after?.video_id ?? (vid || null),
        slug: after?.slug ?? (slug || null),
        note: note ?? '',
        by: 'user' as const,
        via: 'center' as const,
        before: ok ? { ...before } : null,
        row: ok ? { ...after } : null,
        streak: ok ? studioStreak(rows, c) : null,
        journal: 'publish/uploads.json',
      };
    };
  }

  // ------------------------------------------------------------ подпись холда
  const holdAt = (c: string, b: { batch_id?: string; topic_id?: string }) =>
    world
      .holds()
      .find((h) => h.channel === c && h.batch_id === b.batch_id && h.topic_id === b.topic_id);

  function holdSignCheck(c: string, b: { batch_id?: string; topic_id?: string; note?: string }) {
    const hold_id = `${c}/${b.batch_id ?? ''}/${b.topic_id ?? ''}`;
    const note = typeof b.note === 'string' ? b.note.trim() : '';
    const sign = (code: SignCode, details: string[] = []) =>
      new Fault(SIGN_REFUSALS[code][0], code, SIGN_REFUSALS[code][1], [
        SIGN_REFUSALS[code][2],
        ...details,
      ]);
    if (!note) throw sign('empty_note');
    const problem = world.holdsProblem();
    const row = holdAt(c, b);
    const code = signCodeOf(row, problem);
    if (code || !row)
      throw sign(code ?? 'no_such_hold', [`hold ${hold_id}`, ...(problem ? [problem] : [])]);
    const cc = COMPLIANCE[row.reason_code ?? ''] ?? { sensitivity: 'отмечено', rights: '—' };
    // CC-0169 (CF-0846): строка «Сцены флага» — как её пишет `publish.hold_sign_plan`.
    const scenes = row.sensitivity_scenes ?? null;
    const scenesLine =
      scenes === 'whole_topic'
        ? ['Сцены флага: вся тема']
        : scenes?.length
          ? [`Сцены флага: ${scenes.map((x) => shortScene(x, row.topic_id)).join(', ')}`]
          : [];
    return {
      ok: true,
      why: null,
      hold_id,
      batch_id: row.batch_id,
      topic_id: row.topic_id,
      script_id: row.script_id,
      verdict: row.verdict,
      flagged: [
        `вердикт compliance-checker: ${row.verdict ?? '—'}`,
        `чувствительность контента: ${cc.sensitivity}`,
        ...scenesLine,
        `права (для сведения): ${cc.rights}`,
        `причина холда: ${row.reason ?? '—'}`,
      ],
      content_sensitivity_check: { flagged: true, notes: cc.sensitivity },
      sensitivity_scenes: scenes,
      rights_holder_check: { cleared: true, notes: cc.rights },
      meaning:
        'Подпись значит: вы посмотрели ролик и решили, что его можно публиковать. Холд закроется, ролик пойдёт в публикацию; строка холда в реестре останется — с вашей подписью и заметкой.',
      note,
      signature: { user: 'user', note, via: 'center' as const },
      ledger: 'publish/publication-holds.json',
      ledger_fingerprint: `sha256:${world.holds().length}`,
      hold: { ...row },
    };
  }

  // ------------------------------------------------------------ пауза
  function pauseSetCheck(
    c: string,
    b: { reason?: string; until?: string | null; replace?: boolean },
  ) {
    const reason = (b.reason ?? '').trim();
    if (!reason)
      throw new Fault(422, 'note_required', 'Пауза говорит, почему: напишите причину.', [
        'channel_pause.set_pause: --reason is empty - a pause says why',
      ]);
    let until: string | null = null;
    if (b.until) {
      const m = /^(\d{4}-\d{2}-\d{2})$/.exec(b.until.trim());
      const iso = m ? `${m[1]}T00:00:00+03:00` : b.until.trim();
      if (Number.isNaN(Date.parse(iso)))
        throw new Fault(422, 'invalid', `Срок паузы не читается: ${b.until}`, [
          `PauseError: until ${b.until}`,
        ]);
      until = iso;
    }
    const stands = world.pauseOf(c);
    const replace = !!b.replace;
    let why: string | null = null;
    if (until && Date.parse(until) <= Date.parse(world.now()))
      why = `Срок паузы (${until}) уже прошёл - ставить нечего.`;
    else if (stands && !replace)
      why = `У канала уже есть пауза: ${stands.reason} - снимите её или замените (replace).`;
    const row = { channel: c, by: 'user', reason: marked(reason), until };
    return {
      ok: why == null,
      why,
      state: stands ? ('paused' as const) : ('free' as const),
      line: stands
        ? `${c}: публикации НА ПАУЗЕ - ${stands.reason}`
        : `${c}: публикации идут (паузы нет)`,
      open_row: stands,
      row,
      replace,
      replaces: replace ? stands : null,
    };
  }

  function pauseClearCheck(c: string, b: { note?: string | null }) {
    const stands = world.pauseOf(c);
    return {
      ok: !!stands,
      why: stands ? null : `${c}: паузы нет - снимать нечего.`,
      state: stands ? ('paused' as const) : ('free' as const),
      line: stands
        ? `${c}: публикации НА ПАУЗЕ - ${stands.reason}`
        : `${c}: публикации идут (паузы нет)`,
      open_row: stands,
      row: stands ? { ...stands, cleared_by: 'user', clear_note: marked(b.note) } : null,
    };
  }

  const pauseNow = (c: string): S['ChannelPause'] => {
    const row = world.pauseOf(c);
    return {
      channel: c,
      as_of: world.now(),
      state: row ? 'paused' : 'free',
      line: row ? `${c}: публикации НА ПАУЗЕ - ${row.reason}` : `${c}: публикации идут (паузы нет)`,
      row,
      open_row: row,
      history: row ? [row] : [],
      registry: 'publish/channel-pauses.json',
    };
  };

  // ------------------------------------------------------------ карточка
  function cardOf(c: string, b: { batch_id?: string; dir?: string | null; slug?: string }) {
    const batch = `${b.dir || c}/${b.batch_id ?? ''}`;
    if (!state.cards.some((x) => x.batch === batch))
      throw new Fault(404, 'unknown_batch', `батча ${batch} нет`, [
        `pipeline/${batch}: no such directory`,
      ]);
    const card = state.cards.find(
      (x) => x.batch === batch && (x.slug === b.slug || x.script_id === b.slug),
    );
    if (!card)
      throw new Fault(404, 'unknown_video', `${b.slug}: такого ролика в батче ${batch} нет`, [
        `CardError: no video ${b.slug} in pipeline/${batch}`,
      ]);
    return card;
  }

  function placeCheck(
    c: string,
    b: {
      batch_id?: string;
      dir?: string | null;
      slug?: string;
      day?: string | null;
      replace?: boolean;
    },
  ) {
    if (b.day && b.day !== '_queue' && !/^\d{4}-\d{2}-\d{2}$/.test(b.day))
      throw new Fault(422, 'invalid', `'${b.day}': не день (YYYY-MM-DD) и не _queue`, [
        `day ${b.day}`,
      ]);
    const card = cardOf(c, b);
    const src = `pipeline/${card.batch}/work/publish-card/${card.slug}.md`;
    const target = card.bucket ? `publish/${c}/${card.bucket}/${card.slug}.md` : null;
    let why: string | null = null;
    let slot: unknown = null;
    let paused: string | null = null;
    if (card.ready == null) why = `${src}: карточки нет - сначала её собирают.`;
    else if (!card.ready) why = 'Карточка не готова (claims_not_checked) - в publish/ она не идёт.';
    else if (!card.bucket)
      why = `${card.slug}: ролика нет в publish/${c}/ - карточка идёт за принятым роликом, не впереди него.`;
    else if (b.day && b.day !== card.bucket)
      // CC-0167 (CF-0857): day — папка, где ролик батча лежит сейчас, а не слот.
      why = `${card.slug}: ролик батча лежит в publish/${c}/${card.bucket}/, не в ${b.day}/ - day - папка, где ролик лежит сейчас, не слот; пусто - фабрика найдёт ролик батча сама.`;
    else if (card.placed && !b.replace)
      why = `${target}: заметка уже там - замена только с replace.`;
    else if (card.bucket === '_queue') {
      const pause = world.pauseOf(c);
      const free = world.nextFree(c);
      if (pause)
        paused = `${c}: publications are paused (${pause.reason}) - ${card.slug} gets no slot`;
      else if (!free) why = `${card.slug}: слота нет - в горизонте нет свободного слота`;
      else
        slot = {
          slot: free.at,
          day: free.day,
          line: `${free.label} — ${card.slug}`,
          note: null,
          warnings: [
            `WINDOW ${c}: ${card.slug} и соседний ролик — одна пара паттернов в окне из 3 дней; ставится с повтором пары`,
          ],
          moves: state.placeMoves
            ? [
                {
                  slug: 'vanguards-doomsday',
                  batch_id: '2026-10-09T0200Z',
                  from: free.day,
                  slot: free.at,
                  day: free.day,
                  line: `сдвигается на следующий свободный слот после ${free.label}`,
                },
              ]
            : [],
        };
    }
    return {
      ok: why == null,
      why,
      batch: `pipeline/${card.batch}`,
      slug: card.slug,
      card: src,
      ready: !!card.ready,
      not_ready: card.ready ? null : card.ready == null ? 'no card' : 'claims_not_checked',
      bucket: card.bucket,
      target,
      target_exists: card.placed,
      replace: !!b.replace,
      day: b.day ?? null,
      slot,
      paused,
    };
  }

  function draftProblems(d: unknown): string[] {
    if (typeof d !== 'object' || d === null) return ['the draft is not a JSON object'];
    const x = d as Record<string, unknown>;
    const out: string[] = [];
    for (const k of ['title', 'about'])
      if (typeof x[k] !== 'string' || !(x[k] as string).trim())
        out.push(`\`${k}\` must be a non-empty string`);
    for (const k of ['hashtags', 'tags'])
      if (!Array.isArray(x[k]) || !(x[k] as unknown[]).every((v) => typeof v === 'string'))
        out.push(`\`${k}\` must be a list of strings`);
    return out;
  }

  function refuseModel(b: { draft?: unknown; model?: boolean }) {
    if (b.model || b.draft == null)
      throw new Fault(
        409,
        'model_refused',
        'Черновик через модель — не из центра: центр собирает карточку только из данного черновика и без проверки утверждений (claims=False). Черновик моделью и проверку утверждений делает publish_card.py build у оператора.',
        [
          'publish_card.build with a model (asker) or the claim check is not run from the center: pass `draft` and no `model`; nothing was called',
        ],
      );
  }

  function buildCheck(
    c: string,
    b: { batch_id?: string; dir?: string | null; slug?: string; draft?: unknown },
  ) {
    const card = cardOf(c, b);
    const problems = draftProblems(b.draft);
    return {
      ok: !problems.length,
      why: problems.length ? `Черновик не годится: ${problems.join('; ')}` : null,
      batch: `pipeline/${card.batch}`,
      slug: card.slug,
      script_id: card.script_id,
      out: `pipeline/${card.batch}/work/publish-card/${card.slug}.md`,
      exists: card.ready != null,
      exists_ready: card.ready,
      draft: b.draft,
      problems,
      claims: false,
      will_be:
        'not_ready (claims_not_checked): без проверки утверждений карточка не готова к выкладке - готовой её делает сборка с моделью у оператора',
    };
  }

  // ------------------------------------------------------------ ротация
  function rotationOk(c: string) {
    if (world.noRotation.includes(c) || state.rotationBroken)
      throw new Fault(
        409,
        'rotation_broken',
        `channel '${c}': patterns.rotation is missing - K and the distribution window are channel settings`,
        ['RotationError: patterns.rotation is missing'],
      );
  }

  const standing = (sid: string, batch?: string | null) =>
    state.rows.filter((r) => r.script_id === sid && (!batch || r.batch_id === batch)).at(-1);

  function assignCheck(
    c: string,
    b: { batch_id?: string; script_ids?: string[]; despite_shortage?: boolean },
  ) {
    rotationOk(c);
    const ids = b.script_ids ?? [];
    if (!ids.length || !b.batch_id)
      throw new Fault(422, 'invalid', 'Нужны батч и хотя бы один сценарий.', [
        'batch_id and script_ids are required',
      ]);
    const held = b.despite_shortage ? [] : state.awaiting.map((a) => a.script_id);
    const scripts = ids.map((s) => {
      const row = standing(s, b.batch_id);
      if (row && !row.rejection_verdict)
        return {
          script_id: s,
          state: 'standing',
          pattern_id: row.pattern_id,
          rhythm_id: row.rhythm_id,
          seq: row.seq,
        };
      if (held.includes(s))
        return {
          script_id: s,
          state: 'held',
          retry_when: 'когда в пуле появятся шоты нового трейлера',
          pool_says: 'waiting',
        };
      return { script_id: s, state: 'fresh' };
    });
    const allHeld = scripts.every((x) => x.state === 'held');
    return {
      ok: !allHeld,
      why: allHeld
        ? 'Все предложенные темы ждут пополнения пула (CF-0149) - назначать нечего; despite_shortage - если вы посмотрели и не согласны с переписью.'
        : null,
      batch_id: b.batch_id,
      scripts,
      despite_shortage: !!b.despite_shortage,
      eligible_pairs: ['moment-breakdown/hold', 'number-reveal/build', 'myth-check/turn'],
      ledger: 'rotation/ledger',
    };
  }

  function rejectCheck(
    c: string,
    b: { script_id?: string; reason?: string; rejects_rhythm?: boolean; batch_id?: string | null },
  ) {
    rotationOk(c);
    const sid = b.script_id ?? '';
    const row = standing(sid, b.batch_id);
    let why: string | null = null;
    let ruling: Record<string, unknown> | null = null;
    if (!row) why = `${sid} has no standing assignment to reject in rotation/ledger/${c}.csv`;
    else if ((b.reason ?? '').trim().length < MIN_REASON)
      why = `a rejection needs a written reason of at least ${MIN_REASON} characters (R2)`;
    else if (row.rejection_verdict || state.rejected.has(sid))
      ruling = {
        verdict: 'denied',
        explanation: `${sid} was already rejected once (seq ${row.seq}); one rejection per script - the assignment stands`,
        replacement: null,
        rule: 'R3',
        excluded_rhythm: null,
        row,
      };
    else
      ruling = {
        verdict: 'upheld',
        explanation:
          'upheld; the fallback is the next pair in the rotation' +
          (b.rejects_rhythm
            ? `, and every pair on \`${row.rhythm_id}\` was excluded from the draw`
            : ''),
        replacement: b.rejects_rhythm ? ['number-reveal', 'build'] : ['moment-breakdown', 'hold'],
        rule: null,
        excluded_rhythm: b.rejects_rhythm ? row.rhythm_id : null,
        row,
      };
    return {
      ok: why == null,
      why,
      script_id: sid,
      batch_id: b.batch_id ?? null,
      reason: b.reason ?? '',
      rejects_rhythm: !!b.rejects_rhythm,
      ruling,
      verdict: ruling?.verdict ?? null,
      writes:
        ruling == null
          ? null
          : ruling.verdict === 'denied'
            ? 'the denial on the standing row (rejection_verdict: denied) - the assignment stands'
            : 'the rejection upheld on the row and a new row: the replacement pair, rotation-after-rejection',
    };
  }

  function refuseCheck(
    c: string,
    b: { script_id?: string; reason?: string; deficit?: string; batch_id?: string | null },
  ) {
    rotationOk(c);
    const parts = (b.deficit ?? '').split('/').filter(Boolean);
    if (!parts.length || parts[0] !== 'pipeline' || parts.some((p) => p === '.' || p === '..'))
      throw new Fault(
        422,
        'invalid',
        `'${b.deficit ?? ''}': дефицит - файл батча под pipeline/ (plan.assetless-rung.json)`,
        [`deficit '${b.deficit ?? ''}' is not a path under pipeline/`],
      );
    const sid = b.script_id ?? '';
    const reason = (b.reason ?? '').trim();
    const row = standing(sid, b.batch_id);
    let why: string | null = null;
    if (!state.deficits.has(b.deficit!)) why = `FileNotFoundError: ${b.deficit}`;
    else if (reason.length < MIN_REASON)
      why = `Отказу нужна письменная причина об этом ролике - не короче ${MIN_REASON} знаков.`;
    else if (!row) why = `${b.batch_id ? `${b.batch_id}/` : ''}${sid}: нет стоящего назначения.`;
    else if (row.rejection_verdict)
      why = `seq ${row.seq} уже несёт отказ (${row.rejection_verdict}) - эту строку нельзя закрыть ещё и отказом за нехваткой материала; нужен человек.`;
    return {
      ok: why == null,
      why,
      script_id: sid,
      batch_id: b.batch_id ?? null,
      reason,
      deficit: b.deficit,
      anchors: why ? [] : [{ anchor: 'trailer-2', needs: 'шоты второго трейлера' }],
      row: row ?? null,
      writes: 'a shortage record, then the row closed (rejection upheld), no replacement',
    };
  }

  // ------------------------------------------------------------ исполнение
  type Check = (c: string, b: never) => { ok: boolean } & Record<string, unknown>;
  const checks: Record<WriteAction, Check> = {
    pause_set: pauseSetCheck as Check,
    pause_clear: pauseClearCheck as Check,
    card_place: placeCheck as Check,
    card_build: buildCheck as Check,
    rotation_assign: assignCheck as Check,
    rotation_reject: rejectCheck as Check,
    rotation_refuse: refuseCheck as Check,
    api_upload_switch: switchCheck as Check,
    api_upload: uploadCheck as Check,
    studio_record: recordCheck as Check,
    studio_edited: editedCheck(true) as Check,
    studio_edited_undo: editedCheck(false) as Check,
    hold_sign: holdSignCheck as Check,
  };

  function act(
    action: WriteAction,
    c: string,
    b: Record<string, unknown>,
    sent: Record<string, unknown>,
  ): unknown {
    switch (action) {
      case 'hold_sign': {
        const out = holdSignCheck(c, b);
        const row = holdAt(c, b)!;
        row.signature = { user: 'user', date: world.now(), note: out.note, via: 'center' };
        return {
          action,
          channel: c,
          hold_id: out.hold_id,
          row: { ...row, ...holdSignInfo(row) },
          fingerprint: `sha256:signed-${out.hold_id}`,
          holds: world.holdsOf(c),
        };
      }
      case 'api_upload_switch': {
        const on = !!b.on;
        if (on && words(sent.audit) !== words(AUDIT_PHRASE))
          throw new Fault(
            422,
            'audit_unconfirmed',
            `API-загрузка включается только после аудита YouTube API: напишите «${AUDIT_PHRASE}». Переключатель не тронут - запросите план заново.`,
            [
              `audit ${JSON.stringify(sent.audit ?? null)} is not '${AUDIT_PHRASE}'; the token is spent`,
            ],
          );
        const prev = state.switches[c];
        const row: SwitchRow = {
          on,
          at: world.now(),
          by: 'user',
          note: marked(typeof b.note === 'string' ? b.note : null),
        };
        // В строку истории — о чём предупредило включение (`ApiSwitchRow.warnings`).
        const logged: SwitchHistoryRow = { ...row, warnings: on ? [...API_WARNINGS] : [] };
        state.switches[c] = { ...row, history: [...(prev?.history ?? []), logged] };
        return {
          action,
          channel: c,
          on,
          changed: true,
          warnings: on ? [...API_WARNINGS] : [],
          state: switchState(c),
        };
      }
      case 'api_upload': {
        const out = uploadCheck(c, b);
        const outcome = state.uploadNext;
        state.uploadNext = null;
        const vid = 'Zk3pQ9wLm2A';
        const lines = [
          `upload ${out.video}: 100%`,
          `uploaded: https://youtube.com/shorts/${vid} (private until ${out.publish_at})`,
        ];
        if (outcome === 'reauthorize')
          throw new Fault(
            409,
            'reauthorize',
            'Токен YouTube надо переразрешить - ничего не загружено: refresh token revoked (invalid_grant)',
            [
              'ReauthorizeRequired: invalid_grant',
              'python3 agents/publisher/upload.py --authorize (the user, at the terminal)',
            ],
          );
        if (outcome === 'upload_failed')
          throw new Fault(409, 'upload_failed', 'YouTube не принял загрузку: quotaExceeded (403)', [
            'UploadError: quotaExceeded (403)',
            `upload ${out.video}: 0%`,
          ]);
        if (outcome === 'uploaded_unrecorded')
          throw new Fault(
            500,
            'uploaded_unrecorded',
            'Ролик загружен, но запись о загрузке не легла - внесите её по строкам ниже, прежде чем что-то повторять.',
            [
              ...lines,
              'ERROR journal: publish/uploads.json: [Errno 28] No space left on device',
              `MANUAL publish/uploads.json: {"entry_id": "${out.entry_id}", "video_id": "${vid}", "source": "api", "publish_at": "${out.publish_at}"}`,
              `MANUAL ${out.note}: ## Загружено — https://youtube.com/shorts/${vid}`,
            ],
          );
        const row: UploadRow = {
          channel: c,
          slug: out.slug,
          video_id: vid,
          source: 'api',
          publish_at: out.publish_at,
          entry_id: out.entry_id,
          recorded_at: world.now(),
        };
        state.uploads.push(row);
        return {
          action,
          channel: c,
          slug: out.slug,
          row,
          lines: [...lines, `journal: publish/uploads.json += ${vid}`],
          shown: `${out.summary}\n\n${TOS_NOTICE}\n${UPLOAD_QUESTION} ${String(sent.answer)}`,
        };
      }
      case 'studio_edited':
      case 'studio_edited_undo': {
        const edited = action === 'studio_edited';
        const out = editedCheck(edited)(c, b);
        const i = state.uploads.findIndex((u) => u.video_id === out.video_id);
        const row: UploadRow = { ...(out.row as UploadRow), user_edited_at: world.now() };
        state.uploads[i] = row;
        return {
          action,
          channel: c,
          edited,
          by: 'user',
          via: 'center',
          row: { ...row },
          streak: studioStreak(state.uploads, c),
        };
      }
      case 'studio_record': {
        const out = recordCheck(c, b);
        const row: UploadRow = {
          channel: c,
          slug: out.slug,
          video_id: out.video_id,
          source: 'studio',
          publish_at: (out.row?.publish_at as string | null) ?? null,
          entry_id: (out.row?.entry_id as string | null) ?? null,
          recorded_at: world.now(),
        };
        state.uploads.push(row);
        const streak = world.recorded(row);
        return {
          action,
          channel: c,
          slug: out.slug,
          status: 'added',
          row: { ...out.row, recorded_at: row.recorded_at },
          ledger: { published: true, video_id: out.video_id },
          streak,
        };
      }
      case 'pause_set': {
        const out = pauseSetCheck(c, b);
        const row: S['PauseRow'] = {
          pause_id: `pause-${world.now().slice(0, 16).replace(/[-:]/g, '')}Z`,
          channel: c,
          by: 'user',
          reason: out.row.reason,
          set_at: world.now(),
          until: out.row.until,
          cleared_at: null,
          cleared_by: null,
          clear_note: null,
        };
        world.setPause(c, row);
        return { action, channel: c, row, pause: pauseNow(c) };
      }
      case 'pause_clear': {
        const was = world.pauseOf(c)!;
        const row = {
          ...was,
          cleared_at: world.now(),
          cleared_by: 'user',
          clear_note: marked(b.note as string),
        };
        world.setPause(c, null);
        return { action, channel: c, row, pause: pauseNow(c) };
      }
      case 'card_place': {
        const out = placeCheck(c, b);
        const card = cardOf(c, b);
        const report: string[] = [];
        const slot = out.slot as { day: string; line: string } | null;
        if (out.paused) report.push(`PAUSED ${c}: ${card.slug} остаётся в _queue/ - ${out.paused}`);
        if (slot) {
          world.place(c, card.slug, slot.day);
          card.bucket = slot.day;
          report.push(
            `${card.slug}: _queue -> ${slot.day}`,
            ...((out.slot as { warnings: string[] }).warnings ?? []).map((w) => `WARNING ${w}`),
          );
        }
        card.placed = true;
        return {
          action,
          channel: c,
          slug: card.slug,
          path: `publish/${c}/${card.bucket}/${card.slug}.md`,
          report,
        };
      }
      case 'card_build': {
        const card = cardOf(c, b);
        card.ready = false;
        const path = `pipeline/${card.batch}/work/publish-card/${card.slug}.md`;
        return {
          action,
          channel: c,
          slug: card.slug,
          status: 'not_ready',
          path,
          problems: [
            {
              check: 'claims',
              status: 'claims_not_checked',
              why: 'утверждения карточки не проверены (claims=False)',
            },
          ],
          mark: { status: 'not_ready', why: 'claims_not_checked' },
          view: `${path}\n  NOT READY  ${(b.draft as { title?: string }).title ?? ''}\n  claims_not_checked`,
        };
      }
      case 'rotation_assign': {
        const out = assignCheck(c, b);
        const pairs = [
          ['moment-breakdown', 'hold'],
          ['number-reveal', 'build'],
          ['myth-check', 'turn'],
        ] as const;
        const res = out.scripts.map((s, i) => {
          if (s.state !== 'fresh') return s;
          const [p, r] = pairs[i % pairs.length]!;
          const row: RotationRow = {
            script_id: s.script_id,
            batch_id: out.batch_id!,
            pattern_id: p,
            rhythm_id: r,
            seq: 100 + state.rows.length,
            rejection_verdict: null,
          };
          state.rows.push(row);
          return {
            script_id: s.script_id,
            state: 'assigned',
            pattern_id: p,
            rhythm_id: r,
            seq: row.seq,
          };
        });
        return { action, channel: c, result: res };
      }
      case 'rotation_reject': {
        const out = rejectCheck(c, b);
        const row = standing(out.script_id, out.batch_id)!;
        const ruling = out.ruling!;
        state.rejected.add(row.script_id);
        if (ruling.verdict === 'upheld') {
          row.rejection_verdict = 'upheld';
          const [p, r] = ruling.replacement as [string, string];
          state.rows.push({
            ...row,
            pattern_id: p,
            rhythm_id: r,
            seq: 100 + state.rows.length,
            rejection_verdict: null,
          });
        } else row.rejection_verdict = 'denied';
        return { action, channel: c, result: { ...ruling } };
      }
      case 'rotation_refuse': {
        const out = refuseCheck(c, b);
        const row = standing(out.script_id, out.batch_id)!;
        row.rejection_verdict = 'upheld';
        state.awaiting.push({ script_id: row.script_id, batch_id: row.batch_id });
        return {
          action,
          channel: c,
          result: {
            closed_seq: row.seq,
            shortage: `rotation/ledger/${c}.shortage.jsonl`,
            replacement: null,
          },
        };
      }
    }
  }

  const fingerprint = (out: unknown) => JSON.stringify(out);

  function plan(action: WriteAction, c: string, raw: unknown): WriteReply {
    state.calls.push({ kind: 'plan', action, channel: c, body: raw });
    try {
      if (state.readOnly) throw readOnlyFault();
      if (!world.channels.includes(c)) throw new Fault(404, 'unknown_channel', `канала ${c} нет`);
      const b = (raw ?? {}) as Record<string, unknown>;
      if (action === 'card_build') refuseModel(b);
      const out = checks[action](c, b as never);
      const fp = fingerprint(out);
      let confirm: string | null = null;
      if (out.ok) {
        confirm = `pub-${action}-${++n}`;
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
          ...out,
          action,
          channel: c,
          fingerprint: `sha256:${fp.length}-${n}`,
          confirm,
          expires_in_s: confirm ? state.life : null,
        },
      };
    } catch (e) {
      if (e instanceof Fault) return fault(e);
      throw e;
    }
  }

  const readOnlyFault = () =>
    new Fault(
      409,
      'not_working_factory',
      'Только смотреть: рабочая копия на ветке cc-api, а не main',
      ['CC_API_WRITES is off'],
    );

  /** `target` — что ещё стоит в адресе «да» (холд): токен другого холда — `confirm_mismatch`. */
  function confirm(
    action: WriteAction,
    c: string,
    raw: unknown,
    target: Record<string, string> | null = null,
  ): WriteReply {
    state.calls.push({ kind: 'confirm', action, channel: c, body: raw });
    try {
      if (state.readOnly) throw readOnlyFault();
      if (!world.channels.includes(c)) throw new Fault(404, 'unknown_channel', `канала ${c} нет`);
      const token = ((raw ?? {}) as { confirm?: string }).confirm ?? '';
      if (action === 'api_upload') {
        // Как `publish_net.api_upload`: ответ проверяется до токена — токен цел, ничего не звали.
        const answer = (raw as { answer?: unknown } | null)?.answer;
        if (words(answer) !== 'да')
          throw new Fault(
            422,
            'answer_required',
            'Загрузка - только после вашего «да»: прочитайте сводку и условия YouTube и напишите «да».',
            [
              `answer ${JSON.stringify(answer ?? null)} is not one of upload_gate.YES; the token is not spent, nothing was called`,
            ],
          );
      }
      const got = tokens.get(token);
      if (!got)
        throw new Fault(
          409,
          'confirm_unknown',
          'Подтверждение не найдено или уже использовано - запросите план заново.',
          ['no such confirm token in this API process (used, unknown, or the server restarted)'],
        );
      const next = state.next;
      state.next = null;
      if (next === 'busy')
        throw new Fault(
          409,
          'busy',
          'Идёт другая запись публикации - подождите и запросите план заново.',
          ['the publication write lock was not free in 30.0 s; the token is not spent'],
        );
      tokens.delete(token);
      const bound = (got.bound ?? {}) as Record<string, unknown>;
      const otherTarget = !!target && Object.entries(target).some(([k, v]) => bound[k] !== v);
      if (got.action !== action || got.channel !== c || otherTarget)
        throw new Fault(
          409,
          'confirm_mismatch',
          `Подтверждение выдано для ${got.action} ${got.channel}, а не для ${action} ${c} - ничего не записано.`,
          [`token of ${got.action} ${got.channel}, asked ${action} ${c}; the token is spent`],
        );
      if (got.expires <= Date.now())
        throw new Fault(
          409,
          'confirm_expired',
          'Подтверждение устарело (живёт 120 с) - запросите план заново.',
          ['expired'],
        );
      if (next === 'refused')
        throw new Fault(409, 'refused', 'Фабрика отказала: реестр занят другим процессом.', [
          'the check changed since the plan',
        ]);
      if (next === 'factory_broken')
        throw new Fault(
          500,
          'factory_broken',
          'Фабрика ответила ошибкой посреди записи - посмотрите состояние, прежде чем повторять.',
          ['OSError: disk full'],
        );
      const out = checks[action](c, got.bound as never);
      if (next === 'check_changed' || fingerprint(out) !== got.fp) {
        if (!out.ok)
          throw new Fault(409, 'refused', (out.why as string) || 'Фабрика отказала.', [
            'the check changed since the plan',
          ]);
        throw new Fault(
          409,
          'check_changed',
          'Проверка изменилась с момента плана - посмотрите план заново.',
          [`the fingerprint of the ${action} plan differs from the plan's`],
        );
      }
      const body = act(
        action,
        c,
        got.bound as Record<string, unknown>,
        (raw ?? {}) as Record<string, unknown>,
      );
      state.written.push({ action, channel: c, bound: got.bound });
      return { status: 200, body };
    } catch (e) {
      if (e instanceof Fault) return fault(e);
      throw e;
    }
  }

  /** Переключатель API-загрузки каналов — для GET `…/api-upload`. */
  const channelsSwitch = (list: readonly string[]) => list.map(switchState);

  /** Все выданные токены устарели у фабрики (как будто прошло 120 с) — «да» получит `confirm_expired`. */
  const expireTokens = () => {
    for (const t of tokens.values()) t.expires = 0;
  };

  return { state, plan, confirm, channelsSwitch, expireTokens };
}

export type PublishWrites = ReturnType<typeof createPublishWrites>;

const ROUTES: Record<string, WriteAction> = {
  'api-upload/switch': 'api_upload_switch',
  upload: 'api_upload',
  'studio/record': 'studio_record',
  'studio/edited': 'studio_edited',
  'studio/edited/undo': 'studio_edited_undo',
  'pause/set': 'pause_set',
  'pause/clear': 'pause_clear',
  'card/place': 'card_place',
  'card/build': 'card_build',
  'rotation/assign': 'rotation_assign',
  'rotation/reject': 'rotation_reject',
  'rotation/refuse': 'rotation_refuse',
};

/**
 * POST `/api/publish/{c}/<группа>/<действие>[/plan]` и `/api/publish/{c}/holds/{batch}/{topic}/
 * sign[/plan]`; null — не запись без сети.
 */
export function routePublishWrite(
  w: PublishWrites,
  rest: string[],
  body: unknown,
): WriteReply | null {
  // `…/upload[/plan]` — одно слово действия, прочие — «группа/действие[/plan]».
  const [c, ...path] = rest;
  const planned = path.at(-1) === 'plan';
  if (c && path[0] === 'holds' && path[3] === 'sign' && path.length === (planned ? 5 : 4)) {
    const target = { batch_id: path[1]!, topic_id: path[2]! };
    return planned
      ? w.plan('hold_sign', c, { ...((body ?? {}) as object), ...target })
      : w.confirm('hold_sign', c, body, target);
  }
  const name = (planned ? path.slice(0, -1) : path).join('/');
  if (!c || !name || path.length > 4) return null;
  const action = ROUTES[name];
  if (!action) return null;
  return planned ? w.plan(action, c, body) : w.confirm(action, c, body);
}
