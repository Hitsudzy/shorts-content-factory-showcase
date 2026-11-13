// Подставной ввод прочитанного в Studio (CC-0074 фабрики, договор 0.25.0; экран — CC-0077):
// `…/studio/record/plan {read}` — упрощённый `studio_read.parse_read` (доли из строк по подписям
// «Досмотрели»/«Пролистали», замечания по-английски, как у фабрики, отказ `read_refused` строкой
// `ReadError`), у каждого ролика — его последнее сохранённое чтение (`stored`); одноразовый токен на
// `life` секунд. `…/studio/record {confirm}` — токен сгорает при любом исходе, кроме `busy`;
// проверка пересчитывается и сверяется с отпечатком (`check_changed`), потом — запись: чтения
// роликов (`added|replaced|unchanged`), строка посещения.
// Ручки теста: `life`, `next` (исход следующего «да»: `busy`, `check_changed`, `factory_broken`),
// `planNext` (отказ следующего плана: `journal_unreadable`, `store_unreadable`, `factory_broken`),
// `readOnly` (каждый POST — 409 `not_working_factory`), `calls`, `written`. Импорты — относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];
type Code = S['StudioWriteProblem']['code'] | 'not_working_factory';

export type StudioEntryReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: Code; details: string[] } };

export type StudioEntryOutcome = 'busy' | 'check_changed' | 'factory_broken';
export type StudioPlanOutcome = 'journal_unreadable' | 'store_unreadable' | 'factory_broken';

/** Последнее чтение ролика, что лежит у канала; записывает новое. */
export type StudioWorld = {
  channels: () => readonly string[];
  /** Ролики канала по журналу загрузок: id → entry_id. */
  journal: (c: string) => Record<string, string>;
  latest: (c: string, videoId: string) => S['StudioReadRow'] | null;
  store: (c: string, row: S['StudioReadRow']) => void;
  /** Строка посещения легла (последнее посещение). */
  visit: (c: string, line: Record<string, unknown>) => void;
  lastVisitAt: (c: string) => string | null;
};

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

const refused = (line: string) =>
  new Fault(422, 'read_refused', line, ['studio_read.ReadError', 'nothing written']);

const HOOKS = ['upload', 'batch-start', 'daily', 'manual'];
const VIEWED = [
  'досмотрели',
  'посмотрели',
  'смотрели',
  'продолжили просмотр',
  'продолжили смотреть',
  'viewed',
  'chose to view',
  'stayed to watch',
];
const SWIPED = ['пролистали', 'пролистнули', 'не стали смотреть', 'swiped away', 'swiped'];
const LABELS = [
  ...VIEWED.map((w) => [w, 'viewed'] as const),
  ...SWIPED.map((w) => [w, 'swiped'] as const),
].sort((a, b) => b[0].length - a[0].length);
const esc = (w: string) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const LABEL_RE = new RegExp(
  `(?<![\\p{L}\\d_])(${LABELS.map(([w]) => esc(w)).join('|')})(?![\\p{L}\\d_])`,
  'giu',
);
const LABEL_OF = Object.fromEntries(LABELS) as Record<string, 'viewed' | 'swiped'>;
const PCT_RE = /(?<![\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*%/g;
const NOT_ENOUGH = /недостаточно данных|not enough data/i;
const NOT_ENOUGH_NOTE =
  'not enough data yet: Studio shows no share for this video («Статистика пока недоступна: недостаточно данных.») - normal for a new video';
const ID_RE = /^[A-Za-z0-9_-]{11}$/;
const URL_ID_RE =
  /(?:youtube\.com\/shorts\/|youtu\.be\/|studio\.youtube\.com\/video\/|[?&]v=)([A-Za-z0-9_-]{11})/;

const clean = (t: unknown) => (typeof t === 'string' ? t.replace(/\s+/g, ' ').trim() : '');

function linesOf(o: Record<string, unknown>): string[] {
  const raw = o.lines ?? o.text;
  if (raw == null) return [];
  const list = typeof raw === 'string' ? raw.split(/\r?\n/) : raw;
  if (!Array.isArray(list))
    throw refused(`\`lines\` ${JSON.stringify(raw)}: give a list of strings or one text`);
  return list.map(clean).filter(Boolean);
}

function pct(v: unknown): number | null {
  if (v == null || typeof v === 'boolean') return null;
  let x: number;
  if (typeof v === 'number') x = v;
  else {
    const m = new RegExp(PCT_RE.source).exec(clean(v));
    if (!m) return null;
    x = Number(m[1]!.replace(',', '.'));
  }
  return x >= 0 && x <= 100 ? Math.round(x * 100) / 100 : null;
}

function sharesFromLines(lines: string[]) {
  const text = lines.join('\n');
  const labels = [...text.matchAll(LABEL_RE)].map((m) => ({
    start: m.index,
    end: m.index + m[0].length,
    metric: LABEL_OF[m[1]!.toLowerCase()]!,
  }));
  const found: Record<'viewed' | 'swiped', number[]> = { viewed: [], swiped: [] };
  const warnings: string[] = [];
  labels.forEach((l, i) => {
    const stop = labels[i + 1]?.start ?? text.length;
    const vals = [...text.slice(l.end, stop).matchAll(PCT_RE)].map((m) =>
      Number(m[1]!.replace(',', '.')),
    );
    if (vals.length) {
      found[l.metric].push(vals[0]!);
      if (vals.length > 1)
        warnings.push(
          `${l.metric}: extra percents after the label ignored: ${JSON.stringify(vals.slice(1))}`,
        );
    }
  });
  const out: Record<'viewed' | 'swiped', number | null> = { viewed: null, swiped: null };
  for (const metric of ['viewed', 'swiped'] as const) {
    const uniq = [...new Set(found[metric])].sort((a, b) => a - b);
    if (uniq.length === 1 && uniq[0]! >= 0 && uniq[0]! <= 100) out[metric] = uniq[0]!;
    else if (uniq.length > 1)
      warnings.push(
        `${metric}: two different values in the lines ${JSON.stringify(uniq)} - not chosen`,
      );
  }
  return { out, warnings, onPage: new Set(labels.map((l) => l.metric)) };
}

function instant(text: unknown): string {
  const t = String(text);
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(t) || Number.isNaN(Date.parse(t))) {
    if (Number.isNaN(Date.parse(t)))
      throw refused(`read_at '${t}': give an ISO time with its zone`);
    throw refused(`read_at '${t}': no zone`);
  }
  return new Date(Date.parse(t)).toISOString().slice(0, 19) + 'Z';
}

/** Упрощённый `studio_read.parse_read`: проверить и разобрать, ничего не писать. */
export function parseRead(world: StudioWorld, channel: string, doc: unknown) {
  if (!doc || typeof doc !== 'object' || Array.isArray(doc))
    throw refused('the read is not a JSON object');
  const d = doc as Record<string, unknown>;
  const ch = clean(d.channel);
  if (!ch) throw refused('no `channel` in the read - which channel was Studio showing?');
  if (ch !== channel) throw refused(`--channel ${channel} but the read is of ${ch}`);
  if (!d.read_at) throw refused('no `read_at` - when was the page read (ISO with zone)?');
  const read_at = instant(d.read_at);
  const hook = clean(d.hook);
  if (!HOOKS.includes(hook)) throw refused(`hook '${hook}': one of ${HOOKS.join(', ')}`);
  const journal = world.journal(ch);
  const others = world
    .channels()
    .filter((c) => c !== ch)
    .flatMap((c) => Object.keys(world.journal(c)).map((id) => [id, c] as const));
  const warnings: string[] = [];
  let raw = d.videos;
  if (raw == null) {
    warnings.push('videos: not read this visit (no `videos`)');
    raw = [];
  }
  if (!Array.isArray(raw)) throw refused('`videos` is not a list');
  const videos: S['StudioParsedVideo'][] = [];
  const unstored: S['StudioUnstored'][] = [];
  for (const o of raw as unknown[]) {
    if (!o || typeof o !== 'object') throw refused(`video ${JSON.stringify(o)}: not an object`);
    const obj = o as Record<string, unknown>;
    const lines = linesOf(obj);
    let vid: string | null = null;
    if (obj.video_id != null) {
      vid = String(obj.video_id);
      if (!ID_RE.test(vid)) throw refused(`video_id '${vid}': not an 11-character YouTube id`);
    } else if (typeof obj.url === 'string') vid = URL_ID_RE.exec(obj.url)?.[1] ?? null;
    const { out, warnings: w, onPage } = sharesFromLines(lines);
    const notEnough = lines.some((l) => NOT_ENOUGH.test(l));
    const shares: Record<'viewed' | 'swiped', number | null> = { viewed: null, swiped: null };
    for (const metric of ['viewed', 'swiped'] as const) {
      const givenRaw = obj[metric];
      const given = pct(givenRaw);
      if (givenRaw != null && givenRaw !== '' && given == null)
        w.push(`${metric}: ${JSON.stringify(givenRaw)} is not a share`);
      const seen = out[metric];
      if (given != null && seen != null && Math.abs(given - seen) > 0.05) {
        w.push(`${metric}: recognised ${given} but the lines say ${seen} - not chosen`);
        shares[metric] = null;
      } else shares[metric] = given ?? seen;
      if (shares[metric] == null && !w.some((x) => x.startsWith(metric))) {
        const none = givenRaw == null || givenRaw === '';
        if (metric === 'swiped' && !onPage.has('swiped') && none) continue;
        if (notEnough && !onPage.has(metric) && none) continue;
        w.push(`${metric}: not recognised in the lines`);
      }
    }
    const { viewed: v, swiped: s } = shares;
    if (v != null && s != null && Math.abs(v + s - 100) > 1)
      w.push(`viewed ${v} + swiped ${s} = ${Math.round((v + s) * 100) / 100}, not ~100`);
    const entry = vid ? (journal[vid] ?? null) : null;
    if (vid && entry == null) w.push(`${vid}: not in publish/uploads.json of ${ch}`);
    const note = notEnough && v == null && s == null ? NOT_ENOUGH_NOTE : null;
    const period_text = clean(obj.period_text) || null;
    if (period_text == null && note == null)
      w.push('period_text: the period the shares cover was not copied');
    const title = clean(obj.title) || null;
    if (!vid) {
      unstored.push({ title, raw_lines: lines, warnings: [...w, 'no video id - not stored'] });
      continue;
    }
    const other = others.find(([id]) => id === vid);
    if (other)
      throw refused(
        `video ${vid} is of channel ${other[1]} in publish/uploads.json, not ${ch} - Studio was showing another channel; nothing written`,
      );
    if (videos.some((x) => x.video_id === vid)) throw refused(`video ${vid} is twice in one read`);
    videos.push({
      kind: 'studio',
      channel: ch,
      video_id: vid,
      entry_id: entry,
      read_at,
      hook,
      period_text,
      viewed_pct: v,
      swiped_pct: s,
      raw_lines: lines,
      warnings: w,
      note,
      title,
      stored: world.latest(ch, vid),
    });
  }
  return {
    channel: ch,
    read_at,
    hook,
    ui_language: clean(d.ui_language) || 'ru',
    videos,
    unstored,
    warnings,
  };
}

type Parsed = ReturnType<typeof parseRead>;

export function createStudioEntry(world: StudioWorld) {
  const tokens = new Map<string, { channel: string; read: unknown; fp: string; expires: number }>();
  let n = 0;
  const state = {
    /** Срок жизни токена, секунд (у фабрики — 120). */
    life: 120,
    /** Исход следующего «да» (одноразово). */
    next: null as StudioEntryOutcome | null,
    /** Отказ следующего плана (одноразово). */
    planNext: null as StudioPlanOutcome | null,
    /** API не на рабочей фабрике: каждый POST — 409 `not_working_factory`. */
    readOnly: false,
    calls: [] as { kind: 'plan' | 'confirm'; channel: string; body: unknown }[],
    written: [] as { channel: string; read: unknown }[],
  };

  const fingerprint = (c: string, parsed: Parsed) =>
    JSON.stringify([
      parsed,
      parsed.videos.map((v) => world.latest(c, v.video_id)),
      world.lastVisitAt(c),
    ]);

  const guard = (c: string) => {
    if (state.readOnly)
      throw new Fault(
        409,
        'not_working_factory',
        'Только смотреть: рабочая копия на ветке cc-api, а не main',
        ['CC_API_WRITES is off'],
      );
    if (!world.channels().includes(c))
      throw new Fault(404, 'unknown_channel', `Канала ${c} нет в журнале загрузок.`, [
        `channels/${c}.json: not found`,
      ]);
  };

  const planFault = (o: StudioPlanOutcome) =>
    o === 'journal_unreadable'
      ? new Fault(409, 'journal_unreadable', 'Журнал загрузок publish/uploads.json не читается.', [
          "publish/uploads.json line 3: Expecting ',' delimiter",
        ])
      : o === 'store_unreadable'
        ? new Fault(409, 'store_unreadable', 'Хранилище статистики канала не читается.', [
            "analytics/example-film/studio.jsonl line 7: Expecting ',' delimiter",
          ])
        : new Fault(500, 'factory_broken', 'Фабрика ответила ошибкой — посмотрите её состояние.', [
            'OSError: disk full',
          ]);

  function plan(c: string, raw: unknown): StudioEntryReply {
    state.calls.push({ kind: 'plan', channel: c, body: raw });
    try {
      guard(c);
      const o = state.planNext;
      state.planNext = null;
      if (o) throw planFault(o);
      const read = (raw as { read?: unknown } | null)?.read;
      const parsed = parseRead(world, c, read);
      const fp = fingerprint(c, parsed);
      const confirm = `studio-${++n}`;
      tokens.set(confirm, { channel: c, read, fp, expires: Date.now() + state.life * 1000 });
      return {
        status: 200,
        body: {
          action: 'studio_read_record',
          ok: true,
          why: null,
          fingerprint: `sha256:${fp.length}-${n}`,
          confirm,
          expires_in_s: state.life,
          ...parsed,
          recorded_by: 'user',
          via: 'center',
        } satisfies S['StudioReadRecordPlan'],
      };
    } catch (e) {
      if (e instanceof Fault) return fault(e);
      throw e;
    }
  }

  function confirm(c: string, raw: unknown): StudioEntryReply {
    state.calls.push({ kind: 'confirm', channel: c, body: raw });
    try {
      guard(c);
      const token = (raw as { confirm?: string } | null)?.confirm ?? '';
      const got = tokens.get(token);
      if (!got)
        throw new Fault(
          409,
          'confirm_unknown',
          'Подтверждение не найдено или уже использовано - запросите план заново.',
          [`no token ${token}`],
        );
      const next = state.next;
      state.next = null;
      if (next === 'busy')
        throw new Fault(
          409,
          'busy',
          'Идёт другая запись чтения Studio - подождите и нажмите ещё раз.',
          ['the Studio write lock was not free in 30.0 s; the token is not spent'],
        );
      tokens.delete(token);
      if (got.channel !== c)
        throw new Fault(
          409,
          'confirm_mismatch',
          `Подтверждение выдано для ${got.channel}, а не для ${c} - ничего не записано.`,
          ['the token is spent'],
        );
      if (got.expires <= Date.now())
        throw new Fault(
          409,
          'confirm_expired',
          'Подтверждение устарело (живёт 120 с) - запросите план заново.',
          ['expired'],
        );
      if (next === 'factory_broken')
        throw new Fault(
          500,
          'factory_broken',
          'Фабрика ответила ошибкой посреди записи - посмотрите состояние, прежде чем повторять.',
          ['OSError: disk full'],
        );
      const parsed = parseRead(world, c, got.read);
      if (next === 'check_changed' || fingerprint(c, parsed) !== got.fp)
        throw new Fault(
          409,
          'check_changed',
          'Прочитанное или хранилище изменились с момента плана - посмотрите план заново.',
          ["the fingerprint of the studio_read_record plan differs from the plan's"],
        );
      const studio = { added: 0, replaced: 0, unchanged: 0 };
      for (const v of parsed.videos) {
        const was = world.latest(c, v.video_id);
        const same =
          was?.read_at === v.read_at &&
          was.viewed_pct === v.viewed_pct &&
          was.swiped_pct === v.swiped_pct;
        if (was?.read_at === v.read_at) studio[same ? 'unchanged' : 'replaced']++;
        else studio.added++;
        if (!same)
          world.store(c, {
            channel: c,
            video_id: v.video_id,
            entry_id: v.entry_id ?? null,
            read_at: v.read_at,
            hook: v.hook,
            period_text: v.period_text ?? null,
            viewed_pct: v.viewed_pct ?? null,
            swiped_pct: v.swiped_pct ?? null,
            raw_lines: v.raw_lines ?? [],
            warnings: v.warnings ?? [],
            note: v.note ?? null,
            recorded_at: new Date().toISOString(),
            recorded_by: 'user',
            via: 'center',
          });
      }
      const logged = world.lastVisitAt(c) !== parsed.read_at;
      if (logged)
        world.visit(
          c,
          {
            read_at: parsed.read_at,
            hook: parsed.hook,
            ui_language: parsed.ui_language,
            recorded_at: new Date().toISOString(),
            recorded_by: 'user',
            via: 'center',
            videos_read: parsed.videos.length + parsed.unstored.length,
            videos_stored: parsed.videos.length,
            warnings: parsed.warnings,
          },
        );
      state.written.push({ channel: c, read: got.read });
      return {
        status: 200,
        body: {
          action: 'studio_read_record',
          channel: c,
          written: true,
          read_at: parsed.read_at,
          hook: parsed.hook,
          recorded_by: 'user',
          via: 'center',
          studio,
          visit_logged: logged,
        } satisfies S['StudioReadRecordResult'],
      };
    } catch (e) {
      if (e instanceof Fault) return fault(e);
      throw e;
    }
  }

  /** Все выданные токены устарели (как будто прошло 120 с) — «да» получит `confirm_expired`. */
  const expireTokens = () => {
    for (const t of tokens.values()) t.expires = 0;
  };

  return { state, plan, confirm, expireTokens };
}

const fault = (e: Fault): StudioEntryReply => ({
  status: e.status,
  body: { message: e.message, code: e.code, details: e.details },
});

export type StudioEntry = ReturnType<typeof createStudioEntry>;
