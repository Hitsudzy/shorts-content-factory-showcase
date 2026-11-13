// У каждого шага тура цель и ссылка перехода — настоящие метки `data-tour` в коде центра:
// переименовали метку в компоненте — тест скажет, какой шаг потерял подсветку.
import { STEPS } from './steps';

// Исходники экранов текстом (без тестов и без самого тура).
const SOURCES = import.meta.glob<string>(['../**/*.tsx', '!../**/*.test.tsx', '!./**'], {
  query: '?raw',
  import: 'default',
  eager: true,
});

// `data-tour="x"` в разметке и `tour="x"` — проп, который компонент кладёт в `data-tour`.
const MARKS = new Set(
  Object.values(SOURCES).flatMap((text) =>
    [...text.matchAll(/\b(?:data-)?tour="([a-z-]+)"/g)].map((m) => m[1]!),
  ),
);
// Кнопка «Обучение» живёт в самом туре.
MARKS.add('tour-button');

describe('CC-0072: метки тура в экранах', () => {
  it('исходники экранов прочитаны', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(30);
    expect(Object.keys(SOURCES).some((f) => f.includes('/tour/'))).toBe(false);
  });

  it.each(STEPS.filter((s) => s.target || s.open).map((s) => [s.id, s] as const))(
    'шаг «%s»: цель и ссылка есть в коде',
    (_, step) => {
      if (step.target) expect(MARKS, `data-tour="${step.target}"`).toContain(step.target);
      if (step.open) expect(MARKS, `data-tour="${step.open}"`).toContain(step.open);
    },
  );
});
