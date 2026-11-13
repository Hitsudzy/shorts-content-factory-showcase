import { describe, expect, it } from 'vitest';

import { cardKeys, staleAfterBuild } from './cards';
import { publishKeys } from './publish';
import { videoKeys } from './videos';

describe('staleAfterBuild — что перечитать по итогу сборки карточки (CC-0178)', () => {
  const stale = staleAfterBuild('example-film', 'zootopia-2');

  it('карточка дня — только собранного ролика, чужие по прежнему «день/ролик» не трогает', () => {
    expect(stale(publishKeys.note('example-film', 'zootopia-2', '2026-10-13'))).toBe(true);
    expect(stale(publishKeys.note('example-film', 'zootopia-2', ''))).toBe(true);
    // Перенесённый ролик: лента ещё старая — перечитать его прежний день значит 404.
    expect(stale(publishKeys.note('example-film', 'filler-1', '2026-10-14'))).toBe(false);
    expect(stale(publishKeys.note('example-tech', 'zootopia-2', '2026-10-13'))).toBe(false);
  });

  it('виды, где видно состояние карточки, и ролики — перечитываются; итог сборки и холды — нет', () => {
    expect(stale(publishKeys.queue('example-film', 14))).toBe(true);
    expect(stale(publishKeys.overview)).toBe(true);
    expect(stale([...publishKeys.all, 'stash', 'example-film'])).toBe(true);
    expect(stale(videoKeys.all)).toBe(true);
    expect(stale(cardKeys.run('example-film', 'run-zootopia-2-auto'))).toBe(false);
    expect(stale(publishKeys.holds('example-film'))).toBe(false);
    expect(stale(publishKeys.pause('example-film'))).toBe(false);
  });

  it('ролик не назван — как раньше, все карточки дней', () => {
    expect(staleAfterBuild('example-film', null)(publishKeys.note('example-film', 'a', 'd'))).toBe(
      true,
    );
  });
});
