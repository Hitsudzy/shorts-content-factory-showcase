// Темы батча словами для человека (CC-0092): итог каждого законченного этапа для кадра
// киноленты («нашёл 6 тем, взял 3, отсеял 3», «проверку прошли 2 из 3»), тон состояния темы,
// футаж «хватает / не хватает», расход поиска батча рядом с квотой дня. Число и его слово —
// через неразрывный пробел (`NB`): на узком кадре они не расходятся по строкам.
import type { BatchTopics, SearchQuota, TopicState, TopicSummary } from '@/api/batchTopics';
import type { Tone } from '@/components/common/Status';

import { plural } from './format';
import type { FrameKind } from './stages';

/** Неразрывный пробел. */
export const NB = '\u00a0';
const word = (n: number, one: string, few: string, many: string) =>
  `${n}${NB}${plural(n, one, few, many)}`;
export const topicsWord = (n: number) => word(n, 'тему', 'темы', 'тем');
const scriptsWord = (n: number) => word(n, 'сценарий', 'сценария', 'сценариев');
const shotsWord = (n: number) => word(n, 'кадр', 'кадра', 'кадров');
const searchesWord = (n: number) => word(n, 'поиск', 'поиска', 'поисков');
const videosWord = (n: number) => word(n, 'ролик', 'ролика', 'роликов');
/** «2 из 3» — одним куском. */
export const ofText = (a: number, b: number) => `${a}${NB}из${NB}${b}`;

/** Тон метки состояния темы. */
export const PHASE_TONE: Record<TopicState['phase'], Tone> = {
  in_work: 'live',
  done: 'ok',
  reserve: 'idle',
  dropped: 'idle',
  stalled: 'warn',
};

export const PHASE_TIP: Record<TopicState['phase'], string> = {
  in_work: 'Тема идёт по батчу: строка говорит, на каком она этапе',
  done: 'Тема дошла до конца батча',
  reserve: 'Тема прошла проверку, но в батч не попала — ждёт в резерве',
  dropped: 'Тему отсеял этап батча; причина — в строке',
  stalled: 'Батч не идёт, а тема не дошла до конца',
};

/** Вид работы словами: «фильм», «сериал»; неизвестный — null (сырое — под «подробнее»). */
export function kindText(kind: string | null | undefined): string | null {
  const k = (kind ?? '').toLowerCase();
  if (/film|movie/.test(k)) return 'фильм';
  if (/series|tv|show/.test(k)) return 'сериал';
  if (/game/.test(k)) return 'игра';
  if (/anime/.test(k)) return 'аниме';
  if (/person|actor/.test(k)) return 'человек';
  return null;
}

/** Подпись источника: издание, иначе домен ссылки. */
export function sourceLabel(s: { url: string; publication?: string | null }): string {
  if (s.publication) return s.publication;
  try {
    return new URL(s.url).hostname.replace(/^www\./, '');
  } catch {
    return 'ссылка';
  }
}

const scriptsOf = (t: BatchTopics) => t.topics.flatMap((x) => x.scripts ?? []);

/**
 * Итоги законченных этапов по видам кадра киноленты: строки, которые кадр показывает под
 * подписью, каждая — своей строкой. Этап, который ещё не записал свой файл, итога не даёт.
 */
export function frameSummaries(t: BatchTopics | undefined): Partial<Record<FrameKind, string[]>> {
  const out: Partial<Record<FrameKind, string[]>> = {};
  if (!t || !t.trend_hunter_done) return out;
  const taken = t.topics.length;
  const skipped = t.skipped.length;
  const trends = [
    `нашёл ${topicsWord(taken + skipped)}, взял${NB}${taken}${skipped ? `, отсеял${NB}${skipped}` : ''}`,
  ];
  if (t.compliance) {
    const judged = t.topics.filter((x) => x.compliance && x.compliance.place !== 'not_judged');
    const passed = judged.filter((x) => x.compliance?.place === 'batch').length;
    const reserve = judged.filter((x) => x.compliance?.place === 'reserve').length;
    trends.push(`проверку прошли ${ofText(passed, judged.length)}`);
    if (reserve) trends.push(`в${NB}резерве${NB}${reserve}`);
  }
  out.trends = trends;

  const indexed = t.topics.filter((x) => x.footage.indexer);
  if (indexed.length) {
    const enough = indexed.filter((x) => deepEnough(x) === true).length;
    out.footage = [`футажа хватает: ${ofText(enough, indexed.length)}`];
  }
  const subs = indexed.filter((x) => x.footage.indexer?.substituted).length;
  if (subs) out.extra = [`${topicsWord(subs)} на${NB}замену`];

  if (t.topics.some((x) => x.scripts != null))
    out.research = [`написал ${scriptsWord(scriptsOf(t).length)}`];

  const checked = scriptsOf(t).filter((s) => s.compliance);
  if (checked.length) {
    const ok = checked.filter((s) => s.compliance?.passes).length;
    out.scripts = [`проверку прошли ${ofText(ok, checked.length)}`];
  }
  const edited = scriptsOf(t).filter((s) => s.video);
  if (edited.length) {
    const built = edited.filter((s) => s.video?.slug).length;
    out.edit = [`собрано роликов: ${ofText(built, edited.length)}`];
  }
  const judged = scriptsOf(t).filter((s) => s.frame?.gate);
  if (judged.length) {
    const ok = judged.filter((s) => s.frame?.gate === 'pass').length;
    out.judge = [`кадры прошли: ${ofText(ok, judged.length)}`];
    out.accept = [`на приёмку: ${videosWord(ok)}`];
  }
  return out;
}

/** Хватает ли футажа теме: мера индексатора, иначе — трендхантера; null — не мерили. */
export function deepEnough(x: TopicSummary): boolean | null {
  const ix = x.footage.indexer;
  if (ix) return ix.depth?.deep_enough ?? !ix.thin;
  return x.footage.pool?.deep_enough ?? null;
}

/** Футаж темы одной строкой: «годных 41 кадр из 64, нужно 24 — хватает». */
export function footageLine(x: TopicSummary): string | null {
  const d = x.footage.indexer?.depth;
  const p = x.footage.pool;
  const usable = d?.usable_shots ?? p?.usable;
  const floor = d?.floor ?? p?.floor;
  const shots = d?.shots ?? p?.shots;
  if (usable == null) return null;
  const enough = deepEnough(x);
  return [
    `годных ${shotsWord(usable)}${shots != null ? ` из${NB}${shots}` : ''}`,
    floor != null ? `нужно${NB}${floor}` : null,
  ]
    .filter(Boolean)
    .join(', ')
    .concat(enough == null ? '' : enough ? ' — хватает' : ' — не хватает');
}

/** Расход поиска батча рядом с квотой дня; null — фабрика его не записала. */
export function quotaText(q: SearchQuota | null | undefined): string | null {
  if (!q || q.spent_searches == null) return null;
  const day =
    q.daily_limit_searches != null
      ? ` · квота дня${NB}${q.daily_limit_searches}${q.remaining_searches != null ? `, осталось${NB}${q.remaining_searches}` : ''}`
      : q.remaining_searches != null
        ? ` · осталось${NB}${q.remaining_searches}`
        : '';
  return `батч потратил ${searchesWord(q.spent_searches)}${day}`;
}

/** Сколько тем в каком состоянии: «в работе 2 · в резерве 1». */
export function countsText(t: BatchTopics): string {
  const c = t.counts;
  return [
    c.in_work ? `в работе${NB}${c.in_work}` : null,
    c.done ? `готово${NB}${c.done}` : null,
    c.stalled ? `встали${NB}${c.stalled}` : null,
    c.reserve ? `в резерве${NB}${c.reserve}` : null,
    c.dropped ? `отсеяно позже${NB}${c.dropped}` : null,
  ]
    .filter(Boolean)
    .join(' · ');
}

/** Место темы после проверки тем (02) словами. */
export const PLACE_TEXT: Record<NonNullable<TopicSummary['compliance']>['place'], string> = {
  batch: 'пропущена в батч',
  reserve: 'в резерве',
  refused: 'не пропущена',
  not_judged: 'не проверялась',
};
