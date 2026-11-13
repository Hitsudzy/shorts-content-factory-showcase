// CC-0132: строки фабрики о задачах банка — для человека: id мемов именами, пути словами, тире
// не уходит в начало строки.
import { nbDashes } from '@/api/humanText';

import {
  afterDash,
  busyWhy,
  COMMIT_REFUSED_TITLE,
  humanNote,
  jobCommitView,
  namesIn,
} from './jobs';

const NB = String.fromCharCode(0xa0);

describe('слова задач банка мемов', () => {
  it('id мемов — именами, в кавычках и без; короткий id не задевает вставленное имя', () => {
    const ids = ['roll-safe', 'safe', 'distracted-boyfriend'];
    expect(namesIn('Задача упала на «distracted-boyfriend»: ошибка.', ids)).toBe(
      'Задача упала на «Distracted boyfriend»: ошибка.',
    );
    expect(namesIn("мема 'roll-safe' нет, safe есть", ids)).toBe(
      'мема «Roll safe» нет, «Safe» есть',
    );
    expect(namesIn('без id', [])).toBe('без id');
  });

  it('заметка плана: папка оригиналов и прочие пути — словами', () => {
    expect(humanNote('Оригиналы картинок останутся в _desk/originals/ банка.')).toBe(
      'Оригиналы картинок останутся в папке оригиналов банка.',
    );
    expect(humanNote('Журнал — в shared/inserts/memes/_desk/jobs.')).toBe(
      'Журнал — в папке банка.',
    );
    expect(humanNote('Вырезку придётся сделать заново: roll-safe.', ['roll-safe'])).toBe(
      'Вырезку придётся сделать заново: «Roll safe».',
    );
  });

  it('тире — с неразрывным пробелом перед ним', () => {
    expect(nbDashes('пойдёт в фоне — её ход - на столе')).toBe(
      `пойдёт в фоне${NB}— её ход${NB}— на столе`,
    );
    expect(busyWhy({ kind_word: 'вырезка фона' })).toBe(
      `Идёт вырезка фона${NB}— дождитесь её конца: отмены нет`,
    );
  });

  it('причина после тире — со строчной, аббревиатуры и латиница — как есть', () => {
    expect(afterDash('Распознавание не нашло предмета')).toBe('распознавание не нашло предмета');
    expect(afterDash('ЦРУ запретило')).toBe('ЦРУ запретило');
    expect(afterDash('GIF — поля не режет')).toBe('GIF — поля не режет');
  });
});

describe('CC-0161: коммит итога задачи', () => {
  it('отказ git — заметная строка, слово git — подробностью', () => {
    expect(
      jobCommitView({
        commit: { status: 'refused', sha: null, committed: null, detail: ' fatal: lock | x ' },
      }),
    ).toEqual({
      kind: 'refused',
      title: COMMIT_REFUSED_TITLE,
      action: 'Скажите фабрике.',
      detail: 'fatal: lock | x',
    });
    expect(COMMIT_REFUSED_TITLE).toBe(
      `Результат сохранён, но фабрика не смогла записать его в историю изменений${NB}— в её папке остались незаписанные правки.`,
    );
    expect(jobCommitView({ commit: { status: 'refused', detail: null } })).toEqual({
      kind: 'refused',
      title: COMMIT_REFUSED_TITLE,
      action: 'Скажите фабрике.',
      detail: null,
    });
  });

  it('записано в историю — приглушённо, sha коротко; «нечего» и старый стол — ничего', () => {
    expect(
      jobCommitView({ commit: { status: 'committed', sha: 'abcdef1234567890', committed: ['a'] } }),
    ).toEqual({ kind: 'committed', text: 'записано в историю', sha: 'abcdef1' });
    expect(jobCommitView({ commit: { status: 'committed', sha: null } })).toEqual({
      kind: 'committed',
      text: 'записано в историю',
      sha: null,
    });
    expect(jobCommitView({ commit: { status: 'nothing', detail: 'no git work tree' } })).toBeNull();
    expect(jobCommitView({ commit: null })).toBeNull();
    expect(jobCommitView({})).toBeNull();
  });
});
