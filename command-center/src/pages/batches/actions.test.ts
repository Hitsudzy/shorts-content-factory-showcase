import { countdownText, guardLabel, killLine, secondsLeft, stopReasonText } from './actions';

describe('слова действий', () => {
  it('отсчёт токена: округление вверх, не меньше нуля, без срока — null', () => {
    expect(secondsLeft(10_000, 0)).toBe(10);
    expect(secondsLeft(10_000, 9_001)).toBe(1);
    expect(secondsLeft(10_000, 10_000)).toBe(0);
    expect(secondsLeft(10_000, 99_000)).toBe(0);
    expect(secondsLeft(null, 0)).toBeNull();
    expect(countdownText(114)).toBe('1:54');
    expect(countdownText(7)).toBe('0:07');
    expect(countdownText(120)).toBe('2:00');
  });

  it('kill -9 — из строки фабрики, только сама команда', () => {
    expect(
      killLine(
        'исполнитель pid 4188 не умер за 30 с после SIGTERM (группа 4188); SIGKILL не послан - решить руками: kill -9 -4188 (docs/running-a-batch.md)',
      ),
    ).toBe('kill -9 -4188');
    expect(killLine('батч 2026-10-10T0530Z остановлен')).toBeNull();
    expect(killLine(null)).toBeNull();
  });

  it('проверки запуска по-русски, незнакомая — как есть', () => {
    expect(guardLabel('open')).toBe('Открытые батчи');
    expect(guardLabel('quota')).toBe('quota');
  });
});

describe('отказ остановки своими словами (CC-0131)', () => {
  it('исполнитель и шаг — без pid и сигналов; чужая строка — null', () => {
    expect(
      stopReasonText(
        'исполнитель pid 4188 не умер за 30 с после SIGTERM (группа 4188); SIGKILL не послан - решить руками: kill -9 -4188',
      ),
    ).toMatch(/^Исполнитель не остановился за 30 с после просьбы завершиться\./);
    expect(
      stopReasonText(
        'шаг 05 pid 7 не умер за 30 с после SIGTERM; SIGKILL не послан - kill -9 -7 руками',
      ),
    ).toMatch(/^Шаг не остановился за 30 с/);
    expect(stopReasonText('батч остановлен')).toBeNull();
  });
});
