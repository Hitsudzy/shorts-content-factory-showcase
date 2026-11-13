import { renderChannel, TEMPLATE_INPUTS } from '@/mocks/channelTemplate';

import { readDoc } from './fields';
import { todoItems } from './firstBatch';
import {
  diffHunks,
  draftStance,
  initialInputs,
  inputErrorsByField,
  lineDiff,
  localError,
  serverErrors,
  stanceErrors,
  stripTasks,
  WIZARD_SLUG_ERROR,
  thesisNote,
} from './wizard';

const input = (name: string) => TEMPLATE_INPUTS.find((i) => i.name === name)!;
const files = renderChannel({
  channel_id: 'example-food',
  display_name: 'ExampleFood',
  language: 'en',
});
const stance = files[1]!.text;

describe('мастер «Новый канал»: логика', () => {
  it('входы — из шаблона, язык по умолчанию фабрики', () => {
    expect(initialInputs(TEMPLATE_INPUTS)).toEqual({
      channel_id: '',
      display_name: '',
      language: 'en',
    });
  });

  it('своя проверка: обязательность, регулярка фабрики, адрес мастера', () => {
    expect(localError(input('channel_id'), '')).toBe('Нужно заполнить');
    expect(localError(input('channel_id'), 'Food')).toMatch(/Латиница/);
    expect(localError(input('channel_id'), 'example-food')).toBeNull();
    // `new` фабрика (0.5.0) отклоняет сама — её текст; своя строка — запасная.
    expect(localError(input('channel_id'), 'new')).toBeNull();
    const ids = { channel_id: 'new', display_name: 'X', language: '' };
    expect(inputErrorsByField(ids, {}).channel_id).toEqual([WIZARD_SLUG_ERROR]);
    const theirs = { channel_id: ["'new' - служебное имя, не канал"] };
    expect(inputErrorsByField(ids, theirs)).toBe(theirs);
    expect(
      stanceErrors([
        { field: 'stance.channel_id', text: 'a', code: null, text_ru: null },
        { field: 'stance', text: 'b', code: null, text_ru: null },
        { field: 'stancer', text: 'c', code: null, text_ru: null },
        { field: null, text: 'd', code: null, text_ru: null },
      ]).map((l) => l.text),
    ).toEqual(['a', 'b']);
    expect(localError(input('language'), '')).toBeNull();
    expect(localError(input('language'), 'english')).toMatch(/Код языка/);
    expect(localError(input('display_name'), 'Любое')).toBeNull();
  });

  it('ошибки dry-run раскладываются по полям без технической приставки', () => {
    const r = serverErrors([
      {
        field: 'channel_id',
        text: "channel_id: канал 'example-film' уже есть (channels/example-film.json)",
        code: null,
        text_ru: "channel_id: канал 'example-film' уже есть (channels/example-film.json)",
      },
      {
        field: 'display_name',
        text: 'display_name: one line',
        code: null,
        text_ru: null,
      },
      {
        field: null,
        text: 'example-food.json: theme.text: low contrast',
        code: 'theme_invalid',
        text_ru: 'Оформление канала: цвета и шрифты заданы не по правилам.',
      },
    ]);
    expect(r.byField.channel_id).toEqual(["Канал 'example-film' уже есть"]);
    expect(r.byField.display_name).toEqual(['One line']);
    expect(r.rest.map((l) => l.code)).toEqual(['theme_invalid']);
  });

  it('номера задач уходят из подсказки', () => {
    expect(stripTasks('CC-0008: the template. Later (CF-0197).')).toBe('The template. Later.');
  });

  it('черновик позиции: точечная правка файла фабрики, пусто — правки нет', () => {
    expect(thesisNote(stance)).toMatch(/one sentence/);
    expect(draftStance(stance, { thesis: '  ' })).toBeNull();
    const next = draftStance(stance, { thesis: 'Food facts, checked.' })!;
    expect(readDoc(next)?.position).toMatchObject({ thesis: 'Food facts, checked.' });
    const diff = diffHunks(lineDiff(stance, next));
    expect(diff.filter((l) => l.kind !== ' ')).toEqual([
      { kind: '-', text: '    "thesis": "",' },
      { kind: '+', text: '    "thesis": "Food facts, checked.",' },
    ]);
  });

  it('«что ещё нужно до первого батча» — из заметок файлов шаблона', () => {
    const items = todoItems(readDoc(files[0]!.text), readDoc(stance), 'конвейера нет', 'x');
    expect(items.map((i) => i.id)).toEqual([
      'pipeline',
      'schedule',
      'blocks',
      'theme',
      'stance',
      'brand',
    ]);
    expect(items.find((i) => i.id === 'blocks')!.more[0]).toBe(
      'нет ключей: scope, sources, patterns, insert_layers, voice_profile',
    );
  });
});
