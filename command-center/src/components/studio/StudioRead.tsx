// «Прочитать Studio» в один клик (CC-0120, фабрика CF-0735). Хуки «пора ли» только подсвечивают
// кнопку — рядом строка фабрики `why` и «последнее чтение N ч назад»; сами они ничего не
// запускают. Клик — план (`POST /api/studio/read/plan`: какие каналы, «только чтение в вашем
// Chrome»), «да» с токеном — сессия чтения стартует отдельно, итог — опросом одной строкой:
// прочитано / расширение не подключено / нужен вход / ошибка (`word`, `line`; лог, run_id и
// записанные каналы — под «Подробнее»). Запуск на API выключен (`launch.available: false`):
// кнопка погашена с `launch.why`, план всё равно можно посмотреть.
import { useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import {
  planStudioRead,
  startStudioRead,
  studioKeys,
  useStudioReadRun,
  type StudioHook,
  type StudioReadDue,
  type StudioReadResult,
  type StudioReadStarted,
} from '@/api/studioRead';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { confirmText } from '@/pages/batches/actions';
import { FlowNotes, ReplanButton } from '@/pages/batches/ActionParts';
import { useChannelNames } from '@/pages/batches/names';
import { useConfirmFlow } from '@/pages/batches/useConfirmFlow';

import { hookWordOf, useStudioDueState, type Run, type StudioDueState } from './studioDue';
import { ageText, outcomeTone } from './studioWords';

/** Что сделать после итога, простыми словами (кроме «прочитано»). */
const NEXT: Partial<Record<StudioReadResult['code'], string>> = {
  no_extension: 'Откройте Chrome, включите расширение Claude in Chrome и нажмите ещё раз.',
  login_needed: 'Войдите в аккаунт YouTube в Chrome и нажмите ещё раз.',
  error: 'Сессия чтения не дошла до конца — журнал под «Подробнее».',
};

function Reading() {
  return (
    <p role="status" data-testid="studio-reading" className="m-0 animate-pulse text-[13px]">
      Читаю Studio в вашем Chrome — только чтение…
    </p>
  );
}

/** Строка итога уже говорит, что сделать («… нажмите ещё раз»): подсказку не повторяем. */
const SAYS_NEXT = /нажмите ещё раз|войдите|включите|откройте/i;

function ResultLine({
  r,
  onClose,
  more,
}: {
  r: StudioReadResult;
  onClose: () => void;
  more?: ReactNode;
}) {
  const tone = outcomeTone(r.code);
  // Слово итога уже на значке: «нужен вход: …» в строке — без него.
  const line = r.line.startsWith(`${r.word}: `) ? r.line.slice(r.word.length + 2) : r.line;
  const lineText = line ? line[0]!.toUpperCase() + line.slice(1) : r.line;
  const next = NEXT[r.code] && !SAYS_NEXT.test(r.line) ? NEXT[r.code] : null;
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      data-testid="studio-result"
      data-code={r.code}
      className="grid gap-1 text-[13px]"
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={tone}>Studio: {r.word}</StatusBadge>
        <span data-testid="studio-result-line">{lineText}</span>
        <Button size="sm" variant="ghost" onClick={onClose} data-testid="studio-result-close">
          Скрыть
        </Button>
      </div>
      {next ? (
        <span className="text-muted-foreground" data-testid="studio-result-next">
          {next}
        </span>
      ) : null}
      <More className="mt-0">
        <span>код итога: {r.code}</span>
        {r.detail ? <span>фабрика: {r.detail}</span> : null}
        {r.recorded.length ? <span>записаны каналы: {r.recorded.join(', ')}</span> : null}
        {r.run_id ? <span>сессия {r.run_id}</span> : null}
        {r.log ? <span>журнал {r.log}</span> : null}
        {more}
      </More>
    </div>
  );
}

/**
 * Кнопка «Прочитать Studio» с окном плана и итогом. `due` — ответ хука (его `launch` и
 * `running`); `highlight` — подсвеченный вид (хук говорит «пора»).
 */
export function StudioReadAction({
  due,
  highlight = false,
  run,
  onRun,
  more,
}: {
  due: StudioReadDue;
  highlight?: boolean;
  run: Run | null;
  onRun: (run: Run | null) => void;
  /** Подробности вокруг кнопки — в одном «Подробнее» с подробностями итога. */
  more?: ReactNode;
}) {
  const name = useChannelNames();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const flow = useConfirmFlow({
    plan: () => planStudioRead(),
    act: (confirm: string) => startStudioRead(confirm),
    onDone: (r: StudioReadStarted) => {
      if (r.run_id) onRun({ id: r.run_id, pollS: r.poll_s });
      setOpen(false);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: [...studioKeys.all, 'due'] }),
  });
  // Сессия, о которой знает фабрика (запущена из другого места центра), — тоже опрашиваем.
  const runId = run?.id ?? due.running ?? null;
  const result = useStudioReadRun(runId, run?.pollS ?? null);
  const reading = !!runId && !result.data?.done;
  const off = !due.launch.available;

  const onOpenChange = (v: boolean) => {
    setOpen(v);
    if (v) flow.start(undefined);
    else flow.reset();
  };
  const plan = flow.plan;
  const opener = off ? (
    <Button variant="ghost" data-testid="studio-read-plan">
      Что прочитает…
    </Button>
  ) : (
    <Button
      variant={highlight ? 'default' : 'outline'}
      data-testid="studio-read-open"
      disabled={reading}
    >
      Прочитать Studio
    </Button>
  );

  return (
    <div className="grid gap-2" data-testid="studio-read">
      <div className="flex flex-wrap items-center gap-2">
        {off ? (
          <Tip content={due.launch.why ?? 'Запуск чтения из центра выключен'}>
            <span tabIndex={0} data-testid="studio-read-off" className="rounded-lg">
              <Button
                variant={highlight ? 'default' : 'outline'}
                data-testid="studio-read-open"
                disabled
              >
                Прочитать Studio
              </Button>
            </span>
          </Tip>
        ) : null}
        <ConfirmDialog
          open={open}
          onOpenChange={onOpenChange}
          tip={
            off
              ? 'План чтения: какие каналы и как — сам запуск пока выключен'
              : 'Сессия Claude прочитает Studio в вашем Chrome — только после вашего «да»'
          }
          trigger={opener}
          title="Прочитать YouTube Studio?"
          description="Сессия Claude откроет studio.youtube.com в вашем Chrome — только чтение: долю «досмотрели/пролистали». Ничего в Studio не меняет."
          confirmLabel={confirmText('Прочитать', flow)}
          pendingLabel="Запускаю…"
          pending={flow.acting}
          confirmDisabled={!flow.canConfirm || off}
          confirmTestId="studio-read-confirm"
          onConfirm={() => void flow.confirm()}
          extraActions={<ReplanButton flow={flow} onClick={() => flow.replan()} />}
        >
          {plan ? (
            <div className="grid gap-2 text-[13px]" data-testid="studio-plan">
              {plan.ok && off ? (
                <p
                  role="status"
                  data-testid="studio-plan-off"
                  className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] p-2.5"
                >
                  {plan.launch.why ?? due.launch.why}
                </p>
              ) : null}
              {!plan.ok ? (
                <p role="alert" data-testid="studio-plan-why" className="m-0 text-danger">
                  {plan.refusals[0]?.message ?? plan.why}
                </p>
              ) : null}
              <div className="grid gap-1">
                <span className="text-muted-foreground">Каналы, которые прочитает:</span>
                <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                  {plan.channels.map((c) => (
                    <li key={c} data-testid="studio-plan-channel" data-channel={c}>
                      <StatusBadge tone="idle">{name(c)}</StatusBadge>
                    </li>
                  ))}
                </ul>
              </div>
              <p className="m-0" data-testid="studio-plan-chrome">
                Только чтение в вашем Chrome: нужен открытый Chrome с расширением Claude in Chrome и
                вход в YouTube.
              </p>
              <More className="mt-0">
                {plan.lines.map((l, i) => (
                  <span key={`l${i}`}>{l}</span>
                ))}
                {plan.refusals.map((r) => (
                  <span key={r.code}>
                    {r.code}: {r.line ?? r.message}
                  </span>
                ))}
                {plan.argv ? <span>запустит: {plan.argv.join(' ')}</span> : null}
                <span>
                  кто: {plan.by ?? '—'} · откуда: {plan.via ?? '—'}
                </span>
                <span>выключатель {plan.launch.switch}</span>
                <span>отпечаток проверки {plan.fingerprint}</span>
                {plan.expires_in_s != null ? (
                  <span>подтверждение живёт {plan.expires_in_s} с</span>
                ) : null}
              </More>
            </div>
          ) : null}
          <FlowNotes
            flow={flow}
            timeoutText="Фабрика не ответила вовремя. Нажмите «Прочитать Studio» ещё раз чуть позже."
          />
        </ConfirmDialog>
      </div>
      {off ? (
        <span className="text-xs text-muted-foreground" data-testid="studio-launch-off">
          {due.launch.why ?? 'Запуск чтения из центра выключен.'}
        </span>
      ) : null}
      {reading ? <Reading /> : null}
      {result.isError ? (
        <p role="alert" className="m-0 text-[13px] text-danger" data-testid="studio-result-error">
          Итог чтения не узнать — посмотрите позже.
        </p>
      ) : null}
      {result.data?.done ? (
        <ResultLine r={result.data} onClose={() => onRun(null)} more={more} />
      ) : more ? (
        <More className="mt-0">{more}</More>
      ) : null}
    </div>
  );
}

/** Кнопка чтения блока с подробностями хука под одним «Подробнее». */
export function StudioDueAction({ due, state }: { due: StudioReadDue; state: StudioDueState }) {
  const hookWord = hookWordOf(due);
  return (
    <StudioReadAction
      due={due}
      highlight={due.due}
      run={state.run}
      onRun={state.setRun}
      more={
        <>
          {hookWord ? <span>повод: {hookWord}</span> : null}
          {due.channels.map((c) => (
            <span key={c.channel}>{c.why}</span>
          ))}
          {due.skipped.map((s) => (
            <span key={s}>пропущено: {s}</span>
          ))}
          {due.last_read_at ? <span>последнее чтение {due.last_read_at}</span> : null}
        </>
      }
    />
  );
}

/** Подсвеченная кнопка по хуку (см. `useStudioDueState`) — в «Публикации» и окне запуска. */
export function StudioDue({
  hook,
  channel = null,
  enabled = true,
  className,
}: {
  hook: StudioHook;
  channel?: string | null;
  enabled?: boolean;
  className?: string;
}) {
  const state = useStudioDueState(hook, { channel, enabled });
  const due = state.due;
  if (!due) return null;
  const hookWord = hookWordOf(due);
  return (
    <div
      data-testid="studio-due"
      data-hook={hook}
      data-due={due.due || undefined}
      className={cn(
        'grid gap-2 rounded-sm border border-[color-mix(in_srgb,var(--primary)_45%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_8%,var(--card))] p-3 text-[13px]',
        className,
      )}
    >
      {due.due ? (
        <p className="m-0">
          <b className="font-semibold">Пора прочитать Studio. </b>
          <span data-testid="studio-why">{due.why}</span>{' '}
          <span className="text-muted-foreground" data-testid="studio-age">
            ({ageText(due.age_hours)})
          </span>
          {hookWord ? (
            <span className="text-muted-foreground" data-testid="studio-hook">
              {' '}
              Повод: {hookWord}.
            </span>
          ) : null}
        </p>
      ) : null}
      <StudioDueAction due={due} state={state} />
    </div>
  );
}
