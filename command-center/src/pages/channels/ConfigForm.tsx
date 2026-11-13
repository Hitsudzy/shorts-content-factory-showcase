// Форма настроек канала: блок на каждый ключ верхнего уровня (сворачивается), тултип на
// каждом поле из его пояснения в конфиге; пояснения (`*_note`) — не поля ввода.
import { useEffect, useId, useMemo, useState, type ReactNode } from 'react';

import type { ConfigField } from '@/api/channels';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';

import {
  buildBlocks,
  fieldKey,
  KIND_LABEL,
  keyLabel,
  leaves,
  lockedReason,
  noteTip,
  pathLabel,
  valueAt,
  type Block,
  type FieldNode,
  type FileKind,
} from './fields';
import { inputBase } from './styles';

export type FormProps = {
  fields: readonly ConfigField[];
  docs: Record<FileKind, Record<string, unknown> | null>;
  /** Ключи полей с ошибкой проверки → что сказала проверка (по-человечески). */
  errors: ReadonlyMap<string, string[]>;
  changed: ReadonlySet<string>;
  disabled: boolean;
  disabledWhy: string | null;
  onChange: (file: FileKind, path: readonly string[], value: unknown) => void;
  onPending: (key: string, pending: boolean) => void;
  /** Перейти к полю: блок раскрывается, поле — в фокус. `n` меняется на каждый переход. */
  focus: { key: string; n: number } | null;
};

const domId = (key: string) => `f-${key.replace(/[^\w-]/g, '_')}`;

function FieldTip({ field, label }: { field: ConfigField; label: string }) {
  const { tip } = noteTip(field.note);
  const locked = lockedReason(field);
  const content = (
    <div className="grid gap-1">
      <div>{tip ?? 'У этого поля нет своего пояснения в конфиге.'}</div>
      <div className="opacity-75">
        {KIND_LABEL[field.kind]}
        {field.checked_by.length ? ' · фабрика проверяет блок перед сохранением' : ''}
        {locked ? ` · ${locked}` : ''}
      </div>
    </div>
  );
  return (
    <Tip content={content} wide side="top">
      <button
        type="button"
        aria-label={`Что это: ${label}`}
        data-has-note={tip ? 'true' : 'false'}
        className={cn(
          'inline-grid size-[18px] shrink-0 place-items-center rounded-full border text-[11px] leading-none',
          tip
            ? 'border-[color-mix(in_srgb,var(--primary)_45%,var(--border))] text-primary-text'
            : 'text-muted-foreground',
        )}
      >
        ?
      </button>
    </Tip>
  );
}

/** Значение-текст: короткое — строкой, длинное или с переносами — полем побольше. */
function TextInput(props: {
  id: string;
  value: string;
  disabled: boolean;
  invalid: boolean;
  onChange: (v: string) => void;
}) {
  const long = props.value.length > 70 || props.value.includes('\n');
  const common = {
    id: props.id,
    disabled: props.disabled,
    'aria-invalid': props.invalid || undefined,
    className: cn(inputBase, long && 'min-h-[84px] resize-y leading-[1.45]'),
  };
  return long ? (
    <textarea
      {...common}
      rows={Math.min(8, Math.ceil(props.value.length / 90) + 1)}
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
    />
  ) : (
    <input
      {...common}
      type="text"
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
    />
  );
}

const NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;

/**
 * Поле с разбором (число, список JSON): пока введённое не разбирается, значение в черновик
 * не идёт, а под полем — что не так.
 */
function ParsedInput<T>(props: {
  id: string;
  value: T;
  show: (v: T) => string;
  read: (s: string) => { ok: true; value: T } | { ok: false; why: string };
  multiline?: boolean;
  disabled: boolean;
  invalid: boolean;
  onChange: (v: T) => void;
  pendingKey: string;
  onPending: (key: string, pending: boolean) => void;
}) {
  const shown = props.show(props.value);
  const [text, setText] = useState(shown);
  const [seen, setSeen] = useState(shown);
  const [why, setWhy] = useState<string | null>(null);
  if (seen !== shown) {
    // Значение поменяли снаружи (сырой JSON, «отменить правки», сохранение).
    setSeen(shown);
    setText(shown);
    setWhy(null);
  }
  const { onPending, pendingKey } = props;
  useEffect(() => {
    onPending(pendingKey, why !== null);
    return () => onPending(pendingKey, false);
  }, [why, onPending, pendingKey]);
  const change = (s: string) => {
    setText(s);
    const r = props.read(s);
    if (r.ok) {
      setWhy(null);
      setSeen(props.show(r.value));
      props.onChange(r.value);
    } else setWhy(r.why);
  };
  const common = {
    id: props.id,
    disabled: props.disabled,
    value: text,
    'aria-invalid': props.invalid || why !== null || undefined,
    'aria-describedby': why ? `${props.id}-why` : undefined,
  };
  return (
    <>
      {props.multiline ? (
        <textarea
          {...common}
          rows={Math.min(6, Math.max(1, Math.ceil(text.length / 80)))}
          className={cn(inputBase, 'resize-y font-mono text-xs')}
          onChange={(e) => change(e.target.value)}
        />
      ) : (
        <input
          {...common}
          inputMode="decimal"
          className={cn(inputBase, 'max-w-[220px] font-mono')}
          onChange={(e) => change(e.target.value)}
        />
      )}
      {why ? (
        <div id={`${props.id}-why`} className="text-xs text-danger">
          {why}
        </div>
      ) : null}
    </>
  );
}

function readNumber(s: string) {
  const t = s.trim().replace(',', '.');
  return NUMBER.test(t)
    ? ({ ok: true, value: Number(t) } as const)
    : ({ ok: false, why: 'Нужно число, например 45 или 1.1' } as const);
}

function readJson(s: string) {
  try {
    return { ok: true, value: JSON.parse(s) as unknown } as const;
  } catch {
    return {
      ok: false,
      why: 'Не читается как JSON: список пишется в квадратных скобках, текст — в кавычках, например ["film", "tv_series"]',
    } as const;
  }
}

function FieldRow({ field, props }: { field: ConfigField; props: FormProps }) {
  const key = fieldKey(field.file, field.path);
  const id = domId(key);
  const doc = props.docs[field.file];
  const value = valueAt(doc, field.path);
  const label = keyLabel(field.path.at(-1)!);
  const locked = lockedReason(field);
  const disabled = props.disabled || !!locked || doc === null;
  const errs = props.errors.get(key);
  const invalid = !!errs?.length;
  const changed = props.changed.has(key);
  const { trimmed, full } = noteTip(field.note);
  const set = (v: unknown) => props.onChange(field.file, field.path, v);

  let input: ReactNode;
  if (value === undefined) {
    input = <div className="text-xs text-muted-foreground">в черновике этого поля нет</div>;
  } else if (typeof value === 'string') {
    input = (
      <TextInput id={id} value={value} disabled={disabled} invalid={invalid} onChange={set} />
    );
  } else if (typeof value === 'boolean') {
    input = (
      <label className="inline-flex w-max items-center gap-2 text-[13px]">
        <input
          id={id}
          type="checkbox"
          checked={value}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          className="size-4 accent-[var(--primary)]"
          onChange={(e) => set(e.target.checked)}
        />
        {value ? 'да' : 'нет'}
      </label>
    );
  } else if (typeof value === 'number') {
    input = (
      <ParsedInput
        id={id}
        value={value}
        show={String}
        read={readNumber}
        disabled={disabled}
        invalid={invalid}
        onChange={set}
        pendingKey={key}
        onPending={props.onPending}
      />
    );
  } else {
    input = (
      <ParsedInput
        id={id}
        value={value}
        show={(v) => JSON.stringify(v)}
        read={readJson}
        multiline
        disabled={disabled}
        invalid={invalid}
        onChange={set}
        pendingKey={key}
        onPending={props.onPending}
      />
    );
  }

  return (
    <div
      data-field={key}
      data-invalid={invalid || undefined}
      className={cn(
        'grid gap-1.5 rounded-sm px-2 py-2 sm:grid-cols-[minmax(160px,240px)_minmax(0,1fr)] sm:gap-3',
        invalid &&
          'bg-[color-mix(in_srgb,var(--danger)_8%,transparent)] ring-1 ring-[color-mix(in_srgb,var(--danger)_45%,var(--border))]',
      )}
    >
      <div className="flex min-w-0 items-start gap-1.5 pt-1">
        <label htmlFor={id} className="min-w-0 text-[13px] [overflow-wrap:anywhere]">
          {label}
        </label>
        <FieldTip field={field} label={pathLabel(field.path)} />
        {changed ? (
          <span className="mt-0.5 size-[7px] shrink-0 rounded-full bg-primary" title="изменено" />
        ) : null}
      </div>
      <div className="grid min-w-0 gap-1">
        {input}
        {errs?.map((e) => (
          <div key={e} className="text-xs text-danger">
            {e}
          </div>
        ))}
        {trimmed ? (
          <More label="Пояснение целиком" className="mt-0">
            <span className="font-sans">{full}</span>
          </More>
        ) : null}
      </div>
    </div>
  );
}

function Nodes({
  nodes,
  props,
  depth,
}: {
  nodes: readonly FieldNode[];
  props: FormProps;
  depth: number;
}) {
  return (
    <>
      {nodes.map((n) =>
        n.field.kind === 'object' ? (
          depth === 0 ? (
            <Nodes
              key={n.field.path.join('.')}
              nodes={n.children}
              props={props}
              depth={depth + 1}
            />
          ) : (
            <fieldset
              key={n.field.path.join('.')}
              data-field={fieldKey(n.field.file, n.field.path)}
              className="grid gap-0.5 border-l-2 pl-3 sm:ml-2"
            >
              <legend className="flex items-center gap-1.5 py-1 text-[13px] font-semibold">
                {keyLabel(n.field.path.at(-1)!)}
                <FieldTip field={n.field} label={pathLabel(n.field.path)} />
              </legend>
              <Nodes nodes={n.children} props={props} depth={depth + 1} />
            </fieldset>
          )
        ) : (
          <FieldRow key={n.field.path.join('.')} field={n.field} props={props} />
        ),
      )}
    </>
  );
}

function BlockView({
  block,
  open,
  onToggle,
  props,
}: {
  block: Block;
  open: boolean;
  onToggle: () => void;
  props: FormProps;
}) {
  const bodyId = useId();
  const title = block.key ? keyLabel(block.key) : 'Основное';
  const all = leaves(block.nodes);
  const keys = block.field
    ? [fieldKey(block.file, block.field.path)]
    : all.map((f) => fieldKey(f.file, f.path));
  const hasError = keys.some((k) => props.errors.has(k));
  const hasChange = keys.some((k) => props.changed.has(k));
  const checks = block.field?.checked_by ?? [];
  const n = all.length;
  const countText = `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'поле' : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? 'поля' : 'полей'}`;
  return (
    <section
      data-block={block.id}
      className={cn(
        'rounded-lg border bg-card',
        hasError && 'border-[color-mix(in_srgb,var(--danger)_55%,var(--border))]',
      )}
    >
      <div className="flex items-center gap-2 px-3 py-2.5 sm:px-4">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={`${title}, ${countText}`}
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span
            aria-hidden
            className={cn('text-muted-foreground transition-transform', open && 'rotate-90')}
          >
            ▸
          </span>
          <span className="min-w-0 font-semibold [overflow-wrap:anywhere]">{title}</span>
          <span className="text-xs whitespace-nowrap text-muted-foreground">{countText}</span>
        </button>
        {hasError ? <StatusBadge tone="danger">ошибка</StatusBadge> : null}
        {hasChange ? <StatusBadge tone="live">изменено</StatusBadge> : null}
        {block.field ? <FieldTip field={block.field} label={title} /> : null}
      </div>
      {open ? (
        <div id={bodyId} className="grid gap-0.5 border-t px-1.5 py-2 sm:px-2">
          <Nodes nodes={block.nodes} props={props} depth={0} />
          {checks.length ? (
            <More className="mx-2 mt-1">
              <span>проверки блока: {checks.join(', ')}</span>
            </More>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** Блок, в котором живёт поле `file:a.b.c`: блок ключа `a` или «Основное». */
function blockOf(blocks: readonly Block[], key: string): Block | undefined {
  const [file, path = ''] = key.split(/:(.*)/s);
  const top = `${file}:${path.split('.')[0]}`;
  return (
    blocks.find((b) => b.id === top) ??
    blocks.find((b) => b.id === `${file}:` && path && !path.includes('.'))
  );
}

function matches(block: Block, q: string) {
  if (!q) return true;
  const hay = [block.key ?? 'основное', ...leaves(block.nodes).map((f) => f.path.join(' '))]
    .join(' ')
    .toLowerCase()
    .replaceAll('_', ' ');
  return hay.includes(q);
}

function Section({
  title,
  tip,
  blocks,
  props,
  query,
}: {
  title: string;
  tip: string;
  blocks: Block[];
  props: FormProps;
  query: string;
}) {
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  const [seenFocus, setSeenFocus] = useState<number | null>(null);
  const focus = props.focus;
  if (focus && focus.n !== seenFocus) {
    setSeenFocus(focus.n);
    const b = blockOf(blocks, focus.key);
    if (b && !open.has(b.id)) setOpen(new Set([...open, b.id]));
  }
  const shown = blocks.filter((b) => matches(b, query));
  if (!blocks.length) return null;
  return (
    <section className="grid gap-2">
      <div className="flex items-center gap-2 pt-1">
        <h2 className="eyebrow">{title}</h2>
        <Tip content={tip}>
          <span
            tabIndex={0}
            className="text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
          >
            что это
          </span>
        </Tip>
        <button
          type="button"
          className="ml-auto text-xs text-primary-text"
          onClick={() => setOpen(open.size ? new Set() : new Set(blocks.map((b) => b.id)))}
        >
          {open.size ? 'Свернуть все' : 'Развернуть все'}
        </button>
      </div>
      {shown.length ? (
        shown.map((b) => (
          <BlockView
            key={b.id}
            block={b}
            open={open.has(b.id) || !!query}
            onToggle={() => {
              const next = new Set(open);
              if (next.has(b.id)) next.delete(b.id);
              else next.add(b.id);
              setOpen(next);
            }}
            props={props}
          />
        ))
      ) : (
        <p className="m-0 px-1 text-muted-foreground">Ничего не нашлось.</p>
      )}
    </section>
  );
}

export function ConfigForm(props: FormProps) {
  const [query, setQuery] = useState('');
  const config = useMemo(() => buildBlocks(props.fields, 'config'), [props.fields]);
  const stance = useMemo(() => buildBlocks(props.fields, 'stance'), [props.fields]);
  const focus = props.focus;

  useEffect(() => {
    if (!focus) return;
    // После раскрытия блока: самое глубокое поле, на которое указывает ошибка.
    const t = window.setTimeout(() => {
      let key = focus.key;
      let el: Element | null;
      for (;;) {
        const k = CSS.escape(key);
        el = document.querySelector(`[data-field="${k}"],[data-block="${k}"]`);
        const cut = key.lastIndexOf('.');
        if (el || cut < 0) break;
        key = key.slice(0, cut);
      }
      el?.scrollIntoView?.({ block: 'center' });
      (el?.querySelector('input,textarea') as HTMLElement | null)?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(t);
  }, [focus]);

  return (
    <div className="grid gap-3" data-tour="channel-settings">
      <div className="flex flex-wrap items-center gap-3">
        <label className="sr-only" htmlFor="field-search">
          Найти поле
        </label>
        <input
          id="field-search"
          type="search"
          placeholder="Найти поле: например, voice или score"
          value={query}
          onChange={(e) => setQuery(e.target.value.trim().toLowerCase().replaceAll('_', ' '))}
          className={cn(inputBase, 'max-w-[360px] bg-card')}
        />
        {props.disabledWhy ? (
          <span className="text-xs text-warning">{props.disabledWhy}</span>
        ) : null}
      </div>
      <Section
        title="Конфиг канала"
        tip="Настройки, которые читают стадии фабрики. Подсказка у каждого поля — из пояснений самого конфига"
        blocks={config}
        props={props}
        query={query}
      />
      <Section
        title="Позиция канала"
        tip="Файл позиции: что канал делает и чего не делает. Его читают пишущие стадии"
        blocks={stance}
        props={props}
        query={query}
      />
    </div>
  );
}
