// Лента событий батча по курсору (CC-0045 фабрики, `GET …/events?after=&limit=`): хвост
// `RUN_EVENTS.jsonl` целыми строками. Правила договора: держать `next` и спрашивать с него;
// `more` — за `next` уже лежат целые строки, спросить сразу; `reset` — `after` оказался за
// концом файла (файл заменили), ответ — это хвост: всё прежнее выбросить и начать с него.
// В памяти — не больше `EVENTS_KEEP` последних строк (большой батч пишет десятки МБ).
import type { Schemas } from './client';

export type BatchEvents = Schemas['BatchEvents'];
export type BatchEvent = Schemas['BatchEvent'];

/** Сколько последних строк ленты держать в памяти. */
export const EVENTS_KEEP = 500;
/** Сколько страниц подряд дочитывать за один опрос, пока фабрика говорит `more`. */
export const MORE_PAGES = 5;

export type Feed = {
  /** Последние строки, старые — сверху; не больше `EVENTS_KEEP`. */
  lines: BatchEvent[];
  /** Курсор следующего опроса (`after`). */
  next: number;
  /** Размер файла событий на момент последнего ответа, байт. */
  size: number;
  /** Фабрика сказала `more` и за этот опрос дочитать не успели — спросить сразу. */
  more: boolean;
  /** Сколько раз лента начиналась заново (`reset`). */
  resets: number;
  /** Сколько строк выброшено из памяти сверх `EVENTS_KEEP` (или при сбросе). */
  dropped: number;
  /** Рекомендованная пауза до следующего опроса, с. */
  pollS: number;
};

/** Добавить ответ к ленте: `reset` — начать заново с его хвоста; лишнее сверху — выбросить. */
export function applyPage(
  feed: Feed | undefined,
  page: BatchEvents,
  keep: number = EVENTS_KEEP,
): Feed {
  const restart = !feed || page.reset;
  const before = restart ? [] : feed.lines;
  const all = before.length ? before.concat(page.events) : page.events;
  const cut = Math.max(0, all.length - keep);
  return {
    lines: cut ? all.slice(cut) : all,
    next: page.next,
    size: page.size,
    more: page.more,
    resets: (feed?.resets ?? 0) + (feed && page.reset ? 1 : 0),
    dropped: (restart ? (feed?.lines.length ?? 0) : 0) + (feed?.dropped ?? 0) + cut,
    pollS: page.poll_s,
  };
}

/**
 * Один опрос ленты: спросить с курсора и, пока фабрика говорит `more`, сразу ещё — не больше
 * `maxPages` страниц (остаток — следующим опросом, `feed.more` = true). Первый опрос
 * (`prev` нет) — без `after`: фабрика отдаёт хвост.
 */
export async function pullFeed(
  prev: Feed | undefined,
  fetchPage: (after: number | null) => Promise<BatchEvents>,
  maxPages: number = MORE_PAGES,
  keep: number = EVENTS_KEEP,
): Promise<Feed> {
  let feed = prev;
  for (let i = 0; i < maxPages; i++) {
    const page = await fetchPage(feed ? feed.next : null);
    feed = applyPage(feed, page, keep);
    if (!page.more) break;
  }
  return feed!;
}

/** Пауза до следующего опроса, мс: `more` — почти сразу, иначе — как советует фабрика. */
export function feedDelay(feed: Feed | undefined, fallbackS = 3): number {
  if (feed?.more) return 250;
  return Math.max(1, feed?.pollS ?? fallbackS) * 1000;
}
