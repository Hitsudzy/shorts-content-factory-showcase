// CC-0152 (CF-0821): «Не в копилке» — своя строка центра по коду и названию, тёзка одной строкой.
import { LEFT_OUT_NAMESAKE } from '@/mocks/videos';

import { LEFT_OUT_REASON, leftOutText, namesakeText, notifiedText, withoutMark } from './leftOut';

const NBH = '\u2011';

describe('CC-0152: не в копилке (CF-0821)', () => {
  it('приставку фабрики «НЕ В КОПИЛКЕ: » снимаем', () => {
    expect(withoutMark('НЕ В КОПИЛКЕ: имя занято')).toBe('имя занято');
    expect(withoutMark('имя занято')).toBe('имя занято');
    expect(withoutMark(null)).toBe('');
  });

  it('строка — по названию ролика и коду; без путей, батча и строки фабрики', () => {
    const x = {
      code: 'slug_taken',
      slug: 'usb-c-myths',
      batch_id: 'example-film/2026-10-06T0210Z',
      alert_ru:
        'Ролик usb-c-myths (2026-10-06T0210Z) принят, но в копилку publish/example-film/_queue/ …',
    };
    const t = leftOutText(x, 'USB-C: мифы');
    expect(t).toBe(
      `Ролик «USB${NBH}C: мифы» принят, но в копилку не попал: такое имя уже занято роликом другого батча`,
    );
    expect(t).not.toMatch(/publish\/|_queue|2026-10-06|usb-c-myths/);
  });

  it('нет названия — имя ролика словами; неизвестный код — без причины', () => {
    expect(leftOutText({ code: 'render_missing', slug: 'usb-c-myths' })).toBe(
      'Ролик «Usb c myths» принят, но в копилку не попал: в батче нет файла ролика',
    );
    expect(leftOutText({ code: 'something_new' })).toBe('Ролик принят, но в копилку не попал');
  });

  it('у каждого кода «не в копилке» фабрики — своя причина', () => {
    expect(Object.keys(LEFT_OUT_REASON).sort()).toEqual(
      [
        'batch_missing',
        'channel_unknown',
        'other_version_placed',
        'queue_failed',
        'render_missing',
        'slug_taken',
      ].sort(),
    );
    for (const why of Object.values(LEFT_OUT_REASON)) expect(why).not.toMatch(/publish|--|_/);
  });

  it('тёзка — одной строкой, путь не виден', () => {
    expect(namesakeText(LEFT_OUT_NAMESAKE)).toBe('У того ролика другая тема');
    expect(namesakeText({})).toBeNull();
    expect(namesakeText(null)).toBeNull();
  });

  it('уведомление — только когда ушло', () => {
    expect(notifiedText({ status: 'sent' })).toBe('Фабрика отправила уведомление');
    expect(notifiedText({ status: 'off' })).toBeNull();
    expect(notifiedText(null)).toBeNull();
  });
});
