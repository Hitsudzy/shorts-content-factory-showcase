import { describe, expect, it } from 'vitest';

import { channelsInText } from './names';

const CHANNELS = [
  { id: 'example-film', former_ids: [], display_name: 'ExampleFilm' },
  { id: 'example-science', former_ids: ['example-science'], display_name: 'ExampleScience' },
];

describe('текст фабрики — названиями каналов (ревью экранов CC-0089, CC-0120)', () => {
  it('id канала словом — названием; в путях и файлах — как есть', () => {
    expect(channelsInText('канал example-film есть', CHANNELS)).toBe('канал ExampleFilm есть');
    expect(channelsInText('example-film: лента на 3 дн. вперёд (≥ 3)', CHANNELS)).toBe(
      'ExampleFilm: лента на 3 дн. вперёд (≥ 3)',
    );
    expect(channelsInText('канал example-science есть', CHANNELS)).toBe('канал ExampleScience есть');
    expect(channelsInText('channels/example-film.json', CHANNELS)).toBe('channels/example-film.json');
    expect(channelsInText('pipeline/example-film/x', CHANNELS)).toBe('pipeline/example-film/x');
  });

  it('батч — каналом и временем по МСК', () => {
    expect(channelsInText('уже был: example-film 2026-10-09T2305Z - 1 батч', CHANNELS)).toBe(
      'уже был: ExampleFilm · батч 10.10, 02:05 - 1 батч',
    );
  });
});
