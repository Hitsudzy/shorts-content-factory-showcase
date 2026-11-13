// Карточка задачи `/dev/<id>` (CC-0124): тело как markdown, чеклист галочками, сведения
// фронтматтера, связанные задачи (номера в тексте — ссылки) и история из git. Только чтение.
import type { ReactNode } from 'react';
import { Link, useLocation, useParams } from 'react-router';

import { isUnknownTask, useDevTask, type DevTask } from '@/api/dev';
import { Card, CardHead } from '@/components/common/Card';
import { SkeletonCard } from '@/components/common/Skeletons';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { StatusBadge } from '@/components/common/Status';

import { MarkdownView } from './MarkdownView';
import { Bar, IdText, TaskLink, TaskStatus, WithIds, type FromState } from './parts';
import { dayText, milestoneText, projectLabel, shortSha, statusWord, typeLabel } from './words';

function Back() {
  const from = (useLocation().state as FromState | null)?.from ?? '';
  return (
    <Link
      to={`/dev${from}`}
      data-testid="dev-back"
      className="w-max rounded-sm text-[13px] text-primary-text underline-offset-2 hover:underline"
    >
      ← К задачам
    </Link>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-2 border-t py-1.5 first:border-t-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function Facts({ t }: { t: DevTask }) {
  const milestoneLink = t.milestone
    ? `/dev?project=${t.project}&milestone=${encodeURIComponent(t.milestone)}`
    : null;
  return (
    <Card data-testid="task-facts">
      <CardHead eyebrow="Свойства" title="Сведения" />
      <dl className="m-0 text-[13px]">
        <Row label="Статус">
          <Tip content={statusWord(t.status).tip}>
            <span tabIndex={0} className="inline-flex rounded-full">
              <TaskStatus status={t.status} />
            </span>
          </Tip>
        </Row>
        <Row label="Проект">{projectLabel(t.project)}</Row>
        <Row label="Веха">
          {milestoneLink ? (
            <Link
              to={milestoneLink}
              className="text-primary-text underline-offset-2 hover:underline"
            >
              {t.milestone}
            </Link>
          ) : (
            'без вехи'
          )}
        </Row>
        <Row label="Тип">{typeLabel(t.type)}</Row>
        {t.repo ? <Row label="Репозиторий">{t.repo}</Row> : null}
        <Row label="Заведена">{dayText(t.created) ?? '—'}</Row>
        {t.closed ? <Row label="Закрыта">{dayText(t.closed)}</Row> : null}
        {t.dod ? <Row label="Готово, когда">{t.dod}</Row> : null}
        {t.blocked_by.length ? (
          <Row label="Ждёт">
            {t.blocked_by.map((b, i) => (
              <span key={b}>
                {i ? ', ' : ''}
                <TaskLink id={b} />
              </span>
            ))}
          </Row>
        ) : null}
        {Object.entries(t.extra).map(([k, v]) => (
          <Row key={k} label={k}>
            {typeof v === 'string' ? v : JSON.stringify(v)}
          </Row>
        ))}
        <Row label="Файл">
          <span className="font-mono text-xs">
            {t.path} · {t.branch}
          </span>
          {t.archived ? (
            <StatusBadge tone="idle" className="ml-2">
              архив {t.archive}
            </StatusBadge>
          ) : null}
        </Row>
      </dl>
    </Card>
  );
}

function Related({ t }: { t: DevTask }) {
  if (!t.related.length) return null;
  return (
    <Card data-testid="task-related">
      <CardHead eyebrow="Упомянуты в задаче" title="Связанные задачи" />
      <ul className="m-0 grid list-none gap-0 p-0 text-[13px]">
        {t.related.map((r) => (
          <li
            key={r.id}
            className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2.5 gap-y-1 border-t py-2 first:border-t-0"
          >
            <TaskLink id={r.id} />
            <span className="min-w-0 [overflow-wrap:anywhere]">
              {r.title ? (
                <IdText text={r.title} />
              ) : (
                <span className="text-muted-foreground">файла задачи нет</span>
              )}
            </span>
            {r.status ? (
              <span className="col-start-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <TaskStatus status={r.status} />
                {projectLabel(r.project)}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function History({ t }: { t: DevTask }) {
  return (
    <Card data-testid="task-history">
      <CardHead eyebrow="Коммиты с номером задачи" title="История из git" />
      {t.commits.length ? (
        <ol className="m-0 grid list-none gap-0 p-0 text-[13px]">
          {t.commits.map((c) => (
            <li
              key={`${c.project}-${c.sha}`}
              className="grid gap-0.5 border-t py-2 first:border-t-0"
            >
              <span className="min-w-0 [overflow-wrap:anywhere]">
                <WithIds text={c.subject} />
              </span>
              <span className="text-xs text-muted-foreground">
                {dayText(c.date)} · <span className="font-mono">{shortSha(c.sha)}</span>
                {c.project !== t.project ? ` · ${projectLabel(c.project).toLowerCase()}` : ''}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="m-0 text-[13px] text-muted-foreground">
          Коммитов с номером {t.id} нет — задача ещё не начата или коммиты названы иначе.
        </p>
      )}
    </Card>
  );
}

function Checklist({ t }: { t: DevTask }) {
  if (!t.items.length) return null;
  const done = t.items.filter((i) => i.done).length;
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]"
      data-testid="task-checklist"
    >
      <span>
        Чеклист: сделано {done} из {t.items.length}
      </span>
      <span className="w-40">
        <Bar
          done={done}
          total={t.items.length}
          label={`Чеклист: сделано ${done} из ${t.items.length}`}
        />
      </span>
    </div>
  );
}

function Loaded({ t }: { t: DevTask }) {
  return (
    <>
      <div className="grid gap-1.5">
        <div className="eyebrow">
          {projectLabel(t.project)} · {milestoneText(t.milestone)} ·{' '}
          <span className="font-mono normal-case">{t.id}</span>
        </div>
        <h1
          className="text-[22px] font-semibold text-balance [overflow-wrap:anywhere]"
          data-testid="task-title"
        >
          <IdText text={t.title ?? t.id} />
        </h1>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <TaskStatus status={t.status} />
          <span>{typeLabel(t.type)}</span>
          {t.created ? <span>заведена {dayText(t.created)}</span> : null}
          {t.closed ? <span>закрыта {dayText(t.closed)}</span> : null}
        </div>
        <p className="m-0 text-xs text-muted-foreground" data-testid="dev-readonly">
          Только просмотр: статусы задач меняет фабрика сама, центр их не правит.
        </p>
      </div>
      <div className="grid items-start gap-gap lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
        <Card data-testid="task-body" className="grid gap-3">
          <Checklist t={t} />
          {t.body.trim() ? (
            <MarkdownView source={t.body} />
          ) : (
            <p className="m-0 text-muted-foreground">В задаче нет текста — только фронтматтер.</p>
          )}
        </Card>
        <div className="grid gap-gap">
          <Facts t={t} />
          <Related t={t} />
          <History t={t} />
        </div>
      </div>
    </>
  );
}

export function TaskCard() {
  const id = useParams().id ?? '';
  const q = useDevTask(id);
  return (
    <>
      <Back />
      {q.isPending ? (
        <div className="grid items-start gap-gap lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
          <SkeletonCard rows={6} label="Читаю задачу из git…" data-testid="task-pending" />
          <SkeletonCard rows={4} />
        </div>
      ) : isUnknownTask(q.error) ? (
        <Card data-testid="task-unknown">
          <EmptyState title={<h1 className="m-0 text-[15px] font-semibold">Задачи {id} нет</h1>}>
            Такого номера нет ни у фабрики, ни у центра — может быть, опечатка в ссылке. Все задачи
            — в списке «Разработки».
          </EmptyState>
        </Card>
      ) : q.isError ? (
        <Card>
          <ErrorState title="Задачу не прочитать" error={q.error} onRetry={() => void q.refetch()}>
            API не ответил на задачу {id}. Проверьте, что API центра запущен.
          </ErrorState>
        </Card>
      ) : (
        <Loaded t={q.data} />
      )}
    </>
  );
}
