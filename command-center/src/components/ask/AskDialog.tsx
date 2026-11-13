// Окно «Попросить оператора» (CC-0019): одно на всё приложение, открывается кнопкой в шапке
// (контекст — экран) или кнопкой на ролике, батче, канале (контекст подставлен). Текст словами,
// видимое «Откуда», явное «Отправить» — прямая запись `POST /api/requests` без плана. Отказ —
// строкой фабрики (`text_ru`) в окне, введённое остаётся. Вне рабочей фабрики кнопки открытия и
// «Отправить» погашены причиной (`WriteGate`/`WriteButton`).
import { useCallback, useId, useRef, useState, type ReactNode } from 'react';
import { useLocation } from 'react-router';

import { REQUEST_TEXT_MAX, requestErrorText, useCreateRequest } from '@/api/requests';
import { useWrites } from '@/api/writes';
import { MessageIcon } from '@/components/common/icons';
import { More } from '@/components/common/More';
import { Tip } from '@/components/common/Tip';
import { useToast } from '@/components/common/useToast';
import { WriteButton, WriteGate } from '@/components/common/WriteButton';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useChannelNames } from '@/pages/batches/names';
import { inputBase } from '@/pages/channels/styles';

import { ASK_TIP, contextOf, contextRows, type AskContext, type AskTarget } from './target';
import { AskOpenContext, useAsk } from './useAsk';

/** Отказ записи просьбы: строка фабрики для человека, английская — под «подробнее». */
export function RequestRefusal({
  e,
  action,
  testId,
}: {
  e: unknown;
  action: 'create' | 'close' | 'cancel';
  testId?: string;
}) {
  const t = requestErrorText(e, action);
  return (
    <div
      role="alert"
      data-testid={testId ?? `${action}-error`}
      className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-2.5"
    >
      <div className="font-semibold text-danger">{t.title}</div>
      <p className="m-0 text-muted-foreground">{t.text}</p>
      {t.detail ? (
        <More className="mt-0">
          <span>{t.detail}</span>
        </More>
      ) : null}
    </div>
  );
}

/** «Откуда» словами: экран, канал, батч, ролик. */
export function ContextList({
  context,
  channel,
  testId,
  className,
  inline = false,
}: {
  context: unknown;
  channel?: string | null;
  testId?: string;
  className?: string;
  /** Одной строкой «Откуда: …» — в карточке просьбы. */
  inline?: boolean;
}) {
  const channelName = useChannelNames();
  const rows = contextRows(context, channelName, channel);
  if (!rows.length) return null;
  if (inline)
    return (
      <p data-testid={testId} className={cn('m-0 text-xs text-muted-foreground', className)}>
        Откуда:{' '}
        {rows
          .map((r) => (r.key === 'area' ? r.value : `${r.label.toLowerCase()} ${r.value}`))
          .join(' · ')}
      </p>
    );
  return (
    <dl
      data-testid={testId}
      className={cn(
        'm-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[13px]',
        className,
      )}
    >
      {rows.map((r) => (
        <div key={r.key} className="contents" data-row={r.key}>
          <dt className="text-muted-foreground">{r.label}</dt>
          <dd className="m-0 [overflow-wrap:anywhere]">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function AskWindow({ ctx, onClose }: { ctx: AskContext; onClose: () => void }) {
  const id = useId();
  const toast = useToast();
  const create = useCreateRequest();
  const writes = useWrites();
  const area = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState('');
  const trimmed = text.trim();
  const long = trimmed.length > REQUEST_TEXT_MAX;
  const why = !trimmed
    ? 'Сначала напишите просьбу'
    : long
      ? `Просьба длиннее ${REQUEST_TEXT_MAX} знаков — сократите её`
      : undefined;
  const send = () => {
    if (why || create.isPending || !writes.allowed) return;
    create.mutate(
      { text: trimmed, channel: ctx.channel ?? null, context: ctx },
      {
        onSuccess: () => {
          toast('Просьба отправлена оператору');
          onClose();
        },
      },
    );
  };
  return (
    <AlertDialogContent
      data-testid="ask-dialog"
      onOpenAutoFocus={(e) => {
        e.preventDefault();
        area.current?.focus();
      }}
    >
      <AlertDialogHeader>
        <AlertDialogTitle>Попросить оператора</AlertDialogTitle>
        <AlertDialogDescription>
          Напишите словами, что сделать или проверить.{' '}
          <Tip content={ASK_TIP} wide>
            <span
              tabIndex={0}
              data-testid="ask-how"
              className="cursor-help text-primary-text underline decoration-dotted underline-offset-4"
            >
              Кто это сделает?
            </span>
          </Tip>
        </AlertDialogDescription>
      </AlertDialogHeader>
      <div className="grid gap-1.5 rounded-sm border bg-[color-mix(in_srgb,var(--muted-foreground)_6%,transparent)] p-2.5">
        <span className="eyebrow">Откуда просьба</span>
        <ContextList context={ctx} testId="ask-context" />
      </div>
      <form
        className="grid gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <label htmlFor={id} className="text-[13px] text-muted-foreground">
          Просьба
        </label>
        <textarea
          id={id}
          ref={area}
          data-testid="ask-text"
          rows={4}
          value={text}
          placeholder="например: посмотри, почему обрывается музыка на 0:42"
          onChange={(e) => {
            setText(e.target.value);
            if (create.isError) create.reset();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              send();
            }
          }}
          className={cn(inputBase, 'h-auto min-h-24 resize-y py-2 text-sm')}
        />
        {trimmed.length > REQUEST_TEXT_MAX * 0.9 ? (
          <span
            data-testid="ask-length"
            className={cn('text-xs', long ? 'text-danger' : 'text-muted-foreground')}
          >
            {trimmed.length} из {REQUEST_TEXT_MAX} знаков
          </span>
        ) : null}
      </form>
      {create.isError ? <RequestRefusal e={create.error} action="create" /> : null}
      <More className="mt-0">
        <span>контекст для оператора:</span>
        <span className="whitespace-pre-wrap" data-testid="ask-context-json">
          {JSON.stringify(ctx, null, 2)}
        </span>
      </More>
      <AlertDialogFooter>
        <AlertDialogCancel disabled={create.isPending}>Отмена</AlertDialogCancel>
        <WriteButton
          variant="default"
          data-testid="ask-send"
          aria-busy={create.isPending || undefined}
          disabled={create.isPending}
          why={why}
          tip={`${ASK_TIP}. Ctrl+Enter — тоже отправить`}
          onClick={send}
        >
          {create.isPending ? 'Отправляю…' : 'Отправить'}
        </WriteButton>
      </AlertDialogFooter>
    </AlertDialogContent>
  );
}

/** Провайдер окна просьбы: одно окно, `useAsk()` открывает его с контекстом. */
export function AskProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [ctx, setCtx] = useState<AskContext | null>(null);
  const [open, setOpen] = useState(false);
  const ask = useCallback(
    (target?: AskTarget) => {
      setCtx(contextOf(location, target));
      setOpen(true);
    },
    [location],
  );
  return (
    <AskOpenContext value={ask}>
      {children}
      <AlertDialog open={open} onOpenChange={setOpen}>
        {open && ctx ? (
          <AskWindow key={JSON.stringify(ctx)} ctx={ctx} onClose={() => setOpen(false)} />
        ) : null}
      </AlertDialog>
    </AskOpenContext>
  );
}

/**
 * Кнопка «попросить» с подставленным контекстом (ролик, батч, канал). Вне рабочей фабрики
 * погашена причиной; вне провайдера (страница без шапки) — не рисуется.
 */
export function AskButton({
  target,
  tip,
  label = 'Попросить оператора',
  testId = 'ask-open',
  className,
}: {
  target: AskTarget;
  tip: string;
  label?: string;
  testId?: string;
  className?: string;
}) {
  const ask = useAsk();
  if (!ask) return null;
  return (
    <WriteGate tip={`${tip}. ${ASK_TIP}`} wide>
      <Button size="sm" data-testid={testId} className={className} onClick={() => ask(target)}>
        <MessageIcon className="size-[14px]" />
        {label}
      </Button>
    </WriteGate>
  );
}

/** Общая кнопка в шапке: контекст — только экран. На телефоне — одна иконка. */
export function AskHeaderButton() {
  const ask = useAsk();
  return (
    <WriteGate tip={`Свободная просьба оператору с этого экрана. ${ASK_TIP}`} wide>
      <Button
        aria-label="Попросить оператора"
        data-testid="ask-open-header"
        data-tour="ask"
        onClick={() => ask?.()}
      >
        <MessageIcon className="size-[15px]" />
        <span className="hidden sm:inline">Попросить оператора</span>
      </Button>
    </WriteGate>
  );
}
