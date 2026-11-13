// Черновик формы окна канала и тело PUT из него (`ScheduleSettingsEdit`).
// CF-0830 (CC-0152): `windows` — несколько окон в сутках, 1–4 «ЧЧ:ММ» через запятую; они
// перекрывают одно «Начало окна». Поле пустое и окон не было — `windows` в теле нет (не меняется);
// окна были, а поле очистили — `[]`: фабрика снимает окна, снова одно `window`. Проверяет фабрика
// (422 `invalid`), центр только делит строку на времена.
// CF-0922 (CC-0185): `min_feed_days` — горизонт ленты (на сколько дней вперёд ставится лента),
// `batch_feed_days` — порог батча (батч, когда лента короче). Порог API отдаёт в силе; в тело PUT
// он идёт, только когда его поменяли: не заданный порог фабрика сама поднимает до горизонта.
import type { ScheduleSettings, ScheduleSettingsEdit } from '@/api/schedule';

export type Draft = {
  enabled: boolean;
  window: string;
  window_hours: string;
  /** Горизонт ленты, дн. */
  min_feed_days: string;
  /** Порог батча, дн. (CF-0922). */
  batch_feed_days: string;
  /** Окна через запятую: «05:30, 17:00»; пусто — одно окно. */
  windows: string;
  note: string;
};

export const draftOf = (s: ScheduleSettings): Draft => ({
  enabled: s.enabled ?? true,
  window: s.window ?? '',
  window_hours: s.window_hours == null ? '' : String(s.window_hours),
  min_feed_days: s.min_feed_days == null ? '' : String(s.min_feed_days),
  batch_feed_days: s.batch_feed_days == null ? '' : String(s.batch_feed_days),
  windows: (s.windows ?? []).join(', '),
  note: '',
});

const num = (v: string): number | null => {
  const t = v.trim().replace(',', '.');
  if (!t) return null;
  const x = Number(t);
  return Number.isNaN(x) ? null : x;
};

/** «05:30, 17:00» → ['05:30', '17:00']: делим по запятой, точке с запятой и пробелам. */
export const windowsList = (v: string): string[] =>
  v
    .split(/[,;\s]+/)
    .map((x) => x.trim())
    .filter(Boolean);

/** Порог батча фабрики по умолчанию (`batch_schedule.DEFAULTS`, CF-0922): API его не отдаёт. */
export const BATCH_FEED_DEFAULT = 14;

/** Откуда порог батча: задан в центре, в файле канала или по умолчанию фабрики. */
export type ThresholdOrigin = 'center' | 'channel' | 'default';

/**
 * Откуда порог батча (CC-0185). Пульт задал — `overlay`; значение по умолчанию фабрики (14,
 * поднятое до горизонта) — 'default'; другое — из файла канала. Строка `source` ключей файла не
 * называет, так что порог, заданный в файле ровно как по умолчанию, тоже 'default' — в силе то же.
 * `null` — порога нет (ошибка настроек или фабрика его не знает).
 */
export function thresholdOrigin(s: ScheduleSettings): ThresholdOrigin | null {
  if (s.batch_feed_days == null) return null;
  if (s.overlay && 'batch_feed_days' in s.overlay) return 'center';
  return s.batch_feed_days === Math.max(BATCH_FEED_DEFAULT, s.min_feed_days ?? 0)
    ? 'default'
    : 'channel';
}

/**
 * Порог батча ниже горизонта в черновике — фабрика ответит 409 (CF-0922). Порог по умолчанию,
 * который не трогали, фабрика сама поднимает до горизонта — тогда не в счёт.
 */
export function thresholdBelow(
  d: Draft,
  was: Draft,
  origin: ThresholdOrigin | null,
): { threshold: number; horizon: number } | null {
  const threshold = num(d.batch_feed_days);
  const horizon = num(d.min_feed_days);
  if (threshold == null || horizon == null) return null;
  const counts = origin !== 'default' || d.batch_feed_days.trim() !== was.batch_feed_days.trim();
  return counts && threshold < horizon ? { threshold, horizon } : null;
}

/**
 * Тело PUT: все поля формы — фабрика сама скажет, что поменялось (`changed`). `windows` — только
 * когда есть что записать или снять: `had` — у канала окна уже есть. Порог батча — только когда
 * он отличается от `was` (черновика с сервера) или `was` не дан, а поле не пустое.
 */
export function editOf(d: Draft, had = false, was?: Draft): ScheduleSettingsEdit {
  const windows = windowsList(d.windows);
  const threshold = num(d.batch_feed_days);
  const touched = was ? threshold !== num(was.batch_feed_days) : threshold != null;
  return {
    enabled: d.enabled,
    window: d.window.trim() || null,
    window_hours: num(d.window_hours),
    min_feed_days: num(d.min_feed_days),
    ...(touched && threshold != null ? { batch_feed_days: threshold } : {}),
    ...(windows.length ? { windows } : had ? { windows: [] } : {}),
    note: d.note.trim() || null,
  };
}
