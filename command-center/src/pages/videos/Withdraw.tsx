// «Снять окончательно…» у открытого ролика (CC-0115 шаг 3 → CC-0107 API,
// `…/videos/{slug}/withdraw[/plan]`): ролик больше не пойдёт никуда, его тема закончена — пул
// отпустит исходники темы, и месячный архив их уберёт. План фабрики ничего не пишет: что записи
// говорят о ролике сейчас и после, что снятие отпустит и что ещё держат. «Да» — ваш ответ:
// по-русски, своими словами, с именем ролика (так фабрика записывает снятие только под
// названным роликом); центр ответ не подставляет. Исходники пула и ключ записи — под «подробнее».
import { useState } from 'react';

import type { Video } from '@/api/videos';
import {
  planWithdraw,
  topicStatusText,
  useAfterWithdraw,
  withdraw,
  withdrawAnswerHint,
  withdrawAnswerOk,
  withdrawProblemText,
  type WithdrawPlan,
  type WithdrawResult,
} from '@/api/withdraw';
import { More } from '@/components/common/More';
import { sizeText } from '@/pages/batches/going';
import { plural } from '@/pages/batches/format';
import { Done, PlanHead, WriteAction } from '@/pages/publishing/Writes';

const sources = (n: number) => `${n} ${plural(n, 'исходник', 'исходника', 'исходников')}`;
const freed = (n: number) => plural(n, 'освободится', 'освободятся', 'освободятся');

function WithdrawPlanView({ plan, title }: { plan: WithdrawPlan; title: string }) {
  return (
    <>
      <PlanHead plan={plan} yes="можно снять" no="снять нельзя" />
      <p className="m-0" data-testid="withdraw-plan-video">
        Ролик: {title}
      </p>
      {plan.status || plan.status_after ? (
        <p className="m-0" data-testid="withdraw-plan-status">
          Сейчас записи говорят: {topicStatusText(plan.status)}
          {plan.ok ? ` → после снятия: ${topicStatusText(plan.status_after)}` : ''}
        </p>
      ) : null}
      {plan.ok ? (
        <p className="m-0" data-testid="withdraw-plan-frees">
          {plan.frees.length
            ? `После снятия ${freed(plan.frees.length)} ${sources(plan.frees.length)} темы (${sizeText(plan.frees_bytes)}).`
            : 'Ни один исходник темы не освободится: их ещё держат.'}
          {plan.kept.length ? ` Ещё держат: ${sources(plan.kept.length)}.` : ''}
        </p>
      ) : null}
      {plan.open_batches.length ? (
        <p className="m-0 text-muted-foreground" data-testid="withdraw-plan-open">
          Идут батчи ({plan.open_batches.length}) — исходники, которые они держат, останутся.
        </p>
      ) : null}
      <p className="m-0 text-xs text-muted-foreground" data-testid="withdraw-plan-line">
        Сейчас с диска ничего не уходит: исходники уберёт месячный архив, когда тема закончена.
      </p>
      <More className="mt-0">
        <span>{plan.line}</span>
        <span>
          {plan.action} · {plan.entry_id} · by {plan.by} · via {plan.via}
        </span>
        {plan.topic_id ? <span>тема: {plan.topic_id}</span> : null}
        {plan.frees.map((f) => (
          <span key={f.video_id}>
            отпустит: {f.video_id} ({f.files.length} файлов, {sizeText(f.bytes)})
          </span>
        ))}
        {plan.kept.map((k) => (
          <span key={k.video_id}>
            держит: {k.video_id} — {k.blocked_by.join(', ') || '—'}
          </span>
        ))}
        {plan.open_batches.map((b) => (
          <span key={b}>идёт: {b}</span>
        ))}
        <span>журнал: {plan.journal}</span>
        <span>отпечаток плана {plan.fingerprint}</span>
      </More>
    </>
  );
}

export function Withdraw({ batch, video, title }: { batch: string; video: Video; title: string }) {
  const [done, setDone] = useState<WithdrawResult | null>(null);
  const after = useAfterWithdraw();
  const slug = video.slug;
  return (
    <div className="grid gap-2" data-testid="withdraw">
      {done ? (
        <Done
          tone="ok"
          testId="withdraw-done"
          title="Ролик снят окончательно"
          onClose={() => setDone(null)}
        >
          <span>
            {done.frees.length
              ? `Освобождено: ${sources(done.frees.length)} — их уберёт месячный архив.`
              : 'Исходники темы пока держат другие ролики или батчи.'}
          </span>
          <More className="mt-0">
            <span>{done.entry_id}</span>
            <span>журнал: {done.journal}</span>
          </More>
        </Done>
      ) : (
        <div>
          <WriteAction
            id="withdraw"
            label="Снять окончательно…"
            title="Снять ролик окончательно?"
            description="Фабрика проверила, что изменится после снятия. С диска сейчас ничего не уходит."
            body={{}}
            tip="Ролик больше не пойдёт в публикацию, исходники его темы освободятся; фабрика сначала покажет план"
            confirmLabel="Снять окончательно"
            pendingLabel="Снимаю…"
            danger
            triggerVariant="outline"
            yes={{
              label: (
                <>
                  Напишите сами, по-русски, что снимаете ролик, и назовите его так:{' '}
                  <b className="font-mono font-semibold" data-testid="withdraw-name">
                    {slug}
                  </b>
                </>
              ),
              ok: (v) => withdrawAnswerOk(v, slug),
              hint: (v) => withdrawAnswerHint(v, slug),
            }}
            plan={() => planWithdraw(batch, slug)}
            act={(c, typed) => withdraw(batch, slug, c, typed)}
            view={(p) => <WithdrawPlanView plan={p} title={title} />}
            problemText={withdrawProblemText}
            onSettled={after}
            onDone={setDone}
          />
        </div>
      )}
    </div>
  );
}
