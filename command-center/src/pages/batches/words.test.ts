import { describe, expect, it } from 'vitest';

import type { BatchTopics } from '@/api/batchTopics';
import { readableSlug } from '@/api/videos';

import { isKnownStage } from './stages';
import {
  eventParts,
  exitText,
  logLabel,
  nameOf,
  needsLine,
  resultText,
  tookText,
  topicName,
  topicNames,
} from './words';

describe('коды карточки батча словами (CC-0118)', () => {
  it('isKnownStage: стадия словаря и её поздний повтор; пусто и незнакомое — нет', () => {
    expect(isKnownStage('video-editor')).toBe(true);
    expect(isKnownStage('video-editor-late')).toBe(true);
    expect(isKnownStage('mystery-late')).toBe(false);
    expect(isKnownStage('video-editor-judge')).toBe(true);
    expect(isKnownStage('frame-judge-judge')).toBe(true);
    expect(isKnownStage('mystery-judge')).toBe(false);
    expect(isKnownStage('constructor')).toBe(false);
    expect(isKnownStage(null)).toBe(false);
  });

  it('стадии, агенты и источники — по-русски; незнакомый код — «Шаг фабрики»', () => {
    expect(nameOf('video-editor')).toBe('Монтаж');
    expect(nameOf('content-researcher')).toBe('Исследование и сценарии');
    expect(nameOf('video-editor-late')).toBe('Монтаж (поздний повтор)');
    // Раунд добора после отказа судьи кадра (CC-0150) — другая пометка, чем у позднего повтора.
    expect(nameOf('video-editor-judge')).toBe('Монтаж (повтор после отказа судьи кадра)');
    expect(nameOf('frame-judge-judge')).toBe('Проверка кадров (повтор после отказа судьи кадра)');
    expect(nameOf('frame-judge')).toBe('Проверка кадров');
    expect(nameOf('studio-read')).toBe('Чтение Studio');
    // Нет в словаре, но видно по имени, какой это кадр.
    expect(nameOf('render-preview')).toBe('Монтаж');
    expect(nameOf('mystery-tool')).toBe('Шаг фабрики');
    expect(nameOf(null)).toBe('Шаг фабрики');
  });

  it('что исполнитель сделал без вас: известные коды, похожие и незнакомые', () => {
    expect(tookText('skipped_no_permission')).toBe('пропустил шаг — нет разрешения');
    expect(tookText('skipped_for_reasons')).toBe('пропустил шаг');
    expect(tookText('picked_default_value')).toBe('взял значение по умолчанию');
    expect(tookText('whatever_x')).toBe('решил сам, не дожидаясь вас');
    expect(tookText('ждал час и пошёл дальше')).toBe('ждал час и пошёл дальше');
  });

  it('строка needs_human из списка: «стадия: код» — словами, русская — как есть', () => {
    expect(needsLine('studio-read: skipped_no_permission')).toBe(
      'Чтение Studio: исполнитель пошёл дальше — пропустил шаг — нет разрешения',
    );
    expect(needsLine('Студия не читалась')).toBe('Студия не читалась');
    expect(needsLine('studio_read_blocked')).toBe('Исполнитель отложил шаг до вас');
  });

  it('код выхода — словами', () => {
    expect(exitText(0)).toEqual({ label: 'завершён', tone: 'ok' });
    expect(exitText(3)).toEqual({ label: 'завершён с ошибкой', tone: 'warn' });
    expect(exitText(null).label).toBe('не работает');
  });

  it('итог события: известные, незнакомый код, текст', () => {
    expect(resultText('ok').label).toBe('готово');
    expect(resultText('restart').label).toBe('перезапуск');
    expect(resultText('failed').tone).toBe('danger');
    expect(resultText('weird_state').label).toBe('другой итог');
  });

  it('итоги, которые фабрика пишет в RUN_EVENTS.jsonl, — словами; строка без статуса — «запись»', () => {
    const real: [string, string][] = [
      ['start', 'начал'],
      ['done', 'готово'],
      ['failed', 'ошибка'],
      ['stage-start', 'этап начат'],
      ['stage-done', 'этап готов'],
      ['batch-start', 'батч начат'],
      ['batch-resume', 'батч продолжен'],
      ['batch-done', 'батч закрыт'],
      ['red', 'красная проверка'],
    ];
    for (const [code, label] of real) expect(resultText(code).label, code).toBe(label);
    expect(resultText('red').tone).toBe('danger');
    const bare = eventParts(
      { offset: 9, text: null, event: { kind: 'step', stage: 'video-editor' } },
      new Map(),
    );
    expect(bare.result).toEqual({ label: 'запись', tone: 'idle' });
  });

  it('тема: название из данных тем, иначе читаемый слаг', () => {
    const topics = {
      topics: [
        {
          topic_id: 'vanguards-doomsday',
          title: 'Vanguards: Doomsday',
          scripts: [{ video: { slug: 'vanguards-cut-2', needs_you: false } }],
        },
      ],
      skipped: [{ topic_id: 'wicked-for-good', title: 'Charmed: For Good' }],
    } as unknown as BatchTopics;
    const names = topicNames(topics);
    expect(topicName('vanguards-doomsday', names)).toBe('Vanguards: Doomsday');
    expect(topicName('vanguards-cut-2', names)).toBe('Vanguards: Doomsday');
    expect(topicName('wicked-for-good', names)).toBe('Charmed: For Good');
    expect(topicName('quiet_keyboards', names)).toBe('Quiet keyboards');
    expect(readableSlug('')).toBe('');
  });

  it('событие: стадия · тема · итог словами, id шага и слаги — только в raw', () => {
    const names = new Map([['vanguards-doomsday', 'Vanguards: Doomsday']]);
    const p = eventParts(
      {
        offset: 1,
        text: null,
        event: {
          ts: '2026-10-10T05:40:00Z',
          kind: 'step',
          stage: 'video-editor',
          video: 'vanguards-doomsday',
          step: 'edit-29',
          status: 'ok',
        },
      },
      names,
    );
    expect(p.what).toBe('Монтаж · Vanguards: Doomsday');
    expect(p.result?.label).toBe('готово');
    expect(p.time).toBe('08:40:00');
    expect(p.raw).toBe('video-editor · vanguards-doomsday · edit-29 — ok');
    expect(`${p.what} ${p.result?.label}`).not.toMatch(/edit-29|video-editor/);

    const note = eventParts(
      { offset: 2, text: null, event: { kind: 'marker', status: 'restart', note: 'новый файл' } },
      names,
    );
    expect(note).toMatchObject({ what: 'Отметка', note: 'новый файл', marker: true });
    const en = eventParts(
      { offset: 3, text: null, event: { stage: 'x-y', note: 'rc=3 retry' } },
      names,
    );
    expect(en.note).toBeNull();
    expect(en.raw).toContain('rc=3 retry');

    expect(eventParts({ offset: 4, text: 'сырой текст', event: null }, names)).toMatchObject({
      what: 'Запись журнала',
      raw: 'сырой текст',
    });
  });
});

describe('журнал стадии словами (ревью экранов CC-0123)', () => {
  it('стадия, шаг и попытка — словами, без имени файла', () => {
    expect(logLabel('video-editor.s0.a0.log')).toBe('Монтаж');
    expect(logLabel('batch-start.s0.a1.log')).toBe('Старт батча · попытка 2');
    expect(logLabel('trend-hunter.s2.a0.log')).toBe('Поиск трендов · шаг 3');
    expect(logLabel('plan-check-after-supplement.content-researcher-reserve.s0.a0.log')).toBe(
      'Проверка плана после добора: Резерв сценариев',
    );
    expect(logLabel('weird_tool.log')).not.toMatch(/\.log|weird_tool/);
  });
});
