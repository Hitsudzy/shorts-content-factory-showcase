// Что сказала фабрика: отказ сохранения или итог проверки — по-человечески; технические
// строки — только под «подробнее».
import type { CheckLine } from '@/api/channels';
import { More } from '@/components/common/More';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { checkDetail, humanCheck } from './fields';
import type { Problem } from './problem';

const TONE = {
  danger:
    'border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))]',
  warn: 'border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_7%,var(--card))]',
  ok: 'border-[color-mix(in_srgb,var(--success)_40%,var(--border))] bg-[color-mix(in_srgb,var(--success)_7%,var(--card))]',
};
const TITLE = { danger: 'text-danger', warn: 'text-warning', ok: 'text-success' };

export function Problems({
  problem,
  onJump,
  action,
  testId,
}: {
  problem: Problem;
  onJump?: (line: CheckLine) => void;
  action?: React.ReactNode;
  testId?: string;
}) {
  // `details` отказа повторяют английские строки проверок — каждую показываем раз, с кодом причины.
  const own = new Set(problem.errors.map((e) => e.text));
  const technical = [
    ...problem.details.filter((d) => !own.has(d)),
    ...problem.errors.map(checkDetail),
  ];
  return (
    <div
      role={problem.tone === 'ok' ? 'status' : 'alert'}
      data-testid={testId}
      className={cn('grid gap-2 rounded-sm border p-3', TONE[problem.tone])}
    >
      <div className={cn('font-semibold', TITLE[problem.tone])}>{problem.title}</div>
      {problem.message ? <p className="m-0">{problem.message}</p> : null}
      {problem.errors.length ? (
        <ul className="m-0 grid list-none gap-1.5 p-0">
          {problem.errors.map((line, i) => {
            const h = humanCheck(line);
            if (h.ru) {
              // Русская строка фабрики сама называет поле и значение; ссылка — только перейти.
              return (
                <li key={i} className="grid gap-0.5" data-check-code={line.code ?? undefined}>
                  <span>{h.why}</span>
                  {h.where && onJump ? (
                    <Button
                      variant="link"
                      size="sm"
                      className="h-auto w-max max-w-full justify-start px-0 text-left whitespace-normal"
                      aria-label={`К полю в форме «${h.where}»`}
                      onClick={() => onJump(line)}
                    >
                      К полю в форме
                    </Button>
                  ) : null}
                </li>
              );
            }
            return (
              <li key={i} className="grid gap-0.5">
                {h.where ? (
                  onJump ? (
                    <Button
                      variant="link"
                      size="sm"
                      className="h-auto w-max max-w-full justify-start px-0 text-left whitespace-normal"
                      onClick={() => onJump(line)}
                    >
                      Поле «{h.where}»
                    </Button>
                  ) : (
                    <span className="font-semibold">Поле «{h.where}»</span>
                  )
                ) : (
                  <span className="font-semibold">Канал целиком</span>
                )}
                <span className="text-muted-foreground">{h.why}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
      {action ? <div className="flex flex-wrap gap-2">{action}</div> : null}
      {technical.length ? (
        <More className="mt-0">
          {technical.map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </More>
      ) : null}
    </div>
  );
}
