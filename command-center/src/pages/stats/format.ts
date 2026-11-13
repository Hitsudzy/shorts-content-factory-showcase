// Слова и числа экрана «Статистика и аналитик»: метрики YouTube по-русски, исход сбора, стиль
// ролика (измерения сводки и их значения), причины и стадии «нужного футажа», строка «пора
// читать» Studio без служебного префикса.
import type { SummaryGroup, VideoMetrics } from '@/api/analytics';
import type { Tone } from '@/components/common/Status';

const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const dec = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

type N = number | null | undefined;

export const count = (x: N) => (typeof x === 'number' ? num.format(x) : '—');
export const pct = (x: N) => (typeof x === 'number' ? `${dec.format(x)} %` : '—');
export const secs = (x: N) => (typeof x === 'number' ? `${dec.format(x)} с` : '—');

/** Метрики окна YouTube: подпись и подсказка. */
export const METRIC: Record<string, { label: string; tip: string; show: (x: N) => string }> = {
  views: { label: 'Просмотры', tip: 'Все просмотры за окно — число YouTube', show: count },
  engagedViews: {
    label: 'Вовлечённые',
    tip: 'Просмотры, где зритель не пролистал ролик сразу. По ним фабрика сравнивает ролики',
    show: count,
  },
  averageViewPercentage: {
    label: '% просмотра',
    tip: 'Какую долю ролика в среднем смотрят — число YouTube',
    show: pct,
  },
  averageViewDuration: {
    label: 'Время просмотра',
    tip: 'Сколько секунд в среднем смотрят ролик',
    show: secs,
  },
  likes: { label: 'Лайки', tip: 'Лайки за окно', show: count },
  subscribersGained: {
    label: 'Подписки',
    tip: 'Сколько подписались на канал после ролика',
    show: count,
  },
  viewed_pct: {
    label: 'Досмотрели (Studio)',
    tip: 'Доля зрителей, что не пролистали ролик, — из Studio. Это снимок на день чтения, а не окно 7 дней',
    show: pct,
  },
};

/** Исход последнего сбора статистики (`runs.jsonl`, `outcome`). */
export function runState(run: Record<string, unknown> | null | undefined): {
  label: string;
  tone: Tone;
  tip: string;
} {
  if (!run)
    return {
      label: 'не собиралась',
      tone: 'idle',
      tip: 'Фабрика ещё ни разу не спрашивала у YouTube статистику этого канала',
    };
  switch (run.outcome) {
    case 'ok':
      return { label: 'собрана', tone: 'ok', tip: 'Последний сбор прошёл без ошибок' };
    case 'nothing-to-ask':
      return {
        label: 'нечего спрашивать',
        tone: 'idle',
        tip: 'Свежих роликов, по которым нужны числа, не было — сбор ничего не спрашивал',
      };
    case 'reauthorize':
      return {
        label: 'нужен вход',
        tone: 'danger',
        tip: 'Доступ к YouTube Analytics истёк — нужно заново войти в Google',
      };
    case 'api-disabled':
      return {
        label: 'API выключен',
        tone: 'danger',
        tip: 'В проекте Google выключен YouTube Analytics API — сбор не идёт',
      };
    case 'all-forbidden':
      return {
        label: 'YouTube отказал',
        tone: 'danger',
        tip: 'YouTube отказал по всем роликам — возможно, вход не от этого канала',
      };
    default:
      return {
        label: 'ошибка сбора',
        tone: 'warn',
        tip: 'Последний сбор закончился ошибкой — подробности под «Подробнее»',
      };
  }
}

/** Измерения сводки аналитика (`summary.DIMENSIONS`). */
export const DIMENSION: Record<string, { label: string; tip: string }> = {
  pattern: { label: 'Схема сценария', tip: 'Как построен сценарий: список, контраст, разбор…' },
  rhythm: { label: 'Ритм монтажа', tip: 'Как быстро меняются кадры' },
  hook_opener: { label: 'Первая фраза', tip: 'С какого приёма начинается ролик' },
  fact_kind: { label: 'О чём факт', tip: 'Кастинг, сборы, выход, съёмки…' },
  tier: { label: 'Оценка ролика', tip: 'Оценка монтажа и судьи кадров: A — лучшая' },
};

const VALUE: Record<string, string> = {
  unknown: 'не указано',
  list: 'список',
  contrast: 'контраст',
  explainer: 'объяснение',
  'moment-breakdown': 'разбор момента',
  hold: 'длинные кадры',
  staccato: 'быстрые склейки',
  even: 'ровный',
  alternate: 'чередование',
  'number-first': 'сначала число',
  'wildest-fact': 'самый дикий факт',
  'real-reason': 'настоящая причина',
  'sounds-made-up': 'звучит как выдумка',
  'one-detail': 'одна деталь',
  'what-nobody-tells-you': 'о чём молчат',
  'never-supposed-to': 'не должно было случиться',
  'biggest-mistake': 'главная ошибка',
  'before-you-watch': 'перед просмотром',
  casting: 'кастинг',
  box_office: 'кассовые сборы',
  release: 'выход',
  production: 'съёмки',
  reception: 'приём зрителей',
  other: 'другое',
  scandal: 'скандал',
  people_news: 'новости о людях',
  unscripted_moment: 'момент без сценария',
  'strangest-thing': 'самое странное',
  'question-why': 'вопрос «почему»',
};

/** Значение стиля словами; неизвестное — как есть. */
export const styleValue = (v: string) => VALUE[v] ?? v;

export const STAGE: Record<string, string> = {
  hunter: 'поиск тем',
  scripts: 'сценарии',
  editor: 'монтаж',
  'frame-judge': 'судья кадров',
};
export const stageText = (s: string) => STAGE[s] ?? s;

export const KIND: Record<string, string> = {
  work: 'Фильм или сериал',
  person: 'Человек',
  event: 'Событие',
  scene: 'Сцена',
};

/** «due example-film: пора читать (…)» → «Пора читать (…)»: без служебного префикса. */
export function dueText(line: string): string {
  const s = line.replace(/^(due|ok)\s+\S+:\s*/, '');
  return s ? s[0]!.toUpperCase() + s.slice(1) : line;
}

/** Ролик словами: из `entry_id` («канал/батч/слаг») или слага; иначе id YouTube. */
export function videoName(
  v: { video_id?: string | null; slug?: string | null; entry_id?: string | null } | null,
): string {
  const slug = v?.slug ?? v?.entry_id?.split('/').at(-1) ?? null;
  if (!slug) return v?.video_id ?? '—';
  const s = slug.replace(/-/g, ' ');
  return s[0]!.toUpperCase() + s.slice(1);
}

/** «28.09» из «2026-09-28». */
export function shortDay(day: string | null | undefined): string {
  if (!day) return '—';
  const [, m, d] = day.split('-');
  return d && m ? `${d}.${m}` : day;
}

/** Батч словами: «2026-10-09T0200Z» → «09.10». */
export const batchDay = (b: string | null | undefined) => shortDay(b?.slice(0, 10));

/** День минус N дней (публикация по дневной строке и её возрасту). */
export function minusDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d - n)).toISOString().slice(0, 10);
}

// ---------------------------------------------------------------- ролики и сводка

/** День публикации: начало окна или день дневной строки минус её возраст. */
export function publishedDay(v: VideoMetrics): string | null {
  if (v.window?.start) return v.window.start;
  const d = v.last_daily;
  return d && typeof d.age === 'number' ? minusDays(d.day, d.age) : null;
}

/** Состояние окна ролика словами. */
export function windowState(
  v: VideoMetrics,
  collected: boolean,
  firstDays: number,
): { label: string; tone: Tone; tip: string } {
  const w = v.window;
  if (!collected)
    return {
      label: 'окно не собирается',
      tone: 'idle',
      tip: `Окно первых ${firstDays} дней фабрика у YouTube для этого канала не спрашивает`,
    };
  if (!w)
    return {
      label: 'чисел ещё нет',
      tone: 'idle',
      tip: 'YouTube ещё не ответил за окно этого ролика. Из дневных строк окно не пересчитывается',
    };
  if (w.complete === false)
    return {
      label: `идёт ${w.days ?? '?'} из ${firstDays} дн.`,
      tone: 'live',
      tip: `Ролику меньше ${firstDays} дней — окно ещё набирается`,
    };
  if (!w.final)
    return {
      label: 'не окончательные',
      tone: 'warn',
      tip: 'YouTube ещё может поправить последние дни — числа окончательные через 3 дня',
    };
  return { label: 'окончательные', tone: 'ok', tip: 'Числа окна больше не поменяются' };
}

type Stat = { n?: number; median?: number | null };
export const median = (g: SummaryGroup, m: string) =>
  (g.metrics[m] as Stat | undefined)?.median ?? null;
const quote = (v: string) => `«${styleValue(v)}»`;

/** Главная фраза измерения: у кого медиана вовлечённых больше и меньше всего. */
export function leadLine(groups: SummaryGroup[], minSample: number): string {
  const ranked = groups
    .filter((g) => median(g, 'engagedViews') !== null)
    .sort((a, b) => median(b, 'engagedViews')! - median(a, 'engagedViews')!);
  if (ranked.length < 2) return 'Сравнивать пока не с чем: чисел YouTube меньше чем у двух групп.';
  const top = ranked[0]!;
  const low = ranked[ranked.length - 1]!;
  const s =
    `Больше всего вовлечённых просмотров (медиана) — у ${quote(top.value)}: ` +
    `${count(median(top, 'engagedViews'))}, меньше всего — у ${quote(low.value)}: ` +
    `${count(median(low, 'engagedViews'))}.`;
  return ranked.some((g) => g.small_sample)
    ? `${s} В группах меньше ${minSample} роликов — это наблюдение, а не вывод.`
    : s;
}
