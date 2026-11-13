// Свежесть ответа о батчах (договор 0.5.0, CC-0041 фабрики). Скан идущих батчей у фабрики
// долгий (до минуты), поэтому чтение (список, канал, шаблон, dry-run) его не ждёт: отвечает
// последним известным итогом — `checked_at` (когда тот скан начался), `age_s` (сколько ему
// секунд на момент ответа) и `checking` (уже идёт новый). Запись (сохранение, создание,
// «вернуть») всегда сканирует заново, так что устаревшее «открыто» в худшем случае кончается
// отказом 409 `batch_running`.

export type Freshness = {
  checked_at?: string | null;
  age_s?: number | null;
  checking: boolean;
};

/**
 * Паузы переспроса, пока фабрика сканирует (мс): скан идёт 36–55 с, первые ответы — часто.
 * После последней — каждые 30 с, всего не больше `RECHECK_MAX` раз подряд.
 */
export const RECHECK_MS = [3_000, 5_000, 8_000, 13_000, 20_000, 30_000] as const;
export const RECHECK_MAX = 12;

/** Пауза перед n-м (с 1) переспросом подряд; false — хватит. */
export function recheckDelay(n: number): number | false {
  if (n < 1 || n > RECHECK_MAX) return false;
  return RECHECK_MS[Math.min(n, RECHECK_MS.length) - 1]!;
}

type QueryLike<T> = { state: { data: T | undefined; dataUpdatedAt: number; error: unknown } };

/**
 * `refetchInterval` для TanStack Query: пока ответ говорит `checking`, тихо переспросить
 * (без спиннера — данные на экране остаются), с растущей паузой и не дольше `RECHECK_MAX`
 * ответов подряд. Ответ без `checking` или ошибка — переспрос прекращается.
 */
export function recheckWhileChecking<T>(fresh: (data: T) => Freshness | null | undefined) {
  const streak = new WeakMap<object, { at: number; n: number }>();
  return (query: QueryLike<T>): number | false => {
    const { data, dataUpdatedAt, error } = query.state;
    const f = data === undefined ? null : fresh(data);
    if (!f?.checking || error) {
      streak.delete(query);
      return false;
    }
    const s = streak.get(query) ?? { at: -1, n: 0 };
    if (s.at !== dataUpdatedAt) streak.set(query, { at: dataUpdatedAt, n: s.n + 1 });
    return recheckDelay(streak.get(query)!.n);
  };
}

/** «12 с», «3 мин», «2 ч». */
export function agoText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} с`;
  if (s < 3600) return `${Math.floor(s / 60)} мин`;
  return `${Math.floor(s / 3600)} ч`;
}

/**
 * «проверено 12 с назад» (+ «сейчас проверяет заново»), null — фабрика про свежесть не сказала.
 * `elapsed_s` — сколько прошло с ответа (ответ сказал `age_s` на свой момент).
 */
export function freshnessText(f: Freshness | null | undefined, elapsed_s = 0): string | null {
  if (!f || (f.age_s == null && !f.checked_at)) return f?.checking ? 'фабрика проверяет' : null;
  const age = f.age_s == null ? null : f.age_s + Math.max(0, elapsed_s);
  const base = age == null ? `проверено в ${f.checked_at}` : `проверено ${agoText(age)} назад`;
  return f.checking ? `${base}, фабрика уже проверяет заново` : base;
}
