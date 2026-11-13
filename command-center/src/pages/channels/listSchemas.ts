// Поля и проверки списков канала для редактора по строкам (CC-0115 шаг 3, З7) — по правилам
// фабрики: таблица партнёрских
// ссылок (`affiliate.table_errors`), источники фактов (CC-0129, `fact_sources_errors`). Проверка
// здесь — подсказка до плана; решает план фабрики.
import { kindText, tierLabel } from './channelDataWords';
import type { FieldSpec, Row } from './rows';

export const SLUG = /^[a-z0-9][a-z0-9_-]*$/;
const https = (v: unknown) => typeof v === 'string' && /^https:\/\/\S+$/.test(v) && v === v.trim();
const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');

// ---------------------------------------------------------------- партнёрские ссылки
export const PROGRAMME_FIELDS: FieldSpec[] = [
  { key: 'name', label: 'Название программы', placeholder: 'Amazon Associates (US)' },
  { key: 'id', label: 'Короткое имя — латиница, цифры, «-» и «_»', placeholder: 'amazon-us' },
  {
    key: 'network',
    label: 'Партнёрская сеть, латиницей',
    placeholder: 'amazon_associates',
    tip: 'Через какую сеть идёт программа — короткое имя латиницей, как его знает фабрика: amazon_associates, impact, awin',
  },
  {
    key: 'tag',
    label: 'Ваша метка в программе',
    placeholder: 'example-20',
    tip: 'Метка вашего аккаунта из кабинета программы (у Amazon — tracking id вида example-20): по ней сеть засчитывает покупки по ссылке',
  },
  {
    key: 'ref',
    label: 'или код ссылки (если метки нет)',
    tip: 'Реферальный код из кабинета программы, если она выдаёт его вместо метки; нужно одно из двух',
  },
];

export const productFields = (programmes: Row[]): FieldSpec[] => [
  {
    key: 'names',
    label: 'Названия товара, через запятую — первое пойдёт в строку ссылки',
    kind: 'list',
    placeholder: 'Pixel 10 Pro, Pixel 10',
  },
  { key: 'id', label: 'Короткое имя — латиница, цифры, «-» и «_»', placeholder: 'pixel-10' },
  { key: 'aliases', label: 'Другие имена, через запятую (по желанию)', kind: 'list' },
  {
    key: 'programme',
    label: 'Программа',
    kind: 'select',
    options: [
      { v: '', label: 'выберите программу' },
      ...programmes
        .filter((p) => str(p.id))
        .map((p) => ({ v: str(p.id), label: str(p.name) || str(p.id) })),
    ],
  },
  { key: 'url', label: 'Ваша партнёрская ссылка (https://…)', placeholder: 'https://amzn.to/…' },
];

/** Кто и когда добавил — ставится сам (фабрика ждёт `added_by: user` и день). */
export const newAdded = (today: string): Row => ({ added_by: 'user', added_at: today });

export function programmeProblems(rows: Row[]): string[][] {
  const seen = new Set<string>();
  return rows.map((p) => {
    const out: string[] = [];
    const id = str(p.id);
    if (!SLUG.test(id)) out.push('Короткое имя — латиница в нижнем регистре, цифры, «-» и «_»');
    else if (seen.has(id)) out.push('Такое короткое имя уже есть');
    seen.add(id);
    if (!str(p.name)) out.push('Впишите название программы');
    if (!SLUG.test(str(p.network))) out.push('Сеть — латиницей, например amazon_associates');
    if (!str(p.tag) && !str(p.ref)) out.push('Нужна ваша метка или код ссылки в программе');
    return out;
  });
}

export function productProblems(rows: Row[], programmes: Row[]): string[][] {
  const seen = new Set<string>();
  const names = new Map<string, string>();
  const progs = new Map(programmes.map((p) => [str(p.id), p]));
  return rows.map((p) => {
    const out: string[] = [];
    const id = str(p.id);
    if (!SLUG.test(id)) out.push('Короткое имя — латиница в нижнем регистре, цифры, «-» и «_»');
    else if (seen.has(id)) out.push('Такое короткое имя уже есть');
    seen.add(id);
    const list = Array.isArray(p.names) ? p.names.map(str).filter(Boolean) : [];
    if (!list.length) out.push('Впишите хотя бы одно название товара');
    if (list[0] && /[{}<>]/.test(list[0])) out.push('В названии — без скобок { } и < >');
    const aliases = Array.isArray(p.aliases) ? p.aliases.map(str) : [];
    for (const n of [...list, ...aliases]) {
      const k = n.toLowerCase().replace(/\s+/g, '');
      const other = names.get(k);
      if (other != null && other !== id) out.push(`Имя «${n}» уже у другого товара`);
      names.set(k, id);
    }
    const prog = progs.get(str(p.programme));
    if (!prog) out.push('Выберите программу');
    if (!https(p.url)) out.push('Ссылка — полностью, с https://');
    else if (prog) {
      const marks = [str(prog.tag), str(prog.ref)].filter(Boolean);
      if (marks.length && !marks.some((m) => String(p.url).includes(m)))
        out.push('В ссылке нет вашей метки или кода этой программы — она ничего не принесёт');
    }
    return out;
  });
}

// ---------------------------------------------------------------- источники фактов (CC-0129)
// `channels/<c>/fact-sources.json`: ярусы `tiers["1"|"2"]` (источник — `id`, `kind`, `hosts[]`,
// `major_outlet`, `use`, `note`; `ai_policy` и `ai_output_terms` — проверки фабрики, остаются в
// строке как есть), `any_host[]` и `kinds[]`. Проверки — по `fact_rule.validate_sources` и
// `channel_data.policy_errors_of` / `attribution_terms_errors` (cc/api `fact_sources_errors`).

/** Как брать текст источника (`channel_data.TIER_USES`). */
export const TIER_USES = ['read_text', 'cite_only'] as const;
/** Что брать с любого сайта (`fact_rule.SOURCE_TYPES`). */
export const SOURCE_TYPES = ['creator_interview', 'studio_press'] as const;

/** Род источника (`kind`) словами; новый род — латиницей, как его знает фабрика. */
const OUTLET_KIND: Record<string, string> = {
  agency: 'космическое или научное агентство',
  journal: 'научный журнал',
  paper: 'научная статья (DOI)',
  preprint: 'сервер препринтов',
  observatory: 'обсерватория',
  laboratory: 'лаборатория',
  university: 'университет',
  press_release_wire: 'лента пресс-релизов',
  news: 'новостное издание',
  trade: 'отраслевое издание',
  entertainment: 'развлекательное издание',
  encyclopedia: 'энциклопедия',
  episode_guide: 'справочник серий',
  structured_data: 'база данных',
  numbers: 'цифры и сборы',
  vendor: 'сайт компании',
  tech_news: 'технологическое издание',
  model_hub: 'каталог моделей',
  code_host: 'хостинг кода',
  filing: 'отчётность компаний',
  law: 'законы',
  standard: 'стандарты',
  benchmark_org: 'бенчмарки',
  outlet: 'издание',
};

export const OUTLET_FIELDS: FieldSpec[] = [
  {
    key: 'id',
    label: 'Короткое имя — латиница, цифры, «-» и «_»',
    placeholder: 'nasa',
    tip: 'Имя источника для фабрики: латиница в нижнем регистре, цифры, «-» и «_», без пробелов',
  },
  {
    key: 'hosts',
    label: 'Сайты, через запятую — без https://',
    kind: 'list',
    placeholder: 'nasa.gov, science.nasa.gov',
    tip: 'Адреса сайтов источника строчными, без https:// и пути: факт с такого сайта (и его поддоменов) фабрика считает взятым отсюда',
  },
  {
    key: 'kind',
    label: 'Что за источник',
    placeholder: 'научный журнал',
    words: OUTLET_KIND,
    tip: 'Род источника словами, например: научный журнал, новостное издание, сайт компании — знакомый род фабрика запишет своим кодом. Рода, которого фабрика ещё не знает, нет среди слов: его впишите кодом — одним словом латиницей, без пробелов',
  },
  {
    key: 'use',
    label: 'Как брать',
    kind: 'select',
    options: [
      { v: '', label: 'выберите' },
      { v: 'read_text', label: 'читать текст' },
      { v: 'cite_only', label: 'только ссылаться' },
    ],
    tip: '«Читать текст» — фабрика читает статью; можно только у сайта, открытого для ИИ-ботов. «Только ссылаться» — текст не читается, факт лишь ссылается на источник',
  },
  {
    key: 'major_outlet',
    label: 'Крупное издание',
    kind: 'bool',
    check: 'да, на нём может стоять факт о человеке',
    tip: 'Отметьте, если это крупное признанное издание: только на таком источнике фабрика берёт утверждение о реальном человеке',
  },
  {
    key: 'note',
    label: 'Заметка (по желанию)',
    tip: 'Что важно знать об источнике — для вас и для фабрики; на проверку не влияет',
  },
];

export const newOutlet = (): Row => ({ use: 'cite_only', major_outlet: false });

export const ANY_HOST_FIELDS: FieldSpec[] = [
  {
    key: 'source_type',
    label: 'Вид источника',
    kind: 'select',
    options: [
      { v: '', label: 'выберите вид' },
      { v: 'creator_interview', label: 'интервью создателей' },
      { v: 'studio_press', label: 'пресс-материалы компаний и студий' },
    ],
    tip: 'Что фабрика может брать с любого сайта, которого нет в списке «Не брать никогда»',
  },
  {
    key: 'tier',
    label: 'Как считать',
    kind: 'select',
    num: true,
    options: [
      { v: '1', label: 'как основное издание' },
      { v: '2', label: 'как источник только для ссылки' },
    ],
    tip: 'Каким уровнем фабрика считает такой факт: основным изданием или источником только для ссылки',
  },
  {
    key: 'requires',
    label: 'Что нужно от факта',
    kind: 'select',
    options: [
      { v: '', label: 'ничего особого' },
      { v: 'quote', label: 'прямая цитата' },
    ],
    tip: '«Прямая цитата» — фабрика берёт факт, только если у него есть дословные слова человека',
  },
  {
    key: 'note',
    label: 'Заметка (по желанию)',
    tip: 'Пояснение для вас и для фабрики; на проверку не влияет',
  },
];

export const newAnyHost = (): Row => ({ tier: 1 });

type Obj = Record<string, unknown>;
const objOf = (v: unknown): Obj | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Obj) : null;
const HOST = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const VERDICTS = ['allowed', 'forbidden', 'unknown'];

const USE_MISSING = 'Выберите, как брать источник';

/** Проверка robots.txt для ИИ-ботов (`ai_policy`) — что не так, словами (`entry_policy_errors`). */
export function aiPolicyProblems(row: Row): string[] {
  const use = row.use;
  if (use !== 'read_text' && use !== 'cite_only') return [USE_MISSING];
  const p = objOf(row.ai_policy);
  if (!p)
    return [
      'Сайт ещё не проверен на правила для ИИ-ботов — без этой проверки фабрика источник не примет',
    ];
  const checks: unknown[] = Array.isArray(p.checks) ? p.checks : [];
  const whole =
    VERDICTS.includes(p.verdict as string) &&
    typeof p.checked_on === 'string' &&
    DAY.test(p.checked_on) &&
    checks.length > 0 &&
    checks.every((c) => typeof objOf(c)?.robots_url === 'string') &&
    (p.terms_url == null || typeof p.terms_url === 'string');
  if (!whole) return ['Проверка правил для ИИ-ботов записана не полностью — фабрика её не примет'];
  const out: string[] = [];
  if (use === 'read_text' && p.verdict !== 'allowed')
    out.push(
      p.verdict === 'forbidden'
        ? 'Сайт закрыт для ИИ-ботов — его текст читать нельзя, выберите «только ссылаться»'
        : 'Неизвестно, пускает ли сайт ИИ-ботов, — его текст читать нельзя, выберите «только ссылаться»',
    );
  if (use !== 'cite_only' && checks.some((c) => objOf(c)?.any_agent === false))
    out.push('Сайт закрыт для всех роботов — его текст читать нельзя, выберите «только ссылаться»');
  return out;
}

/** Условия сайта для текстов ИИ (`ai_output_terms`): целы ли (`attribution_terms_errors`). */
function termsProblems(row: Row): string[] {
  if (!('ai_output_terms' in row)) return [];
  const t = objOf(row.ai_output_terms);
  const forbidden = t?.forbidden;
  const ok =
    !!t &&
    String(t.terms_url ?? '').startsWith('https://') &&
    Array.isArray(forbidden) &&
    forbidden.length > 0 &&
    forbidden.every((f) =>
      ['id', 'phrase', 'pattern', 'why'].every((k) => str(objOf(f)?.[k]) !== ''),
    );
  return ok ? [] : ['Условия сайта для текстов ИИ записаны не полностью — фабрика их не примет'];
}

export type FactRows = { tier1: Row[]; tier2: Row[]; anyHost: Row[]; kinds: string[] };

export type FactProblems = {
  tier1: string[][];
  tier2: string[][];
  anyHost: string[][];
  /** Что не так со списком целиком (ярусы, виды фактов). */
  doc: string[];
};

const TIER_WORD: Record<string, string> = {
  '1': 'основных изданиях',
  '2': 'источниках только для ссылки',
};

/** Проверка списка источников до плана — подсказка; решает план фабрики. */
export function factProblems(rows: FactRows, doc: Obj | null): FactProblems {
  const banned = new Set(
    (Array.isArray(doc?.do_not_take) ? doc.do_not_take : []).flatMap((r) =>
      Array.isArray(objOf(r)?.hosts) ? (objOf(r)!.hosts as unknown[]).map(String) : [],
    ),
  );
  const seen = new Map<string, string>();
  const tier = (list: Row[], t: '1' | '2') =>
    list.map((r, i) => {
      const out: string[] = [];
      if (!SLUG.test(str(r.id)))
        out.push('Короткое имя — латиница в нижнем регистре, цифры, «-» и «_»');
      const hosts = Array.isArray(r.hosts) ? r.hosts.map(str).filter(Boolean) : [];
      if (!hosts.length) out.push('Впишите хотя бы один сайт');
      for (const h of hosts) {
        if (!HOST.test(h))
          out.push(`Сайт «${h}» — строчными, без https:// и пути, например nasa.gov`);
        if (banned.has(h)) out.push(`Сайт «${h}» — в списке «Не брать никогда»`);
        const where = seen.get(h);
        if (where) out.push(`Сайт «${h}» уже есть — ${where}`);
        else seen.set(h, `в ${TIER_WORD[t]}, запись ${i + 1}`);
      }
      // Проверка robots.txt — про сайт: пока сайта нет, о ней не говорим (кроме «как брать»).
      const policy = aiPolicyProblems(r);
      out.push(...(hosts.length ? policy : policy.filter((x) => x === USE_MISSING)));
      out.push(...termsProblems(r));
      if (r.preprint === true && r.major_outlet === true)
        out.push(
          'Сервер препринтов не может быть крупным изданием: эти тексты никто не рецензировал',
        );
      return out;
    });
  const tier1 = tier(rows.tier1, '1');
  const tier2 = tier(rows.tier2, '2');
  const anyHost = rows.anyHost.map((r) =>
    SOURCE_TYPES.includes(r.source_type as (typeof SOURCE_TYPES)[number])
      ? []
      : ['Выберите вид источника'],
  );
  const out: string[] = [];
  if (!rows.tier1.length) out.push('В основных изданиях нужен хотя бы один источник');
  if (!rows.kinds.length)
    out.push('Нужен хотя бы один вид фактов — иначе фабрика не знает, о чём факты канала');
  const attributed = Array.isArray(doc?.attributed_kinds) ? doc.attributed_kinds : [];
  for (const k of attributed)
    if (typeof k === 'string' && !rows.kinds.includes(k))
      out.push(
        `Вид «${kindText(k)}» убрать нельзя: по нему фабрика подаёт факт как слова его владельца`,
      );
  return { tier1, tier2, anyHost, doc: out };
}

/** Строки правки → документ: прочие ключи файла (`do_not_take`, версии, заметки) — как были. */
export function factDoc(doc: Obj | null, rows: FactRows): Obj {
  const d = doc ?? {};
  const tiers = { ...(objOf(d.tiers) ?? {}) };
  tiers['1'] = rows.tier1;
  if ('2' in tiers || rows.tier2.length) tiers['2'] = rows.tier2;
  const out: Obj = { ...d, tiers };
  if ('any_host' in d || rows.anyHost.length) out.any_host = rows.anyHost;
  if ('kinds' in d || rows.kinds.length) out.kinds = rows.kinds;
  return out;
}

/** Строки правки из документа. */
export function factRowsOf(doc: Obj | null): {
  tier1: unknown;
  tier2: unknown;
  anyHost: unknown;
  kinds: string[];
} {
  const tiers = objOf(doc?.tiers);
  return {
    tier1: tiers?.['1'],
    tier2: tiers?.['2'],
    anyHost: doc?.any_host,
    kinds: Array.isArray(doc?.kinds)
      ? doc.kinds.filter((k): k is string => typeof k === 'string')
      : [],
  };
}

/**
 * Строка отказа проверки фабрики → словами (`fact_sources_errors`); не узнали — null (строка
 * остаётся под «подробнее»). `nameOf` — как назвать источник по его `id` (сайт, не код).
 */
export function factLineText(line: string, nameOf: (id: string) => string): string | null {
  // Ленты новостей канала (`sources.rss.feeds`) — в его настройках, не в этом списке; правило
  // то же (`entry_policy_errors`): читать текст — только у открытого для ИИ-ботов сайта, а
  // закрытый для всех роботов (`*`) сайт не читается вовсе.
  const feed = line.match(/sources\.rss\.feeds\[([^\]]+)\]/);
  if (feed) {
    const site = `Сайт ленты новостей ${feed[1]}`;
    const fix = 'уберите ленту в настройках канала, иначе фабрика не примет список';
    if (/closes it to every agent/.test(line))
      return `${site} закрыт для всех роботов, а канал её читает — ${fix}`;
    if (/robots\.txt verdict for AI bots is forbidden/.test(line))
      return `${site} закрыт для ИИ-ботов, а канал читает её текст — читайте только заголовки или ${fix}`;
    if (/robots\.txt verdict for AI bots/.test(line))
      return `Неизвестно, пускает ли ИИ-ботов сайт ленты новостей ${feed[1]}, а канал читает её текст — читайте только заголовки или ${fix}`;
    if (/no `ai_policy`/.test(line))
      return `${site} не проверен на правила для ИИ-ботов — фабрика не примет список, пока лента не проверена`;
    return `Лента новостей ${feed[1]} в настройках канала нарушает правило для ИИ-ботов — это правится в настройках канала`;
  }
  if (/`tiers\.1` is missing or empty/.test(line))
    return 'В основных изданиях нужен хотя бы один источник';
  const twice = line.match(/host '([^']+)' is listed twice/);
  if (twice) return `Сайт «${twice[1]}» указан дважды`;
  if (/any_host: unknown source_type/.test(line))
    return 'С любого сайта: у записи неизвестный вид источника';
  if (/has no `kinds` list/.test(line)) return 'Нет видов фактов канала';
  if (/`attributed_kinds` names kinds/.test(line))
    return 'Правило «факт со слов владельца» называет виды, которых нет в списке';
  const row = line.match(/tiers\.(\d+)\[([^\]]+)\]/);
  if (!row) return null;
  const who = `${tierLabel(row[1]!)}, ${nameOf(row[2]!)}`;
  if (/ai_output_terms/.test(line))
    return `${who}: условия сайта для текстов ИИ записаны не полностью`;
  if (/no `ai_policy`/.test(line)) return `${who}: сайт не проверен на правила для ИИ-ботов`;
  if (/robots\.txt verdict for AI bots is forbidden/.test(line))
    return `${who}: сайт закрыт для ИИ-ботов — его текст читать нельзя, только ссылаться`;
  if (/robots\.txt verdict for AI bots/.test(line))
    return `${who}: неизвестно, пускает ли сайт ИИ-ботов, — его текст читать нельзя, только ссылаться`;
  if (/closes it to every agent/.test(line))
    return `${who}: сайт закрыт для всех роботов — его текст читать нельзя, только ссылаться`;
  if (/`use` is/.test(line)) return `${who}: не указано, как брать источник`;
  if (/ai_policy/.test(line)) return `${who}: проверка правил для ИИ-ботов записана не полностью`;
  if (/preprint/.test(line)) return `${who}: сервер препринтов не может быть крупным изданием`;
  return null;
}

/** Проверка robots.txt строки словами — под полями источника (сама правится фабрикой). */
export function aiPolicyText(row: Row): string {
  const p = objOf(row.ai_policy);
  if (!p) return 'Сайт ещё не проверен на правила для ИИ-ботов';
  const all = Array.isArray(p.checks) && p.checks.some((c) => objOf(c)?.any_agent === false);
  const verdict = all
    ? 'Сайт закрыт для всех роботов'
    : p.verdict === 'allowed'
      ? 'Сайт открыт для ИИ-ботов'
      : p.verdict === 'forbidden'
        ? 'Сайт закрыт для ИИ-ботов'
        : 'Неизвестно, пускает ли сайт ИИ-ботов';
  const day = typeof p.checked_on === 'string' && DAY.test(p.checked_on) ? p.checked_on : null;
  const when = day ? `, проверено ${day.slice(8, 10)}.${day.slice(5, 7)}.${day.slice(0, 4)}` : '';
  const terms = 'ai_output_terms' in row ? ' · у сайта есть условия для текстов ИИ' : '';
  return `${verdict}${when}${terms}`;
}

// ---------------------------------------------------------------- происхождение футажа (CC-0130)
// `channels/<c>/footage-origin.json` двух видов (cc/api `channel_list_write.footage_origin_errors`):
// у Reel — только `official_channels[]` (`pattern`, `what`, `seen_as`, `channels[] {id, title}`);
// у Science/Tech ещё `footage_origins[]` (`id`, `who`, `licence`, `terms_url`, `found_by[]`,
// `attribution{…}`, `caveats[]`) и `licences{accepted, refused}` — тогда проверка целиком
// `footage_licence.footage_origin_errors`, и у официального канала есть `origin` и `handle`.

/** Своя у каждого файла — решает архив (`footage_licence.PER_FILE`). */
export const PER_FILE = 'per_file';
const CHANNEL_ID = /^UC[0-9A-Za-z_-]{22}$/;
const HANDLE_RE = /^@[0-9A-Za-z_.-]{3,30}$/;
const ATTRIBUTION_VALUES = ['required', 'requested', 'none'];
const WHERE_VALUES = ['description', 'description+on_screen'];
/** Как фабрика находит футаж источника (`footage_licence.FOUND_BY`). */
export const FOUND_BY = [
  'youtube_channels',
  'youtube_search',
  'archive_api',
  'archive_page',
  'stock_api',
  'screen_capture',
  'drawn',
  'api_call',
] as const;
type FoundBy = (typeof FOUND_BY)[number];
const CHANNEL_ROLES = ['footage', 'proof_quote'];
/** Как нашли канал, вписанный здесь (`resolved_by`: фабрика ждёт, что это записано). */
export const RESOLVED_HERE = 'вписан вручную в центре управления';

/** Принятые лицензии словами (`licences.accepted[].id`); код остаётся в файле. */
export const LICENCE_WORDS: Record<string, string> = {
  public_domain: 'общественное достояние',
  cc0: 'CC0 (без условий)',
  cc_by: 'CC BY (с указанием автора)',
  cc_by_sa: 'CC BY-SA (с указанием автора, под той же лицензией)',
  stock_free: 'бесплатная лицензия фотобанка',
  youtube_official_upload: 'ролик официального канала на YouTube',
  youtube_upload: 'стандартная лицензия YouTube',
  own_capture: 'своя запись экрана',
  own_graphic: 'своя графика',
  api_demo: 'ответ модели через API',
};

/** Отклонённые лицензии словами (`licences.refused[].id`). */
export const REFUSED_WORDS: Record<string, string> = {
  noncommercial: 'без коммерческого использования (NC)',
  noderivatives: 'без переделок (ND)',
  non_free: 'несвободные файлы и «все права защищены»',
  esa_standard_only: 'только стандартная лицензия ESA',
  cern_audiovisual: 'аудиовизуальные условия CERN',
  third_party_upload: 'чужие загрузки на YouTube',
};

const FOUND_BY_WORDS: Record<FoundBy, string> = {
  youtube_channels: 'официальные каналы на YouTube',
  youtube_search: 'поиск на YouTube',
  archive_api: 'API архива',
  archive_page: 'страница архива',
  stock_api: 'API фотобанка',
  screen_capture: 'своя запись экрана',
  drawn: 'рисует сама',
  api_call: 'ответ модели через API',
};

/** Название лицензии словами: знакомая — по коду, иначе её `name`, иначе по месту в списке. */
export function licenceName(id: string, accepted: Row[] = []): string {
  if (id === PER_FILE) return 'своя у каждого файла';
  const known = LICENCE_WORDS[id];
  if (known) return known;
  const i = accepted.findIndex((a) => str(a.id) === id);
  const name = i >= 0 ? str(accepted[i]!.name) : '';
  return name || (i >= 0 ? `лицензия ${i + 1} из списка «берём»` : 'лицензия не из принятых');
}

/** Имя источника словами: `who` до скобок («NASA (headquarters…)» → NASA), иначе `name`. */
export const originName = (r: Row | undefined, i = 0): string =>
  str(r?.who).replace(/\s*\(.*$/, '') || str(r?.name) || `Источник ${i + 1}`;

export const officialFields = (science: boolean, origins: Row[]): FieldSpec[] => [
  {
    key: 'seen_as',
    label: 'Как он называется на YouTube (по желанию)',
    placeholder: 'ExampleStream; ExampleStream Brasil',
    wide: true,
    tip: 'Названия правообладателя на YouTube, как их видит зритель; несколько — через «;». Для вас и для аналитика, на поиск не влияет',
  },
  {
    key: 'pattern',
    label: 'Как фабрика его узнаёт, через запятую',
    placeholder: 'google deepmind, deepmind',
    joined: '|',
    tip: 'Слова строчными, по которым фабрика узнаёт правообладателя в названии канала и ролика; несколько вариантов — через запятую, например: google deepmind, deepmind',
  },
  {
    key: 'what',
    label: 'Кто это (по желанию)',
    placeholder: 'стример',
    tip: 'Коротко, для вас: студия, стример, космическое агентство…',
  },
  ...(science
    ? [
        {
          key: 'origin',
          label: 'Откуда его футаж',
          kind: 'select' as const,
          options: [
            { v: '', label: 'выберите источник' },
            ...origins
              .filter((o) => str(o.id))
              .map((o, i) => ({ v: str(o.id), label: originName(o, i) })),
          ],
          tip: 'Источник футажа из списка «Источники футажа» выше: по нему фабрика берёт лицензию и подпись автора для роликов этого канала',
        },
      ]
    : []),
];

export const channelFields = (science: boolean): FieldSpec[] => [
  {
    key: 'title',
    label: 'Название канала',
    placeholder: 'NASA',
    tip: 'Как канал называется на YouTube — для вас; фабрика узнаёт канал по коду',
  },
  {
    key: 'id',
    label: 'Код канала YouTube',
    placeholder: 'UC…',
    tip: 'Код канала: 24 знака, начинается с UC. На YouTube: страница канала → «Подробнее о канале» → «Поделиться» → «Скопировать идентификатор канала»',
  },
  ...(science
    ? [
        {
          key: 'handle',
          label: '@имя канала',
          placeholder: '@NASA',
          tip: 'Имя канала на YouTube с «@», по которому канал нашли: латиница, цифры, «_», «.» и «-», от 3 до 30 знаков',
        },
      ]
    : []),
];

export const newOfficial = (): Row => ({ channels: [] });
export const newChannel = (): Row => ({ resolved_by: RESOLVED_HERE });

export const originFields = (accepted: Row[]): FieldSpec[] => [
  {
    key: 'who',
    label: 'Чей это футаж',
    placeholder: 'NASA',
    tip: 'Агентство, архив или фотобанк — так источник называется на экране центра',
  },
  {
    key: 'id',
    label: 'Короткое имя — латиница, цифры, «-» и «_»',
    placeholder: 'nasa',
    tip: 'Имя источника для фабрики: латиница в нижнем регистре, цифры, «-» и «_», без пробелов',
  },
  {
    key: 'licence',
    label: 'Лицензия',
    kind: 'select',
    options: [
      { v: '', label: 'выберите лицензию' },
      ...accepted
        .filter((a) => str(a.id))
        .map((a) => ({ v: str(a.id), label: licenceName(str(a.id), accepted) })),
      { v: PER_FILE, label: licenceName(PER_FILE) },
    ],
    tip: 'Под какой лицензией источник отдаёт футаж — одна из тех, что канал берёт (список «Лицензии, которые берём» ниже), или своя у каждого файла, как её отмечает архив',
  },
  {
    key: 'terms_url',
    label: 'Страница с условиями (https://…)',
    placeholder: 'https://…',
    tip: 'Страница источника, где написано, на каких условиях брать футаж. У стандартной лицензии YouTube своей страницы нет, у своей записи экрана и своей графики её не бывает — тогда оставьте пустым',
  },
  {
    key: 'found_by.0.how',
    label: 'Как фабрика находит футаж',
    kind: 'select',
    options: [
      { v: '', label: 'выберите способ' },
      ...FOUND_BY.map((v) => ({ v, label: FOUND_BY_WORDS[v] })),
    ],
    tip: 'Главный способ найти футаж у источника; остальные способы, если они есть, остаются в файле как были',
  },
  {
    key: 'found_by.0.works_now',
    label: 'Способ работает',
    kind: 'bool',
    check: 'да, фабрика уже так находит',
    tip: 'Отметьте, если фабрика уже умеет находить футаж этим способом; не отмечено — способ записан на будущее',
  },
  {
    key: 'attribution.credit',
    label: 'Как подписывать автора',
    placeholder: 'NASA',
    tip: 'Подпись автора к ролику — так, как её просит источник',
  },
  {
    key: 'attribution.where',
    label: 'Где подпись',
    kind: 'select',
    options: [
      { v: '', label: 'выберите' },
      { v: 'description', label: 'в описании' },
      { v: 'description+on_screen', label: 'в описании и на экране' },
    ],
    tip: 'Где фабрика ставит подпись автора: только в описании ролика или ещё и в кадре',
  },
  {
    key: 'caveats',
    label: 'Оговорки — каждая с новой строки (по желанию)',
    kind: 'lines',
    wide: true,
    placeholder: 'Эмблему агентства не ставим на обложку',
    tip: 'Что нельзя делать с футажом этого источника — эмблемы, люди в кадре, чужие материалы внутри; для фабрики и для вас',
  },
];

export const newOrigin = (): Row => ({
  found_by: [{ works_now: false }],
  attribution: { where: 'description', on_screen: false },
});

export const ACCEPTED_FIELDS: FieldSpec[] = [
  {
    key: 'id',
    label: 'Лицензия',
    words: LICENCE_WORDS,
    placeholder: 'CC BY (с указанием автора)',
    tip: 'Лицензия, которую канал берёт, словами — знакомую фабрика запишет своим кодом. Новую, которой нет среди слов, впишите кодом: одним словом латиницей, например cc_by_nd',
  },
  {
    key: 'attribution',
    label: 'Подпись автора',
    kind: 'select',
    options: [
      { v: '', label: 'выберите' },
      { v: 'required', label: 'обязательна' },
      { v: 'requested', label: 'желательна — источник просит' },
      { v: 'none', label: 'не нужна' },
    ],
    tip: 'Нужно ли по этой лицензии подписывать автора в ролике',
  },
  {
    key: 'matches',
    label: 'Слова, по которым фабрика узнаёт лицензию, через запятую',
    kind: 'list',
    placeholder: 'cc by, cc-by',
    tip: 'Начало названия лицензии так, как его пишет архив (Commons, ESA, YouTube): по нему фабрика узнаёт лицензию файла; регистр не важен',
  },
  {
    key: 'share_alike',
    label: 'Переделки',
    kind: 'bool',
    check: 'разрешены, если ролик — под той же лицензией',
    tip: 'Отметьте, если лицензия разрешает переделку только при условии, что ролик выйдет под ней же (как CC BY-SA)',
  },
  {
    key: 'license_url',
    label: 'Текст лицензии (https://…, по желанию)',
    placeholder: 'https://creativecommons.org/licenses/by/4.0/',
    tip: 'Ссылка на полный текст лицензии — фабрика ставит её рядом с подписью автора',
  },
  {
    key: 'what',
    label: 'Пояснение (по желанию)',
    tip: 'Что важно знать о лицензии — для вас и для фабрики; на проверку не влияет',
  },
];

export const newAccepted = (): Row => ({ attribution: 'required', share_alike: false });

export const REFUSED_FIELDS: FieldSpec[] = [
  {
    key: 'id',
    label: 'Что не берём',
    words: REFUSED_WORDS,
    placeholder: 'без коммерческого использования (NC)',
    tip: 'Лицензия, которую канал не берёт, словами — знакомую фабрика запишет своим кодом. Новую впишите кодом: одним словом латиницей',
  },
  {
    key: 'tokens',
    label: 'Слова в названии лицензии, через запятую',
    kind: 'list',
    placeholder: 'nc',
    tip: 'Если в названии лицензии файла есть такое слово целиком, фабрика файл не берёт — даже когда лицензия в остальном подходит',
  },
  {
    key: 'terms_url',
    label: 'или страница с условиями, которые запрещают (https://…)',
    placeholder: 'https://…',
    tip: 'Если отказ — не по словам в названии, а по условиям источника: страница, где они написаны',
  },
  {
    key: 'what',
    label: 'Почему не берём',
    tip: 'Коротко, словами: что запрещает лицензия',
  },
];

export const newRefused = (): Row => ({});

export type FootageRows = {
  /** Документ вида Science/Tech (есть источники или лицензии). */
  science: boolean;
  /** Официальные каналы — с их `channels[]` уже внутри. */
  official: Row[];
  origins: Row[];
  accepted: Row[];
  refused: Row[];
};

export type FootageProblems = {
  official: string[][];
  /** Каналы каждого официального канала — по его месту. */
  channels: string[][][];
  origins: string[][];
  accepted: string[][];
  refused: string[][];
  doc: string[];
};

/** Одна ошибка строки за раз — первая по порядку полей, без каскада. */
const one = (xs: string[]) => xs.slice(0, 1);
const listOf = (v: unknown): Row[] =>
  Array.isArray(v) ? v.filter((x): x is Row => !!objOf(x)) : [];
const words = (v: unknown) => (Array.isArray(v) ? v.map(str).filter(Boolean) : []);

/** Проверка происхождения футажа до плана — подсказка; решает план фабрики. */
export function footageProblems(rows: FootageRows): FootageProblems {
  const { science } = rows;
  const accIds = new Set(rows.accepted.map((a) => str(a.id)).filter(Boolean));
  const originIds = new Set(rows.origins.map((o) => str(o.id)).filter(Boolean));
  const official = rows.official.map((r) => {
    const out: string[] = [];
    if (!str(r.pattern)) out.push('Впишите, как фабрика узнаёт правообладателя');
    if (science) {
      const o = str(r.origin);
      if (!o) out.push('Выберите, откуда его футаж');
      else if (!originIds.has(o)) out.push('Выбранного источника больше нет — выберите другой');
      if ('role' in r && !CHANNEL_ROLES.includes(r.role as string))
        out.push('Роль канала записана не так — она под «как файл»');
    }
    if ('channels' in r && !Array.isArray(r.channels))
      out.push('Каналы записаны не списком — они под «как файл»');
    return one(out);
  });
  const seenCh = new Map<string, string>();
  const channels = rows.official.map((r, i) =>
    listOf(r.channels).map((ch) => {
      const out: string[] = [];
      const id = str(ch.id);
      if (!id) out.push('Впишите код канала');
      else if (!CHANNEL_ID.test(String(ch.id))) out.push('Код канала — 24 знака, начинается с UC');
      else if (science) {
        const where = seenCh.get(id);
        if (where) out.push(`Этот канал уже есть — ${where}`);
        else seenCh.set(id, `у правообладателя ${i + 1}`);
      }
      if (science) {
        const h = str(ch.handle);
        if (!h) out.push('Впишите @имя канала');
        else if (!HANDLE_RE.test(String(ch.handle)))
          out.push('@имя — латиница, цифры, «_», «.» и «-», от 3 до 30 знаков');
        if (!str(ch.resolved_by)) out.push('Не записано, как канал нашли — это под «как файл»');
      }
      return one(out);
    }),
  );
  const seenOrigin = new Set<string>();
  const origins = rows.origins.map((o) => {
    const out: string[] = [];
    const id = str(o.id);
    if (!id) out.push('Впишите короткое имя');
    else if (!SLUG.test(String(o.id)))
      out.push('Короткое имя — латиница в нижнем регистре, цифры, «-» и «_»');
    else if (seenOrigin.has(id)) out.push('Такое короткое имя уже есть');
    seenOrigin.add(id);
    const lic = str(o.licence);
    if (!lic) out.push('Выберите лицензию');
    else if (lic !== PER_FILE && !accIds.has(lic))
      out.push('Этой лицензии нет среди тех, что канал берёт');
    const terms = o.terms_url;
    if (lic === 'own_capture' || lic === 'own_graphic') {
      if (terms != null)
        out.push(
          'У своей записи экрана и своей графики страницы с условиями нет — оставьте пустым',
        );
    } else if (lic !== 'youtube_upload' && !https(terms))
      out.push(
        str(terms)
          ? 'Страница с условиями — полностью, с https://'
          : 'Впишите страницу с условиями источника',
      );
    const how: unknown[] = Array.isArray(o.found_by) ? o.found_by : [];
    if (!how.length) out.push('Выберите, как фабрика находит футаж');
    how.forEach((h, j) => {
      const way = objOf(h)?.how;
      if (!FOUND_BY.includes(way as FoundBy))
        out.push(
          j
            ? `Способ ${j + 1} найти футаж записан не так — он под «как файл»`
            : 'Выберите, как фабрика находит футаж',
        );
      else if ((way === 'drawn') !== (lic === 'own_graphic'))
        out.push('«Рисует сама» — способ только своей графики, и у неё он единственный');
      else if ((way === 'api_call') !== (lic === 'api_demo'))
        out.push('«Ответ модели через API» — способ только этой лицензии, и у неё он единственный');
      if (typeof objOf(h)?.works_now !== 'boolean')
        out.push(`У способа ${j + 1} не отмечено, работает ли он — это под «как файл»`);
    });
    const att = objOf(o.attribution);
    if (!str(att?.credit)) out.push('Впишите, как подписывать автора');
    else if (!WHERE_VALUES.includes(att?.where as string)) out.push('Выберите, где подпись');
    return one(out);
  });
  const seenLic = new Set<string>();
  const accepted = rows.accepted.map((a) => {
    const out: string[] = [];
    const id = str(a.id);
    if (!id) out.push('Впишите лицензию');
    else if (seenLic.has(id)) out.push('Эта лицензия уже есть в списке');
    seenLic.add(id);
    if (!ATTRIBUTION_VALUES.includes(a.attribution as string))
      out.push('Выберите, нужна ли подпись автора');
    if (!words(a.matches).length) out.push('Впишите, как лицензия пишется у источника');
    return one(out);
  });
  const refused = rows.refused.map((r) => {
    const out: string[] = [];
    if (!str(r.id)) out.push('Впишите, какую лицензию не берём');
    if (!str(r.what)) out.push('Впишите, почему не берём');
    if (!words(r.tokens).length && !https(r.terms_url))
      out.push('Впишите слова, по которым отказываем, или страницу с условиями (https://…)');
    return one(out);
  });
  const doc: string[] = [];
  if (science) {
    if (!rows.accepted.length) doc.push('Нужна хотя бы одна лицензия, которую канал берёт');
    if (!rows.origins.length) doc.push('Нужен хотя бы один источник футажа');
  }
  return { official, channels, origins, accepted, refused, doc };
}

/**
 * Подпись на экране — по «где подпись» (`where` и `on_screen` фабрика сверяет): правка «где»
 * ставит `on_screen` сама; согласованная строка остаётся как была.
 */
export function withOnScreen(row: Row): Row {
  const att = objOf(row.attribution);
  if (!att || !WHERE_VALUES.includes(att.where as string)) return row;
  const on = att.where === 'description+on_screen';
  return att.on_screen === on ? row : { ...row, attribution: { ...att, on_screen: on } };
}

/** Строки правки из документа; вид — по документу (`footage_origins` или `licences`). */
export function footageRowsOf(doc: Obj | null): {
  science: boolean;
  official: unknown;
  origins: unknown;
  accepted: unknown;
  refused: unknown;
} {
  const lic = objOf(doc?.licences);
  return {
    science: !!doc && ('footage_origins' in doc || 'licences' in doc),
    official: doc?.official_channels,
    origins: doc?.footage_origins,
    accepted: lic?.accepted,
    refused: lic?.refused,
  };
}

/** Строки правки → документ: прочие ключи файла (заметки, `attribution`, хосты) — как были. */
export function footageDoc(doc: Obj | null, rows: FootageRows): Obj {
  const d = doc ?? {};
  const out: Obj = { ...d, official_channels: rows.official };
  if (!rows.science) return out;
  const lic: Obj = { ...(objOf(d.licences) ?? {}), accepted: rows.accepted };
  if ('refused' in lic || rows.refused.length) lic.refused = rows.refused;
  out.licences = lic;
  out.footage_origins = rows.origins;
  return out;
}

export type FootageNames = {
  origin: (id: string) => string;
  licence: (id: string) => string;
  official: (pattern: string) => string;
};

/**
 * Строка отказа проверки фабрики → словами (`footage_origin_errors` и правило
 * `official_channels`); не узнали — null (строка остаётся под «подробнее»).
 */
export function footageLineText(line: string, n: FootageNames): string | null {
  if (/^not a JSON object/.test(line)) return 'Список записан не так, как его ждёт фабрика';
  if (/^no `official_channels` list/.test(line)) return 'Нет списка официальных каналов';
  if (/^no `licences` block/.test(line)) return 'Нет списка лицензий канала';
  if (/^licences\.accepted is empty/.test(line))
    return 'Нужна хотя бы одна лицензия, которую канал берёт';
  if (/^no `footage_origins` list/.test(line)) return 'Нужен хотя бы один источник футажа';
  let m = line.match(/^licences\.accepted\[(\d+)\](?: \(([^)]*)\))?: (.*)$/);
  if (m) {
    const r = m[3]!;
    const twice = r.match(/^id '([^']*)' twice/);
    if (twice) return `Лицензия «${n.licence(twice[1]!)}» указана дважды`;
    const who = m[2] ? `Лицензия «${n.licence(m[2])}»` : `Принятая лицензия ${Number(m[1]) + 1}`;
    if (/^no id/.test(r)) return `${who}: не вписано, какая это лицензия`;
    if (/attribution/.test(r)) return `${who}: не выбрано, нужна ли подпись автора`;
    if (/matches/.test(r)) return `${who}: не вписано, как она пишется у источника`;
    if (/share_alike/.test(r)) return `${who}: не отмечено, нужна ли та же лицензия для переделок`;
    return null;
  }
  m = line.match(/^licences\.refused\[(\d+)\]: (.*)$/);
  if (m) {
    const who = `Отклонённая лицензия ${Number(m[1]) + 1}`;
    if (/needs `id` and `what`/.test(m[2]!)) return `${who}: нужно, какая и почему не берём`;
    if (/neither `tokens`/.test(m[2]!))
      return `${who}: нет ни слов, по которым отказывать, ни страницы с условиями`;
    return null;
  }
  m = line.match(/^footage_origins\[(\d+)\](?: \(([^)]*)\))?: (.*)$/);
  if (m) {
    const r = m[3]!;
    const who = m[2] ? `Источник «${n.origin(m[2])}»` : `Источник ${Number(m[1]) + 1}`;
    if (/^no id/.test(r)) return `${who}: нет короткого имени`;
    if (/^id twice/.test(r)) return `${who}: такое короткое имя уже есть`;
    if (/is neither an accepted licence/.test(r))
      return `${who}: лицензии нет среди тех, что канал берёт`;
    if (/has no `terms_url`/.test(r))
      return `${who}: у своей записи экрана и своей графики страницы с условиями не бывает`;
    if (/no https `terms_url`/.test(r)) return `${who}: нет страницы с условиями (https://…)`;
    if (/no `found_by`/.test(r)) return `${who}: не сказано, как фабрика находит футаж`;
    let j = r.match(/^found_by\[(\d+)\]\.how must be/);
    if (j) return `${who}: способ ${Number(j[1]) + 1} найти футаж назван не так`;
    j = r.match(/^found_by\[(\d+)\] does not say `works_now`/);
    if (j) return `${who}: у способа ${Number(j[1]) + 1} не отмечено, работает ли он`;
    if (/`drawn`/.test(r))
      return `${who}: «рисует сама» — способ только своей графики, и у неё он единственный`;
    if (/`api_call`/.test(r))
      return `${who}: «ответ модели через API» — способ только этой лицензии, и у неё он единственный`;
    if (/`attribution` needs/.test(r)) return `${who}: не вписано, как и где подписывать автора`;
    if (/disagree/.test(r)) return `${who}: подпись на экране записана противоречиво`;
    if (/ai_policy/.test(r))
      return `${who}: не записаны условия API, под которыми публикуем ответы`;
    return null;
  }
  m = line.match(/^official_channels\[(\d+)\](?: \((.*?)\))?(?: channels\[(\d+)\])?: (.*)$/);
  if (m) {
    const r = m[4]!;
    const pat = m[2] && m[2] !== 'None' ? m[2] : '';
    const who = pat
      ? `Правообладатель «${n.official(pat)}»`
      : `Правообладатель ${Number(m[1]) + 1}`;
    const ch = m[3] ?? r.match(/^channels\[(\d+)\]\.id/)?.[1];
    const whoCh = ch != null ? `${who}, канал ${Number(ch) + 1}` : who;
    if (/^not an object/.test(r)) return `${who}: записан не так, как его ждёт фабрика`;
    if (/is not a YouTube channel id/.test(r))
      return `${whoCh}: это не код канала YouTube (24 знака, начинается с UC)`;
    if (/listed twice/.test(r)) return `${whoCh}: этот канал уже есть в списке`;
    if (/@handle/.test(r)) return `${whoCh}: не вписано @имя канала`;
    if (/resolved/.test(r)) return `${whoCh}: не записано, как канал нашли`;
    if (/no `pattern`/.test(r)) return `${who}: не вписано, как фабрика его узнаёт`;
    if (/`channels` is not a list/.test(r)) return `${who}: каналы записаны не списком`;
    if (/is not a footage origin/.test(r)) return `${who}: не выбрано, откуда его футаж`;
    if (/^role/.test(r)) return `${who}: роль канала записана не так`;
    return null;
  }
  return null;
}

/** Прочие способы найти футаж словами — под полями источника (правятся в файле). */
export function foundByText(row: Row): string | null {
  const how: unknown[] = Array.isArray(row.found_by) ? row.found_by.slice(1) : [];
  if (!how.length) return null;
  const said = how.map((h) => {
    const w = FOUND_BY_WORDS[objOf(h)?.how as FoundBy] ?? 'другой способ';
    return objOf(h)?.works_now === true ? w : `${w} (пока не работает)`;
  });
  return how.length === 1
    ? `Ещё способ: ${said[0]} — он правится в файле.`
    : `Ещё способы: ${said.join('; ')} — они правятся в файле.`;
}
