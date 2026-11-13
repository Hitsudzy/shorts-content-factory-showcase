// Ввод прочитанного в YouTube Studio (CC-0074 фабрики, договор 0.25.0; экран — CC-0077): что
// человек увидел в Studio по последним роликам канала (строки «Досмотрели» / «72,4 %») — в два вызова, как записи публикации: `…/studio/record/plan
// {read}` ничего не пишет и показывает, что фабрика распознала (`studio_read.parse_read`), с
// токеном на `expires_in_s`; `…/studio/record {confirm}` пишет (`record(by=user, via=center)`).
// `read` — JSON, который берёт `studio_read.py parse`: его собирает из формы `readOf`. Отказы —
// `StudioWriteProblem {message, code, details}` (разбирает `takeBatch`), словами — `studioProblemText`.
// Замечания фабрики приходят по-английски — словами их называет `warningText` (строка фабрики
// остаётся под «подробнее»).
import { useQueryClient } from '@tanstack/react-query';

import { analyticsKeys } from './analytics';
import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { api, type Schemas } from './client';
import { writeProblemText } from './publishWrites';

export type StudioReadPlan = Schemas['StudioReadRecordPlan'];
export type StudioReadResult = Schemas['StudioReadRecordResult'];
export type StudioParsedVideo = Schemas['StudioParsedVideo'];
export type StudioUnstored = Schemas['StudioUnstored'];
export type StudioWriteProblem = Schemas['StudioWriteProblem'];
/** Прочитанное как его берёт `studio_read.py parse`. */
export type StudioRead = Record<string, unknown>;

const call = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

export const planStudioRead = (channel: string, read: StudioRead) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/analytics/{channel}/studio/record/plan', {
        params: { path: { channel } },
        body: { read },
        signal,
      }),
    ),
  );

export const recordStudioRead = (channel: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/analytics/{channel}/studio/record', {
        params: { path: { channel } },
        body: { confirm },
        signal,
      }),
    ),
  );

/** После записи (и отказа «да») перечитать чтение Studio, метрики и график ролика. */
export function useAfterStudioWrite() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: analyticsKeys.all });
}

// ---------------------------------------------------------------- форма → прочитанное
/** Что вписано по одному ролику. */
export type VideoForm = {
  video_id: string;
  /** Строки, скопированные со страницы ролика в Studio, как есть. */
  lines: string;
  /** «Досмотрели», если человек вписал число сам. */
  viewed: string;
  /** «Пролистали», если вписал. */
  swiped: string;
  /** За какой период цифры — как его называет Studio. */
  period: string;
};

export type StudioForm = {
  videos: VideoForm[];
};

/** Период, который Studio показывает у доли досмотревших по умолчанию. */
export const DEFAULT_PERIOD = 'С момента публикации';

export const emptyVideo = (video_id: string): VideoForm => ({
  video_id,
  lines: '',
  viewed: '',
  swiped: '',
  period: DEFAULT_PERIOD,
});

const linesOf = (text: string) =>
  text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

/** «72,4» / «72.4 %» → 72.4; не число — строка как есть (фабрика скажет, что не доля). */
export function shareOf(text: string): number | string | null {
  const t = text.trim();
  if (!t) return null;
  const m = t.match(/^(\d{1,3}(?:[.,]\d{1,2})?)\s*%?$/);
  return m ? Number(m[1]!.replace(',', '.')) : t;
}

export const videoFilled = (v: VideoForm) =>
  !!(v.lines.trim() || v.viewed.trim() || v.swiped.trim());

/** Почему план спрашивать рано, или null. */
export function formWhy(form: StudioForm): string | null {
  if (!form.videos.some(videoFilled)) return 'Вставьте строки из Studio хотя бы по одному ролику';
  return null;
}

/**
 * Прочитанное для фабрики: ролики — только заполненные (`lines` построчно, доли — числом),
 * хук — «вручную», язык Studio — русский, `read_at` — сейчас (`now`, ISO с зоной).
 */
export function readOf(channel: string, form: StudioForm, now: Date): StudioRead {
  const videos = form.videos.filter(videoFilled).map((v) => {
    const row: Record<string, unknown> = { video_id: v.video_id, lines: linesOf(v.lines) };
    const period = v.period.trim();
    if (period) row.period_text = period;
    const viewed = shareOf(v.viewed);
    const swiped = shareOf(v.swiped);
    if (viewed != null) row.viewed = viewed;
    if (swiped != null) row.swiped = swiped;
    return row;
  });
  const read: StudioRead = {
    channel,
    read_at: now.toISOString(),
    hook: 'manual',
    ui_language: 'ru',
  };
  if (videos.length) read.videos = videos;
  return read;
}

// ---------------------------------------------------------------- слова
const STUDIO_PROBLEM_TEXT: Record<string, string> = {
  read_refused: 'Фабрика не приняла прочитанное — ничего не записано',
  journal_unreadable: 'Журнал загрузок не читается — ничего не записано',
  store_unreadable: 'Хранилище статистики канала не читается — ничего не записано',
  busy: 'Идёт другая запись чтения Studio — подождите и нажмите ещё раз',
  unknown_channel: 'Такого канала нет',
};

export const studioProblemText = (code: string | null | undefined): string =>
  (code && STUDIO_PROBLEM_TEXT[code]) || writeProblemText(code);

const METRIC_RU: Record<string, string> = { viewed: '«Досмотрели»', swiped: '«Пролистали»' };

/** Замечание фабрики словами (строка `parse_read` — по-английски); незнакомое — как есть. */
export function warningText(w: string): string {
  let m: RegExpMatchArray | null;
  if ((m = w.match(/^(viewed|swiped): not recognised in the lines/)))
    return `${METRIC_RU[m[1]!]}: не нашлось в строках — доля не записана`;
  if ((m = w.match(/^(viewed|swiped): two different values in the lines/)))
    return `${METRIC_RU[m[1]!]}: в строках два разных значения — фабрика не выбирает`;
  if ((m = w.match(/^(viewed|swiped): recognised (\S+) but the lines say (\S+)/)))
    return `${METRIC_RU[m[1]!]}: вписано ${m[2]}, а в строках ${m[3]} — фабрика не выбирает`;
  if ((m = w.match(/^(viewed|swiped): .* is not a share/)))
    return `${METRIC_RU[m[1]!]}: вписанное не похоже на долю в процентах`;
  if ((m = w.match(/^(viewed|swiped): extra percents after the label ignored/)))
    return `${METRIC_RU[m[1]!]}: после подписи несколько процентов — взят первый`;
  if ((m = w.match(/^viewed (\S+) \+ swiped (\S+) = (\S+), not ~100/)))
    return `Досмотрели ${m[1]} + пролистали ${m[2]} = ${m[3]}, а должно быть около 100`;
  if (/^period_text:/.test(w)) return 'Не указано, за какой период цифры';
  if (/not in publish\/uploads\.json/.test(w))
    return 'Ролика нет в журнале загрузок канала — цифры лягут без записи о загрузке';
  if (/^videos: not read this visit/.test(w)) return 'Ролики в этот раз не читали';
  if (/no video id - not stored/.test(w)) return 'Нет id ролика — в статистику не ляжет';
  return w;
}

/** Заметка фабрики «у Studio пока мало данных» (CF-0639) словами. */
export const noteText = (note: string | null | undefined) =>
  note ? 'Studio пока не показывает долю — у нового ролика мало данных' : null;

/** «2 новых чтения» и т. п. — число и слово. */
export function countText(n: number, one: string, few: string, many: string): string {
  const d = n % 10;
  const h = n % 100;
  const w = d === 1 && h !== 11 ? one : d >= 2 && d <= 4 && (h < 12 || h > 14) ? few : many;
  return `${n} ${w}`;
}
