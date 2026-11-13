// Подставная правка списков канала (CC-0115 шаг 3 → CC-0114 API): `POST /api/channels/{c}/
// (fact-sources|footage-origin|affiliate)/plan {doc, base_sha256}`
// → `…/{list} {confirm}`. План отказа не бросает: `ok: false`, `refusals`, `why`; «да» отказывает
// задачей `{message, code, details}`. Переключатели теста: `refuse` — код отказа плана,
// `actRefuse` — код отказа «да», `busy`, `expireTokens()`; `check_changed` — когда `base_sha256`
// не тот, что у файла сейчас. Чтение и запись документа — снаружи (`access`): данные канала
// (./channelData) и списки (./rights) держат свои файлы. Импорты — относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];
type Reply<T> = { status: number; body: T };
type Problem = S['ChannelListProblem'];
type Code = Problem['code'];

export type ListName = 'fact-sources' | 'footage-origin' | 'affiliate';
type Doc = Record<string, unknown>;

const ACTION: Record<ListName, S['ChannelListPlan']['action']> = {
  'fact-sources': 'fact_sources_write',
  'footage-origin': 'footage_origin_write',
  affiliate: 'affiliate_write',
};

const FILE: Record<ListName, string> = {
  'fact-sources': 'fact-sources.json',
  'footage-origin': 'footage-origin.json',
  affiliate: 'affiliate.json',
};

const NOTHING = 'ничего не записано';

/** Строки API для кодов (api/channel_lists.py): статус и русская строка. */
export const LIST_REFUSALS: Partial<Record<Code, [number, string]>> = {
  invalid: [422, `Список не прошёл проверку фабрики - ${NOTHING}; что не так, в подробностях.`],
  batch_open: [409, 'Пока идёт батч канала, его списки не пишутся - повторите после батча.'],
  check_changed: [
    409,
    `Список изменился с тех пор, как вы его открыли - откройте заново, ${NOTHING}.`,
  ],
  locked: [409, 'Список сейчас пишет кто-то другой - подождите и повторите.'],
  not_repo: [409, `Корень фабрики - не git-репозиторий: список не закоммитить, ${NOTHING}.`],
  commit_refused: [409, 'Git не принял коммит списка - файл возвращён как был.'],
  write_failed: [500, 'Список не записался - посмотрите диск, прежде чем повторять.'],
};

/** Детерминированный «sha256» документа подставной фабрики. */
export function standInSha(doc: unknown): string {
  const text = JSON.stringify(doc);
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193) >>> 0;
  return h.toString(16).padStart(8, '0').repeat(8);
}

const CHANNEL_ID = /^UC[0-9A-Za-z_-]{22}$/;
const repr = (v: unknown) => (v == null ? 'None' : `'${String(v)}'`);
const docs = (v: unknown) => (Array.isArray(v) ? (v as Doc[]) : []);

/**
 * Происхождение футажа — как `channel_list_write.footage_origin_errors` (CC-0130), коротко: у Reel
 * правило `official_channels`, у Science/Tech — главное из `footage_licence.footage_origin_errors`.
 */
function footageLines(d: Doc): string[] {
  const out: string[] = [];
  if (!('footage_origins' in d) && !('licences' in d)) {
    if (!Array.isArray(d.official_channels)) return ['no `official_channels` list'];
    docs(d.official_channels).forEach((e, i) => {
      const ctx = `official_channels[${i}] (${String(e.pattern ?? 'None')})`;
      if (typeof e.pattern !== 'string' || !e.pattern.trim()) out.push(`${ctx}: no \`pattern\``);
      docs(e.channels).forEach((ch, j) => {
        if (!CHANNEL_ID.test(String(ch.id)))
          out.push(`${ctx}: channels[${j}].id ${repr(ch.id)} is not a YouTube channel id`);
      });
    });
    return out;
  }
  const lic = d.licences as Doc | undefined;
  if (!lic || typeof lic !== 'object') return ['no `licences` block'];
  const ids = new Set(docs(lic.accepted).map((a) => a.id));
  if (!ids.size) out.push('licences.accepted is empty');
  const origins = docs(d.footage_origins);
  if (!origins.length) out.push('no `footage_origins` list');
  const oids = new Set(origins.map((o) => o.id));
  origins.forEach((o, i) => {
    const ctx = `footage_origins[${i}] (${String(o.id)})`;
    if (o.licence !== 'per_file' && !ids.has(o.licence))
      out.push(`${ctx}: licence ${repr(o.licence)} is neither an accepted licence nor 'per_file'`);
    const t = o.terms_url;
    if (o.licence !== 'youtube_upload' && !(typeof t === 'string' && t.startsWith('https://')))
      out.push(`${ctx}: no https \`terms_url\` - the page its licence was read on`);
    const how = docs(o.found_by);
    if (!how.length) out.push(`${ctx}: no \`found_by\``);
    how.forEach((h, j) => {
      if (typeof h.works_now !== 'boolean')
        out.push(`${ctx}: found_by[${j}] does not say \`works_now\``);
    });
    const a = o.attribution as Doc | undefined;
    if (!a || typeof a.credit !== 'string' || !a.credit.trim())
      out.push(
        `${ctx}: \`attribution\` needs \`credit\`, \`where\` (description | description+on_screen) and \`on_screen\``,
      );
  });
  docs(d.official_channels).forEach((e, i) => {
    const ctx = `official_channels[${i}] (${String(e.pattern ?? 'None')})`;
    if (!oids.has(e.origin)) out.push(`${ctx}: origin ${repr(e.origin)} is not a footage origin`);
    docs(e.channels).forEach((ch, j) => {
      if (!CHANNEL_ID.test(String(ch.id)))
        out.push(`${ctx} channels[${j}]: ${repr(ch.id)} is not a YouTube channel id`);
      if (!/^@/.test(String(ch.handle ?? '')))
        out.push(`${ctx} channels[${j}]: no @handle it was resolved from`);
    });
  });
  return out;
}

/** Проверка документа «фабрикой»: строки ошибок (пусто — годен). */
function invalidLines(list: ListName, doc: Doc | Doc[]): string[] {
  const d = doc as Doc;
  if (list === 'fact-sources') {
    const tiers = d.tiers as Record<string, unknown> | null | undefined;
    const out: string[] = [];
    if (
      typeof tiers !== 'object' ||
      tiers === null ||
      !(tiers['1'] as unknown[] | undefined)?.length
    )
      out.push('`tiers.1` is missing or empty');
    if (!Array.isArray(d.kinds) || !d.kinds.length)
      out.push(
        "the fact-sources list has no `kinds` list of strings - the channel's kinds of fact (CF-0627)",
      );
    return out;
  }
  if (list === 'footage-origin') return footageLines(d);
  if (list === 'affiliate' && (!Array.isArray(d.programmes) || !Array.isArray(d.products)))
    return ['affiliate.json: programmes[] and products[] are required'];
  return [];
}

export type ListAccess = {
  /** Документ и его sha сейчас; `doc: null` — файла нет. */
  read: (c: string, list: ListName) => { doc: unknown; sha: string | null };
  /** Записать весь документ. */
  write: (c: string, list: ListName, doc: unknown) => void;
  /** Ещё строки проверки фабрики для канала (ленты новостей канала и т.п.), CC-0129. */
  errors?: (c: string, list: ListName) => string[];
};

export function createListWrites(access: ListAccess) {
  const state = {
    life: 120,
    refuse: null as Code | null,
    actRefuse: null as Code | null,
    busy: false,
    /** Тела планов, как их прислал центр. */
    plans: [] as { channel: string; list: ListName; body: unknown }[],
    /** Записанные списки: `канал список`. */
    written: [] as string[],
  };
  const tokens = new Map<
    string,
    { c: string; list: ListName; doc: unknown; base: string | null; expires: number }
  >();
  let seq = 0;

  const docOf = (list: ListName, b: Doc): Doc | Doc[] | null => {
    const d = b.doc;
    return typeof d === 'object' && d !== null && !Array.isArray(d) ? (d as Doc) : null;
  };

  function codes(c: string, list: ListName, doc: Doc | Doc[] | null, base: string | null) {
    const out: { code: Code; lines: string[] }[] = [];
    const bad =
      doc === null
        ? ['the document is not a JSON object']
        : [...invalidLines(list, doc), ...(access.errors?.(c, list) ?? [])];
    if (bad.length) out.push({ code: 'invalid', lines: bad });
    if (state.refuse) out.push({ code: state.refuse, lines: [`write_list: ${state.refuse}`] });
    if (base !== access.read(c, list).sha)
      out.push({ code: 'check_changed', lines: ['base_sha256 is not the file now'] });
    return out;
  }

  const common = (c: string, list: ListName, base: string | null, ok: boolean) => ({
    action: ACTION[list],
    channel: c,
    list,
    ok,
    path: `channels/${c}/${FILE[list]}`,
    base_sha256: base,
    sha256: access.read(c, list).sha,
    by: 'user',
    via: 'center',
  });

  const problem = (status: number, code: Code, message: string, details: string[] = []) => ({
    status,
    body: { message, code, details } satisfies Problem,
  });

  return {
    state,
    plan(c: string, list: ListName, raw: unknown): Reply<S['ChannelListPlan']> {
      const b = (raw ?? {}) as Doc;
      state.plans.push({ channel: c, list, body: raw });
      const doc = docOf(list, b);
      const base = typeof b.base_sha256 === 'string' ? b.base_sha256 : null;
      const found = codes(c, list, doc, base);
      const now = access.read(c, list);
      const changes = JSON.stringify(now.doc) !== JSON.stringify(doc);
      let confirm: string | null = null;
      if (!found.length) {
        confirm = `list-${list}-${++seq}`;
        tokens.set(confirm, { c, list, doc, base, expires: Date.now() + state.life * 1000 });
      }
      return {
        status: 200,
        body: {
          ...common(c, list, base, !found.length),
          new_sha256: found.length ? null : standInSha(doc),
          // Как у фабрики: строка проверки — отдельный отказ `invalid`.
          refusals: found.flatMap((f) =>
            (f.code === 'invalid' ? f.lines : [f.lines.join('; ')]).map((line) => ({
              code: f.code as S['ChannelListRefusal']['code'],
              line,
              message: LIST_REFUSALS[f.code]?.[1] ?? f.code,
            })),
          ),
          lines: found.flatMap((f) => f.lines),
          dry_run: true,
          changes,
          why: found.length ? (LIST_REFUSALS[found[0]!.code]?.[1] ?? null) : null,
          confirm,
          expires_in_s: confirm ? state.life : null,
        },
      };
    },
    act(c: string, list: ListName, raw: unknown): Reply<S['ChannelListWriteResult'] | Problem> {
      if (state.busy)
        return problem(409, 'busy', 'Идёт другая запись списка - подождите и нажмите ещё раз.', [
          'the channel-list write lock was not free in 5 s; the token is not spent',
        ]);
      const token = (raw as { confirm?: string } | null)?.confirm ?? '';
      const got = tokens.get(token);
      tokens.delete(token);
      if (!got || got.c !== c || got.list !== list)
        return problem(
          409,
          'confirm_unknown',
          'Подтверждение не найдено - запросите план заново.',
          ['no such confirm token in this API process (used, unknown, or the server restarted)'],
        );
      if (got.expires <= Date.now())
        return problem(409, 'confirm_expired', 'Подтверждение устарело - запросите план заново.', [
          'expired',
        ]);
      const found = codes(c, list, got.doc as Doc, got.base);
      if (state.actRefuse) found.unshift({ code: state.actRefuse, lines: ['write_list'] });
      if (found.length) {
        const first = found[0]!;
        const [status, message] = LIST_REFUSALS[first.code] ?? [500, first.code];
        return problem(status, first.code, message, first.lines);
      }
      access.write(c, list, got.doc);
      state.written.push(`${c} ${list}`);
      return {
        status: 200,
        body: {
          ...common(c, list, got.base, true),
          new_sha256: access.read(c, list).sha,
          refusals: [],
          lines: [`WROTE channels/${c}/${FILE[list]}`],
          dry_run: false,
          written: true,
          commit: 'f00dfeed',
        },
      };
    },
    /** Все выданные токены устарели — «да» получит `confirm_expired`. */
    expireTokens() {
      for (const t of tokens.values()) t.expires = 0;
    },
  };
}

export type ListWrites = ReturnType<typeof createListWrites>;

const ROUTE =
  /\/api\/channels\/([^/]+)\/(fact-sources|footage-origin|affiliate)(\/plan)?$/;

/** POST правки списка; null — адрес не этот или список не из `lists`. */
export function routeListWrites(
  w: ListWrites,
  lists: readonly ListName[],
  method: string,
  url: URL,
  body: unknown,
): Reply<unknown> | null {
  if (method !== 'POST') return null;
  const m = url.pathname.match(ROUTE);
  if (!m) return null;
  const list = m[2] as ListName;
  if (!lists.includes(list)) return null;
  const c = decodeURIComponent(m[1]!);
  return m[3] ? w.plan(c, list, body) : w.act(c, list, body);
}
