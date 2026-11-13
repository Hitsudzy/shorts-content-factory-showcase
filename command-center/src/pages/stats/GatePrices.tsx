// «Цена воротец» на «Статистике» (CC-0115 → CC-0100, `GET /api/gate-prices`): для каждого правила
// воротец — сколько готовых роликов окна (последние N батчей фабрики) оно убило бы отказом,
// вердикт (отказ / предупреждение / штраф к оценке), подпись цены и решение пользователя; цены,
// ждущие подписи, и решения без замера. Подпись цены и решение — записи plan → «да» (./GateWrites).
// Имена правил, строки фабрики, слаги убитых роликов — под «подробнее».
import { useGatePrices, type GatePriceResult, type GatePrices as Prices } from '@/api/gatePrices';
import { BatchError } from '@/api/batchProblem';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { SkeletonRows } from '@/components/common/Skeletons';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { dateTimeMsk, plural } from '@/pages/batches/format';

import { GateWrites } from './GateWrites';
import {
  basisText,
  decisionText,
  NOW_MODE,
  priceText,
  ruleText,
  SIGNED_TIP,
  signatureText,
  VERDICT,
} from './gateWords';

function RuleRow({
  r,
  proposed,
  base,
}: {
  r: GatePriceResult;
  proposed: boolean;
  base: string | null;
}) {
  const v = VERDICT[r.verdict];
  const sig = signatureText(r.signature);
  const dec = decisionText(r.decision);
  const killed = r.batches.flatMap((b) =>
    b.killed.map((k) => `${b.batch ?? '?'}: ${k.slug ?? k.item}`),
  );
  return (
    <li
      data-testid="gate-rule"
      data-rule={r.rule}
      className="grid gap-1 border-t py-3 first:border-t-0"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 font-semibold">{ruleText(r.rule)}</span>
        <span className="flex flex-wrap gap-1.5">
          {proposed ? (
            <StatusBadge
              tone="warn"
              tip="Фабрика предлагает подписать эту цену — до подписи правило только предупреждает."
            >
              ждёт подписи
            </StatusBadge>
          ) : null}
          <StatusBadge tone={v.tone} tip={v.tip}>
            {v.label}
          </StatusBadge>
        </span>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
        {r.price == null ? (
          <Tip content="Ни один батч окна не мог показать, что отказ по правилу убил бы, — это не цена ноль.">
            <span
              tabIndex={0}
              data-testid="gate-price"
              className="font-semibold underline decoration-dotted underline-offset-4"
            >
              Цена {priceText(r)}
            </span>
          </Tip>
        ) : (
          <span data-testid="gate-price" className="font-semibold">
            Отказ {priceText(r)}
          </span>
        )}
        <span className="text-muted-foreground">{basisText(r)}</span>
      </div>
      {sig || dec || r.mode ? (
        <div
          className="flex flex-wrap gap-x-3 text-xs text-muted-foreground"
          data-testid="gate-signed"
        >
          {sig ? (
            <Tip content={SIGNED_TIP}>
              <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
                {sig}
              </span>
            </Tip>
          ) : null}
          {dec ? <span>{dec}</span> : null}
          {r.mode ? <span>{NOW_MODE[r.mode] ?? 'сейчас у фабрики свой режим'}</span> : null}
        </div>
      ) : null}
      <GateWrites r={r} base={base} />
      <More className="mt-0.5">
        <span>правило: {r.rule}</span>
        <span>фабрика: {r.why}</span>
        {r.note ? <span>о правиле: {r.note}</span> : null}
        {killed.length ? <span>убил бы: {killed.join(', ')}</span> : null}
        {r.signature?.note ? <span>подпись: {String(r.signature.note)}</span> : null}
        {r.decision?.note ? <span>решение: {String(r.decision.note)}</span> : null}
      </More>
    </li>
  );
}

function Unregistered({ d }: { d: Prices }) {
  if (!d.unregistered.length) return null;
  return (
    <section className="mt-3 grid gap-1.5" data-testid="gate-unregistered">
      <h3 className="m-0 text-[13px] font-semibold">
        <Tip content="По этим правилам вы уже решили, как им работать, но в последних батчах не на чем проверить, сколько роликов они бы убили.">
          <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
            Ваши решения, которые сейчас не пересчитать
          </span>
        </Tip>
      </h3>
      <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
        {d.unregistered.map((u) => (
          <li key={u.rule} data-rule={u.rule} className="flex flex-wrap gap-x-2">
            <span>{ruleText(u.rule)}</span>
            <span className="text-muted-foreground">{decisionText(u.decision)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function GatePrices() {
  const q = useGatePrices();
  const d = q.data;
  const proposed = new Set(d?.proposals.map((p) => p.rule));
  const eyebrow = d
    ? `Воротца · окно — последние ${d.window} ${plural(d.window, 'батч', 'батча', 'батчей')}${
        d.proposals.length ? ` · ждут подписи: ${d.proposals.length}` : ''
      }`
    : 'Воротца';
  return (
    <Card aria-labelledby="gate-prices-title" data-testid="gate-prices">
      <CardHead eyebrow={eyebrow} title="Цена отказа по правилам" titleId="gate-prices-title" />
      {q.isPending ? (
        <SkeletonRows rows={5} height={88} gap={1} bordered={false} label="Считаю цену воротец…" />
      ) : q.isError ? (
        <ErrorState
          title="Цену воротец не посчитать"
          error={q.error}
          onRetry={() => void q.refetch()}
        >
          {q.error instanceof BatchError && q.error.problem
            ? q.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : !q.data.results.length ? (
        <EmptyState title="Правил воротец нет">Фабрика не назвала ни одного правила.</EmptyState>
      ) : (
        <>
          <p className="m-0 mb-1 text-[13px] text-muted-foreground">
            Сколько готовых роликов последних батчей не дошли бы до вас, если бы правило отказывало.
          </p>
          <ul className="m-0 list-none p-0">
            {q.data.results.map((r) => (
              <RuleRow
                key={r.rule}
                r={r}
                proposed={proposed.has(r.rule)}
                base={q.data.ledger_sha256 ?? null}
              />
            ))}
          </ul>
          <Unregistered d={q.data} />
          {q.data.proposals.length ? null : (
            <p
              className="m-0 mt-3 text-[13px] text-muted-foreground"
              data-testid="gate-no-proposals"
            >
              Цен, ждущих вашей подписи, нет.
            </p>
          )}
          <More>
            <span>
              посчитано: {dateTimeMsk(q.data.computed_at)}
              {q.data.cached ? ' (окно и журнал цен не менялись)' : ''}
            </span>
            <span>
              журнал цен: {q.data.ledger}
              {q.data.ledger_exists ? '' : ' (нет файла)'}
            </span>
            <span>окно по умолчанию: {q.data.window_default}</span>
            {q.data.proposals.map((p) => (
              <span key={p.rule}>предложение: {p.line}</span>
            ))}
            <span>подпись из центра: {q.data.signing.what}</span>
          </More>
        </>
      )}
    </Card>
  );
}
