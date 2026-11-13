import { describe, expect, it } from 'vitest';

import type { BatchTopics } from '@/api/batchTopics';
import { createBatchesBackend, PAST, routeBatches, RUNNING } from '@/mocks/batches';
import type { TopicsLevel } from '@/mocks/batchTopics';

import {
  countsText,
  footageLine,
  frameSummaries,
  kindText,
  quotaText,
  sourceLabel,
} from './topicsText';

/** Неразрывные пробелы — обычными: сравниваем слова. */
const plain = <T>(x: T): T => JSON.parse(JSON.stringify(x).replace(/\u00a0/g, ' ')) as T;

const at = (level: TopicsLevel, batch = RUNNING): BatchTopics => {
  const b = createBatchesBackend();
  b.setTopics(batch, level);
  return routeBatches(b, 'GET', new URL(`http://x/api/batches/${batch}/topics`))!
    .body as BatchTopics;
};

describe('темы батча словами', () => {
  it('итоги этапов: только законченные этапы', () => {
    expect(frameSummaries(undefined)).toEqual({});
    expect(frameSummaries(at('none'))).toEqual({});
    expect(plain(frameSummaries(at('01')))).toEqual({ trends: ['нашёл 6 тем, взял 3, отсеял 3'] });
    expect(plain(frameSummaries(at('nothing')))).toEqual({
      trends: ['нашёл 6 тем, взял 0, отсеял 6'],
    });
    expect(plain(frameSummaries(at('02')))).toEqual({
      trends: ['нашёл 6 тем, взял 3, отсеял 3', 'проверку прошли 2 из 3', 'в резерве 1'],
    });
    const s04 = plain(frameSummaries(at('04')));
    expect(s04.footage).toEqual(['футажа хватает: 1 из 2']);
    expect(s04.research).toEqual(['написал 2 сценария']);
    expect(s04.scripts).toEqual(['проверку прошли 2 из 2']);
    expect(s04.edit).toBeUndefined();
    const full = plain(frameSummaries(at('full', PAST)));
    expect(full.edit).toEqual(['собрано роликов: 2 из 2']);
    expect(full.judge).toEqual(['кадры прошли: 1 из 2']);
    expect(full.accept).toEqual(['на приёмку: 1 ролик']);
    // Число и слово — неразрывным пробелом.
    expect(frameSummaries(at('01')).trends![0]).toBe(
      'нашёл 6\u00a0тем, взял\u00a03, отсеял\u00a03',
    );
  });

  it('футаж, расход поиска, счётчики, подписи', () => {
    const t = at('04');
    expect(plain(footageLine(t.topics[0]!))).toBe('годных 45 кадров из 70, нужно 24 — хватает');
    expect(plain(footageLine(t.topics[1]!))).toBe('годных 22 кадра из 36, нужно 24 — не хватает');
    // Индексатор до темы из резерва не дошёл — мера трендхантера.
    expect(plain(footageLine(t.topics[2]!))).toBe('годных 20 кадров из 22, нужно 24 — не хватает');
    expect(plain(quotaText(t.search_quota))).toBe(
      'батч потратил 9 поисков · квота дня 100, осталось 60',
    );
    expect(quotaText(null)).toBeNull();
    expect(plain(quotaText({ spent_searches: 1 }))).toBe('батч потратил 1 поиск');
    expect(plain(countsText(t))).toBe('в работе 2 · в резерве 1');
    expect(kindText('series')).toBe('сериал');
    expect(kindText('podcast')).toBeNull();
    expect(sourceLabel({ url: 'https://www.variety.com/x' })).toBe('variety.com');
    expect(sourceLabel({ url: 'x', publication: 'Variety' })).toBe('Variety');
  });
});
