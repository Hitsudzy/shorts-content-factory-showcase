// Тело задачи как markdown (CC-0124): дерево из `markdown.ts` → элементы React. Никакого
// `dangerouslySetInnerHTML`: что бы ни было в тексте, оно выводится как текст.
import { useMemo } from 'react';

import { CheckIcon } from '@/components/common/icons';
import { cn } from '@/lib/utils';

import { parseMarkdown, type Block, type Inline } from './markdown';
import { IdToken } from './parts';

function Inlines({ c }: { c: Inline[] }) {
  return (
    <>
      {c.map((x, i) => {
        switch (x.t) {
          case 'text':
            return <span key={i}>{x.v}</span>;
          case 'code':
            return (
              <code
                key={i}
                className="rounded-sm bg-[color-mix(in_srgb,var(--muted-foreground)_12%,transparent)] px-1 py-px font-mono text-[0.88em] [overflow-wrap:anywhere]"
              >
                {x.v}
              </code>
            );
          case 'strong':
            return (
              <strong key={i} className="font-semibold">
                <Inlines c={x.c} />
              </strong>
            );
          case 'em':
            return (
              <em key={i}>
                <Inlines c={x.c} />
              </em>
            );
          case 'link':
            return (
              <a
                key={i}
                href={x.href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary-text underline underline-offset-2 [overflow-wrap:anywhere]"
              >
                <Inlines c={x.c} />
              </a>
            );
          case 'task':
            return <IdToken key={i} id={x.id} range={x.range} />;
        }
      })}
    </>
  );
}

const HEADING = ['', 'text-[17px]', 'text-[15px]', 'text-sm', 'text-sm', 'text-sm', 'text-sm'];

function Check({ done }: { done: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        'mt-[3px] inline-flex size-4 shrink-0 items-center justify-center rounded-[4px] border',
        done ? 'border-success bg-success text-background' : 'border-muted-foreground/60',
      )}
    >
      {done ? <CheckIcon className="size-3" /> : null}
    </span>
  );
}

function BlockView({ b }: { b: Block }) {
  switch (b.t) {
    case 'heading': {
      const H = `h${Math.min(6, b.level + 1)}` as 'h2';
      return (
        <H className={cn('mt-2 font-semibold text-balance first:mt-0', HEADING[b.level])}>
          <Inlines c={b.c} />
        </H>
      );
    }
    case 'p':
      return (
        <p className="m-0 [overflow-wrap:anywhere]">
          <Inlines c={b.c} />
        </p>
      );
    case 'hr':
      return <hr className="border-border" />;
    case 'code':
      return (
        <pre className="m-0 rounded-sm border bg-background p-2.5 font-mono text-[12px] leading-[1.45] whitespace-pre-wrap [overflow-wrap:anywhere]">
          <code>{b.v}</code>
        </pre>
      );
    case 'quote':
      return (
        <blockquote className="m-0 border-l-[3px] pl-3 text-muted-foreground">
          <Inlines c={b.c} />
        </blockquote>
      );
    case 'table':
      return (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                {b.head.map((c, i) => (
                  <th key={i} className="border-b px-2 py-1 text-left font-semibold">
                    <Inlines c={c} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {b.rows.map((r, i) => (
                <tr key={i}>
                  {r.map((c, j) => (
                    <td key={j} className="border-b px-2 py-1 align-top">
                      <Inlines c={c} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case 'ul':
    case 'ol': {
      const checklist = b.items.some((it) => it.check !== null);
      const L = b.t === 'ol' && !checklist ? 'ol' : 'ul';
      return (
        <L
          start={L === 'ol' && b.start !== 1 ? b.start : undefined}
          className={cn(
            'm-0 grid gap-1',
            checklist ? 'list-none pl-0' : L === 'ol' ? 'list-decimal pl-5' : 'list-disc pl-5',
          )}
        >
          {b.items.map((it, i) => (
            <li
              key={i}
              data-check={it.check === null ? undefined : it.check ? 'done' : 'open'}
              style={it.depth ? { marginLeft: `${it.depth * 1.25}rem` } : undefined}
              className={cn(
                '[overflow-wrap:anywhere]',
                it.check !== null && 'flex items-start gap-2',
                it.check && 'text-muted-foreground',
              )}
            >
              {it.check !== null ? (
                <>
                  <Check done={it.check} />
                  <span className="sr-only">{it.check ? 'сделано: ' : 'не сделано: '}</span>
                </>
              ) : null}
              <span className="min-w-0">
                <Inlines c={it.c} />
              </span>
            </li>
          ))}
        </L>
      );
    }
  }
}

export function MarkdownView({ source, className }: { source: string; className?: string }) {
  const blocks = useMemo(() => parseMarkdown(source), [source]);
  return (
    <div
      data-testid="markdown"
      className={cn('grid gap-2.5 text-[13.5px] leading-[1.55]', className)}
    >
      {blocks.map((b, i) => (
        <BlockView key={i} b={b} />
      ))}
    </div>
  );
}
