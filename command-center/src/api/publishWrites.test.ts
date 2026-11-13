import { describe, expect, it } from 'vitest';

import {
  batchOf,
  deficitWhy,
  idsOf,
  listOf,
  studioReadOf,
  videoIdOf,
  writeProblemText,
} from './publishWrites';

describe('записи публикации: поля и слова', () => {
  it('теги — через запятую, хэштеги — пробелами или запятыми, без решёток и повторов', () => {
    expect(listOf(' Zenith, MCU ,, Zenith , release date ')).toEqual([
      'Zenith',
      'MCU',
      'release date',
    ]);
    expect(listOf('#Vanguards #Zenith, MCU #Zenith', true)).toEqual(['Vanguards', 'Zenith', 'MCU']);
    expect(idsOf('a1 a2,a3\na1')).toEqual(['a1', 'a2', 'a3']);
  });

  it('батч — «каталог/id» или один id; иначе не батч', () => {
    expect(batchOf('example-film/2026-10-09T0200Z')).toEqual({
      batch_id: '2026-10-09T0200Z',
      dir: 'example-film',
    });
    expect(batchOf(' 2026-10-09T0200Z ')).toEqual({ batch_id: '2026-10-09T0200Z', dir: null });
    expect(batchOf('')).toBeNull();
    expect(batchOf('a/b/c')).toBeNull();
  });

  it('дефицит — только под pipeline/', () => {
    expect(deficitWhy('pipeline/example-film/2026-10-07T0200Z/plan.assetless-rung.json')).toBeNull();
    expect(deficitWhy('')).toMatch(/Укажите/);
    expect(deficitWhy('rotation/ledger/x.json')).toMatch(/только под pipeline/);
    expect(deficitWhy('pipeline/../etc/passwd')).toMatch(/только под pipeline/);
  });

  it('коды отказов — словами; незнакомый — «Фабрика отказала»', () => {
    expect(writeProblemText('confirm_mismatch')).toMatch(/другому действию и сгорело/);
    expect(writeProblemText('model_refused')).toMatch(/моделью/);
    expect(writeProblemText('not_working_factory')).toMatch(/Только смотреть/);
    expect(writeProblemText('что-то новое')).toBe('Фабрика отказала');
    expect(writeProblemText(null)).toBe('Фабрика отказала');
  });

  it('CC-0069: коды переключателя и загрузки — словами', () => {
    expect(writeProblemText('audit_unconfirmed')).toMatch(/Фраза аудита не совпала/);
    expect(writeProblemText('answer_required')).toMatch(/после вашего «да»/);
    expect(writeProblemText('reauthorize')).toMatch(/переразрешить/);
    expect(writeProblemText('upload_failed')).toMatch(/YouTube не принял/);
    expect(writeProblemText('uploaded_unrecorded')).toMatch(/внесите её руками/);
    expect(writeProblemText('switch_unreadable')).toMatch(/не читается/);
  });

  it('подпись холда: коды отказов — словами; устаревший план — «запросите заново»', () => {
    expect(writeProblemText('no_such_hold')).toMatch(/Такого холда нет/);
    expect(writeProblemText('already_signed')).toMatch(/уже подписан/);
    expect(writeProblemText('already_resolved')).toMatch(/уже снят/);
    expect(writeProblemText('not_signable')).toMatch(/центр не снимает/);
    expect(writeProblemText('empty_note')).toMatch(/заметка/);
    expect(writeProblemText('ledger_unreadable')).toMatch(/не читается/);
    expect(writeProblemText('confirm_expired')).toMatch(/План устарел — запросите заново/);
  });
});

describe('CC-0069: прочитанное из Studio', () => {
  it('id ролика — сам id или ссылка; прочее — не id', () => {
    expect(videoIdOf(' rJSXkLVswSs ')).toBe('rJSXkLVswSs');
    expect(videoIdOf('https://youtube.com/shorts/rJSXkLVswSs')).toBe('rJSXkLVswSs');
    expect(videoIdOf('https://www.youtube.com/watch?v=rJSXkLVswSs&t=3')).toBe('rJSXkLVswSs');
    expect(videoIdOf('https://studio.youtube.com/video/rJSXkLVswSs/edit')).toBe('rJSXkLVswSs');
    expect(videoIdOf('short')).toBeNull();
    expect(videoIdOf('')).toBeNull();
  });

  it('поля формы → read; JSON целиком — как есть; плохой JSON — почему', () => {
    const form = {
      title: 'T',
      description: 'D',
      tags: 'a, b',
      visibility: 'Запланировано',
      publishAt: '2026-10-12T01:00+03:00',
    };
    expect(studioReadOf(form, '').read).toEqual({
      title: 'T',
      description: 'D',
      tags: ['a', 'b'],
      visibility: 'Запланировано',
      publish_at: '2026-10-12T01:00+03:00',
    });
    expect(studioReadOf({ ...form, title: ' ' }, '').why).toMatch(/название/);
    expect(studioReadOf({ ...form, publishAt: '' }, '').why).toMatch(/время/);
    expect(studioReadOf(form, '{"title": "X", "tags": "a, b"}').read).toEqual({
      title: 'X',
      tags: 'a, b',
    });
    expect(studioReadOf(form, '{oops').why).toMatch(/JSON/);
    expect(studioReadOf(form, '[1]').why).toMatch(/объект JSON/);
  });
});
