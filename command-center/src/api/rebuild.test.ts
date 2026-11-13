import { describe, expect, it } from 'vitest';

import { parseSeconds, planBody } from './rebuild';

describe('пересборка: секунды и тело плана', () => {
  it('секунды — пробелами, запятыми, минутами, с «с»; дробь — с одной цифрой после запятой', () => {
    expect(parseSeconds('12 18 24')).toEqual({ at: [12, 18, 24] });
    expect(parseSeconds('12, 18, 24')).toEqual({ at: [12, 18, 24] });
    expect(parseSeconds('12,18,24')).toEqual({ at: [12, 18, 24] });
    expect(parseSeconds('12,5 18с 1:05')).toEqual({ at: [12.5, 18, 65] });
    expect(parseSeconds('12 12 18')).toEqual({ at: [12, 18] });
    expect(parseSeconds('')).toHaveProperty('error');
    expect(parseSeconds('12 потом 18')).toEqual({
      error: '«потом» — не секунды. Пишите так: 12 18 24 или 1:05.',
    });
    expect(parseSeconds(Array.from({ length: 21 }, (_, i) => i).join(' '))).toEqual({
      error: 'Не больше 20 секунд за раз.',
    });
  });

  it('исключения — только в reedit; замечание по ролику называет секунды', () => {
    const args = { slug: 'delver', text: ' хук скучный ', exclude: ['4=a:1'], seconds: [12, 18.5] };
    expect(planBody({ ...args, mode: 'reedit' })).toEqual({
      videos: ['delver'],
      mode: 'reedit',
      notes: {
        text: 'хук скучный',
        videos: { delver: { exclude: ['4=a:1'], note: 'замечания на секундах 12, 18,5' } },
      },
    });
    expect(planBody({ ...args, mode: 'rewrite' }).notes).toEqual({
      text: 'хук скучный',
      videos: { delver: { exclude: [], note: 'замечания на секундах 12, 18,5' } },
    });
    expect(
      planBody({ slug: 'delver', mode: 'rewrite', text: '', exclude: [], seconds: [] }).notes,
    ).toEqual({ text: null, videos: null });
  });
});
