// Остановить и продолжить батч (CC-0047; работает и на пересборке `rebuilds/<ts>`): у каждого —
// проверка фабрики с токеном, потом «да». Остановка: флажок «остановить и шаг» (токен к нему
// привязан — переключили, проверка заново), ответ ждём до ~70 с и судим по `ok`, а не по коду:
// 200 `ok:false` — исполнитель пережил SIGTERM, и строка `kill -9` из `reason` показывается
// текстом для рук человека, кнопки «выполнить» нет. `step_left_running`/`reason_step` — шаг
// живёт дальше. Продолжение — до ~15 с. `busy` — идёт другое действие, токен ещё годен.
// Ответы продолжения — `message` фабрики по-русски (код — под «подробнее», договор 0.52+).
// Стоящий батч — ещё «Повторить с…» (CC-0123, ./RerunFrom.tsx).
import { useId, useState, type ReactNode } from 'react';

import {
  planResume,
  planStop,
  resume,
  stop,
  useAfterAction,
  type RerunFromResult,
  type ResumeResult,
  type StopResult,
} from '@/api/batchActions';
import type { GoingBatch } from '@/api/batches';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';

import { confirmText, controlsOf, killLine, resumeText, stopReasonText } from './actions';
import { FlowNotes, KillCommand, Outcome, ReplanButton } from './ActionParts';
import { RerunFromAction, RerunOutcome } from './RerunFrom';
import { stageTitle as titleOf } from './going';
import { useConfirmFlow } from './useConfirmFlow';
import { useExecutorAnswer } from './useExecutor';

const stageTitle = (stage: string | null | undefined) => (stage ? titleOf(stage) : null);

type Done =
  | { kind: 'stop'; r: StopResult }
  | { kind: 'resume'; r: ResumeResult }
  | { kind: 'rerun'; r: RerunFromResult }
  | null;

function StopAction({ batch, onDone }: { batch: string; onDone: (r: StopResult) => void }) {
  const [open, setOpen] = useState(false);
  const [alsoStep, setAlsoStep] = useState(false);
  const after = useAfterAction();
  const boxId = useId();
  const flow = useConfirmFlow({
    plan: (step: boolean) => planStop(batch, step),
    act: (confirm: string, step: boolean) => stop(batch, confirm, step),
    onDone: (r: StopResult) => {
      onDone(r);
      setOpen(false);
    },
    onSettled: () => after(batch),
  });
  const plan = flow.plan;
  const step = plan?.step?.alive ? plan.step : null;

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (v) {
          setAlsoStep(false);
          flow.start(false);
        } else flow.reset();
      }}
      tip="Остановить батч: исполнитель завершится, готовое сохранится; продолжить — отсюда же"
      trigger={
        <Button variant="destructive" size="sm" data-testid="stop-open">
          Остановить…
        </Button>
      }
      title="Остановить батч?"
      description="Фабрика попросит исполнитель батча завершиться и подождёт до 30 секунд. Готовое сохранится; продолжить можно будет кнопкой «Продолжить»."
      confirmLabel={confirmText('Остановить', flow)}
      pendingLabel="Останавливаю… (до 70 с)"
      pending={flow.acting}
      danger
      confirmDisabled={!flow.canConfirm}
      confirmTestId="stop-confirm"
      onConfirm={() => void flow.confirm()}
      extraActions={<ReplanButton flow={flow} onClick={() => flow.replan()} />}
    >
      {plan ? (
        <div className="grid gap-3 text-[13px]" data-testid="stop-plan">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={plan.ok ? 'ok' : 'danger'}>
              {plan.ok ? 'можно остановить' : 'остановить нельзя'}
            </StatusBadge>
            <span data-testid="stop-reason">{plan.reason}</span>
          </div>
          {step ? (
            <p className="m-0" data-testid="stop-step">
              Сейчас работает шаг «{stageTitle(step.stage) ?? step.stage}». Без флажка он доработает
              сам, а продолжение его дождётся.
            </p>
          ) : null}
          <label htmlFor={boxId} className="flex items-center gap-2">
            <input
              id={boxId}
              type="checkbox"
              data-testid="stop-also-step"
              checked={alsoStep}
              disabled={flow.planning || flow.acting || !plan.ok}
              onChange={(e) => {
                setAlsoStep(e.target.checked);
                flow.replan(e.target.checked);
              }}
            />
            <Tip content="Шагу тоже уйдёт просьба завершиться (ещё до 30 с); при продолжении он начнётся заново">
              <span
                tabIndex={0}
                data-testid="stop-also-step-tip"
                className="underline decoration-dotted underline-offset-4"
              >
                Остановить и шаг
              </span>
            </Tip>
          </label>
          <More className="mt-0">
            <span>батч {plan.batch}</span>
            {plan.executor_pid != null ? (
              <span>
                исполнитель pid {plan.executor_pid}
                {plan.executor_pgid != null ? `, группа ${plan.executor_pgid}` : ''}
              </span>
            ) : null}
            {plan.step ? (
              <span>
                шаг {plan.step.run} pid {plan.step.pid ?? '—'}
                {plan.step.log ? ` · журнал ${plan.step.log}` : ''}
              </span>
            ) : null}
            <span>отпечаток проверки {plan.fingerprint}</span>
          </More>
        </div>
      ) : null}
      <FlowNotes
        flow={flow}
        timeoutText="Фабрика не ответила за 70 секунд. Посмотрите статус батча — он мог остановиться."
      />
    </ConfirmDialog>
  );
}

export function ResumeAction({
  batch,
  label = 'Продолжить…',
  onDone,
}: {
  batch: string;
  label?: string;
  onDone: (r: ResumeResult) => void;
}) {
  const [open, setOpen] = useState(false);
  const after = useAfterAction();
  const answer = useExecutorAnswer();
  const flow = useConfirmFlow({
    plan: () => planResume(batch),
    act: (confirm: string) => resume(batch, confirm),
    onDone: (r: ResumeResult) => {
      answer(batch, r);
      onDone(r);
      setOpen(false);
    },
    onSettled: () => after(batch),
  });
  const plan = flow.plan;
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (v) flow.start(null);
        else flow.reset();
      }}
      tip="Продолжить батч с места остановки"
      trigger={
        <Button size="sm" data-testid="resume-open">
          {label}
        </Button>
      }
      title="Продолжить батч?"
      description="Фабрика запустит исполнитель заново с места остановки и подождёт до 15 секунд, пока он возьмёт батч."
      confirmLabel={confirmText('Продолжить', flow)}
      pendingLabel="Продолжаю…"
      pending={flow.acting}
      confirmDisabled={!flow.canConfirm}
      confirmTestId="resume-confirm"
      onConfirm={() => void flow.confirm()}
      extraActions={<ReplanButton flow={flow} onClick={() => flow.replan()} />}
    >
      {plan ? (
        <div className="grid gap-3 text-[13px]" data-testid="resume-plan">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={plan.ok ? 'ok' : 'danger'}>
              {plan.ok ? 'можно продолжить' : 'продолжить нельзя'}
            </StatusBadge>
            <span data-testid="resume-reason">{resumeText(plan)}</span>
          </div>
          <More className="mt-0">
            <span>батч {plan.batch}</span>
            {plan.code ? <span>код: {plan.code}</span> : null}
            {resumeText(plan) !== plan.reason ? <span>фабрика: {plan.reason}</span> : null}
            {plan.argv ? <span>запустит: {plan.argv.join(' ')}</span> : null}
            <span>отпечаток проверки {plan.fingerprint}</span>
          </More>
        </div>
      ) : null}
      <FlowNotes
        flow={flow}
        timeoutText="Фабрика не ответила за 15 секунд. Посмотрите статус батча — исполнитель мог стартовать."
      />
    </ConfirmDialog>
  );
}

function StopOutcome({ r, onClose }: { r: StopResult; onClose: () => void }) {
  const kill = killLine(r.reason);
  const stepKill = killLine(r.reason_step);
  if (!r.ok) {
    return (
      <Outcome
        tone="danger"
        title="Исполнитель не остановился"
        testId="stop-failed"
        onClose={onClose}
      >
        <span data-testid="stop-result-reason">{stopReasonText(r.reason) ?? r.reason}</span>
        {kill ? <KillCommand line={kill} /> : null}
        <More className="mt-0">
          <span>батч {r.batch}</span>
          {stopReasonText(r.reason) && r.reason ? <span>фабрика: {r.reason}</span> : null}
          {r.executor_signalled ? <span>сигнал: {r.executor_signalled}</span> : null}
        </More>
      </Outcome>
    );
  }
  return (
    <Outcome
      tone={r.step_left_running ? 'warn' : 'ok'}
      title="Батч остановлен"
      testId="stop-done"
      onClose={onClose}
    >
      <span data-testid="stop-result-reason">{r.reason}</span>
      {r.step_left_running ? (
        <span data-testid="step-left-running">
          Шаг ещё работает — продолжение его дождётся.
          {r.reason_step ? <> {stopReasonText(r.reason_step) ?? r.reason_step}</> : null}
        </span>
      ) : null}
      {stepKill ? (
        <KillCommand line={stepKill}>
          Шаг не завершился сам. Если уверены — добейте его в Терминале сами:
        </KillCommand>
      ) : null}
      <More className="mt-0">
        {stopReasonText(r.reason_step) && r.reason_step ? (
          <span>фабрика о шаге: {r.reason_step}</span>
        ) : null}
        <span>батч {r.batch}</span>
        {r.executor_signalled ? <span>сигнал: {r.executor_signalled}</span> : null}
        {r.resume_hint ? <span>продолжить из Терминала: {r.resume_hint}</span> : null}
      </More>
    </Outcome>
  );
}

export function ResumeOutcome({ r, onClose }: { r: ResumeResult; onClose: () => void }) {
  if (!r.ok) {
    return (
      <Outcome
        tone="danger"
        title="Исполнитель не продолжил"
        testId="resume-failed"
        onClose={onClose}
      >
        <span data-testid="resume-result-reason">{resumeText(r)}</span>
        <More className="mt-0">
          <span>батч {r.batch}</span>
          {r.code ? <span>код: {r.code}</span> : null}
          {resumeText(r) !== r.reason ? <span>фабрика: {r.reason}</span> : null}
          {r.exit != null ? <span>код выхода {r.exit}</span> : null}
        </More>
      </Outcome>
    );
  }
  return (
    <Outcome tone="ok" title="Батч продолжен" testId="resume-done" onClose={onClose}>
      <span>Исполнитель снова работает с места остановки.</span>
      <More className="mt-0">
        <span>{r.reason}</span>
        {r.pid != null ? <span>pid {r.pid}</span> : null}
        {r.log ? <span>журнал {r.log}</span> : null}
      </More>
    </Outcome>
  );
}

/**
 * Кнопки «Остановить…»/«Продолжить…» батча рядом с его строкой времени (`meta`) и итог
 * последнего действия под ними. `gone` — исполнитель не отвечает (CC-0094): «Остановить» нет,
 * «Продолжить» — с этапа, где батч встал.
 */
export function BatchControl({
  b,
  meta,
  gone = false,
}: {
  b: GoingBatch;
  meta: ReactNode;
  gone?: boolean;
}) {
  const [done, setDone] = useState<Done>(null);
  const can = controlsOf(b, gone);
  const from = gone ? stageTitle(b.next ?? b.stage) : null;
  return (
    <div className="mb-3" data-testid="batch-control" data-tour="batch-stop">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {meta}
        {can.stop || can.resume ? (
          <div className="flex flex-wrap gap-2">
            {can.resume ? (
              <RerunFromAction batch={b.batch} onDone={(r) => setDone({ kind: 'rerun', r })} />
            ) : null}
            {can.resume ? (
              <ResumeAction
                batch={b.batch}
                label={from ? `Продолжить с этапа «${from}»…` : undefined}
                onDone={(r) => setDone({ kind: 'resume', r })}
              />
            ) : null}
            {can.stop ? (
              <StopAction batch={b.batch} onDone={(r) => setDone({ kind: 'stop', r })} />
            ) : null}
          </div>
        ) : null}
      </div>
      {done?.kind === 'stop' ? <StopOutcome r={done.r} onClose={() => setDone(null)} /> : null}
      {done?.kind === 'resume' ? <ResumeOutcome r={done.r} onClose={() => setDone(null)} /> : null}
      {done?.kind === 'rerun' ? <RerunOutcome r={done.r} onClose={() => setDone(null)} /> : null}
    </div>
  );
}
