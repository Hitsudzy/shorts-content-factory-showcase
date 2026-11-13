// Общие куски окон действий экрана «Батчи» (CC-0052): ход проверки, отказы «да», переплан,
// отсчёт на кнопке и строка `kill -9` — только текстом для рук человека.
import type { ReactNode } from 'react';

import { ActionTimeout } from '@/api/batchActions';
import { problemCode } from '@/api/batchProblem';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { countdownText } from './actions';
import { NOT_LOGGED_IN, NOT_LOGGED_IN_TEXT } from './login';
import { Refusal } from './parts';
import { Ticked } from './Ticked';
import type { useConfirmFlow } from './useConfirmFlow';

type Flow = Pick<
  ReturnType<typeof useConfirmFlow>,
  'planning' | 'planError' | 'actError' | 'replannedBecause' | 'expired' | 'spent' | 'left' | 'plan'
>;

/**
 * Сколько ещё живёт план (CC-0131): отсчёт на кнопке «да» без пояснения читался загадкой. Одна
 * строка для всех окон записи — и общего `WriteAction`, и окон экрана «Батчи», пересборки, мемов.
 */
export function PlanLife({
  flow,
  testId = 'plan-life',
}: {
  flow: { plan: { ok: boolean } | null; left: number | null; expired: boolean; spent: boolean };
  testId?: string;
}) {
  if (!flow.plan?.ok || flow.left == null || flow.expired || flow.spent) return null;
  return (
    <p className="m-0 text-xs text-muted-foreground" data-testid={testId}>
      План действует ещё {countdownText(flow.left)} — тот же отсчёт на кнопке; потом фабрика
      проверит заново.
    </p>
  );
}

/** Ход и итог плана, причины переплана, отказ «да» — в окне подтверждения. */
export function FlowNotes({
  flow,
  timeoutText,
  busyTitle = 'Идёт другое действие',
}: {
  flow: Flow;
  timeoutText: string;
  /** Заголовок отказа `busy` — что именно занято (у пересборки — запуск или другая пересборка). */
  busyTitle?: string;
}) {
  const actCode = problemCode(flow.actError);
  return (
    <>
      <PlanLife flow={flow} />
      {flow.planning ? (
        <p role="status" className="m-0 animate-pulse text-muted-foreground" data-testid="planning">
          Фабрика проверяет…
        </p>
      ) : null}
      {flow.planError ? <Refusal error={flow.planError} title="Проверка не удалась" /> : null}
      {flow.replannedBecause ? (
        <div
          role="status"
          data-testid="replanned"
          className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] p-3 text-[13px]"
        >
          <b className="font-semibold">Проверил заново — посмотрите и подтвердите ещё раз</b>
          <span>
            {problemCode(flow.replannedBecause) === 'check_changed'
              ? 'С момента проверки что-то изменилось.'
              : 'Прежнее подтверждение больше не годится.'}
          </span>
          <Refusal error={flow.replannedBecause} className="mt-1 border-0 bg-transparent p-0" />
        </div>
      ) : null}
      {flow.actError ? (
        flow.actError instanceof ActionTimeout ? (
          <p role="alert" data-testid="act-timeout" className="m-0 text-[13px] text-danger">
            {timeoutText}
          </p>
        ) : (
          <div data-testid="act-error" data-code={actCode ?? undefined} className="grid gap-1">
            <Refusal
              error={flow.actError}
              title={
                actCode === 'busy'
                  ? busyTitle
                  : actCode === NOT_LOGGED_IN
                    ? 'Батч не запущен: нет входа в Claude'
                    : 'Фабрика отказала'
              }
              // CC-0177: без входа — словами центра; строка фабрики, код и details — под «подробнее».
              message={actCode === NOT_LOGGED_IN ? <Ticked text={NOT_LOGGED_IN_TEXT} /> : null}
            />
            {actCode === NOT_LOGGED_IN ? (
              <p className="m-0 text-xs text-muted-foreground" data-testid="login-note">
                Подтверждение потрачено. Войдите в Claude и нажмите «Проверить снова» — фабрика
                проверит заново.
              </p>
            ) : null}
            {actCode === 'busy' ? (
              <p className="m-0 text-xs text-muted-foreground" data-testid="busy-note">
                Подтверждение ещё годно — подождите и нажмите ещё раз.
              </p>
            ) : null}
          </div>
        )
      ) : null}
      {flow.expired && !flow.spent ? (
        <p role="status" data-testid="token-expired" className="m-0 text-[13px] text-warning">
          Подтверждение устарело — проверьте заново.
        </p>
      ) : null}
    </>
  );
}

/** «Проверить заново»: когда подтверждения нет, оно истекло или потрачено. */
export function ReplanButton({
  flow,
  onClick,
}: {
  flow: Flow & { plan: { ok: boolean } | null };
  onClick: () => void;
}) {
  const show =
    !flow.planning &&
    (flow.expired || flow.spent || !!flow.planError || (flow.plan && !flow.plan.ok));
  if (!show) return null;
  return (
    <Button variant="ghost" onClick={onClick} data-testid="replan">
      Проверить заново
    </Button>
  );
}

/**
 * Команда `kill -9` для Терминала — текстом, выделяется целиком. Центр её не выполняет и
 * кнопки «выполнить» не даёт: решение и руки — человека.
 */
export function KillCommand({ line, children }: { line: string; children?: ReactNode }) {
  return (
    <div className="grid gap-1" data-testid="kill-command">
      <span className="text-xs text-muted-foreground">
        {children ?? 'Фабрика сама процесс не добивает. Если уверены — выполните в Терминале сами:'}
      </span>
      <code
        data-testid="kill-line"
        className="w-max max-w-full rounded-sm border bg-background px-2 py-1 font-mono text-[13px] select-all [overflow-wrap:anywhere]"
      >
        {line}
      </code>
    </div>
  );
}

/** Итог действия на карточке: успех — спокойно, «не до конца» — тревожно. */
export function Outcome({
  tone,
  title,
  children,
  testId,
  onClose,
}: {
  tone: 'ok' | 'warn' | 'danger';
  title: string;
  children: ReactNode;
  testId: string;
  onClose: () => void;
}) {
  const color =
    tone === 'ok' ? 'var(--success)' : tone === 'warn' ? 'var(--warning)' : 'var(--danger)';
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      data-testid={testId}
      style={{
        borderColor: `color-mix(in srgb, ${color} 40%, var(--border))`,
        background: `color-mix(in srgb, ${color} 7%, var(--card))`,
      }}
      className={cn('mt-3 grid gap-1.5 rounded-sm border p-3 text-[13px]')}
    >
      <div className="flex items-start justify-between gap-2">
        <b className="font-semibold">{title}</b>
        <Button size="sm" variant="ghost" onClick={onClose} data-testid="outcome-close">
          Скрыть
        </Button>
      </div>
      {children}
    </div>
  );
}
