// Карточка просьбы оператору (CC-0019): что вы попросили и откуда, состояние словами, ответ
// оператора и его доставка в Telegram. «Закрыть» — у отвеченной, прямая запись; «Отменить…» —
// у открытой или взятой, одно подтверждение. Отказ — строкой фабрики (`text_ru`), английская —
// под «подробнее». Вне рабочей фабрики обе кнопки погашены причиной.
import { useState } from 'react';

import {
  requestErrorText,
  useCancelRequest,
  useCloseRequest,
  type OperatorRequest,
} from '@/api/requests';
import { ContextList, RequestRefusal } from '@/components/ask/AskDialog';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { useToast } from '@/components/common/useToast';
import { WriteButton } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { dateTimeMsk, whoText } from '@/pages/batches/format';

import { Said } from './QuestionCard';
import { notifyView, REQUEST_STATUS } from './requestsFormat';

function Asked({ r }: { r: OperatorRequest }) {
  const who = whoText(r.created_by);
  const when = dateTimeMsk(r.created);
  return (
    <span className="text-xs text-muted-foreground">
      {[who === 'вы' || !who ? 'Вы попросили' : `Попросил ${who}`, when]
        .filter(Boolean)
        .join(' · ')}
    </span>
  );
}

function Notify({ r }: { r: OperatorRequest }) {
  const v = notifyView(r);
  if (!v) return null;
  return (
    <span data-testid="request-notify" data-notify={v.state}>
      <StatusBadge tone={v.tone} tip={v.tip}>
        {v.label}
      </StatusBadge>
    </span>
  );
}

function CloseButton({ r }: { r: OperatorRequest }) {
  const toast = useToast();
  const close = useCloseRequest();
  return (
    <>
      <WriteButton
        size="sm"
        variant="default"
        data-testid="request-close"
        aria-busy={close.isPending || undefined}
        disabled={close.isPending}
        tip="Ответ прочитан — закрыть просьбу: она уйдёт в историю"
        onClick={() =>
          close.mutate(r.id, {
            onSuccess: () => toast('Просьба закрыта'),
            onError: (e) => {
              const t = requestErrorText(e, 'close');
              if (t.gone) toast(t.text, 'danger');
            },
          })
        }
      >
        {close.isPending ? 'Закрываю…' : 'Закрыть'}
      </WriteButton>
      {close.isError ? (
        <div className="basis-full">
          <RequestRefusal e={close.error} action="close" />
        </div>
      ) : null}
    </>
  );
}

function CancelButton({ r }: { r: OperatorRequest }) {
  const toast = useToast();
  const cancel = useCancelRequest();
  const [open, setOpen] = useState(false);
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) cancel.reset();
      }}
      trigger={
        <Button size="sm" variant="ghost" data-testid="request-cancel">
          Отменить…
        </Button>
      }
      tip="Отменить просьбу: оператор её не будет исполнять. Спросит одно подтверждение"
      title="Отменить просьбу?"
      description={<span className="[overflow-wrap:anywhere]">«{r.text}»</span>}
      error={cancel.isError ? <RequestRefusal e={cancel.error} action="cancel" /> : null}
      confirmLabel="Отменить просьбу"
      pendingLabel="Отменяю…"
      pending={cancel.isPending}
      danger
      confirmTestId="request-cancel-confirm"
      onConfirm={() =>
        cancel.mutate(r.id, {
          onSuccess: () => {
            setOpen(false);
            toast('Просьба отменена');
          },
          onError: (e) => {
            const t = requestErrorText(e, 'cancel');
            if (t.gone) toast(t.text, 'danger');
          },
        })
      }
    />
  );
}

/** Номер, кто что делал, ключ Telegram и контекст в JSON — только здесь. */
export function RequestMore({ r }: { r: OperatorRequest }) {
  return (
    <More className="mt-0">
      <span>просьба: {r.id}</span>
      {r.created ? (
        <span>
          создана: {r.created}
          {r.created_by ? ` (${r.created_by})` : ''}
        </span>
      ) : null}
      {r.channel ? <span>канал: {r.channel}</span> : null}
      {r.taken_by ? (
        <span>
          взял: {r.taken_by}
          {r.taken_at ? ` ${r.taken_at}` : ''}
        </span>
      ) : null}
      {r.answered_by ? (
        <span>
          ответил: {r.answered_by}
          {r.answered_at ? ` ${r.answered_at}` : ''}
        </span>
      ) : null}
      {r.closed_by ? (
        <span>
          закрыл: {r.closed_by}
          {r.closed_at ? ` ${r.closed_at}` : ''}
        </span>
      ) : null}
      {r.cancelled_by ? (
        <span>
          отменил: {r.cancelled_by}
          {r.cancelled_at ? ` ${r.cancelled_at}` : ''}
        </span>
      ) : null}
      {r.notify ? (
        <span>
          telegram: {r.notify.status}, попытка {r.notify.attempt ?? '—'}, {r.notify.key ?? '—'}
          {r.notify.reason ? ` — ${r.notify.reason}` : ''}
        </span>
      ) : null}
      {r.context != null ? (
        <span className="whitespace-pre-wrap" data-testid="request-context-json">
          контекст: {JSON.stringify(r.context, null, 2)}
        </span>
      ) : null}
    </More>
  );
}

/** Живая просьба (открыта, взята, отвечена) — с ответом и кнопками. */
export function RequestCard({ r }: { r: OperatorRequest }) {
  const st = REQUEST_STATUS[r.status];
  const taken = r.status === 'taken' ? dateTimeMsk(r.taken_at) : null;
  return (
    <section
      aria-label={`Просьба: ${r.text.slice(0, 60)}`}
      data-testid="request"
      data-status={r.status}
      data-rid={r.id}
      className={cn(
        'grid min-w-0 content-start gap-2.5 rounded-lg border bg-card p-card',
        r.status === 'answered' && 'border-[color-mix(in_srgb,var(--success)_35%,var(--border))]',
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <Asked r={r} />
        <StatusBadge tone={st.tone} tip={st.tip}>
          {st.label}
        </StatusBadge>
      </div>
      <p
        className="m-0 text-[15px] leading-[1.45] [overflow-wrap:anywhere] whitespace-pre-wrap"
        data-testid="request-text"
      >
        {r.text}
      </p>
      <ContextList context={r.context} channel={r.channel} inline testId="request-context" />
      {taken ? (
        <span className="text-xs text-muted-foreground" data-testid="request-taken">
          Оператор взял в работу {taken}
        </span>
      ) : null}
      {r.answer ? (
        <Said label="Ответ оператора" at={r.answered_at}>
          <span data-testid="request-answer">{r.answer}</span>
        </Said>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {r.status === 'answered' ? <CloseButton r={r} /> : null}
        {r.status === 'open' || r.status === 'taken' ? <CancelButton r={r} /> : null}
        <Notify r={r} />
      </div>
      <RequestMore r={r} />
    </section>
  );
}

/** Закрытая или отменённая просьба в истории. */
export function RequestHistoryItem({ r }: { r: OperatorRequest }) {
  const closed = r.status === 'closed';
  const who = whoText(closed ? r.closed_by : r.cancelled_by);
  const when = dateTimeMsk(closed ? r.closed_at : r.cancelled_at);
  return (
    <li
      data-testid="request-history-item"
      data-rid={r.id}
      data-status={r.status}
      className="grid min-w-0 gap-2 border-t py-3 first:border-t-0 first:pt-0"
    >
      <Asked r={r} />
      <p className="m-0 [overflow-wrap:anywhere] whitespace-pre-wrap">{r.text}</p>
      <ContextList context={r.context} channel={r.channel} inline />
      {r.answer ? (
        <Said label="Ответ оператора" at={r.answered_at}>
          {r.answer}
        </Said>
      ) : null}
      <span
        className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
        data-testid="request-history-state"
      >
        <span>
          {closed ? 'Закрыта' : 'Отменена'}
          {when ? ` ${when}` : ''}
          {who ? ` · ${who === 'вы' ? 'вами' : who}` : ''}
        </span>
        <Notify r={r} />
      </span>
      <RequestMore r={r} />
    </li>
  );
}
