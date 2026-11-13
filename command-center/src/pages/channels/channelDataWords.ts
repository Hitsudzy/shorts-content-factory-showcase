// Слова вкладки «Данные канала» (CC-0115 → CC-0101/0102): концовка, источники фактов,
// партнёрские ссылки. Коды, пути, id изданий и программ — только под «подробнее».
import type { ChannelAffiliate, ChannelEnding, ChannelFactSources } from '@/api/channelData';
import type { Tone } from '@/components/common/Status';
import { plural } from '@/pages/batches/format';
import { styleValue } from '@/pages/stats/format';

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Obj) : null;
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

const sec = (n: number) => `${String(Math.round(n * 10) / 10).replace('.', ',')} с`;

/** Состояние концовки одной строкой и тоном значка. */
export function endingState(e: ChannelEnding): { label: string; tone: Tone; text: string } {
  if (e.path_error)
    return {
      label: 'файла нет',
      tone: 'danger',
      text: 'В конфиге канала назван файл концовки, которого нет.',
    };
  if (!e.exists)
    return {
      label: 'не собрана',
      tone: 'warn',
      text: 'Клипа концовки у канала ещё нет — ролики выйдут без неё.',
    };
  if (e.check && !e.check.ok)
    return {
      label: 'не подходит',
      tone: 'danger',
      text: 'Монтаж не примет клип: формат не тот, что он рендерит.',
    };
  return { label: 'есть', tone: 'ok', text: 'Клип концовки на месте, монтаж его примет.' };
}

/** «3,0 с · 1080×1920 · 30 к/с · со звуком». */
export function probeText(e: ChannelEnding): string | null {
  const p = e.probe;
  if (!p) return null;
  return [
    sec(p.seconds),
    `${p.width}×${p.height}`,
    `${Math.round(p.fps)} к/с`,
    p.has_audio ? 'со звуком' : 'без звука',
  ].join(' · ');
}

/** Можно ли пересобрать концовку из бренда — словами. */
export function renderText(e: ChannelEnding): string {
  const r = e.render;
  if (r.last_run?.running) return 'Сейчас идёт сборка концовки.';
  if (r.by_hand) return 'Собрана вручную — из бренда канала её не пересобрать.';
  if (r.available) return 'Её можно собрать из бренда канала.';
  return r.refusal?.message ?? r.why ?? 'Собрать её из бренда сейчас нельзя.';
}

/**
 * CC-0161: концовка собрана, но git отказал в коммите `ending.mp4` — в папке фабрики остались
 * незаписанные правки. Словами для человека, без «коммита»; слово git — под «подробнее».
 */
export const ENDING_COMMIT_REFUSED_TITLE =
  'Концовка собрана, но не записана в историю изменений\u00a0— в папке фабрики остались незаписанные правки.';

/** Отказ коммита последней сборки концовки (`render.last_run.commit_refused`); null — его нет. */
export function endingCommitRefused(
  e: ChannelEnding,
): { title: string; action: string; detail: string } | null {
  const d = e.render.last_run?.commit_refused?.trim();
  return d ? { title: ENDING_COMMIT_REFUSED_TITLE, action: 'Скажите фабрике.', detail: d } : null;
}

export type Outlet = { id: string; host: string; tip: string | null };

const outletOf = (v: unknown): Outlet | null => {
  const o = obj(v);
  const id = str(o?.id);
  if (!o || !id) return null;
  const host = str(arr(o.hosts)[0]) ?? id;
  const forbidden = obj(o.ai_policy)?.verdict === 'forbidden';
  const cite = o.use === 'cite_only';
  const tip = [
    cite ? 'только ссылка: текст фабрика не читает' : null,
    forbidden ? 'ИИ-ботам вход закрыт в robots.txt' : null,
  ]
    .filter(Boolean)
    .join('; ');
  return { id, host, tip: tip || null };
};

/** Что брать с любого сайта (`any_host[].source_type`). */
const ANY_HOST: Record<string, string> = {
  creator_interview: 'интервью создателей — с прямой цитатой',
  studio_press: 'пресс-материалы студий и дистрибьюторов',
};

/**
 * Виды фактов каналов Science и Tech (`channels/<c>/fact-sources.json` → `kinds`); у Reel они
 * общие со стилем роликов (`styleValue`). Сам код — только под «подробнее».
 */
const KIND: Record<string, string> = {
  measurement: 'измерение',
  discovery: 'открытие',
  mission: 'миссия',
  record: 'рекорд',
  history: 'история',
  spec: 'характеристики',
  price: 'цена',
  release_date: 'дата выхода',
  model_card: 'карточка модели',
  benchmark: 'бенчмарк',
  paper: 'научная статья',
  law: 'закон',
};

/** Виды фактов, которые экран знает словами, — для «Добавить вид фактов» (CC-0129). */
export const KNOWN_KINDS: string[] = [
  ...Object.keys(KIND),
  'production',
  'box_office',
  'casting',
  'release',
  'reception',
  'scandal',
  'people_news',
  'unscripted_moment',
  'other',
];

/** Вид факта словами; неизвестный код — «другой вид факта», не сам код. */
export function kindText(code: string): string {
  const known = KIND[code] ?? styleValue(code);
  return known !== code ? known : 'другой вид факта';
}

export type SourcesView = {
  tiers: { tier: string; outlets: Outlet[] }[];
  anyHost: string[];
  doNotTake: string[];
  kinds: string[];
  /** Коды видов как в файле — для «подробнее». */
  kindCodes: string[];
};

export function sourcesView(s: ChannelFactSources): SourcesView | null {
  const d = obj(s.doc);
  if (!d) return null;
  const tiers = Object.entries(obj(d.tiers) ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([tier, list]) => ({
      tier,
      outlets: arr(list)
        .map(outletOf)
        .filter((x): x is Outlet => !!x),
    }));
  const anyHost = arr(d.any_host).flatMap((v) => {
    const t = str(obj(v)?.source_type);
    return t ? [ANY_HOST[t] ?? 'ещё один вид источника — под «подробнее»'] : [];
  });
  const doNotTake = arr(d.do_not_take).flatMap((v) => {
    const h = str(arr(obj(v)?.hosts)[0]) ?? str(obj(v)?.id);
    return h ? [h] : [];
  });
  const kinds = [
    ...new Set(
      (s.kinds ?? arr(d.kinds).filter((k): k is string => typeof k === 'string')).map(kindText),
    ),
  ];
  const kindCodes = s.kinds ?? arr(d.kinds).filter((k): k is string => typeof k === 'string');
  return { tiers, anyHost, doNotTake, kinds, kindCodes };
}

/** Уровень изданий словами. */
export const tierLabel = (t: string) =>
  t === '1' ? 'Основные издания' : t === '2' ? 'Только для ссылки' : `Уровень ${t}`;

export type Product = { name: string; programme: string | null };

export function affiliateView(a: ChannelAffiliate): {
  programmes: string[];
  products: Product[];
} {
  const d = obj(a.doc);
  const progs = arr(d?.programmes)
    .map(obj)
    .filter((x): x is Obj => !!x);
  const name = (id: unknown) => str(progs.find((p) => p.id === id)?.name) ?? null;
  return {
    programmes: progs.map((p) => str(p.name) ?? str(p.id) ?? '—'),
    products: arr(d?.products)
      .map(obj)
      .filter((x): x is Obj => !!x)
      .map((p) => ({ name: str(arr(p.names)[0]) ?? '—', programme: name(p.programme) })),
  };
}

export const errorsText = (n: number) =>
  `Фабрика нашла в списке ${n} ${plural(n, 'ошибку', 'ошибки', 'ошибок')}`;
