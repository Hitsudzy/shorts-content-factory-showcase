// Слова экрана «Мемы» (CC-0025): имя мема, счётчики, слой мемов в роликах, пустые полосы.
import type { MemeEntry } from '@/api/memes';
import type { Tone } from '@/components/common/Status';

import type { MemeState } from './draft';

function plural(n: number, one: string, few: string, many: string): string {
  const d = n % 10;
  const dd = n % 100;
  if (d === 1 && dd !== 11) return one;
  if (d >= 2 && d <= 4 && (dd < 12 || dd > 14)) return few;
  return many;
}

export const memesWord = (n: number) => `${n} ${plural(n, 'мем', 'мема', 'мемов')}`;
export const filesWord = (n: number) => `${n} ${plural(n, 'файл', 'файла', 'файлов')}`;
export const marksWord = (n: number) => `${n} ${plural(n, 'отметка', 'отметки', 'отметок')}`;

/** «drake-hotline-bling» → «Drake hotline bling»: так мем называет человек. */
export function memeName(id: string): string {
  const s = id.replace(/[-_]+/g, ' ').trim();
  return s ? s[0]!.toUpperCase() + s.slice(1) : id;
}

/** Как мем называть человеку: имя по его id, в кавычках «ёлочках» — в тексте. */
export const quoted = (id: string) => `«${memeName(id)}»`;

export const STATE: Record<MemeState, { label: string; tone: Tone; tip: string }> = {
  new: {
    label: 'Новый',
    tone: 'live',
    tip: 'Новый мем ждёт решения: без «оставить» в библиотеку он не войдёт',
  },
  keep: { label: 'Оставить', tone: 'ok', tip: 'Отмечен «оставить»' },
  drop: { label: 'Убрать', tone: 'danger', tip: 'Отмечен «убрать»' },
  in: { label: 'В библиотеке', tone: 'idle', tip: 'Мем уже в библиотеке, решения по нему нет' },
};

/** Слой мемов в роликах канала (`insert_layers.meme.enabled`): его включает фабрика. */
export function layerText(enabled: boolean | null | undefined): string {
  return enabled
    ? 'Мемы в роликах включены'
    : 'Мемы в роликах выключены — включает фабрика после разбора';
}

/** Кусок видео, из которого вырезана гифка: «кусок видео 12,4–14,1 с». */
export function clipText(clip: MemeEntry['clip']): string | null {
  const a = clip?.start_s;
  const b = clip?.end_s;
  if (typeof a !== 'number' || typeof b !== 'number') return null;
  const n = (x: number) => String(Math.round(x * 10) / 10).replace('.', ',');
  return `кусок видео ${n(a)}–${n(b)} с`;
}

const SIDE: Record<string, string> = { top: 'сверху', bottom: 'снизу' };
const TONE: Record<string, string> = { white: 'белая', black: 'чёрная' };

/**
 * Пустая полоса подписи (CF-0534) словами: фабрика пишет «top 79 white rows (22%)» — центр
 * говорит «сверху белая полоса, 22% высоты». Незнакомое — как есть.
 */
export function bandText(phrase: string): string {
  if (phrase === 'one tone all over') return 'картинка целиком одного тона';
  const parts = phrase.split(/,\s*/).map((p) => {
    const m = /^(top|bottom) \d+ (white|black|\w+) rows \((\d+)%\)$/.exec(p.trim());
    if (!m) return null;
    const tone = TONE[m[2]!] ?? 'однотонная';
    return `${SIDE[m[1]!]} ${tone} полоса, ${m[3]}% высоты`;
  });
  return parts.every(Boolean) ? parts.join('; ') : phrase;
}

/**
 * Полоса подписи для экрана (CF-0762): русская `phrase_ru` фабрики; у старой фабрики её нет —
 * своими словами по английской `phrase`, а незнакомую — «полоса без описания» (английская —
 * под «подробнее»).
 */
export function bandWords(b: { phrase: string; phrase_ru?: string | null }): string {
  if (b.phrase_ru && /[а-яё]/i.test(b.phrase_ru)) return b.phrase_ru;
  const own = bandText(b.phrase);
  return /[а-яё]/i.test(own) ? own : 'пустая полоса подписи без описания';
}

/** Совпадает ли мем с поиском: имя, описание, метки. */
export function matches(entry: MemeEntry, q: string): boolean {
  const s = q.trim().toLowerCase();
  if (!s) return true;
  const hay = [entry.id, memeName(entry.id), entry.description ?? '', ...(entry.tags ?? [])]
    .join(' ')
    .toLowerCase();
  return s.split(/\s+/).every((w) => hay.includes(w));
}

/** Самые частые метки банка — для быстрых фильтров. */
export function topTags(entries: MemeEntry[], n = 12): string[] {
  const count = new Map<string, number>();
  for (const e of entries) for (const t of e.tags ?? []) count.set(t, (count.get(t) ?? 0) + 1);
  return [...count.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, n)
    .map(([t]) => t);
}

/** «12,4» — секунды по-русски, без лишних нулей. */
export const sec = (n: number) => String(Math.round(n * 100) / 100).replace('.', ',');
