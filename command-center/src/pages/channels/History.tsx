// История правок канала и «вернуть»: коммиты, которые меняли его файлы; правку из центра
// можно отменить новым коммитом — только после подтверждения.
import { useHistory, useRevertCommit, type ChannelDetail, type HistoryEntry } from '@/api/channels';
import { useWrites } from '@/api/writes';
import { ConfirmAction } from '@/components/common/ConfirmAction';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { EmptyState, ErrorState } from '@/components/common/States';
import { WriteButton } from '@/components/common/WriteButton';

import { problemOf } from './problem';
import { Problems } from './Problems';
import { SkeletonList } from '@/components/common/Skeletons';

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(d);
}

function RevertButton({
  entry,
  detail,
  dirty,
  revert,
}: {
  entry: HistoryEntry;
  detail: ChannelDetail;
  dirty: boolean;
  revert: ReturnType<typeof useRevertCommit>;
}) {
  const writes = useWrites();
  const busy = revert.isPending;
  const mine = busy && revert.variables?.commit === entry.commit;
  const why = detail.lock.locked
    ? (detail.lock.message ?? 'Идёт батч канала: правка закрыта')
    : !entry.revertible
      ? entry.why_not
        ? entry.why_not.charAt(0).toUpperCase() + entry.why_not.slice(1)
        : 'Эту правку нельзя отменить из центра'
      : null;
  if (why || !writes.allowed) {
    return (
      <WriteButton size="sm" why={why}>
        Вернуть
      </WriteButton>
    );
  }
  return (
    <ConfirmAction
      trigger={
        <WriteButton size="sm" disabled={busy}>
          {mine ? 'Возвращаю…' : 'Вернуть'}
        </WriteButton>
      }
      title="Вернуть как было до этой правки?"
      description={
        <>
          Фабрика сделает новый коммит, который отменяет эту правку; сама правка останется в
          истории.
          {dirty ? ' Несохранённые правки в форме при этом пропадут.' : ''}
        </>
      }
      confirmLabel="Вернуть"
      onConfirm={() => revert.mutate({ commit: entry.commit, base: detail.revision })}
    />
  );
}

export function History({ detail, dirty }: { detail: ChannelDetail; dirty: boolean }) {
  const history = useHistory(detail.id);
  const revert = useRevertCommit(detail.id);

  if (history.isPending) return <SkeletonList rows={4} sub={1} label="Загружаю историю правок…" />;
  if (history.isError)
    return (
      <ErrorState
        title="Не удалось загрузить историю правок"
        error={history.error}
        onRetry={() => void history.refetch()}
      />
    );

  return (
    <div className="grid gap-3">
      {revert.isPending ? (
        <p role="status" className="m-0 text-muted-foreground">
          Возвращаю правку: фабрика заново проверяет конфиг и открытые батчи — это может занять
          несколько секунд.
        </p>
      ) : revert.isError ? (
        <Problems
          problem={problemOf(revert.error, 'Вернуть не получилось')}
          testId="revert-problem"
        />
      ) : revert.isSuccess ? (
        <Problems
          testId="revert-done"
          problem={{
            tone: 'ok',
            title: 'Возвращено',
            message: revert.data.subject.replace(/\s*\(из центра\)$/, ''),
            errors: [],
            details: [`коммит: ${revert.data.commit}`, ...revert.data.files],
          }}
        />
      ) : null}
      {history.data.entries.length === 0 ? (
        <EmptyState title="Правок пока нет">
          Файлы канала ещё ни разу не менялись коммитом.
        </EmptyState>
      ) : (
        <ol className="m-0 grid list-none gap-0 p-0" aria-label="История правок">
          {history.data.entries.map((e) => (
            <li
              key={e.commit}
              data-testid={`commit-${e.short}`}
              className="grid gap-1.5 border-t py-3 first:border-t-0 first:pt-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start sm:gap-4"
            >
              <div className="grid min-w-0 gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground">{when(e.at)}</span>
                  {e.from_center ? (
                    <StatusBadge tone="live" tip="Правка сделана из командного центра">
                      из центра
                    </StatusBadge>
                  ) : (
                    <StatusBadge
                      tone="idle"
                      tip="Коммит сделан в репозитории фабрики, не из центра"
                    >
                      в репозитории
                    </StatusBadge>
                  )}
                  {e.action === 'revert' ? (
                    <StatusBadge tone="warn" tip="Этот коммит отменил более раннюю правку">
                      возврат
                    </StatusBadge>
                  ) : null}
                  {e.reverted_by ? (
                    <StatusBadge tone="idle" tip="Эту правку уже отменили">
                      возвращено
                    </StatusBadge>
                  ) : null}
                </div>
                <div className="font-semibold [overflow-wrap:anywhere]">
                  {e.from_center
                    ? e.subject.replace(/\s*\(из центра\)$/, '')
                    : 'Правка в репозитории фабрики'}
                </div>
                <div className="text-xs text-muted-foreground">{e.author}</div>
                <More className="mt-0">
                  <span>коммит: {e.commit}</span>
                  {!e.from_center ? <span>{e.subject}</span> : null}
                  {e.reverts ? <span>отменяет: {e.reverts}</span> : null}
                  {e.reverted_by ? <span>отменён коммитом: {e.reverted_by}</span> : null}
                  <span>файлы: {e.files.join(', ')}</span>
                </More>
              </div>
              <div>
                <RevertButton entry={e} detail={detail} dirty={dirty} revert={revert} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
