// Причины словами фабрики (CC-0113, CF-0714): у каждого `reason_code` ответа API рядом
// `reason_ru` — строка `funnel.REASONS_RU`, а у сводок — карта «код → строка»
// (`funnel_reasons_ru`, `reasons_ru`). Своих подписей кодов в центре нет: нет ни строки фабрики,
// ни русского уточнения — «причина без описания», а сам код — только под «Подробнее» и в
// подсказке. Без зависимостей — модуль берут и тесты Playwright.

type Reasoned = {
  reason_code?: string | null;
  reason_ru?: string | null;
  reason?: string | null;
};

const hasCyrillic = (s: string) => /[а-яё]/i.test(s);
const clean = (s: string | null | undefined) => s?.trim().replace(/\.$/, '') || null;

/** Причина, у которой нет слов фабрики: код — под «Подробнее» и в подсказке, не на виду. */
export const NO_REASON_TEXT = 'причина без описания';

/** Строка фабрики для кода по карте «код → строка». */
export function hasReasonWords(
  map: Record<string, string | null> | null | undefined,
  code: string,
) {
  return !!clean(map?.[code]);
}

/** Код по карте фабрики «код → строка»; нет строки (null или кода нет в карте) — «причина без описания». */
export function reasonOf(map: Record<string, string | null> | null | undefined, code: string) {
  return clean(map?.[code]) ?? NO_REASON_TEXT;
}

/**
 * Причина строки словами: строка фабрики для кода (`reason_ru`) и, если есть, уточнение
 * `reason` — только русское и не повторяющее её (английское — под «подробнее»). Без строки
 * фабрики — уточнение, без него при коде — «причина без описания» (код — под «Подробнее»);
 * ни кода, ни слов — null.
 */
export function reasonWords(r: Reasoned | null | undefined): string | null {
  if (!r) return null;
  const ru = clean(r.reason_ru);
  const raw = clean(r.reason);
  const detail = raw && hasCyrillic(raw) ? raw : null;
  if (ru && detail && detail.toLowerCase() !== ru.toLowerCase()) return `${ru} — ${detail}`;
  return ru ?? detail ?? (clean(r.reason_code) ? NO_REASON_TEXT : null);
}

/** Код для «подробнее»: «no_fact (строка фабрики)»; без строки фабрики — код. */
export function codeWithWords(r: Reasoned | null | undefined): string | null {
  const code = clean(r?.reason_code);
  if (!code) return null;
  const ru = clean(r?.reason_ru);
  return ru ? `${code} (${ru})` : code;
}

type FactFailures = {
  failures: string[];
  failures_ru?: { code: string; ru?: string | null }[] | null;
};

/**
 * Отказы кандидата факта словами фабрики (CC-0119, `FactCandidate.failures_ru` —
 * `fact_rule_ru.reason_ru`, рядом с `failures`): `{code, words}` по порядку кодов; нет слов
 * (`ru` null, старый ответ без `failures_ru`) — «причина без описания». Код — в подсказке и под
 * «Подробнее», своих подписей кодов fact_rule в центре нет.
 */
export function factFailureWords(c: FactFailures): { code: string; words: string }[] {
  const ru = c.failures_ru ?? [];
  return c.failures.map((code, i) => {
    const r = ru[i]?.code === code ? ru[i] : ru.find((x) => x.code === code);
    // строки fact_rule_ru пишут « - » — на экране тире
    return { code, words: clean(r?.ru)?.replace(/ - /g, ' — ') ?? NO_REASON_TEXT };
  });
}

/**
 * Отказы кандидата факта для экрана (CC-0119): причины со словами фабрики — по одной, коды без
 * слов — одной группой («и ещё одна причина без описания»; без единой расшифрованной — просто
 * «причина без описания»), коды — в подсказке.
 */
export function factFailureGroups(c: FactFailures): {
  described: { code: string; words: string }[];
  undescribed: string[];
} {
  const all = factFailureWords(c);
  return {
    described: all.filter((r) => r.words !== NO_REASON_TEXT),
    undescribed: all.filter((r) => r.words === NO_REASON_TEXT).map((r) => r.code),
  };
}

/** Хвост после расшифрованных причин: «и ещё одна причина без описания» / «и ещё N без описания». */
export function undescribedTail(n: number): string {
  return n === 1 ? 'и ещё одна причина без описания' : `и ещё ${n} без описания`;
}
