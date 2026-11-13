// Вкладка «Данные канала» на странице канала (CC-0115 → CC-0101/0102): концовка канала, источники
// фактов, партнёрские ссылки, происхождение футажа и список правообладателей (только чтение).
// Правка списков и сборка концовки — записи plan → «да» (./ChannelListWrites, CC-0115 шаг 3).
// Пути, id изданий и программ, строки фабрики — под «подробнее».
import type { ReactNode } from 'react';

import { BatchError } from '@/api/batchProblem';
import {
  useFootageOrigin,
  useRightsHolders,
  type ChannelFootageOrigin,
  type ChannelRightsHolders,
} from '@/api/rights';
import {
  useAffiliate,
  useEnding,
  useFactSources,
  type ChannelAffiliate,
  type ChannelEnding,
  type ChannelFactSources,
} from '@/api/channelData';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { SkeletonText } from '@/components/common/Skeletons';
import { ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { WarnLine } from '@/components/common/WarnLine';
import { dateTimeMsk } from '@/pages/batches/format';

import {
  affiliateView,
  endingCommitRefused,
  endingState,
  errorsText,
  probeText,
  renderText,
  sourcesView,
  tierLabel,
} from './channelDataWords';
import { EndingRender, ListEdit } from './ChannelListWrites';

type Q<T> = {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
};

function Loaded<T>({
  q,
  failed,
  lines,
  children,
}: {
  q: Q<T>;
  failed: string;
  lines: number;
  children: (d: T) => ReactNode;
}) {
  if (q.isPending) return <SkeletonText lines={lines} label="Читаю данные канала…" />;
  if (q.isError || q.data === undefined)
    return (
      <ErrorState title={failed} error={q.error} onRetry={() => void q.refetch()}>
        {q.error instanceof BatchError && q.error.problem
          ? q.error.problem.message
          : 'Проверьте, что API фабрики запущен.'}
      </ErrorState>
    );
  return <>{children(q.data)}</>;
}

function Chips({
  items,
  testId,
}: {
  items: { key: string; text: string; tip?: string | null }[];
  testId: string;
}) {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0" data-testid={testId}>
      {items.map((i) => (
        <li key={i.key} className="rounded-sm border px-1.5 py-0.5 text-xs">
          {i.tip ? (
            <Tip content={i.tip}>
              <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
                {i.text}
              </span>
            </Tip>
          ) : (
            i.text
          )}
        </li>
      ))}
    </ul>
  );
}

function Errors({ errors }: { errors: string[] }) {
  if (!errors.length) return null;
  return (
    <p role="alert" data-testid="list-errors" className="m-0 text-[13px] font-semibold text-danger">
      {errorsText(errors.length)} — что именно, под «подробнее».
    </p>
  );
}

function Ending({ e }: { e: ChannelEnding }) {
  const st = endingState(e);
  const probe = probeText(e);
  const refused = endingCommitRefused(e);
  return (
    <div className="grid min-w-0 gap-2 text-[13px]" data-testid="ending">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge tone={st.tone}>{st.label}</StatusBadge>
        <span>{st.text}</span>
      </div>
      {probe ? (
        <div className="font-mono text-xs" data-testid="ending-probe">
          {probe}
        </div>
      ) : null}
      <p className="m-0 text-muted-foreground" data-testid="ending-render">
        {renderText(e)}
      </p>
      {refused ? (
        <WarnLine testId="ending-commit-refused" title={refused.title} action={refused.action} />
      ) : null}
      <More className="mt-0 min-w-0">
        <span>файл: {e.path}</span>
        {e.path_error ? <span>ошибка пути: {e.path_error}</span> : null}
        {e.mtime ? <span>изменён: {dateTimeMsk(e.mtime)}</span> : null}
        {e.declared_seconds != null ? (
          <span>narration_budget.ending_seconds: {e.declared_seconds}</span>
        ) : null}
        {e.probe_error ? <span>ffprobe: {e.probe_error}</span> : null}
        {e.check?.error ? <span>проверка: {e.check.error}</span> : null}
        {e.render.refusal ? <span>код: {e.render.refusal.code}</span> : null}
        {e.render.refusal?.details.map((d) => (
          <span key={d}>{d}</span>
        ))}
        {e.render.factory_ask ? <span>фабрике: {e.render.factory_ask}</span> : null}
        {refused ? (
          <span data-testid="ending-commit-detail" className="min-w-0 [overflow-wrap:anywhere]">
            git отказал в коммите: {refused.detail}
          </span>
        ) : null}
        {refused && e.render.last_run?.log ? (
          <span>журнал сборки: {e.render.last_run.log}</span>
        ) : null}
        {e.data.errors.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </More>
      {e.render.available ? <EndingRender channel={e.channel} /> : null}
    </div>
  );
}

function Sources({ s }: { s: ChannelFactSources }) {
  const v = sourcesView(s);
  return (
    <div className="grid gap-2.5 text-[13px]" data-testid="fact-sources">
      <Errors errors={s.errors} />
      {!v ? (
        <p className="m-0 text-muted-foreground">Списка источников у канала нет.</p>
      ) : (
        <>
          {v.tiers.map((t) => (
            <div key={t.tier} className="grid gap-1" data-testid="sources-tier" data-tier={t.tier}>
              <div className="text-xs text-muted-foreground">
                {tierLabel(t.tier)}: {t.outlets.length}
              </div>
              <Chips
                testId="sources-outlets"
                items={t.outlets.map((o) => ({ key: o.id, text: o.host, tip: o.tip }))}
              />
            </div>
          ))}
          {v.anyHost.length ? (
            <div className="grid gap-1">
              <div className="text-xs text-muted-foreground">С любого сайта</div>
              <ul className="m-0 grid list-disc gap-0.5 pl-5" data-testid="sources-any">
                {v.anyHost.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {v.doNotTake.length ? (
            <div className="grid gap-1">
              <div className="text-xs text-muted-foreground">Не брать никогда</div>
              <Chips testId="sources-never" items={v.doNotTake.map((h) => ({ key: h, text: h }))} />
            </div>
          ) : null}
          {v.kinds.length ? (
            <div className="grid gap-1">
              <div className="text-xs text-muted-foreground">О чём факты канала</div>
              <p className="m-0" data-testid="sources-kinds">
                {v.kinds.join(', ')}
              </p>
            </div>
          ) : null}
        </>
      )}
      <More className="mt-0">
        <span>файл: {s.path}</span>
        {s.missing ? <span>{s.missing}</span> : null}
        {v?.kindCodes.length ? <span>виды фактов: {v.kindCodes.join(', ')}</span> : null}
        {v?.tiers.flatMap((t) =>
          t.outlets.map((o) => <span key={o.id}>{`${t.tier}: ${o.id}`}</span>),
        )}
        {s.errors.map((e) => (
          <span key={e}>{e}</span>
        ))}
      </More>
      <ListEdit channel={s.channel} kind="fact-sources" doc={s.doc} sha={s.sha256 ?? null} />
    </div>
  );
}

function Affiliate({ a }: { a: ChannelAffiliate }) {
  const v = affiliateView(a);
  return (
    <div className="grid gap-2 text-[13px]" data-testid="affiliate">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge
          tone={a.enabled ? 'ok' : 'idle'}
          tip="Переключатель партнёрских ссылок в конфиге канала: пока выключен, фабрика ссылок не ставит"
        >
          {a.enabled ? 'включены' : 'выключены'}
        </StatusBadge>
        <span data-testid="affiliate-counts">
          {a.doc
            ? `программ: ${v.programmes.length} · товаров: ${v.products.length}`
            : 'Таблицы партнёрских ссылок у канала нет.'}
        </span>
      </div>
      <Errors errors={a.errors} />
      {v.products.length ? (
        <ul className="m-0 grid list-none gap-1 p-0" data-testid="affiliate-products">
          {v.products.map((p, i) => (
            <li key={`${p.name}-${i}`} className="flex flex-wrap gap-x-2">
              <span className="font-semibold">{p.name}</span>
              {p.programme ? <span className="text-muted-foreground">{p.programme}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      <More className="mt-0">
        <span>файл: {a.path}</span>
        {a.missing ? <span>{a.missing}</span> : null}
        {typeof a.block?.link_line === 'string' ? (
          <span>строка ссылки: {a.block.link_line}</span>
        ) : null}
        {a.errors.map((e) => (
          <span key={e}>{e}</span>
        ))}
      </More>
      <ListEdit channel={a.channel} kind="affiliate" doc={a.doc} sha={a.sha256 ?? null} />
    </div>
  );
}

function FootageOrigin({ f }: { f: ChannelFootageOrigin }) {
  const origins = Array.isArray(f.doc?.footage_origins) ? f.doc.footage_origins.length : 0;
  const official = Array.isArray(f.doc?.official_channels) ? f.doc.official_channels.length : 0;
  return (
    <div className="grid gap-2 text-[13px]" data-testid="footage-origin">
      <span data-testid="footage-origin-counts">
        {f.doc
          ? // У Reel источников нет — только официальные каналы (CC-0130).
            Array.isArray(f.doc.footage_origins)
            ? `откуда футаж: ${origins} · официальных каналов: ${official}`
            : `официальных каналов правообладателей: ${official}`
          : 'Списка происхождения футажа у канала нет.'}
      </span>
      <Errors errors={f.errors} />
      <More className="mt-0">
        <span>файл: {f.path}</span>
        {f.missing ? <span>{f.missing}</span> : null}
        {f.errors.map((e) => (
          <span key={e}>{e}</span>
        ))}
      </More>
      <ListEdit channel={f.channel} kind="footage-origin" doc={f.doc} sha={f.sha256 ?? null} />
    </div>
  );
}

function Holders({ h }: { h: ChannelRightsHolders }) {
  const n = Array.isArray(h.doc?.entries) ? h.doc.entries.length : 0;
  return (
    <div className="grid gap-2 text-[13px]" data-testid="rights-holders">
      <span data-testid="rights-holders-count">
        {h.doc ? `записей в списке: ${n}` : 'Списка правообладателей у канала нет.'}
      </span>
      <More className="mt-0">
        <span>файл: {h.path}</span>
        {h.missing ? <span>{h.missing}</span> : null}
      </More>
    </div>
  );
}

export function ChannelData({ channel }: { channel: string }) {
  const ending = useEnding(channel);
  const sources = useFactSources(channel);
  const aff = useAffiliate(channel);
  const footage = useFootageOrigin(channel);
  const holders = useRightsHolders(channel);
  return (
    <section
      className="grid gap-gap lg:grid-cols-2"
      aria-label="Данные канала"
      data-testid="channel-data"
    >
      <Card aria-labelledby="ending-title">
        <CardHead eyebrow="Последние секунды ролика" title="Концовка" titleId="ending-title" />
        <Loaded q={ending} failed="Концовку не прочитать" lines={3}>
          {(e) => <Ending e={e} />}
        </Loaded>
      </Card>
      <Card aria-labelledby="affiliate-title">
        <CardHead
          eyebrow="Ссылки в описании"
          title="Партнёрские ссылки"
          titleId="affiliate-title"
        />
        <Loaded q={aff} failed="Партнёрские ссылки не прочитать" lines={3}>
          {(a) => <Affiliate a={a} />}
        </Loaded>
      </Card>
      <Card aria-labelledby="sources-title" className="lg:col-span-2">
        <CardHead eyebrow="Откуда берутся факты" title="Источники фактов" titleId="sources-title" />
        <Loaded q={sources} failed="Источники фактов не прочитать" lines={6}>
          {(s) => <Sources s={s} />}
        </Loaded>
      </Card>
      <Card aria-labelledby="footage-origin-title">
        <CardHead
          eyebrow="Откуда футаж"
          title="Происхождение футажа"
          titleId="footage-origin-title"
        />
        <Loaded q={footage} failed="Происхождение футажа не прочитать" lines={3}>
          {(f) => <FootageOrigin f={f} />}
        </Loaded>
      </Card>
      <Card aria-labelledby="holders-title">
        <CardHead
          eyebrow="Подсказка проверки соответствия"
          title="Список правообладателей"
          titleId="holders-title"
        />
        <Loaded q={holders} failed="Список правообладателей не прочитать" lines={3}>
          {(h) => <Holders h={h} />}
        </Loaded>
      </Card>
    </section>
  );
}
