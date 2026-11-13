import { describeFields, REEL_CONFIG_TEXT } from '@/mocks/channels';

import {
  buildBlocks,
  checkDetail,
  errorKeys,
  humanCheck,
  jsonProblems,
  leaves,
  noteTip,
  readDoc,
  setValue,
} from './fields';

describe('правка конфига без переформатирования', () => {
  it('меняются только байты значения: строчные массивы и порядок ключей на месте', () => {
    const next = setValue(REEL_CONFIG_TEXT, ['scope', 'min_popularity_score'], 50);
    expect(next).toBe(
      REEL_CONFIG_TEXT.replace('"min_popularity_score": 45', '"min_popularity_score": 50'),
    );
    expect(next).toContain('"content_type": ["tv_series", "film", "animation"],');
  });

  it('строки экранируются, булевы и списки пишутся как JSON', () => {
    let t = setValue(REEL_CONFIG_TEXT, ['voice_profile', 'voice'], 'am "puck"');
    t = setValue(t, ['video_editor', 'burn_subtitles'], false);
    t = setValue(t, ['former_channel_ids'], ['a', 'b']);
    const doc = readDoc(t)!;
    expect((doc.voice_profile as Record<string, unknown>).voice).toBe('am "puck"');
    expect((doc.video_editor as Record<string, unknown>).burn_subtitles).toBe(false);
    expect(doc.former_channel_ids).toEqual(['a', 'b']);
    expect(t.split('\n').length).toBeGreaterThanOrEqual(REEL_CONFIG_TEXT.split('\n').length);
  });
});

describe('блоки формы', () => {
  const fields = describeFields(readDoc(REEL_CONFIG_TEXT) as never, 'config');

  it('блок на каждый ключ-объект, простые ключи — в «Основное», пояснения — не поля', () => {
    const blocks = buildBlocks(fields, 'config');
    expect(blocks.map((b) => b.key)).toEqual([
      null,
      'scope',
      'voice_profile',
      'video_editor',
      'batch_schedule',
    ]);
    const all = blocks.flatMap((b) => leaves(b.nodes)).map((f) => f.path.join('.'));
    expect(all).toContain('scope.min_popularity_score');
    expect(all.some((p) => p.endsWith('note'))).toBe(false);
  });

  it('тултип — без номера задачи в начале; длинное пояснение укорочено', () => {
    expect(noteTip('CF-0060: a candidate below this score is not taken.').tip).toBe(
      'A candidate below this score is not taken.',
    );
    expect(noteTip('CF-0592 (grill 06.10): when the batch may start.').tip).toBe(
      'When the batch may start.',
    );
    const long = noteTip(`${'Word '.repeat(120)}end.`);
    expect(long.trimmed).toBe(true);
    expect(long.tip!.length).toBeLessThan(380);
  });
});

describe('ошибки — человеческим языком', () => {
  const text =
    'example-film.json.video_editor.max_attempts_per_video: must be a positive integer, got 0';
  const ru =
    'Настройки монтажёра, поле video_editor.max_attempts_per_video (сейчас 0): значение не подходит монтажёру - с ним он не соберёт ролик.';

  it('русская строка фабрики — как есть; английская и код — только в «подробнее»', () => {
    const line = {
      text,
      field: 'video_editor.max_attempts_per_video',
      code: 'video_editor_invalid',
      text_ru: ru,
    };
    expect(humanCheck(line)).toEqual({
      where: 'video editor → max attempts per video',
      why: ru,
      ru: true,
    });
    expect(checkDetail(line)).toBe(`${text} (код причины: video_editor_invalid)`);
    expect([...errorKeys([line])]).toEqual([
      'config:video_editor',
      'config:video_editor.max_attempts_per_video',
    ]);
  });

  it('нет русской строки — запасной путь: поле по-русски и причина словами проверки', () => {
    const line = {
      text: 'example-film.json.scope.min_popularity_score: must be a number from 0 to 100, got 450',
      field: 'scope.min_popularity_score',
      code: null,
      text_ru: null,
    };
    expect(humanCheck(line)).toEqual({
      where: 'scope → min popularity score',
      why: 'Must be a number from 0 to 100, got 450',
      ru: false,
    });
    expect(checkDetail(line)).toBe(line.text);
    expect([...errorKeys([line])]).toEqual(['config:scope', 'config:scope.min_popularity_score']);
    expect(
      humanCheck({
        text: 'stance.json.channel_id: wrong',
        field: 'stance.channel_id',
        code: null,
        text_ru: null,
      }).where,
    ).toBe('Позиция: channel id');
  });

  it('синтаксис JSON — по-русски, со строкой и столбцом', () => {
    const [p] = jsonProblems('{\n  "a": 1\n  "b": 2\n}');
    expect(p).toMatchObject({ line: 3, text: 'между полями нужна запятая' });
    expect(jsonProblems('[1]')[0]!.text).toMatch(/одним объектом/);
    expect(jsonProblems(REEL_CONFIG_TEXT)).toEqual([]);
  });
});
