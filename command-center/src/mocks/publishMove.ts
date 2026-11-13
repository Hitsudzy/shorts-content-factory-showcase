// Подставной перенос размещённых роликов (CC-0166; фабрика CC-0165/CF-0856, договор 0.73.0):
// `POST …/{c}/move/plan {moves, unplace}` и `POST …/{c}/move/confirm {confirm, base_sha256}`.
// Как у фабрики: пачка правок судится целиком — порядок не важен, «25→24, 26→25 и 24-й в копилку»
// проходит, без возврата 24-го оба переноса — `day_taken`; вернуть в копилку можно только ролик,
// которого нет в журнале загрузок (`in_studio`); перенос ролика в Studio правит журнал и
// предупреждает строкой `STUDIO …` (дату в Studio ставит человек). Токен — одноразовый, на
// `life` секунд, только когда годится каждая правка; `batch_open` — только на «да», не в плане.
// Лишние поля и больше 60 правок — 422. `state.next` — исход «да» на выбор теста: `batch_open`,
// `check_changed`, `busy`. Импорты — относительные (общий для Vitest и Playwright).
// CC-0180 (договор 0.78.0, фабрика CF-0918): `withdraw` — снять ролик из Studio из ленты в запас
// копилки (отказы `not_in_studio`, `in_reserve`, `not_placed`, `published`; строка `STUDIO …`), день
// снятого можно занять в этом же плане; перенос ролика запаса — `reserve: true`, `from_day` null;
// день за горизонтом — строка `HORIZON …`, не отказ. Как у фабрики: `refusals` плана — все отказы
// правок с их слагом, `why` — первый из них.
import type { components } from '../api/schema.gen';
import { namesakesMessage } from './stash';

type S = components['schemas'];

export type MoveOutcome = 'batch_open' | 'check_changed' | 'busy';

export type MoveReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: string; details: string[] } };

/** Размещённый ролик канала: день, слот, есть ли строка журнала загрузок (он уже в Studio). */
export type MovePlaced = {
  slug: string;
  day: string;
  at: string;
  label: string;
  videoId: string | null;
  batch: string | null;
};

/** Что переносу нужно от остальной подставной публикации. */
export type MoveWorld = {
  channels: readonly string[];
  now: () => string;
  readOnly: () => boolean;
  hasSlot: (c: string) => boolean;
  /** Размещённые ролики канала (папки дней и журнал загрузок). */
  placed: (c: string) => MovePlaced[];
  /** Слот канала в день `day`: ISO и подпись фабрики. */
  slotOf: (c: string, day: string) => { at: string; label: string };
  /** Запас копилки: ролики, снятые из ленты (строка журнала с `withdrawn`). */
  reserve: (c: string) => { slug: string; videoId: string; batch: string | null }[];
  /** Строка журнала есть, пары в папке дня нет. */
  journalOnly: (c: string) => string[];
  /** Горизонт канала; null — старая фабрика. */
  horizon: (c: string) => S['StashHorizon'] | null;
  /** Записать: переносы (`from` null — из запаса), возвраты в копилку, снятия; тронутые файлы. */
  apply: (
    c: string,
    moves: {
      slug: string;
      from: string | null;
      to: string;
      videoId: string | null;
      batch: string | null;
    }[],
    unplace: { slug: string; day: string }[],
    withdraw: { slug: string; day: string; at: string; videoId: string }[],
  ) => string[];
};

/** Больше правок за раз фабрика не принимает. */
export const MOVE_MAX = 60;

/** Русские сообщения центра по коду отказа правки. */
export const MOVE_RU: Record<string, string> = {
  not_found: 'Ролика нет ни в папке дня, ни в журнале загрузок.',
  duplicate: 'Ролик назван в плане дважды.',
  in_studio: 'Ролик уже в Studio — вернуть его в копилку нельзя, только перенести на другой день.',
  bad_day: 'День не похож на дату ГГГГ-ММ-ДД.',
  same_day: 'Ролик уже стоит в этот день.',
  too_soon: 'Слот этого дня уже прошёл — переносить можно только на дни впереди.',
  day_taken:
    'В этот день уже стоит другой ролик — освободите день в этом же плане: перенесите его или верните в копилку.',
  not_in_studio:
    'Ролика нет в Studio (нет живой строки журнала загрузок) — снимать из ленты нечего; такой ролик возвращается в копилку обычным снятием со слота.',
  in_reserve:
    'Ролик уже снят из ленты и лежит в запасе копилки — снимать нечего; вернуть его можно переносом на день.',
  not_placed:
    'У ролика есть строка журнала загрузок, но нет пары в папке дня — забирать в копилку нечего; сначала поправьте запись.',
  published: 'Слот ролика уже прошёл — опубликованный ролик не переносится и не снимается.',
};

const DAY = /^\d{4}-\d{2}-\d{2}$/;

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

type Body = { moves: S['MoveEdit'][]; unplace: string[]; withdraw: string[] };

/** Тело плана как его проверяет pydantic фабрики: лишние поля — 422. */
function parse(raw: unknown): Body {
  const bad = (why: string) =>
    new Fault(422, 'invalid', 'Фабрика не приняла запрос: тело плана не по договору.', [why]);
  if (raw == null || typeof raw !== 'object' || Array.isArray(raw))
    throw bad('body is not an object');
  const b = raw as Record<string, unknown>;
  const extra = Object.keys(b).filter((k) => !['moves', 'unplace', 'withdraw'].includes(k));
  if (extra.length) throw bad(`extra fields: ${extra.join(', ')}`);
  const moves = b.moves ?? [];
  const unplace = b.unplace ?? [];
  const withdraw = b.withdraw ?? [];
  if (!Array.isArray(moves) || !Array.isArray(unplace) || !Array.isArray(withdraw))
    throw bad('moves, unplace and withdraw are lists');
  for (const m of moves) {
    if (!m || typeof m !== 'object') throw bad('a move is not an object');
    const keys = Object.keys(m as object);
    if (keys.some((k) => k !== 'slug' && k !== 'day' && k !== 'batch_id'))
      throw bad(`extra fields in a move`);
    const e = m as Record<string, unknown>;
    if (typeof e.slug !== 'string' || typeof e.day !== 'string') throw bad('slug and day are text');
  }
  if ([...unplace, ...withdraw].some((u) => typeof u !== 'string'))
    throw bad('unplace and withdraw are lists of names');
  const edits = moves.length + unplace.length + withdraw.length;
  if (edits > MOVE_MAX)
    throw new Fault(422, 'bad_order', `Больше ${MOVE_MAX} правок за раз фабрика не принимает.`, [
      `${edits} edits > ${MOVE_MAX}`,
    ]);
  return {
    moves: moves as S['MoveEdit'][],
    unplace: unplace as string[],
    withdraw: withdraw as string[],
  };
}

type Token = { channel: string; body: Body; base: string; expires: number };

export function createMove(world: MoveWorld) {
  const tokens = new Map<string, Token>();
  let n = 0;
  const state = {
    /** Исход следующего «да» (одноразово). */
    next: null as MoveOutcome | null,
    life: 120,
    calls: [] as { kind: 'plan' | 'confirm'; channel: string; body: unknown }[],
    written: [] as {
      channel: string;
      moves: S['MoveEdit'][];
      unplace: string[];
      withdraw: string[];
    }[],
  };

  /** Отпечаток размещения канала — `state_sha256` фабрики. */
  const baseOf = (c: string) => {
    const s = JSON.stringify([
      world.placed(c).map((p) => [p.slug, p.day, p.videoId]),
      world.reserve(c).map((r) => r.slug),
    ]);
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    return `sha256:${c}-${(h >>> 0).toString(16)}`;
  };

  const refusal = (code: S['MoveRefusal']['code'], slug: string | null, line: string) => ({
    code,
    slug,
    line,
    message: MOVE_RU[code] ?? code,
  });

  function check(c: string, b: Body) {
    if (!world.channels.includes(c)) throw new Fault(404, 'unknown_channel', `Канала ${c} нет.`);
    if (!world.hasSlot(c)) throw new Fault(409, 'no_queue', `У канала ${c} нет слота публикации.`);
    if (!b.moves.length && !b.unplace.length && !b.withdraw.length)
      throw new Fault(422, 'empty_order', 'Не названо ни одной правки.', [
        'moves, unplace and withdraw are empty',
      ]);
    const placed = world.placed(c);
    const reserve = world.reserve(c);
    // CC-0183 (CF-0920): `<батч>/<имя>` в `unplace` и `withdraw`, `batch_id` в `moves`; голое имя в
    // `unplace` и `withdraw` значит ролик в папке дня.
    const address = (raw: string) => {
      const parts = raw.split('/');
      return { raw, slug: parts.at(-1)!, batch: parts.at(-2) ?? null };
    };
    const placedOf = (slug: string, batch: string | null | undefined) =>
      placed.find((p) => p.slug === slug && (!batch || p.batch === batch));
    const reserveOf = (slug: string, batch: string | null | undefined) =>
      reserve.filter((r) => r.slug === slug && (!batch || r.batch === batch));
    const journalOnly = new Set(world.journalOnly(c));
    const horizon = world.horizon(c);
    const today = world.now().slice(0, 10);
    const named = new Map<string, number>();
    const nameKey = (slug: string, batch: string | null | undefined) =>
      batch ? `${batch}/${slug}` : slug;
    for (const s of [
      ...b.unplace,
      ...b.withdraw,
      ...b.moves.map((m) => nameKey(m.slug, m.batch_id)),
    ])
      named.set(s, (named.get(s) ?? 0) + 1);

    const unplaceItems: S['MoveItem'][] = b.unplace.map((raw) => {
      const { slug, batch } = address(raw);
      const p = placedOf(slug, batch);
      const refusals: S['MoveRefusal'][] = [];
      if (!p) refusals.push(refusal('not_found', slug, `${slug}: not placed in publish/${c}/`));
      else if ((named.get(raw) ?? 0) > 1)
        refusals.push(refusal('duplicate', slug, `${slug}: named twice`));
      else if (p.videoId)
        refusals.push(
          refusal('in_studio', slug, `${slug}: in the upload journal (${p.videoId}) - only a move`),
        );
      return {
        op: 'unplace',
        slug,
        batch_id: p?.batch ?? null,
        video_id: p?.videoId ?? null,
        in_studio: !!p?.videoId,
        reserve: false,
        ok: !refusals.length,
        from_day: p?.day ?? null,
        from_slot: p?.at ?? null,
        day: null,
        slot: null,
        label: null,
        refusals,
        warnings: [],
        path: null,
        journal: null,
      };
    });

    const withdrawItems: S['MoveItem'][] = b.withdraw.map((raw) => {
      const { slug, batch } = address(raw);
      const p = placedOf(slug, batch);
      const r = p ? undefined : reserveOf(slug, batch)[0];
      const refusals: S['MoveRefusal'][] = [];
      if (!p && !r && !journalOnly.has(slug))
        refusals.push(refusal('not_found', slug, `${slug}: not placed in publish/${c}/`));
      else if ((named.get(raw) ?? 0) > 1)
        refusals.push(refusal('duplicate', slug, `${slug}: named twice`));
      else if (r)
        refusals.push(refusal('in_reserve', slug, `${slug}: already withdrawn into the копилка`));
      else if (journalOnly.has(slug))
        refusals.push(refusal('not_placed', slug, `${slug}: a journal row with no pair in a day`));
      else if (!p?.videoId)
        refusals.push(refusal('not_in_studio', slug, `${slug}: no live row of the upload journal`));
      else if (Date.parse(p.at) < Date.parse(world.now()))
        refusals.push(refusal('published', slug, `${slug}: the slot of ${p.day} has passed`));
      return {
        op: 'withdraw',
        slug,
        batch_id: p?.batch ?? r?.batch ?? null,
        video_id: p?.videoId ?? r?.videoId ?? null,
        in_studio: !!(p?.videoId ?? r?.videoId),
        reserve: false,
        ok: !refusals.length,
        from_day: p?.day ?? null,
        from_slot: p?.at ?? null,
        day: null,
        slot: null,
        label: null,
        refusals,
        warnings: [],
        path: null,
        journal: null,
      };
    });

    const moveItems: S['MoveItem'][] = b.moves.map(({ slug, batch_id, day }) => {
      const p = placedOf(slug, batch_id);
      const rs = p ? [] : reserveOf(slug, batch_id);
      const r = rs[0];
      const refusals: S['MoveRefusal'][] = [];
      // CC-0183: голое имя двух роликов — фабрика не может сказать, какой: `ambiguous`.
      const twins = [
        ...placed.filter((x) => x.slug === slug),
        ...reserve.filter((x) => x.slug === slug),
      ].map((x) => x.batch ?? '?');
      if (!p && !r)
        refusals.push(refusal('not_found', slug, `${slug}: not placed in publish/${c}/`));
      else if (!batch_id && twins.length > 1)
        refusals.push({
          ...refusal('ambiguous', slug, `${slug}: two videos of the name`),
          message: namesakesMessage(slug, twins),
        });
      else if ((named.get(nameKey(slug, batch_id)) ?? 0) > 1)
        refusals.push(refusal('duplicate', slug, `${slug}: named twice`));
      else if (!DAY.test(day)) refusals.push(refusal('bad_day', slug, `${slug}: bad day ${day}`));
      else if (day === p?.day)
        refusals.push(refusal('same_day', slug, `${slug}: already on ${day}`));
      else if (day <= today || Date.parse(world.slotOf(c, day).at) < Date.parse(world.now()))
        refusals.push(refusal('too_soon', slug, `${slug}: the slot of ${day} has passed`));
      const slot = DAY.test(day) ? world.slotOf(c, day) : null;
      return {
        op: 'move',
        slug,
        batch_id: p?.batch ?? r?.batch ?? null,
        video_id: p?.videoId ?? r?.videoId ?? null,
        in_studio: !!(p?.videoId ?? r?.videoId),
        reserve: !!r,
        ok: !refusals.length,
        from_day: p?.day ?? null,
        from_slot: p?.at ?? null,
        day,
        slot: slot?.at ?? null,
        label: slot?.label ?? null,
        refusals,
        warnings: [],
        path: null,
        journal: null,
      };
    });

    // Пачка целиком: где окажется каждый ролик, если пройдут годные правки. Отказанный перенос
    // оставляет ролик на месте — он занимает свой день и для следующих (до неподвижной точки).
    for (let changed = true; changed;) {
      changed = false;
      const leaving = new Set(
        [...unplaceItems, ...withdrawItems, ...moveItems]
          .filter((i) => i.ok && i.from_day)
          .map((i) => i.slug),
      );
      const count = new Map<string, number>();
      for (const p of placed)
        if (!leaving.has(p.slug)) count.set(p.day, (count.get(p.day) ?? 0) + 1);
      for (const i of moveItems) if (i.ok) count.set(i.day!, (count.get(i.day!) ?? 0) + 1);
      for (const i of moveItems) {
        if (!i.ok || (count.get(i.day!) ?? 0) <= 1) continue;
        const other = placed.find((p) => p.day === i.day && !leaving.has(p.slug));
        i.refusals.push(
          refusal(
            'day_taken',
            i.slug,
            `${i.slug}: ${i.day} is taken${other ? ` by ${other.slug}` : ' by another move'}`,
          ),
        );
        i.ok = false;
        changed = true;
      }
    }
    for (const i of withdrawItems)
      if (i.ok)
        i.warnings.push(
          `STUDIO ${i.slug} (${i.video_id}): in Studio it must be taken off its schedule - «Ограниченный доступ», no publication date - by a human or the center on the user's word; this tool writes the journal and the копилка only (CF-0918)`,
        );
    for (const i of moveItems) {
      if (!i.ok) continue;
      if (horizon && i.day! > horizon.last_day)
        i.warnings.push(
          `HORIZON ${i.slug}: ${i.label} is past the channel's horizon (${horizon.days} дн., до ${horizon.last_day} МСК; CF-0918) - the day is the user's, written as named`,
        );
      if (i.reserve)
        i.warnings.push(
          `STUDIO ${i.slug} (${i.video_id}) comes back from the копилка: in Studio set «Отложенная публикация» on ${i.label} (it stands at «Ограниченный доступ») - a human or the center on the user's word; no new upload (CF-0918)`,
        );
      else if (i.in_studio)
        i.warnings.push(
          `STUDIO ${i.slug} (${i.video_id}) is in Studio: the date there is set by a human or the center on the user's word - this tool writes the journal only (it must read ${i.label} in Studio)`,
        );
    }

    const items = [...unplaceItems, ...withdrawItems, ...moveItems];
    const lines = items.map((i) =>
      !i.ok
        ? `${i.slug}: REFUSED ${i.refusals[0]!.code}`
        : i.op === 'unplace'
          ? `${i.slug}: ${i.from_day} -> publish/${c}/_queue/`
          : i.op === 'withdraw'
            ? `${i.slug}: ${i.from_day} -> publish/${c}/_reserve/`
            : `${i.slug}: ${i.from_day ?? 'the reserve'} -> ${i.label}`,
    );
    const ok = items.every((i) => i.ok);
    const refusals = items.flatMap((i) => i.refusals);
    return {
      ok,
      items,
      refusals,
      lines: [...lines, ...items.flatMap((i) => i.warnings)],
      moved: moveItems.filter((i) => i.ok).length,
      unplaced: unplaceItems.filter((i) => i.ok).length,
      withdrawn: withdrawItems.filter((i) => i.ok).length,
      why: refusals[0]?.message ?? null,
    };
  }

  function fail(e: unknown): MoveReply {
    if (e instanceof Fault)
      return { status: e.status, body: { message: e.message, code: e.code, details: e.details } };
    throw e;
  }

  const readOnly = () =>
    new Fault(
      409,
      'not_working_factory',
      'Только смотреть: рабочая копия на ветке cc-api, а не main',
      ['CC_API_WRITES is off'],
    );

  const head = (c: string, b: Body) => ({
    action: 'publish_move' as const,
    channel: c,
    task: 'CF-0856',
    moves: b.moves,
    unplace: b.unplace,
    withdraw: b.withdraw,
    warnings: [] as string[],
    ledger: 'перенос не трогает учёт ротации: ролик уже снят с очереди сценариев',
    by: 'user',
    via: 'center',
  });

  function plan(c: string, raw: unknown): MoveReply {
    state.calls.push({ kind: 'plan', channel: c, body: raw });
    try {
      if (world.readOnly()) throw readOnly();
      const b = parse(raw);
      const out = check(c, b);
      const base = baseOf(c);
      let confirm: string | null = null;
      if (out.ok) {
        confirm = `publish-move-${++n}`;
        tokens.set(confirm, { channel: c, body: b, base, expires: Date.now() + state.life * 1000 });
      }
      const body: S['MovePlan'] = {
        ...head(c, b),
        ...out,
        dry_run: true,
        base_sha256: base,
        sha256: base,
        fingerprint: `${base}/${out.items.length}`,
        confirm,
        expires_in_s: confirm ? state.life : null,
      };
      return { status: 200, body };
    } catch (e) {
      return fail(e);
    }
  }

  function confirm(c: string, raw: unknown): MoveReply {
    state.calls.push({ kind: 'confirm', channel: c, body: raw });
    try {
      if (world.readOnly()) throw readOnly();
      const r = (raw ?? {}) as { confirm?: string; base_sha256?: string | null };
      const got = tokens.get(r.confirm ?? '');
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
      tokens.delete(r.confirm!);
      if (got.channel !== c)
        throw new Fault(409, 'confirm_mismatch', 'Подтверждение выдано другому каналу.', [
          `token of ${got.channel}`,
        ]);
      if (got.expires <= Date.now())
        throw new Fault(409, 'confirm_expired', 'Подтверждение устарело (живёт 120 с).', [
          'expired',
        ]);
      if (next === 'batch_open')
        throw new Fault(409, 'batch_open', 'Идёт батч — слоты переносят, когда он закончится.', [
          `pipeline/${c}/2026-10-10T0200Z: batch is running`,
        ]);
      const now = baseOf(c);
      if (next === 'check_changed' || now !== got.base || (r.base_sha256 && r.base_sha256 !== now))
        throw new Fault(
          409,
          'check_changed',
          'Слоты или журнал загрузок изменились с момента плана.',
          [`base ${r.base_sha256 ?? got.base} != ${now}`],
        );
      const out = check(c, got.body);
      const touched = world.apply(
        c,
        out.items
          .filter((i) => i.op === 'move')
          .map((i) => ({
            slug: i.slug,
            from: i.from_day ?? null,
            to: i.day!,
            videoId: i.video_id ?? null,
            batch: i.batch_id ?? null,
          })),
        out.items
          .filter((i) => i.op === 'unplace')
          .map((i) => ({ slug: i.slug, day: i.from_day! })),
        out.items
          .filter((i) => i.op === 'withdraw')
          .map((i) => ({
            slug: i.slug,
            day: i.from_day!,
            at: i.from_slot!,
            videoId: i.video_id!,
          })),
      );
      state.written.push({
        channel: c,
        moves: got.body.moves,
        unplace: got.body.unplace,
        withdraw: got.body.withdraw,
      });
      const body: S['MoveResult'] = {
        ...head(c, got.body),
        ...out,
        dry_run: false,
        items: out.items.map((i) => ({
          ...i,
          path:
            i.op === 'unplace'
              ? `publish/${c}/_queue/${i.slug}.md`
              : i.op === 'withdraw'
                ? `publish/${c}/_reserve/${i.slug}.md`
                : (touched.find((t) => t === `publish/${c}/${i.day}/${i.slug}.md`) ?? null),
          journal: !i.in_studio
            ? null
            : i.op === 'withdraw'
              ? { from_at: i.from_slot, to_at: null }
              : i.op === 'move'
                ? { from_at: i.from_slot, to_at: i.slot }
                : null,
        })),
        base_sha256: got.base,
        sha256: got.base,
        written: true,
        new_sha256: baseOf(c),
        commit: '5d1e7a90c3b2f4e6',
        touched,
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

  return { state, plan, confirm, expireTokens };
}

export type MoveBackend = ReturnType<typeof createMove>;

/** `POST …/{c}/move/plan` и `POST …/{c}/move/confirm`; null — не адрес переноса. */
export function routeMove(
  m: MoveBackend,
  method: string,
  rest: string[],
  body: unknown,
): MoveReply | null {
  const [c, what, step] = rest;
  if (!c || what !== 'move' || method !== 'POST' || rest.length !== 3) return null;
  if (step === 'plan') return m.plan(c, body);
  if (step === 'confirm') return m.confirm(c, body);
  return null;
}
