// «Просьбы» в табе «Вопросы» (CC-0019): ваши просьбы оператору (`GET /api/requests`). Сверху —
// с пришедшим ответом (закрыть), под ними — ждут оператора (открыты или взяты; отменить),
// ниже — история закрытых и отменённых (`?status=all`, новые сверху, по 10). Номера и контекст
// в JSON — только под «подробнее».
import { useState } from 'react';

import { useRequests } from '@/api/requests';
import { AskButton } from '@/components/ask/AskDialog';
import { Card, CardHead } from '@/components/common/Card';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/button';

import { RequestCard, RequestHistoryItem } from './RequestCard';
import { answeredOrder, pendingOrder, requestHistoryOrder } from './requestsFormat';
import { SkeletonRows } from '@/components/common/Skeletons';

const HISTORY_PAGE = 10;

/** Пока список читается — скелетон карточек просьб (CC-0121); `children` — для читалки. */
function Loading({ children, height = 88 }: { children: string; height?: number }) {
  return <SkeletonRows rows={3} height={height} gap={10} label={children} />;
}

function RequestsHistory() {
  const q = useRequests('all');
  const [shown, setShown] = useState(HISTORY_PAGE);
  const list = (q.data?.requests ?? [])
    .filter((r) => r.status === 'closed' || r.status === 'cancelled')
    .sort(requestHistoryOrder);
  return (
    <Card aria-labelledby="requests-history-title" data-testid="requests-history">
      <CardHead
        eyebrow={q.data ? `История · просьб: ${list.length}` : 'История'}
        title="Закрытые и отменённые"
        titleId="requests-history-title"
      />
      {q.isPending ? (
        <Loading>Читаю историю…</Loading>
      ) : q.isError ? (
        <ErrorState title="Историю не прочитать" error={q.error} onRetry={() => void q.refetch()}>
          Проверьте, что API фабрики запущен.
        </ErrorState>
      ) : !list.length ? (
        <EmptyState title="Закрытых просьб пока нет">
          Здесь соберутся просьбы, которые вы закрыли после ответа или отменили.
        </EmptyState>
      ) : (
        <>
          <ul className="m-0 grid list-none p-0">
            {list.slice(0, shown).map((r) => (
              <RequestHistoryItem key={r.id} r={r} />
            ))}
          </ul>
          {list.length > shown ? (
            <div className="mt-2">
              <Button
                size="sm"
                data-testid="requests-history-more"
                onClick={() => setShown((n) => n + HISTORY_PAGE)}
              >
                Показать ещё {Math.min(HISTORY_PAGE, list.length - shown)}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

export function Requests() {
  const live = useRequests('live');
  const all = live.data?.requests ?? [];
  const answered = all.filter((r) => r.status === 'answered').sort(answeredOrder);
  const pending = all.filter((r) => r.status === 'open' || r.status === 'taken').sort(pendingOrder);
  return (
    <>
      <Card aria-labelledby="requests-summary-title" data-testid="requests-summary">
        <CardHead
          eyebrow="Просьбы оператору"
          titleId="requests-summary-title"
          title={
            live.data
              ? answered.length
                ? `Пришёл ответ: ${answered.length}`
                : pending.length
                  ? `Ждут оператора: ${pending.length}`
                  : 'Незакрытых просьб нет'
              : 'Читаю очередь…'
          }
          actions={
            <AskButton
              testId="ask-new"
              label="Новая просьба"
              tip="Свободная просьба оператору"
              target={{}}
            />
          }
        />
        <p className="m-0 text-muted-foreground">
          Просьбу берёт сессия-оператор — центр сам ничего не исполняет. Ответ приходит сюда и в
          Telegram; прочитали — закройте просьбу.
        </p>
      </Card>

      {live.isPending ? (
        <Loading height={120}>Читаю просьбы…</Loading>
      ) : live.isError ? (
        <ErrorState
          title="Просьбы не прочитать"
          error={live.error}
          onRetry={() => void live.refetch()}
        >
          Проверьте, что API фабрики запущен.
        </ErrorState>
      ) : !all.length ? (
        <EmptyState title="Просьб к оператору нет">
          Нажмите «Попросить оператора» в шапке или на ролике, батче, канале — просьба появится
          здесь.
        </EmptyState>
      ) : (
        <>
          {answered.length ? (
            <div className="grid gap-2.5" data-testid="answered-requests">
              <h2 className="eyebrow">Пришёл ответ · {answered.length}</h2>
              <div className="grid gap-gap md:grid-cols-2">
                {answered.map((r) => (
                  <RequestCard key={r.id} r={r} />
                ))}
              </div>
            </div>
          ) : null}
          {pending.length ? (
            <div className="grid gap-2.5" data-testid="pending-requests">
              <h2 className="eyebrow">Ждут оператора · {pending.length}</h2>
              <div className="grid gap-gap md:grid-cols-2">
                {pending.map((r) => (
                  <RequestCard key={r.id} r={r} />
                ))}
              </div>
            </div>
          ) : null}
        </>
      )}

      <RequestsHistory />
    </>
  );
}
