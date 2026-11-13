// Живые блоки главной: что уже отдаёт API фабрики (`/api/health`, `/api/version`).
import type { ReactNode } from 'react';

import type { AgentPin, Version } from '@/api/client';
import { CONTRACT } from '@/api/contract.gen';
import { useHealth, useVersion } from '@/api/hooks';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { EmptyState, ErrorState } from '@/components/common/States';
import { cn } from '@/lib/utils';
import { SkeletonBadge, SkeletonList } from '@/components/common/Skeletons';
import { apiStartedText, STALE_TIP } from '@/pages/versions/apiProcessText';

const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 12) : '—');

function formatWhen(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(d);
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t py-[11px] first:border-t-0 first:pt-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </li>
  );
}

function ApiBadge() {
  const health = useHealth();
  if (health.isPending) return <SkeletonBadge width="5.5rem" label="проверяю" />;
  if (health.isError)
    return (
      <StatusBadge tone="danger" tip="API фабрики не ответил на проверку связи">
        нет связи
      </StatusBadge>
    );
  if (health.data.api !== CONTRACT.version)
    return (
      <StatusBadge
        tone="warn"
        tip="API отвечает по другой версии договора, чем собран центр. Номера — под «подробнее»"
      >
        другой договор
      </StatusBadge>
    );
  return (
    <StatusBadge tone="ok" tip="API фабрики отвечает и говорит на том же договоре, что и центр">
      на связи
    </StatusBadge>
  );
}

function TreeBadge({ dirty }: { dirty: boolean | null }) {
  if (dirty === null)
    return (
      <StatusBadge tone="idle" tip="Фабрика не смогла проверить рабочую копию">
        неизвестно
      </StatusBadge>
    );
  return dirty ? (
    <StatusBadge tone="warn" tip="В рабочей копии фабрики есть незакоммиченные правки">
      есть правки
    </StatusBadge>
  ) : (
    <StatusBadge tone="ok" tip="Рабочая копия фабрики совпадает с последним коммитом">
      чистая
    </StatusBadge>
  );
}

function FactoryBody({ v }: { v: Version }) {
  const health = useHealth();
  const built = formatWhen(v.center.built_at);
  const started = apiStartedText(v);
  return (
    <>
      <ul className="m-0 grid list-none p-0">
        <Row label="Связь с API">
          <ApiBadge />
        </Row>
        <Row label="Рабочая копия">
          <TreeBadge dirty={v.factory.dirty} />
        </Row>
        {v.stale ? (
          <Row label="Код API">
            <StatusBadge tone="warn" tip={STALE_TIP}>
              <span data-testid="factory-api-stale">старый код</span>
            </StatusBadge>
          </Row>
        ) : null}
        <Row label="Центр">
          <span className="font-mono text-[12.5px]">
            {v.center.version ? `версия ${v.center.version}` : 'версия не указана'}
          </span>
          {v.center.built ? null : (
            <StatusBadge tone="warn" className="ml-2" tip="Фабрика не нашла собранный центр">
              не собран
            </StatusBadge>
          )}
          {built ? (
            <span className="block text-xs text-muted-foreground">собран {built}</span>
          ) : null}
        </Row>
      </ul>
      <More>
        <span>коммит фабрики: {v.factory.commit ?? 'вне git'}</span>
        {started ? <span>{started}</span> : null}
        {v.stale_paths?.length ? <span>изменился код: {v.stale_paths.join(', ')}</span> : null}
        <span>
          договор API: центр {CONTRACT.version} · сервер {health.data?.api ?? v.api}
        </span>
        <span>sha256 договора: {short(CONTRACT.sha256)}</span>
        <span>раздача центра: {v.center.dist}</span>
        {v.center.built_at ? <span>собран: {v.center.built_at}</span> : null}
      </More>
    </>
  );
}

/** Карточка «Фабрика»: версия, связь, рабочая копия, сборка центра. */
export function FactoryCard() {
  const version = useVersion();
  const health = useHealth();
  const retry = () => {
    void health.refetch();
    void version.refetch();
  };

  let title: ReactNode = 'Фабрика';
  let body: ReactNode;
  if (version.isPending)
    body = <SkeletonList rows={3} sub={[0, 0, 1]} more label="Спрашиваю фабрику о версии…" />;
  else if (version.isError)
    body = (
      <ErrorState title="Нет связи с фабрикой" error={version.error} onRetry={retry}>
        Центр не получил версию фабрики. Проверьте, что API фабрики запущен, и повторите.
      </ErrorState>
    );
  else {
    title = version.data.factory.version
      ? `Версия ${version.data.factory.version}`
      : 'Версия не указана';
    body = <FactoryBody v={version.data} />;
  }

  return (
    <Card aria-labelledby="factory-title" data-testid="factory-card">
      <CardHead eyebrow="Фабрика" title={title} titleId="factory-title" />
      {body}
    </Card>
  );
}

function initials(name: string): string {
  const parts = name.split(/[-_\s]+/).filter(Boolean);
  const [a, b] = parts;
  return (a && b ? a.charAt(0) + b.charAt(0) : name.slice(0, 2)).toUpperCase();
}

function AgentRow({ a }: { a: AgentPin }) {
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-t py-[11px] first:border-t-0 first:pt-0">
      <span
        aria-hidden
        className={cn(
          'grid size-[34px] place-items-center rounded-full border font-display text-[13px]',
          a.ok
            ? 'border-[color-mix(in_srgb,var(--success)_45%,var(--border))] bg-muted'
            : 'border-[color-mix(in_srgb,var(--warning)_45%,var(--border))] bg-muted',
        )}
      >
        {initials(a.agent)}
      </span>
      <div className="min-w-0">
        <div className="truncate font-semibold">{a.agent}</div>
        <div className="truncate text-xs text-muted-foreground">
          {a.ok ? 'стоит на своём пине, готов к батчу' : 'не на пине — батч его не возьмёт'}
        </div>
      </div>
      {a.ok ? (
        <StatusBadge tone="ok" tip="Код агента ровно тот, что закреплён в фабрике">
          на пине
        </StatusBadge>
      ) : (
        <StatusBadge
          tone="warn"
          tip="Код агента не совпадает с закреплённым в фабрике — батч его не возьмёт. Причина — под «подробнее»"
        >
          не на пине
        </StatusBadge>
      )}
    </li>
  );
}

/** Карточка «Агенты»: пины агентов фабрики и готовность к батчу. */
export function AgentsCard({ className }: { className?: string }) {
  const version = useVersion();

  let title: ReactNode = 'Агенты фабрики';
  let body: ReactNode;
  if (version.isPending)
    body = <SkeletonList rows={5} avatar sub={1} more label="Загружаю пины агентов…" />;
  else if (version.isError)
    body = (
      <ErrorState title="Пины агентов не загрузились" error={version.error}>
        Нет ответа от API фабрики — см. карточку «Фабрика».
      </ErrorState>
    );
  else if (version.data.agents_error)
    body = (
      <ErrorState title="Фабрика не прочитала пины агентов" error={version.data.agents_error} />
    );
  else if (version.data.agents.length === 0)
    body = <EmptyState title="Агентов нет">Фабрика не закрепила ни одного агента.</EmptyState>;
  else {
    const agents = version.data.agents;
    const off = agents.filter((a) => !a.ok).length;
    title = off ? `${off} из ${agents.length} не на пине` : `Все ${agents.length} на своих пинах`;
    body = (
      <>
        <ul className="m-0 grid list-none p-0">
          {agents.map((a) => (
            <AgentRow key={a.agent} a={a} />
          ))}
        </ul>
        <More>
          {agents.map((a) => (
            <span key={a.agent}>
              {a.path} @ {a.rev} → {short(a.sha)} · HEAD {short(a.head)}
              {a.branch ? ` (${a.branch})` : ''}
              {a.why ? ` · ${a.why}` : ''}
            </span>
          ))}
        </More>
      </>
    );
  }

  return (
    <Card aria-labelledby="agents-title" className={className} data-testid="agents-card">
      <CardHead eyebrow="Агенты" title={title} titleId="agents-title" />
      {body}
    </Card>
  );
}
