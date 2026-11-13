// Редактор списка по строкам (CC-0115 шаг 3, З7): у каждой строки — поля её схемы с подписями
// по-русски, добавить/убрать строку, проверка на лету словами. Поля, которых редактор не знает
// (отметки фабрики, проверки, история), остаются в строке как были — правка их не теряет.
// Состояние — снаружи (`Item[]`): так документ собирается из строк в одном месте.
import { useId, type ReactNode } from 'react';

import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { itemOf, type FieldSpec, type Item, type Row } from './rows';
import { inputBase } from './styles';

function FieldInput({
  f,
  value,
  onChange,
  testId,
}: {
  f: FieldSpec;
  value: string;
  onChange: (v: string) => void;
  testId: string;
}) {
  const id = useId();
  return (
    // Подпись — в верхней строке, растущей по соседу: перенос подписи не сдвигает поле вниз
    // относительно поля рядом (CC-0131); поле и список — одной высоты (`h-8`), ровно по линии.
    <label
      htmlFor={id}
      className={cn(
        'grid min-w-0 grid-cols-1 grid-rows-[1fr_auto] gap-0.5',
        f.wide && 'sm:col-span-2',
      )}
    >
      {f.tip ? (
        <Tip content={f.tip}>
          <span
            tabIndex={0}
            className="w-max max-w-full self-end text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
          >
            {f.label}
          </span>
        </Tip>
      ) : (
        <span className="self-end text-xs text-muted-foreground">{f.label}</span>
      )}
      {f.kind === 'bool' ? (
        // Флажок — по первой строке подписи, даже когда она переносится (CC-0129).
        <span className="flex min-h-8 items-start gap-2 pt-1.5">
          <input
            id={id}
            type="checkbox"
            data-testid={testId}
            checked={!!value}
            onChange={(e) => onChange(e.target.checked ? '1' : '')}
            className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
          />
          <span>{f.check ?? 'да'}</span>
        </span>
      ) : f.kind === 'select' ? (
        <select
          id={id}
          data-testid={testId}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={cn(inputBase, 'h-8')}
        >
          {/* Значение, которого нет среди вариантов, — своим пунктом: поле не врёт о строке. */}
          {!value || f.options!.some((o) => o.v === value) ? null : (
            <option value={value}>другое значение (см. «как файл»)</option>
          )}
          {f.options!.map((o) => (
            <option key={o.v} value={o.v}>
              {o.label}
            </option>
          ))}
        </select>
      ) : f.kind === 'lines' ? (
        // Одна строка поля — один элемент списка (оговорки и т.п., CC-0130).
        <textarea
          id={id}
          data-testid={testId}
          value={value}
          placeholder={f.placeholder}
          spellCheck={false}
          rows={Math.min(8, Math.max(3, value.split('\n').length + 1))}
          onChange={(e) => onChange(e.target.value)}
          className={cn(inputBase, 'h-auto min-h-16 py-1.5')}
        />
      ) : (
        <input
          id={id}
          data-testid={testId}
          value={value}
          placeholder={f.placeholder}
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
          className={cn(inputBase, 'h-8')}
        />
      )}
    </label>
  );
}

export function RowsEditor({
  id,
  title,
  items,
  fields,
  onChange,
  problems,
  newRow,
  addLabel,
  rowName,
  extra,
}: {
  id: string;
  title: string;
  items: Item[];
  fields: FieldSpec[];
  onChange: (items: Item[]) => void;
  /** Что не так с каждой строкой (по порядку) — словами. */
  problems: string[][];
  /** Новая строка: поля, что ставятся сами (кто и когда добавил). */
  newRow: () => Row;
  addLabel: string;
  /** Как назвать строку в её шапке. */
  rowName: (item: Item, i: number) => string;
  /** Что показать под полями строки (то, что правится не здесь, — словами), CC-0129. */
  extra?: (item: Item) => ReactNode;
}) {
  const set = (uid: number, key: string, v: string) =>
    onChange(items.map((x) => (x.uid === uid ? { ...x, text: { ...x.text, [key]: v } } : x)));
  return (
    // `min-w-0`: у fieldset ширина по самому длинному пункту списка — на телефоне вылезал бы за край.
    <fieldset
      className="m-0 grid min-w-0 grid-cols-1 gap-2 border-0 p-0"
      data-testid={`rows-${id}`}
    >
      <legend className="mb-1 text-[13px] font-semibold">
        {title} <span className="font-normal text-muted-foreground">· {items.length}</span>
      </legend>
      {items.length ? null : (
        <p className="m-0 text-xs text-muted-foreground" data-testid={`rows-${id}-empty`}>
          Пока ни одной записи.
        </p>
      )}
      {items.map((item, i) => {
        const bad = problems[i] ?? [];
        return (
          <div
            key={item.uid}
            data-testid={`rows-${id}-row`}
            data-bad={bad.length ? '1' : undefined}
            className={cn(
              'grid min-w-0 grid-cols-1 gap-2 rounded-sm border p-2',
              bad.length && 'border-[color-mix(in_srgb,var(--danger)_45%,var(--border))]',
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <b className="text-[13px] font-semibold [overflow-wrap:anywhere]">
                {rowName(item, i)}
              </b>
              <Button
                size="sm"
                variant="ghost"
                data-testid={`rows-${id}-remove`}
                onClick={() => onChange(items.filter((x) => x.uid !== item.uid))}
              >
                Убрать
              </Button>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {fields.map((f) => (
                <FieldInput
                  key={f.key}
                  f={f}
                  value={item.text[f.key] ?? ''}
                  onChange={(v) => set(item.uid, f.key, v)}
                  testId={`rows-${id}-${f.key}`}
                />
              ))}
            </div>
            {extra?.(item)}
            {bad.length ? (
              <ul
                className="m-0 grid list-disc gap-0.5 pl-5 text-xs text-danger"
                data-testid={`rows-${id}-problems`}
              >
                {bad.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
      <div>
        <Button
          size="sm"
          variant="outline"
          data-testid={`rows-${id}-add`}
          onClick={() => onChange([...items, itemOf(newRow(), fields)])}
        >
          {addLabel}
        </Button>
      </div>
    </fieldset>
  );
}
