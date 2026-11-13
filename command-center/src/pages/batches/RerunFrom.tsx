// «Повторить с…» (CC-0123, фабрика CF-0739): упавший или застрявший батч — заново с выбранной
// стадии. Окно: стадии по порядку плана (`GET …/rerun-from`; недоступные погашены, причина
// словами фабрики), по выбору — план (`…/rerun-from/plan`: что сбросится и пойдёт заново, что
// останется), флажок «сразу продолжить», заметка; «да» (`…/rerun-from` с токеном плана) — итог:
// бэкап состояния, продолжен ли исполнитель (или почему нет — `resume_failed`). Коды, пути,
// строки фабрики — только под «подробнее».
import { useEffect, useId, useRef, useState } from 'react';

import {
  planRerunFrom,
  rerunFrom,
  useAfterAction,
  useRerunStages,
  type RerunFromResult,
  type RerunStage,
} from '@/api/batchActions';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { Pending } from '@/components/common/Skeletons';
import { StatusBadge } from '@/components/common/Status';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

import { confirmText } from './actions';
import { FlowNotes, Outcome, ReplanButton } from './ActionParts';
import { Refusal } from './parts';
import { rerunStatus, rerunWhy } from './rerunText';
import { stageName } from './stages';
import { useConfirmFlow } from './useConfirmFlow';

const NOTE_MAX = 500;

function StageList({
  stages,
  chosen,
  onChoose,
  disabled,
}: {
  stages: RerunStage[];
  chosen: string | null;
  onChoose: (stage: string) => void;
  disabled: boolean;
}) {
  const name = useId();
  const can = stages.filter((s) => s.can).length;
  return (
    <fieldset className="m-0 grid min-w-0 gap-1.5 border-0 p-0" data-testid="rerun-stages">
      <legend className="mb-1.5 text-[13px] font-semibold">
        С какой стадии повторить
        <span className="ml-2 font-normal text-muted-foreground" data-testid="rerun-can-count">
          {can ? `можно с ${can} из ${stages.length}` : 'ни с одной нельзя'}
        </span>
      </legend>
      <ol className="m-0 grid max-h-72 list-none gap-0 overflow-y-auto rounded-sm border p-0 text-[13px]">
        {stages.map((s) => {
          const id = `${name}-${s.stage}`;
          return (
            <li
              key={s.stage}
              data-testid="rerun-stage"
              data-stage={s.stage}
              data-can={s.can}
              className={cn(
                'border-t first:border-t-0',
                chosen === s.stage && 'bg-[color-mix(in_srgb,var(--primary)_9%,var(--card))]',
              )}
            >
              <label
                htmlFor={id}
                className={cn(
                  'grid grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-x-2 px-2.5 py-1.5',
                  s.can ? 'cursor-pointer' : 'cursor-not-allowed text-muted-foreground',
                )}
              >
                <input
                  id={id}
                  type="radio"
                  name={name}
                  value={s.stage}
                  checked={chosen === s.stage}
                  disabled={!s.can || disabled}
                  onChange={() => onChoose(s.stage)}
                  aria-describedby={s.can ? undefined : `${id}-why`}
                />
                <span className="min-w-0">{stageName(s.stage)}</span>
                <span className="text-xs text-muted-foreground">{rerunStatus(s.status)}</span>
                {!s.can ? (
                  <span
                    id={`${id}-why`}
                    data-testid="rerun-stage-why"
                    className="col-start-2 col-end-4 text-xs"
                  >
                    {rerunWhy(s.why)}
                  </span>
                ) : null}
              </label>
            </li>
          );
        })}
      </ol>
      <More className="mt-0">
        {stages.map((s) => (
          <span key={s.stage}>
            {s.stage}: {s.status}, {s.can ? 'можно' : `нельзя (${s.code ?? '—'}: ${s.why})`}
          </span>
        ))}
      </More>
    </fieldset>
  );
}

export function RerunFromAction({
  batch,
  onDone,
}: {
  batch: string;
  onDone: (r: RerunFromResult) => void;
}) {
  const [open, setOpen] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [resume, setResume] = useState(true);
  const [note, setNote] = useState('');
  // «Да» берёт флажок и заметку на момент нажатия: токен плана привязан только к стадии.
  const extra = useRef({ resume: true, note: '' });
  useEffect(() => {
    extra.current = { resume, note };
  }, [resume, note]);
  const after = useAfterAction();
  const stages = useRerunStages(batch, open);
  const boxId = useId();
  const noteId = useId();
  const flow = useConfirmFlow({
    plan: (s: string) => planRerunFrom(batch, s),
    act: (confirm: string) => rerunFrom(batch, confirm, extra.current),
    onDone: (r: RerunFromResult) => {
      onDone(r);
      setOpen(false);
    },
    onSettled: () => after(batch),
  });
  const plan = flow.plan;
  const choose = (s: string) => {
    setStage(s);
    flow.start(s);
  };
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        setStage(null);
        setResume(true);
        setNote('');
        flow.reset();
      }}
      tip="Повторить батч с выбранной стадии: она и всё после неё пойдут заново, готовое до неё останется"
      trigger={
        <Button size="sm" variant="outline" data-testid="rerun-open">
          Повторить с…
        </Button>
      }
      title="Повторить батч со стадии?"
      description="Выберите стадию: фабрика сбросит её и всё, что шло после неё, а готовое до неё оставит. Перед сбросом сохранится копия состояния батча."
      confirmLabel={confirmText('Повторить', flow)}
      pendingLabel={resume ? 'Повторяю и продолжаю…' : 'Повторяю…'}
      pending={flow.acting}
      danger
      confirmDisabled={!flow.canConfirm}
      confirmTestId="rerun-confirm"
      onConfirm={() => void flow.confirm()}
      extraActions={stage ? <ReplanButton flow={flow} onClick={() => flow.replan()} /> : null}
    >
      {stages.isPending ? (
        <Pending label="Спрашиваю фабрику, с каких стадий можно повторить…">
          <Skeleton className="h-40 w-full rounded-sm" />
        </Pending>
      ) : stages.isError ? (
        <Refusal error={stages.error} title="Фабрика не сказала, с каких стадий можно повторить" />
      ) : (
        <div className="grid gap-3 text-[13px]">
          {stages.data.executor_alive ? (
            <p className="m-0 text-warning" data-testid="rerun-alive">
              Исполнитель батча работает — повторить можно только остановленный батч.
            </p>
          ) : null}
          <StageList
            stages={stages.data.stages_for_rerun}
            chosen={stage}
            onChoose={choose}
            disabled={flow.acting}
          />
        </div>
      )}
      {plan ? (
        <div className="grid gap-3 text-[13px]" data-testid="rerun-plan">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={plan.ok ? 'ok' : 'danger'}>
              {plan.ok ? 'можно повторить' : 'повторить нельзя'}
            </StatusBadge>
            <span data-testid="rerun-message">{rerunWhy(plan.message)}</span>
          </div>
          {plan.reset.length ? (
            <div className="grid gap-1" data-testid="rerun-reset">
              <b className="font-semibold">Сбросится и пойдёт заново</b>
              <ul className="m-0 grid list-none gap-0.5 p-0">
                {plan.reset.map((s) => (
                  <li key={s} data-testid="rerun-reset-stage">
                    {stageName(s)}
                    {plan.reset_status[s] ? (
                      <span className="ml-2 text-xs text-muted-foreground">
                        сейчас: {rerunStatus(plan.reset_status[s])}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="grid gap-1" data-testid="rerun-kept">
            <b className="font-semibold">Останется как есть</b>
            {plan.kept.length ? (
              <ul className="m-0 grid list-none gap-0.5 p-0">
                {[...new Set(plan.kept.map((k) => k.stage))].map((s) => {
                  const n = plan.kept.filter((k) => k.stage === s).length;
                  return (
                    <li key={s} data-testid="rerun-kept-stage">
                      {stageName(s)}
                      <span className="ml-2 text-xs text-muted-foreground">
                        {n === 1 ? 'её файл' : `её файлы: ${n}`}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <span className="text-muted-foreground">
                Файлов ранних стадий фабрика не назвала.
              </span>
            )}
          </div>
          {plan.ok ? (
            <>
              <label htmlFor={boxId} className="flex items-center gap-2">
                <input
                  id={boxId}
                  type="checkbox"
                  data-testid="rerun-resume"
                  checked={resume}
                  disabled={flow.acting}
                  onChange={(e) => setResume(e.target.checked)}
                />
                Сразу продолжить — исполнитель пойдёт с этой стадии
              </label>
              <label htmlFor={noteId} className="grid gap-1">
                <span>
                  Заметка <span className="text-muted-foreground">(необязательно)</span>
                </span>
                <textarea
                  id={noteId}
                  data-testid="rerun-note"
                  value={note}
                  maxLength={NOTE_MAX}
                  rows={2}
                  disabled={flow.acting}
                  placeholder="например: сценарии заново после правки футажа"
                  onChange={(e) => setNote(e.target.value)}
                  className="min-h-14 rounded-sm border bg-background px-2.5 py-1.5 text-[13px]"
                />
              </label>
            </>
          ) : null}
          <More className="mt-0">
            <span>батч {plan.batch}</span>
            {plan.code ? <span>код: {plan.code}</span> : null}
            <span>фабрика: {plan.reason}</span>
            {plan.lines.map((l, i) => (
              <span key={i}>{l}</span>
            ))}
            {plan.kept.map((k) => (
              <span key={k.path}>
                останется {k.path} ({k.stage})
              </span>
            ))}
            {plan.logs.map((l) => (
              <span key={l}>журнал {l}</span>
            ))}
            {Object.entries(plan.keys).map(([k, v]) => (
              <span key={k}>
                {k}: {v.join(', ') || '—'}
              </span>
            ))}
            <span>отпечаток проверки {plan.fingerprint}</span>
          </More>
        </div>
      ) : null}
      {stage ? (
        <FlowNotes
          flow={flow}
          timeoutText="Фабрика не ответила за 30 секунд. Посмотрите статус батча — сброс мог пройти."
        />
      ) : null}
    </ConfirmDialog>
  );
}

/** Итог «Повторить с…» на карточке батча: сброшен, продолжен — или сброшен, но не продолжен. */
export function RerunOutcome({ r, onClose }: { r: RerunFromResult; onClose: () => void }) {
  const from = r.from_stage ? `«${stageName(r.from_stage)}»` : 'выбранной';
  const more = (
    <More className="mt-0">
      <span>батч {r.batch}</span>
      {r.code ? <span>код: {r.code}</span> : null}
      <span>фабрика: {r.reason}</span>
      {r.backup ? <span>копия состояния {r.backup}</span> : null}
      {r.reset.length ? <span>сброшены: {r.reset.join(', ')}</span> : null}
      {r.note ? <span>заметка: {r.note}</span> : null}
      {r.pid != null ? <span>исполнитель pid {r.pid}</span> : null}
      {r.log ? <span>журнал {r.log}</span> : null}
      {r.resume_code ? <span>продолжение: {r.resume_code}</span> : null}
      {r.resume_reason ? <span>{r.resume_reason}</span> : null}
    </More>
  );
  if (!r.ok || !r.done)
    return (
      <Outcome tone="danger" title="Батч не повторён" testId="rerun-failed" onClose={onClose}>
        <span data-testid="rerun-result-message">{rerunWhy(r.message)}</span>
        {more}
      </Outcome>
    );
  if (r.code === 'resume_failed' || (r.resume_asked && !r.resumed))
    return (
      <Outcome
        tone="warn"
        title={`Батч сброшен до стадии ${from}, но не продолжен`}
        testId="rerun-resume-failed"
        onClose={onClose}
      >
        <span data-testid="rerun-result-message">{rerunWhy(r.message)}</span>
        <span>Сброс сохранён — продолжите батч кнопкой «Продолжить», когда будет можно.</span>
        {more}
      </Outcome>
    );
  return (
    <Outcome
      tone="ok"
      title={r.resumed ? `Батч повторяется со стадии ${from}` : `Батч сброшен до стадии ${from}`}
      testId="rerun-done"
      onClose={onClose}
    >
      <span data-testid="rerun-result-message">{rerunWhy(r.message)}</span>
      {r.backup ? (
        <span className="text-muted-foreground">
          Копия прежнего состояния сохранена — путь под «подробнее».
        </span>
      ) : null}
      {more}
    </Outcome>
  );
}
