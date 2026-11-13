import { fixtures, READ_ONLY_REASON, writesModes } from '@/mocks/fixtures';

import { plainReason } from './plainReason';
import { writesOf } from './writes';

describe('writesOf (CC-0059)', () => {
  it('health ещё нет — не гасим: решает сервер', () => {
    expect(writesOf(undefined)).toMatchObject({ allowed: true, reason: null, dev: false });
  });

  it('рабочая фабрика, только смотреть, флаг разработки', () => {
    expect(writesOf({ ...fixtures.health, ...writesModes.on })).toMatchObject({
      allowed: true,
      dev: false,
    });
    expect(writesOf({ ...fixtures.health, ...writesModes.off })).toMatchObject({
      allowed: false,
      reason: READ_ONLY_REASON,
    });
    expect(writesOf({ ...fixtures.health, ...writesModes.dev })).toMatchObject({
      allowed: true,
      dev: true,
      devReason: READ_ONLY_REASON,
    });
  });

  it('writes:false без причины — общая строка, а не пустота', () => {
    const w = writesOf({
      ...fixtures.health,
      writes: false,
      writes_reason: null,
      writes_dev: false,
    });
    expect(w.reason).toBe('API запущен не на рабочей фабрике');
  });

  it('причина простыми словами: пути из строки фабрики убраны', () => {
    expect(plainReason(READ_ONLY_REASON)).toBe(
      'это рабочая копия разработки, а не рабочая фабрика',
    );
    expect(
      plainReason(
        'это рабочая копия разработки (~/factory/.worktrees/cc-api), а не рабочая фабрика',
      ),
    ).toBe('это рабочая копия разработки, а не рабочая фабрика');
    expect(plainReason('основной чекаут не на main (cc/api)')).toBe('основной чекаут не на main');
    expect(plainReason('копия в /srv/factory/x не main')).toBe('копия в не main');
    // договор 0.35.0: корень фабрики — `.../<имя>`, домашний каталог — `~`
    expect(plainReason('это рабочая копия разработки (.../cc-api), а не рабочая фабрика')).toBe(
      'это рабочая копия разработки, а не рабочая фабрика',
    );
    expect(plainReason('не git-репозиторий .../factory')).toBe('не git-репозиторий');
    expect(plainReason('копия в ~/x/y не main')).toBe('копия в не main');
    expect(plainReason('ветка dev')).toBe('ветка dev');
    expect(plainReason('(/a/b)')).toBe('API запущен не на рабочей фабрике');
  });
});
