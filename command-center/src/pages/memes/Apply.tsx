// «Применить разбор» (CC-0025): два шага, как у остальных записей с подтверждением — план
// фабрики (что войдёт в библиотеку, что уйдёт, какие файлы удалятся, что она откажется убрать)
// и «да» с отсчётом. Применяется сохранённый черновик: с несохранёнными отметками кнопка
// погашена. После «да» — стол и обзор перечитываются.
import { useState, type ReactNode } from 'react';

import { applyMarks, planApply, type MemeApplyPlan, type MemeApplyResult } from '@/api/memes';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { WriteButton } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { confirmText } from '@/pages/batches/actions';
import { FlowNotes, Outcome, ReplanButton } from '@/pages/batches/ActionParts';
import { useConfirmFlow } from '@/pages/batches/useConfirmFlow';

import { filesWord, memesWord, quoted } from './format';

function Line({
  testId,
  title,
  ids,
  tone,
  children,
}: {
  testId: string;
  title: string;
  ids: string[];
  tone?: 'warn' | 'danger';
  children?: ReactNode;
}) {
  if (!ids.length && !children) return null;
  return (
    <li data-testid={testId} className="grid gap-0.5">
      <b
        className={
          tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warning' : 'font-semibold'
        }
      >
        {title}
      </b>
      {ids.length ? (
        <span className="text-muted-foreground [overflow-wrap:anywhere]">
          {ids.slice(0, 12).map(quoted).join(', ')}
          {ids.length > 12 ? ` и ещё ${ids.length - 12}` : ''}
        </span>
      ) : null}
      {children}
    </li>
  );
}

export function PlanView({ plan }: { plan: MemeApplyPlan }) {
  const nothing =
    !plan.accept.length &&
    !plan.remove.length &&
    !plan.cutout_changed.length &&
    !plan.refused.length &&
    !plan.held.length;
  return (
    <div className="grid gap-2 text-[13px]" data-testid="apply-plan">
      {!plan.ok ? (
        <p role="alert" className="m-0 text-danger" data-testid="plan-why">
          {plan.why ?? 'Фабрика не даст применить разбор.'}
        </p>
      ) : null}
      {nothing ? (
        <p className="m-0 text-muted-foreground" data-testid="plan-nothing">
          Применять нечего: в сохранённых отметках нет ни «оставить» у новых мемов, ни «убрать», ни
          перемен «можно вырезать».
        </p>
      ) : null}
      <ul className="m-0 grid list-none gap-2 p-0">
        <Line
          testId="plan-accept"
          title={`Войдут в библиотеку: ${memesWord(plan.accept.length)}`}
          ids={plan.accept}
        />
        <Line
          testId="plan-remove"
          title={`Уберу из банка: ${memesWord(plan.remove.length)}`}
          ids={plan.remove}
          tone="danger"
        />
        <Line
          testId="plan-cut"
          title={`Поменяю «можно вырезать»: ${memesWord(plan.cutout_changed.length)}`}
          ids={plan.cutout_changed}
        />
        {plan.files_to_delete.length ? (
          <Line
            testId="plan-files"
            title={`Удалю из банка ${filesWord(plan.files_to_delete.length)} — картинки и вырезки`}
            ids={[]}
            tone="danger"
          >
            <More className="mt-0">
              {plan.files_to_delete.map((f) => (
                <span key={f}>{f}</span>
              ))}
            </More>
          </Line>
        ) : null}
        <Line
          testId="plan-refused"
          title={`Не уберу: ${memesWord(plan.refused.length)} — это образцы по умолчанию для своих тем; сначала фабрика поменяет образец`}
          ids={plan.refused.map((r) => r.id)}
          tone="warn"
        >
          {plan.refused.length ? (
            <More className="mt-0">
              {plan.refused.map((r) => (
                <span key={r.id}>
                  {r.id}: intent {r.intent}
                </span>
              ))}
            </More>
          ) : null}
        </Line>
        <Line
          testId="plan-held"
          title={`Останутся, хоть и отмечены «убрать»: ${memesWord(plan.held.length)} — они уже в библиотеке`}
          ids={plan.held}
          tone="warn"
        />
        {plan.errors.length ? (
          <Line
            testId="plan-errors"
            title="Индекс банка вышел бы неверным — фабрика не применит"
            ids={[]}
            tone="danger"
          >
            <More className="mt-0">
              {plan.errors.map((e) => (
                <span key={e}>{e}</span>
              ))}
            </More>
          </Line>
        ) : null}
      </ul>
      <More>
        <span>банк: {plan.bank}</span>
        <span>drop: {String(plan.drop)}</span>
        <span>отпечаток плана: {plan.fingerprint}</span>
      </More>
    </div>
  );
}

export function ApplyDone({ r, onClose }: { r: MemeApplyResult; onClose: () => void }) {
  return (
    <Outcome tone="ok" title="Разбор применён" testId="apply-done" onClose={onClose}>
      <span>
        Вошли в библиотеку: {memesWord(r.accept.length)}; убраны: {memesWord(r.remove.length)};
        «можно вырезать» поменялось у {memesWord(r.cutout_changed.length)}.
        {r.files_to_delete.length ? ` Удалено файлов: ${r.files_to_delete.length}.` : ''}
      </span>
    </Outcome>
  );
}

/** На телефоне — короче: панель кнопок в одну строку. */
const label = (
  <>
    Применить<span className="max-sm:hidden">&nbsp;разбор</span>…
  </>
);

export function ApplyAction({
  channel,
  bankLabel,
  why,
  onDone,
  onSettled,
}: {
  channel: string;
  bankLabel: string;
  /** Почему нельзя (несохранённые отметки, черновик поменяли мимо) — кнопка погашена. */
  why: string | null;
  /** Фабрика применила разбор (итог показывает стол — не в панели кнопок). */
  onDone: (r: MemeApplyResult | null) => void;
  onSettled: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [drop, setDrop] = useState(false);
  const setDone = onDone;
  const flow = useConfirmFlow({
    plan: (d: boolean) => planApply(channel, d),
    act: (confirm: string) => applyMarks(channel, confirm),
    onDone: (r: MemeApplyResult) => {
      setDone(r);
      setOpen(false);
    },
    onSettled,
  });
  const plan = flow.plan;
  const canDrop = !!plan && (plan.held.length > 0 || drop);
  return (
    <>
      {why ? (
        <WriteButton size="sm" why={why} data-testid="apply-open">
          {label}
        </WriteButton>
      ) : (
        <ConfirmDialog
          open={open}
          onOpenChange={(v) => {
            setOpen(v);
            if (v) {
              setDone(null);
              setDrop(false);
              flow.start(false);
            } else flow.reset();
          }}
          tip="Фабрика проверит сохранённые отметки и покажет, что изменится; запись — после вашего «да»"
          trigger={
            <Button size="sm" data-testid="apply-open">
              {label}
            </Button>
          }
          title={`Применить разбор банка ${bankLabel}?`}
          description="Фабрика проверила сохранённые отметки. Вот что она сделает с банком мемов:"
          confirmLabel={confirmText('Применить', flow)}
          pendingLabel="Применяю…"
          pending={flow.acting}
          confirmDisabled={!flow.canConfirm}
          confirmTestId="apply-confirm"
          onConfirm={() => void flow.confirm()}
          extraActions={<ReplanButton flow={flow} onClick={() => flow.replan()} />}
        >
          {plan ? <PlanView plan={plan} /> : null}
          {canDrop ? (
            <label className="flex items-start gap-2 text-[13px]" data-testid="apply-drop">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-[var(--primary)]"
                checked={drop}
                disabled={flow.planning || flow.acting}
                onChange={(e) => {
                  setDrop(e.target.checked);
                  flow.replan(e.target.checked);
                }}
              />
              <span>
                Убрать и мемы, которые уже в библиотеке, но отмечены «убрать». Фабрика проверит
                заново.
              </span>
            </label>
          ) : null}
          <FlowNotes
            flow={flow}
            busyTitle="Идёт другая запись мемов"
            timeoutText="Фабрика не ответила за 30 секунд. Откройте банк заново — разбор мог примениться."
          />
        </ConfirmDialog>
      )}
    </>
  );
}
