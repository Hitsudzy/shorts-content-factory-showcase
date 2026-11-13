// Строки редактора списка (CC-0115 шаг 3, CC-0129): текст полей ↔ строка документа; поля, которых
// редактор не знает, и не тронутые поля (null, числа, коды, флажки) уходят обратно как были.
import { getAt, hasAt, itemOf, rowOf, setAt, type FieldSpec } from './rows';

const FIELDS: FieldSpec[] = [
  { key: 'name', label: 'Имя' },
  { key: 'hosts', label: 'Сайты', kind: 'list' },
  { key: 'big', label: 'Крупное', kind: 'bool' },
  { key: 'tier', label: 'Уровень', kind: 'select', num: true, options: [] },
  { key: 'need', label: 'Что нужно', kind: 'select', options: [] },
  { key: 'why', label: 'Почему', words: { curated: 'внесён вручную' } },
];

describe('строки редактора списка', () => {
  it('не тронутая строка уходит как была — null, числа, флажки, коды, чужие поля', () => {
    const row = {
      name: '  Как есть ',
      hosts: ['a.org', 'b.org'],
      big: false,
      tier: 1,
      need: null,
      why: 'curated',
      ai_policy: { verdict: 'allowed', checks: [{ robots_url: 'https://a.org/robots.txt' }] },
      extra: { deep: [1, 2] },
    };
    expect(rowOf(itemOf(row, FIELDS), FIELDS)).toEqual(row);
  });

  it('правка: флажок, число, список, слово → код; пустое поле убирает ключ', () => {
    const item = itemOf({ name: 'x', big: false, tier: 1, need: 'quote', why: 'curated' }, FIELDS);
    expect(item.text).toMatchObject({ big: '', tier: '1', need: 'quote', why: 'внесён вручную' });
    const out = rowOf(
      {
        ...item,
        text: { ...item.text, big: '1', tier: '2', hosts: ' c.org , ,d.org', need: '', name: '' },
      },
      FIELDS,
    );
    expect(out).toEqual({ big: true, tier: 2, hosts: ['c.org', 'd.org'], why: 'curated' });
  });

  it('снятый флажок: был — false, не было — ключа нет', () => {
    const had = itemOf({ big: true }, FIELDS);
    expect(rowOf({ ...had, text: { ...had.text, big: '' } }, FIELDS)).toEqual({ big: false });
    const none = itemOf({}, FIELDS);
    expect(rowOf(none, FIELDS)).toEqual({});
  });

  it('вложенные поля (CC-0130): правится только своё, соседи и чужие поля — как были', () => {
    const NESTED: FieldSpec[] = [
      { key: 'attribution.credit', label: 'Подпись' },
      { key: 'attribution.on_screen', label: 'На экране', kind: 'bool' },
      { key: 'found_by.0.how', label: 'Как', kind: 'select', options: [] },
      { key: 'caveats', label: 'Оговорки', kind: 'lines' },
    ];
    const row = {
      id: 'nasa',
      attribution: { required: false, requested: true, credit: 'NASA', on_screen: false },
      found_by: [
        { how: 'youtube_channels', works_now: true },
        { how: 'archive_api', endpoint: 'https://images-api.nasa.gov', works_now: false },
      ],
      caveats: ['Эмблема — не общественное достояние.', 'Без намёка на одобрение, NASA.'],
      quote: 'как есть',
    };
    const item = itemOf(row, NESTED);
    expect(item.text).toMatchObject({
      'attribution.credit': 'NASA',
      'attribution.on_screen': '',
      'found_by.0.how': 'youtube_channels',
      caveats: 'Эмблема — не общественное достояние.\nБез намёка на одобрение, NASA.',
    });
    expect(rowOf(item, NESTED)).toEqual(row);
    const out = rowOf(
      {
        ...item,
        text: {
          ...item.text,
          'attribution.credit': 'NASA/JPL',
          'attribution.on_screen': '1',
          caveats: ' Одна оговорка \n\n',
        },
      },
      NESTED,
    );
    expect(out).toEqual({
      ...row,
      attribution: { required: false, requested: true, credit: 'NASA/JPL', on_screen: true },
      caveats: ['Одна оговорка'],
    });
    expect(out.found_by).toBe(row.found_by);
  });

  it('вложенное поле новой строки создаёт свой уровень; пустое — ключа нет', () => {
    const NESTED: FieldSpec[] = [
      { key: 'attribution.credit', label: 'Подпись' },
      { key: 'found_by.0.how', label: 'Как' },
    ];
    const item = itemOf({}, NESTED);
    expect(rowOf(item, NESTED)).toEqual({});
    expect(
      rowOf(
        { ...item, text: { 'attribution.credit': 'ESA', 'found_by.0.how': 'archive_api' } },
        NESTED,
      ),
    ).toEqual({ attribution: { credit: 'ESA' }, found_by: [{ how: 'archive_api' }] });
    const had = itemOf({ attribution: { credit: 'ESA', where: 'description' } }, NESTED);
    expect(rowOf({ ...had, text: { ...had.text, 'attribution.credit': '' } }, NESTED)).toEqual({
      attribution: { where: 'description' },
    });
  });

  it('варианты через «|» (CC-0130): в поле — через запятую; не тронутое — как было', () => {
    const ALTS: FieldSpec[] = [{ key: 'pattern', label: 'Как узнаёт', joined: '|' }];
    const item = itemOf({ pattern: 'european southern observatory|eso', x: 1 }, ALTS);
    expect(item.text.pattern).toBe('european southern observatory, eso');
    expect(rowOf(item, ALTS)).toEqual({ pattern: 'european southern observatory|eso', x: 1 });
    const edited = { ...item, text: { pattern: ' eso , european southern observatory,, ' } };
    expect(rowOf(edited, ALTS)).toEqual({ pattern: 'eso|european southern observatory', x: 1 });
    expect(rowOf({ ...item, text: { pattern: ' , ' } }, ALTS)).toEqual({ x: 1 });
  });

  it('getAt / hasAt / setAt по ключу с точками', () => {
    const row = { a: { b: null }, l: [{ x: 1 }] };
    expect(getAt(row, 'l.0.x')).toBe(1);
    expect(getAt(row, 'a.b.c')).toBeUndefined();
    expect(hasAt(row, 'a.b')).toBe(true);
    expect(hasAt(row, 'l.1')).toBe(false);
    expect(setAt(row, 'l.0.y', 2)).toEqual({ a: { b: null }, l: [{ x: 1, y: 2 }] });
    expect(setAt(row, 'z.q', undefined)).toBe(row);
  });
});
