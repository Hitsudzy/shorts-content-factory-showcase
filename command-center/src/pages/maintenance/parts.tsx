// Общие куски экрана «Обслуживание и расход» (CC-0033): поле «да» (пустое, набираете вы сами —
// центр его не подставляет и вставку не принимает), выбор батча, плитка с числом.
import { useId, type ReactNode } from 'react';

import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';
import { inputBase } from '@/pages/channels/styles';

export function YesField({
  value,
  onChange,
  testId,
  what,
}: {
  value: string;
  onChange: (v: string) => void;
  testId: string;
  /** Что подтверждается: «Освободить пул?». */
  what: string;
}) {
  const id = useId();
  return (
    <div className="grid gap-1" data-testid={`${testId}-field`}>
      <label htmlFor={id} className="font-semibold">
        {what} Введите «да»
      </label>
      <input
        id={id}
        data-testid={testId}
        value={value}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onPaste={(e) => e.preventDefault()}
        className={cn(inputBase, 'max-w-40')}
      />
      <span className="text-xs text-muted-foreground">
        Ответ набираете вы — прочитав план. Кнопка подтверждения включится после «да».
      </span>
    </div>
  );
}

export function BatchSelect({
  label,
  value,
  onChange,
  options,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  testId: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="grid min-w-0 flex-1 basis-56 gap-1 text-[13px]">
      <span className="text-xs text-muted-foreground">{label}</span>
      <select
        id={id}
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={inputBase}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Плитка «подпись — число» (`.stat` макета); `tip` — что это за число. */
export function Tile({
  label,
  value,
  sub,
  tip,
  testId,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tip?: string;
  testId?: string;
  tone?: 'ok' | 'warn';
}) {
  const caption = (
    <span
      tabIndex={tip ? 0 : undefined}
      className={cn(
        'w-max text-xs text-muted-foreground',
        tip && 'underline decoration-dotted underline-offset-4',
      )}
    >
      {label}
    </span>
  );
  return (
    <div
      className={cn(
        'grid min-w-0 content-start gap-0.5 rounded-sm border px-3 py-2.5',
        tone === 'ok' && 'border-[color-mix(in_srgb,var(--success)_40%,var(--border))]',
        tone === 'warn' && 'border-[color-mix(in_srgb,var(--warning)_45%,var(--border))]',
      )}
      data-testid={testId}
    >
      {tip ? <Tip content={tip}>{caption}</Tip> : caption}
      <span className="font-display text-[22px] leading-tight font-semibold tabular-nums">
        {value}
      </span>
      {sub ? <span className="text-xs text-muted-foreground">{sub}</span> : null}
    </div>
  );
}
