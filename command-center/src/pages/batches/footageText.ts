// Слова блока «Футаж по темам» (CC-0119): состояния тем, сводка, факты строки, источник чисел.
import type { BatchFootage, FootageTopic } from '@/api/batches';
import type { Tone } from '@/components/common/Status';

import { plural } from './format';

/** Слова состояний, если фабрика своего не дала (`state_ru` null у незнакомого). */
const STATE_WORDS: Record<string, string> = {
  queued: 'в очереди',
  collecting: 'собирается',
  collected: 'собрано',
  short: 'не хватило',
  refused: 'отказано',
  stopped: 'остановлено',
};

const STATE_TONE: Record<string, Tone> = {
  queued: 'idle',
  collecting: 'live',
  collected: 'ok',
  short: 'warn',
  refused: 'danger',
  stopped: 'idle',
};

/** Порядок счётчиков в сводке. */
const ORDER = ['collected', 'collecting', 'queued', 'short', 'refused', 'stopped'];

export function stateWord(t: Pick<FootageTopic, 'state' | 'state_ru'>): string {
  return t.state_ru ?? STATE_WORDS[t.state] ?? 'состояние неизвестно';
}

export const stateTone = (state: string): Tone => STATE_TONE[state] ?? 'idle';

/** «собрано 1 · собирается 1 · не хватило 1» — по `counts`, словами фабрики из строк тем. */
export function countsLine(f: Pick<BatchFootage, 'counts' | 'topics'>): string {
  const word = (state: string) =>
    f.topics.find((t) => t.state === state && t.state_ru)?.state_ru ??
    STATE_WORDS[state] ??
    'другое';
  const keys = [
    ...ORDER.filter((k) => f.counts[k]),
    ...Object.keys(f.counts).filter((k) => !ORDER.includes(k) && f.counts[k]),
  ];
  return keys.map((k) => `${word(k)} ${f.counts[k]}`).join(' · ');
}

/** Что под строкой темы: источники, кадры против порога, последнее видео. */
export function factsOf(t: FootageTopic): { text: string; low?: boolean }[] {
  const out: { text: string; low?: boolean }[] = [];
  if (t.collected != null)
    out.push({
      text:
        t.needed != null ? `источников ${t.collected} из ${t.needed}` : `источников ${t.collected}`,
    });
  if (t.usable_shots != null) {
    const n = Math.round(t.usable_shots);
    const shots = `${n} ${plural(n, 'пригодный кадр', 'пригодных кадра', 'пригодных кадров')}`;
    out.push({
      text: t.floor != null ? `${shots} (порог ${Math.round(t.floor)})` : shots,
      low: t.floor != null && t.usable_shots < t.floor,
    });
  }
  if (t.last_video) out.push({ text: `последнее видео: ${t.last_video}` });
  return out;
}

/** Откуда числа — в подсказке; у файла прогресса подсказки нет. */
export const SOURCE_TIP: Partial<Record<BatchFootage['source'], string>> = {
  events:
    'Восстановлено по журналу: эта версия разметки футажа файла прогресса не пишет, поэтому «собрано» — верхняя оценка по событиям прогона.',
  report: 'По итоговому отчёту разметки футажа: живого хода сбора нет, только итог.',
};

export const SOURCE_WORD: Partial<Record<BatchFootage['source'], string>> = {
  events: 'восстановлено по журналу',
  report: 'по итогу разметки',
};
