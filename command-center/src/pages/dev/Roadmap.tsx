// Дорожная карта «Разработки» (`/dev?view=roadmap`, CC-0124): ROADMAP.md фабрики и центра —
// вехи по порядку, их статус (сделана — с датой, текущая — первая не сделанная), спринты и задачи
// в порядке таблицы. Статус задачи — из списка задач; сделанные вехи свёрнуты.
import { useMemo } from 'react';

import {
  useDevRoadmap,
  useDevTasks,
  type DevMilestone,
  type DevRoadmap,
  type DevSprint,
  type DevTaskRow,
} from '@/api/dev';
import { Card, CardHead } from '@/components/common/Card';
import { SkeletonCard } from '@/components/common/Skeletons';
import { ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';

import { currentMilestone, progressOf } from './groups';
import { Bar, IdText, TaskLink, TaskStatus } from './parts';
import { useFilters } from './useFilters';
import { dayText, projectLabel, shortSha } from './words';

type Lookup = Map<string, DevTaskRow>;

function Tasks({ ids, rows }: { ids: string[]; rows: Lookup }) {
  if (!ids.length) return null;
  return (
    <ol className="m-0 grid list-none gap-0 p-0 text-[13px]">
      {ids.map((id) => {
        const t = rows.get(id);
        return (
          <li
            key={id}
            data-testid="roadmap-task"
            data-id={id}
            className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-x-2.5 gap-y-1 border-t py-1.5 first:border-t-0 sm:grid-cols-[5.5rem_minmax(0,1fr)_auto]"
          >
            <TaskLink id={id} />
            <span className="min-w-0 [overflow-wrap:anywhere]">
              {t?.title ? (
                <IdText text={t.title} />
              ) : (
                <span className="text-muted-foreground">файла задачи нет</span>
              )}
            </span>
            {t ? (
              <TaskStatus status={t.status} className="col-start-2 w-max sm:col-start-3" />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function chip(done: string | null | undefined, current: boolean) {
  if (done) return <StatusBadge tone="ok">сделана {dayText(done)}</StatusBadge>;
  if (current) return <StatusBadge tone="live">текущая</StatusBadge>;
  return <StatusBadge tone="idle">впереди</StatusBadge>;
}

function Count({ ids, rows }: { ids: string[]; rows: Lookup }) {
  const p = progressOf(ids.map((id) => rows.get(id)).filter((t): t is DevTaskRow => !!t));
  if (!ids.length) return null;
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span>
        сделано {p.done} из {p.total}
      </span>
      <span className="w-24">
        <Bar done={p.done} total={p.total} label={`Сделано ${p.done} из ${p.total}`} />
      </span>
    </span>
  );
}

function Sprint({ s, rows }: { s: DevSprint; rows: Lookup }) {
  return (
    <div className="grid gap-1.5 rounded-sm border px-3 py-2" data-testid="roadmap-sprint">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <span className="text-[13.5px] font-semibold">
          Спринт {s.version ? `${s.version} — ` : ''}
          {s.title}
        </span>
        {s.done ? <StatusBadge tone="ok">сделан {dayText(s.done)}</StatusBadge> : null}
        <Count ids={s.tasks} rows={rows} />
      </div>
      <Tasks ids={s.tasks} rows={rows} />
    </div>
  );
}

function Milestone({ m, current, rows }: { m: DevMilestone; current: boolean; rows: Lookup }) {
  const all = [...m.tasks, ...m.sprints.flatMap((s) => s.tasks)];
  return (
    <details
      open={!m.done}
      data-testid="roadmap-milestone"
      data-version={m.version ?? ''}
      data-current={current || undefined}
      className="group border-t pt-3 first:border-t-0 first:pt-0"
    >
      <summary className="grid cursor-pointer list-none gap-1.5 [&::-webkit-details-marker]:hidden">
        <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <span aria-hidden className="text-muted-foreground">
            <span className="group-open:hidden">▸</span>
            <span className="hidden group-open:inline">▾</span>
          </span>
          <span className="text-[15px] font-semibold">
            {m.version ? `Веха ${m.version} — ` : ''}
            {m.title}
          </span>
          {chip(m.done, current)}
        </span>
        <Count ids={all} rows={rows} />
      </summary>
      <div className="mt-2 grid gap-2 pl-5 max-sm:pl-0">
        <Tasks ids={m.tasks} rows={rows} />
        {m.sprints.map((s) => (
          <Sprint key={s.heading} s={s} rows={rows} />
        ))}
        {!all.length ? (
          <p className="m-0 text-[13px] text-muted-foreground">В таблице вехи задач нет.</p>
        ) : null}
      </div>
    </details>
  );
}

function ProjectRoadmap({ r, rows }: { r: DevRoadmap; rows: Lookup }) {
  const current = currentMilestone(r);
  return (
    <Card data-testid="roadmap" data-project={r.project}>
      <CardHead
        eyebrow={projectLabel(r.project)}
        title={`Дорожная карта: ${projectLabel(r.project).toLowerCase()}`}
      />
      {r.error ? (
        <p role="status" className="m-0 text-[13px] text-warning" data-testid="roadmap-error">
          Дорожную карту не прочитать: {r.error}
        </p>
      ) : r.milestones.length ? (
        <div className="grid gap-3">
          {r.milestones.map((m) => (
            <Milestone key={m.heading} m={m} current={m.version === current} rows={rows} />
          ))}
        </div>
      ) : (
        <p className="m-0 text-[13px] text-muted-foreground">В ROADMAP.md нет вех.</p>
      )}
      <p className="m-0 mt-3 text-xs text-muted-foreground" data-testid="roadmap-source">
        Прочитано из git: ROADMAP.md{r.branch ? ` · ${r.branch}` : ''}{' '}
        {r.sha ? <span className="font-mono">{shortSha(r.sha)}</span> : null}
      </p>
    </Card>
  );
}

export function Roadmap() {
  const [f] = useFilters();
  const q = useDevRoadmap();
  const tasks = useDevTasks('');
  const rows = useMemo<Lookup>(
    () => new Map((tasks.data?.tasks ?? []).map((t) => [t.id, t])),
    [tasks.data],
  );
  if (q.isPending)
    return (
      <div className="grid items-start gap-gap lg:grid-cols-2">
        <SkeletonCard rows={6} label="Читаю дорожные карты…" data-testid="roadmap-pending" />
        <SkeletonCard rows={6} />
      </div>
    );
  if (q.isError)
    return (
      <Card>
        <ErrorState
          title="Дорожные карты не прочитать"
          error={q.error}
          onRetry={() => void q.refetch()}
        >
          API не ответил на ROADMAP.md фабрики и центра.
        </ErrorState>
      </Card>
    );
  const shown = q.data.filter((r) => !f.project.length || f.project.includes(r.project));
  return (
    <div className="grid items-start gap-gap lg:grid-cols-2">
      {shown.map((r) => (
        <ProjectRoadmap key={r.project} r={r} rows={rows} />
      ))}
    </div>
  );
}
