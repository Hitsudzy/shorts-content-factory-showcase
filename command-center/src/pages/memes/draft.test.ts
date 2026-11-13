import type { MemeDesk } from '@/api/memes';
import { createMemesBackend } from '@/mocks/memes';

import {
  bodyOf,
  changedIds,
  coreOf,
  cutOf,
  draftStore,
  isDirty,
  marksOf,
  resetMemeDrafts,
  staleIds,
  stateOf,
  withCut,
  withNote,
  withVerdict,
  wholeOf,
} from './draft';

const desk = (patch: Partial<MemeDesk> = {}): MemeDesk => ({
  ...createMemesBackend().desk('example-tech'),
  ...patch,
});

afterEach(() => resetMemeDrafts());

describe('отметки черновика', () => {
  it('coreOf берёт только v, cut, note; подпись «кто и когда» и мусор — прочь', () => {
    expect(
      coreOf({ v: 'keep', cut: true, note: 'x', marked_by: 'user', via: 'center', junk: 1 }),
    ).toEqual({ v: 'keep', cut: true, note: 'x' });
    expect(coreOf({ v: 'maybe', cut: 'yes' })).toEqual({});
    expect(coreOf(null)).toEqual({});
    expect(marksOf({ a: { v: 'drop' }, b: 'x' })).toEqual({ a: { v: 'drop' }, b: {} });
  });

  it('то же решение ещё раз — снять решение; пустая отметка исчезает', () => {
    let m = withVerdict({}, 'a', 'keep');
    expect(m).toEqual({ a: { v: 'keep' } });
    m = withVerdict(m, 'a', 'drop');
    expect(m).toEqual({ a: { v: 'drop' } });
    m = withVerdict(m, 'a', 'drop');
    expect(m).toEqual({});
  });

  it('«можно вырезать»: GIF — никогда; вернулись к сохранённому — отметки cut нет', () => {
    const still = { id: 'a', gif: false, cutout: false };
    let m = withCut({}, undefined, still);
    expect(m).toEqual({ a: { cut: true } });
    expect(cutOf(still, m.a)).toBe(true);
    m = withCut(m, undefined, still);
    expect(m).toEqual({});
    // Сохранено с cut — переключение туда-обратно пишет cut явно.
    expect(withCut({ a: { cut: false } }, { cut: false }, still)).toEqual({ a: { cut: true } });
    const gif = { id: 'g', gif: true, cutout: true };
    expect(withCut({}, undefined, gif)).toEqual({});
    expect(cutOf(gif, { cut: true })).toBe(false);
  });

  it('CC-0143: «целиком» — ровно обратное «можно вырезать», с черновиком; GIF — всегда целиком', () => {
    const still = { gif: false, cutout: false };
    const cut = { gif: false, cutout: true };
    const gif = { gif: true, cutout: true };
    expect(wholeOf(still, undefined)).toBe(true);
    expect(wholeOf(still, { cut: true })).toBe(false);
    expect(wholeOf(cut, undefined)).toBe(false);
    expect(wholeOf(cut, { cut: false })).toBe(true);
    expect(wholeOf(gif, undefined)).toBe(true);
    expect(wholeOf(gif, { cut: true })).toBe(true);
    for (const [e, m] of [
      [still, undefined],
      [still, { cut: true }],
      [cut, undefined],
      [cut, { cut: false }],
      [gif, { cut: true }],
    ] as const)
      expect(wholeOf(e, m)).toBe(!cutOf(e, m));
  });

  it('заметка: пустая — без заметки', () => {
    expect(withNote({}, 'a', 'смешно')).toEqual({ a: { note: 'смешно' } });
    expect(withNote({ a: { v: 'keep', note: 'x' } }, 'a', '')).toEqual({ a: { v: 'keep' } });
  });

  it('что поменялось, тело сохранения без мемов не из банка, состояние мема', () => {
    const saved = { a: { v: 'keep' as const }, gone: { v: 'drop' as const } };
    const local = { ...saved, b: { v: 'drop' as const }, c: {} };
    expect(changedIds(local, saved)).toEqual(['b']);
    const ids = new Set(['a', 'b', 'c']);
    expect(bodyOf(local, ids)).toEqual({ a: { v: 'keep' }, b: { v: 'drop' } });
    expect(staleIds(local, ids)).toEqual(['gone']);
    expect(stateOf({ review: 'pending' }, undefined)).toBe('new');
    expect(stateOf({ review: null }, undefined)).toBe('in');
    expect(stateOf({ review: 'pending' }, { v: 'drop' })).toBe('drop');
  });
});

describe('хранилище черновиков', () => {
  it('стол приходит — черновик фабричный; правка — несохранённое', () => {
    const d = desk();
    draftStore.sync(d);
    const got = draftStore.get(d.bank)!;
    expect(got.base).toBe(d.fingerprint);
    expect(got.local['always-has-been']).toEqual({ v: 'keep', cut: false });
    draftStore.edit(d.bank, d, (l) => withVerdict(l, 'bell-curve', 'drop'));
    expect(isDirty(draftStore.get(d.bank)!)).toBe(true);
    expect(draftStore.anyDirty()).toBe(true);
  });

  it('несохранённое не затирается: чужой отпечаток — «изменились в другом месте»', () => {
    const d = desk();
    draftStore.sync(d);
    draftStore.edit(d.bank, d, (l) => withVerdict(l, 'bell-curve', 'drop'));
    draftStore.sync({ ...d, fingerprint: 'other', decisions: {} });
    const got = draftStore.get(d.bank)!;
    expect(got.conflict).toBe(true);
    expect(got.local['bell-curve']).toEqual({ v: 'drop' });
    expect(got.base).toBe(d.fingerprint);
    draftStore.replace({ ...d, fingerprint: 'other', decisions: {} });
    expect(draftStore.get(d.bank)).toMatchObject({ base: 'other', local: {}, conflict: false });
  });

  it('без несохранённого — просто берёт новый черновик фабрики', () => {
    const d = desk();
    draftStore.sync(d);
    draftStore.sync({ ...d, fingerprint: 'other', decisions: { 'bell-curve': { v: 'keep' } } });
    expect(draftStore.get(d.bank)).toMatchObject({
      base: 'other',
      local: { 'bell-curve': { v: 'keep' } },
      conflict: false,
    });
  });

  it('сохранено: новый base, правки во время сохранения остаются несохранёнными', () => {
    const d = desk();
    draftStore.sync(d);
    draftStore.edit(d.bank, d, (l) => withVerdict(l, 'bell-curve', 'drop'));
    const sent = draftStore.get(d.bank)!.local;
    draftStore.edit(d.bank, d, (l) => withVerdict(l, 'roll-safe', 'keep'));
    draftStore.saved(d.bank, 'fp2', sent);
    const got = draftStore.get(d.bank)!;
    expect(got.base).toBe('fp2');
    expect(changedIds(got.local, got.saved)).toEqual(['roll-safe']);
  });
});
