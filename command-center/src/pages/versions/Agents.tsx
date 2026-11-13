// Агенты против пинов (`agents[]` `GET /api/versions`): у каждого — имя, что делает, пин и «на
// пине» / «расходится»; у расходящегося — почему словами и что сделать, строка тоном «внимание»
// (спокойно: ничего не сломано, батч просто его не возьмёт). Строка фабрики, коммиты, ветка и
// изменённые файлы — под «Подробнее» у строки; вывод проверки целиком — под «Подробнее» карточки.
import type { AgentState, Versions } from '@/api/versions';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';

import {
  AGENT,
  DOTTED,
  DRIFT_STYLE,
  TIP,
  agentName,
  agentsTitle,
  driftText,
  fixText,
  initials,
  rootLines,
  rootLineText,
} from './format';

const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 12) : '—');

function AgentRow({ a }: { a: AgentState }) {
  const drift = driftText(a);
  const role = AGENT[a.agent]?.role;
  return (
    <li
      data-testid="versions-agent"
      data-agent={a.agent}
      data-ok={a.ok ? '1' : '0'}
      className="grid gap-2 rounded-sm border border-l-[3px] px-3 py-2.5"
      style={a.ok ? undefined : DRIFT_STYLE}
    >
      <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3 sm:grid-cols-[auto_minmax(0,1fr)_auto]">
        <span
          aria-hidden
          className={cn(
            'grid size-[34px] place-items-center rounded-full border bg-muted font-display text-[13px]',
            a.ok
              ? 'border-[color-mix(in_srgb,var(--success)_45%,var(--border))]'
              : 'border-[color-mix(in_srgb,var(--warning)_55%,var(--border))]',
          )}
        >
          {initials(a.agent)}
        </span>
        <div className="min-w-0">
          <div className="font-semibold [overflow-wrap:anywhere]">{agentName(a.agent)}</div>
          {role ? <div className="text-xs text-muted-foreground">{role}</div> : null}
        </div>
        <div className="col-span-2 flex flex-wrap items-center gap-2 sm:col-span-1 sm:justify-end">
          <Tip wide content={TIP.pin}>
            <span
              tabIndex={0}
              className="text-xs text-muted-foreground"
              data-testid="versions-pin-tip"
            >
              <span className={DOTTED}>пин</span>{' '}
              <span className="font-mono text-foreground" data-testid="versions-agent-pin">
                {a.rev}
              </span>
            </span>
          </Tip>
          {a.ok ? (
            <StatusBadge
              tone="ok"
              tip="Код агента ровно тот, что закреплён в фабрике: батч его возьмёт"
            >
              на пине
            </StatusBadge>
          ) : (
            <StatusBadge
              tone="warn"
              tip="Код агента не тот, что закреплён в фабрике: пока он не вернётся на пин, батч на этой копии не запустится"
            >
              <span data-testid="versions-agent-drift">расходится</span>
            </StatusBadge>
          )}
        </div>
      </div>
      {drift ? (
        <div className="grid gap-0.5 text-[13px] sm:pl-[46px]">
          <span className="font-medium text-warning" data-testid="versions-agent-why">
            {drift}
          </span>
          <span className="text-muted-foreground">{fixText(a)}</span>
          <More className="mt-0.5">
            {a.why ? <span>{a.why}</span> : null}
            <span>
              {a.path} · пин {a.rev} → {short(a.sha)} · HEAD {short(a.head)}
              {a.branch ? ` (${a.branch})` : ' (detached)'}
            </span>
            {a.dirty?.length ? <span>изменены: {a.dirty.join(', ')}</span> : null}
            {a.line ? <span>{a.line}</span> : null}
          </More>
        </div>
      ) : null}
    </li>
  );
}

/** Карточка «Агенты фабрики». */
export function AgentsCard({ v }: { v: Versions }) {
  const off = v.agents.filter((a) => !a.ok).length;
  const title = v.lock.error ? 'Пины не прочитаны' : agentsTitle(off, v.agents.length);
  return (
    <Card aria-labelledby="versions-agents-title" data-testid="versions-agents">
      <CardHead eyebrow="Агенты фабрики" title={title} titleId="versions-agents-title" />
      {v.lock.error ? (
        <ErrorState title="Фабрика не прочитала пины агентов" error={v.lock.error}>
          Без файла пинов не видно, какие версии агентов закреплены. Батч на этой копии не
          запустится.
        </ErrorState>
      ) : v.agents.length === 0 ? (
        <EmptyState title="Агентов нет">Фабрика не закрепила ни одного агента.</EmptyState>
      ) : (
        <ul className="m-0 grid list-none gap-2 p-0" data-testid="versions-agent-list">
          {[...v.agents]
            .sort((a, b) => Number(a.ok) - Number(b.ok))
            .map((a) => (
              <AgentRow key={a.agent} a={a} />
            ))}
        </ul>
      )}
      <More label="Подробнее: вывод проверки">
        <span>
          {v.status.command} · код выхода {v.status.exit_code ?? '—'} · {v.lock.path}
        </span>
        {v.status.lines.map((l, i) => (
          <span key={i} className="whitespace-pre-wrap">
            {l.text}
          </span>
        ))}
        {v.status.stderr ? <span>{v.status.stderr}</span> : null}
        {v.status.error ? <span>{v.status.error}</span> : null}
      </More>
    </Card>
  );
}

/** Замечания проверки вне агентов: битые ссылки, несвязанные файлы; проверка не ответила. */
export function RootNotes({ v }: { v: Versions }) {
  const lines = rootLines(v);
  if (!lines.length && !v.status.error) return null;
  return (
    <Card
      aria-labelledby="versions-root-title"
      data-testid="versions-root"
      className="border-l-[3px]"
      style={DRIFT_STYLE}
    >
      <CardHead
        eyebrow="Проверка копии фабрики"
        title={v.status.error ? 'Проверка не ответила' : 'Ещё замечания проверки'}
        titleId="versions-root-title"
      />
      {v.status.error ? (
        <p className="m-0 text-[13px]">
          Сверка агентов с пинами не дошла до конца — строки выше взяты из файла пинов. Проверьте
          заново через минуту.
        </p>
      ) : null}
      {lines.length ? (
        <ul className="m-0 grid list-disc gap-1 pl-5 text-[13px]" data-testid="versions-root-lines">
          {lines.map((l, i) => (
            <li key={i}>{rootLineText(l)}</li>
          ))}
        </ul>
      ) : null}
      <More>
        {lines.map((l, i) => (
          <span key={i}>{l.text}</span>
        ))}
        {v.status.error ? <span>{v.status.error}</span> : null}
      </More>
    </Card>
  );
}
