// Карточка «Что ещё нужно до первого батча»: в конце мастера и в редакторе нового канала.
import { More } from '@/components/common/More';

import type { TodoItem } from './firstBatch';

export function TodoList({ items }: { items: readonly TodoItem[] }) {
  if (!items.length) return null;
  return (
    <section
      aria-labelledby="todo-title"
      data-testid="todo"
      className="grid gap-2.5 rounded-lg border bg-card px-card py-4"
    >
      <div>
        <div className="eyebrow">Дальше</div>
        <h2 id="todo-title" className="mt-0.5 text-[17px] font-semibold">
          Что ещё нужно до первого батча
        </h2>
        <p className="m-0 mt-1 text-xs text-muted-foreground">
          Отдельного списка у фабрики нет — это то, что говорят заметки шаблона в файлах канала.
        </p>
      </div>
      <ol className="m-0 grid list-none gap-2.5 p-0">
        {items.map((t, i) => (
          <li
            key={t.id}
            data-todo={t.id}
            className="grid grid-cols-[22px_minmax(0,1fr)] gap-2 border-t pt-2.5 first:border-t-0 first:pt-0"
          >
            <span className="mt-px grid size-[22px] place-items-center rounded-full border font-mono text-[11px] text-muted-foreground">
              {i + 1}
            </span>
            <div className="grid min-w-0 gap-0.5">
              <div className="font-semibold">{t.title}</div>
              <p className="m-0 text-muted-foreground">{t.text}</p>
              {t.more.length ? (
                <More className="mt-0.5">
                  {t.more.map((m, k) => (
                    <span key={k}>{m}</span>
                  ))}
                </More>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
