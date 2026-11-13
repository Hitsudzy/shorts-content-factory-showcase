// Слова тёзок (CC-0183): кто тёзка, чем отличить, как название читается в окнах; `~` не показывается.
import {
  namesakeMark,
  namesakesOf,
  stashKeyOf,
  stashTitles,
  withMark,
  withoutBatchTail,
} from './stashWords';
import type { StashVideo } from '@/api/stash';

const video = (slug: string, batch_id: string, title: string) =>
  ({ slug, batch_id, title_clean: title }) as unknown as StashVideo;

describe('CC-0183: слова тёзок', () => {
  it('тёзки — только имена с двумя батчами', () => {
    const names = namesakesOf([
      { slug: 'a', batch_id: '2026-11-04T0200Z' },
      { slug: 'a', batch_id: '2026-10-09T0200Z' },
      { slug: 'b', batch_id: '2026-10-09T0200Z' },
      { slug: 'c', batch_id: null },
    ]);
    expect([...names.keys()]).toEqual(['a']);
  });

  it('метка: дата батча; нет тёзки — ничего; один день — со временем; не дата — сам id', () => {
    const names = namesakesOf([
      { slug: 'a', batch_id: '2026-11-04T0200Z' },
      { slug: 'a', batch_id: '2026-10-09T0200Z' },
      { slug: 'b', batch_id: '2026-11-04T0200Z' },
      { slug: 'b', batch_id: '2026-11-04T1000Z' },
      { slug: 'c', batch_id: 'rebuild-x' },
      { slug: 'c', batch_id: 'rebuild-y' },
    ]);
    expect(namesakeMark(names, 'a', '2026-11-04T0200Z')).toBe('батч от 4.11');
    expect(namesakeMark(names, 'a', '2026-10-09T0200Z')).toBe('батч от 9.10');
    expect(namesakeMark(names, 'x', '2026-10-09T0200Z')).toBeNull();
    expect(namesakeMark(names, 'a', null)).toBeNull();
    expect(namesakeMark(names, 'b', '2026-11-04T0200Z')).toBe('батч от 4.11, 05:00');
    expect(namesakeMark(names, 'b', '2026-11-04T1000Z')).toBe('батч от 4.11, 13:00');
    expect(namesakeMark(names, 'c', 'rebuild-x')).toMatch(/rebuild-x/);
    expect(withMark('Название', null)).toBe('Название');
    expect(withMark('Название', 'батч от 4.11')).toBe('Название · батч от 4.11');
  });

  it('название по батчу; у тёзки к нему добавлен батч; без тёзок — как раньше', () => {
    const titleOf = stashTitles([
      video('a', '2026-11-04T0200Z', 'Новый'),
      video('a', '2026-10-09T0200Z', 'Старый'),
      video('b', '2026-10-09T0200Z', 'Один'),
    ]);
    expect(titleOf('a', '2026-11-04T0200Z')).toBe('Новый · батч от 4.11');
    expect(titleOf('a', '2026-10-09T0200Z')).toBe('Старый · батч от 9.10');
    expect(titleOf('b', '2026-10-09T0200Z')).toBe('Один');
    expect(titleOf('b')).toBe('Один');
    expect(titleOf(null)).toBe('—');
    expect(stashKeyOf({ slug: 'a', batch_id: 'B' })).toBe('B/a');
    expect(stashKeyOf({ slug: 'a' })).toBe('a');
  });

  it('файл `<имя>~<батч>` оператор не видит; `~` вне имени остаётся', () => {
    expect(withoutBatchTail('publish/r/_queue/neon-rift~2026-10-09T0200Z.mp4')).toBe(
      'publish/r/_queue/neon-rift.mp4',
    );
    expect(withoutBatchTail('~/publish/note.md, ~ 5 минут')).toBe('~/publish/note.md, ~ 5 минут');
  });
});
