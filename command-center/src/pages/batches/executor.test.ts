import { controlsOf } from './actions';
import { answerCheck, eventAgeText, executorGone } from './executor';

const AS_OF = '2026-10-12T20:53:00Z';

describe('исполнитель не отвечает (CC-0094)', () => {
  it('решает строка списка (CC-0110): не жив, замок свободен, статус running', () => {
    const row = { status: 'running', executor_alive: false, lock_held: false };
    expect(executorGone(row)).toBe(true);
    expect(executorGone({ ...row, executor_alive: true })).toBe(false);
    // null — проверка фабрики упала: не «умер».
    expect(executorGone({ ...row, executor_alive: null })).toBe(false);
    expect(executorGone({ status: 'running' })).toBe(false);
    expect(executorGone({ ...row, lock_held: true })).toBe(false);
    expect(executorGone({ ...row, status: 'stopped' })).toBe(false);
    expect(executorGone(null)).toBe(false);
    expect(
      executorGone(answerCheck({ executor_alive: true, lock_held: true, status: 'running' })),
    ).toBe(false);
  });

  it('кнопки: исполнитель не отвечает — «Продолжить», без «Остановить»', () => {
    expect(controlsOf({ status: 'running', fresh: true })).toEqual({ stop: true, resume: false });
    expect(controlsOf({ status: 'running', fresh: true }, true)).toEqual({
      stop: false,
      resume: true,
    });
  });

  it('возраст последнего события по часам фабрики', () => {
    expect(eventAgeText('2026-10-12T20:46:00Z', AS_OF)).toBe('последнее событие 7\u00a0мин назад');
    expect(eventAgeText('2026-10-12T20:52:50Z', AS_OF)).toBe(
      'последнее событие меньше минуты назад',
    );
    expect(eventAgeText(null, AS_OF)).toBeNull();
    expect(eventAgeText('2026-10-12T20:46:00Z', null)).toBeNull();
  });
});
