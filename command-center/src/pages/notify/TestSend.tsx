// «Отправить пробное сообщение…» (CC-0115 шаг 3 → CC-0109 API, `POST /api/notify/test-send[/plan]`):
// то же, что `notify.py test --send`. План — какие каналы включены (по имени), какие из них
// унесут текст с этой машины, что сухой прогон фабрики сделал бы по каждому; ничего не уходит.
// «Да» вы набираете сами — тогда шина отправляет одно сообщение во все включённые каналы, и
// по каждому видно, дошло ли. Строки шины и ключ журнала — под «подробнее».
import { useState } from 'react';

import {
  planTestSend,
  testSend,
  testSendProblemText,
  useAfterTestSend,
  type NotifyTestSendPlan,
  type NotifyTestSendResult,
} from '@/api/notify';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Done, PlanHead, WriteAction } from '@/pages/publishing/Writes';

import { backendLabel, backendResult, previewText } from './format';

/** Что сухой прогон сделал бы с каналом: `would send` или `skipped: …`. */
const wouldText = (ok: boolean, external: boolean) =>
  ok ? (external ? 'отправит с машины' : 'отправит') : 'пропустит';

function TestPlanView({ plan }: { plan: NotifyTestSendPlan }) {
  const external = new Set(plan.channels.filter((c) => c.external).map((c) => c.name));
  const text = previewText(plan.text);
  return (
    <>
      <PlanHead plan={plan} yes="можно отправить" no="отправить нельзя" />
      <ul className="m-0 grid list-none gap-1 p-0" data-testid="test-plan-channels">
        {plan.would.map((w) => (
          <li
            key={w.via}
            className="flex flex-wrap items-center gap-2"
            data-testid="test-plan-channel"
            data-name={w.via}
          >
            <b className="font-semibold">{backendLabel(w.via)}</b>
            <StatusBadge
              tone={w.ok ? (external.has(w.via) ? 'warn' : 'ok') : 'idle'}
              tip={
                w.ok
                  ? external.has(w.via)
                    ? 'Текст уйдёт с этой машины во внешний сервис'
                    : 'Канал примет сообщение'
                  : 'Канал не настроен и сообщение пропустит'
              }
            >
              {wouldText(w.ok, external.has(w.via))}
            </StatusBadge>
          </li>
        ))}
      </ul>
      {plan.note ? (
        <p className="m-0 text-warning" data-testid="test-plan-note">
          {plan.note}
        </p>
      ) : null}
      <div className="grid gap-0.5">
        <span className="text-xs text-muted-foreground">Текст сообщения:</span>
        <span
          className="border-l-2 border-primary pl-3 whitespace-pre-wrap [overflow-wrap:anywhere]"
          data-testid="test-plan-text"
        >
          {text.lines.join('\n') || '—'}
          {text.link ? (
            <span className="block text-xs text-muted-foreground">и ссылку на центр</span>
          ) : null}
        </span>
      </div>
      <p className="m-0 text-xs text-muted-foreground">
        Сообщение уйдёт один раз и ляжет в журнал уведомлений как проверка.
      </p>
      <More className="mt-0">
        <span>
          {plan.action} · by {plan.by} · via {plan.via}
        </span>
        {plan.would.map((w) => (
          <span key={w.via}>
            {w.via}: {w.detail}
          </span>
        ))}
        {plan.channels
          .filter((c) => c.skip_reason)
          .map((c) => (
            <span key={c.name}>
              {c.name}: {c.skip_reason}
            </span>
          ))}
        {plan.delivery_reason ? <span>доставка: {plan.delivery_reason}</span> : null}
        <span>отпечаток плана {plan.fingerprint}</span>
      </More>
    </>
  );
}

function Sent({ r, onClose }: { r: NotifyTestSendResult; onClose: () => void }) {
  return (
    <Done
      tone={r.delivered ? 'ok' : 'warn'}
      testId="test-send-done"
      title={r.delivered ? 'Пробное сообщение отправлено' : 'Отправлено, но не дошло'}
      onClose={onClose}
    >
      <ul className="m-0 grid list-none gap-1 p-0" data-testid="test-send-results">
        {r.results.map((x) => {
          const res = backendResult(x.detail);
          return (
            <li key={x.via} className="flex flex-wrap items-center gap-2" data-name={x.via}>
              <b className="font-semibold">{backendLabel(x.via)}</b>
              <StatusBadge tone={res.tone} tip={x.detail}>
                {res.label}
              </StatusBadge>
            </li>
          );
        })}
      </ul>
      <More className="mt-0">
        <span>ключ журнала: {r.key}</span>
        {r.delivery_reason ? <span>доставка: {r.delivery_reason}</span> : null}
        {r.results.map((x) => (
          <span key={x.via}>
            {x.via}: {x.detail}
          </span>
        ))}
      </More>
    </Done>
  );
}

export function TestSend() {
  const [done, setDone] = useState<NotifyTestSendResult | null>(null);
  const after = useAfterTestSend();
  return (
    <div className="grid gap-2" data-testid="test-send">
      {done ? <Sent r={done} onClose={() => setDone(null)} /> : null}
      <div>
        <WriteAction
          id="test-send"
          label="Отправить пробное сообщение…"
          title="Отправить пробное сообщение?"
          description="Фабрика проверила, какие каналы его получат. Пока ничего не отправлено."
          body={{}}
          tip="Проверка по-настоящему: сообщение уйдёт во все включённые каналы; фабрика сначала покажет план"
          confirmLabel="Отправить"
          pendingLabel="Отправляю…"
          triggerVariant="outline"
          yes
          plan={() => planTestSend()}
          act={(c) => testSend(c)}
          view={(p) => <TestPlanView plan={p} />}
          problemText={testSendProblemText}
          onSettled={after}
          onDone={setDone}
        />
      </div>
    </div>
  );
}
