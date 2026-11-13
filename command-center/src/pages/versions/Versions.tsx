// «Версии и агенты» (CC-0031, API — CC-0030 / CC-0119, договор 0.58.0) — только чтение: какой
// выпуск фабрики стоит, какой центр, что готовится (ветки выпусков с рабочей копией), агенты
// против пинов — расхождения словами, спокойно, и что сделать. Проверка у фабрики небыстрая
// (git по всем агентам), поэтому ответ сохранён на `ttl_s`; «Проверить заново» — свежая проверка.
import { useVersions, useRecheck, type Versions as V } from '@/api/versions';
import { Card } from '@/components/common/Card';
import { CopyButton } from '@/components/common/CopyButton';
import { More } from '@/components/common/More';
import {
  Pending,
  SkeletonCard,
  SkeletonList,
  SkeletonRows,
  SkeletonText,
} from '@/components/common/Skeletons';
import { ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { whenText } from '@/pages/notify/format';

import { AgentsCard, RootNotes } from './Agents';
import { ApiProcess } from './ApiProcess';
import { CenterCard, FactoryCard, InWorkCard } from './Cards';
import { agentName, DRIFT_STYLE, rootLines, SYNC_COMMAND, syncFixes } from './format';

function Checked({ v }: { v: V | undefined }) {
  const recheck = useRecheck();
  const at = v ? whenText(v.checked_at) : null;
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="versions-checked">
      {v ? (
        <Tip
          wide
          content={`Проверка обходит всех агентов — это несколько секунд, поэтому фабрика держит ответ ${Math.round(v.ttl_s)} с. «Проверить заново» — свежая проверка.`}
        >
          <span tabIndex={0} className="text-xs text-muted-foreground">
            проверено {at ? `${at} МСК` : '—'}
            {v.cached ? ' · сохранённый ответ' : ''}
          </span>
        </Tip>
      ) : null}
      <Button
        size="sm"
        data-testid="versions-recheck"
        disabled={recheck.isPending || !v}
        onClick={() => recheck.mutate()}
      >
        {recheck.isPending ? 'Проверяю…' : 'Проверить заново'}
      </Button>
      {recheck.isError ? (
        <span role="alert" className="text-xs text-danger" data-testid="versions-recheck-error">
          Не проверилось — фабрика не ответила
        </span>
      ) : null}
    </div>
  );
}

/** Полоса сверху: всё ли на пинах — одной фразой. Расхождение — тоном «внимание», без тревоги. */
function Summary({ v }: { v: V }) {
  if (v.lock.error) return null;
  const off = v.agents.filter((a) => !a.ok).length;
  const notes = rootLines(v).length;
  const synced = v.agents.filter(syncFixes);
  if (!off && !notes)
    return (
      <div
        className="flex flex-wrap items-center gap-2 rounded-lg border px-4 py-3 text-[13px]"
        data-testid="versions-summary"
        data-drift="0"
      >
        <span aria-hidden className="size-[7px] rounded-full bg-success" />
        <b className="font-semibold">Всё на своих пинах</b>
        <span className="text-muted-foreground">
          агенты стоят ровно на закреплённых версиях — батч на этой копии может идти
        </span>
      </div>
    );
  return (
    <div
      role="status"
      className="grid gap-2 rounded-lg border border-l-[3px] px-4 py-3 text-[13px]"
      style={DRIFT_STYLE}
      data-testid="versions-summary"
      data-drift="1"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span aria-hidden className="size-[7px] rounded-full bg-warning" />
        <b className="font-semibold">
          {!off
            ? 'Проверка нашла расхождение с пинами'
            : off === 1
              ? 'Агент расходится с пином'
              : 'Агенты расходятся с пинами'}
        </b>
        <span className="text-muted-foreground">
          {off
            ? `Пока ${off === 1 ? 'он не вернётся' : 'они не вернутся'} на пин, батч на этой копии фабрики не запустится. Что сделать — в строке каждого агента ниже.`
            : 'Пока его не поправить, батч на этой копии фабрики не запустится. Что именно — ниже.'}
        </span>
      </div>
      {synced.length ? (
        <>
          <div className="flex flex-wrap items-center gap-2" data-testid="versions-sync">
            <span>
              Синхронизация агентов в терминале, в папке фабрики, вернёт на пин:{' '}
              {synced.map((a) => agentName(a.agent)).join(', ')}.
            </span>
            <CopyButton
              value={SYNC_COMMAND}
              what="команда синхронизации"
              tip="Скопировать команду в буфер — вставьте её в терминал в папке фабрики"
              data-testid="versions-sync-copy"
            />
          </div>
          <More className="mt-0" label="Подробнее: команда">
            <code>{SYNC_COMMAND}</code>
          </More>
        </>
      ) : null}
    </div>
  );
}

/** Скелетон той же формы: полоса, три карточки сверху, список агентов. */
function Skeleton() {
  return (
    <Pending
      label="Спрашиваю фабрику о версиях…"
      className="gap-gap"
      data-testid="versions-pending"
    >
      <SkeletonText bare lines={1} className="rounded-lg border px-4 py-3" />
      <div className="grid items-start gap-gap lg:grid-cols-3">
        <SkeletonCard bare rows={0}>
          <SkeletonText bare lines={2} lineHeight={30} widths={[34, 70]} />
          <SkeletonList bare rows={3} badge className="mt-2" />
        </SkeletonCard>
        <SkeletonCard bare rows={0}>
          <SkeletonText bare lines={2} lineHeight={30} widths={[30, 60]} />
          <SkeletonList bare rows={2} badge className="mt-2" />
        </SkeletonCard>
        <SkeletonCard bare rows={3} more />
      </div>
      <SkeletonCard bare rows={0} more>
        <SkeletonRows bare rows={5} height={58} gap={8} />
      </SkeletonCard>
    </Pending>
  );
}

export function Versions() {
  const q = useVersions();
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">Фабрика, агенты и центр: что стоит и что готовится</div>
          <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
            Версии и агенты
          </h1>
        </div>
        <Checked v={q.data} />
      </div>
      {q.isPending ? (
        <Skeleton />
      ) : q.isError ? (
        <Card>
          <ErrorState title="Версии не прочитать" error={q.error} onRetry={() => void q.refetch()}>
            Фабрика не ответила на проверку версий. Проверьте, что API фабрики запущен.
          </ErrorState>
        </Card>
      ) : (
        <>
          <Summary v={q.data} />
          <ApiProcess />
          <div className="grid items-start gap-gap lg:grid-cols-3">
            <FactoryCard v={q.data} />
            <CenterCard v={q.data} />
            <InWorkCard v={q.data} />
          </div>
          <RootNotes v={q.data} />
          <AgentsCard v={q.data} />
        </>
      )}
    </>
  );
}
