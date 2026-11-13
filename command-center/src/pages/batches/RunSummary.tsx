// «Сводка прогона» в раскрытом прошлом прогоне (CC-0115 → CC-0099, `GET …/summary`): время
// прогона (шёл, работал, простои, ожидание человека, оператор), воронка тем по шагам, оценки
// роликов по тирам и то, на что стоит посмотреть. RUN_SUMMARY.md целиком и строки фабрики —
// под «подробнее». Сводки ещё нет (`data_note`/`file_note`) — так и сказано; посчитать не вышло
// (`data_error`) — отказ, а файл, если есть, всё равно под «подробнее».
import type { CSSProperties } from 'react';

import { useRunSummary, type BatchRunSummary } from '@/api/runSummary';
import { More } from '@/components/common/More';
import { Pending } from '@/components/common/Skeletons';
import { Tip } from '@/components/common/Tip';
import { Skeleton } from '@/components/ui/skeleton';
import { tierColor } from '@/pages/videos/scoreWords';

import { dateTimeMsk } from './format';
import { Refusal } from './parts';
import { sizeText } from './going';
import { summaryView, type SummaryView } from './runSummaryText';

function Fact({ label, value, tip }: { label: string; value: string; tip?: string }) {
  const body = (
    <span className="grid min-w-0 gap-0.5" data-testid="summary-fact">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-[13px] font-semibold">{value}</span>
    </span>
  );
  if (!tip) return body;
  return (
    <Tip content={tip}>
      <span tabIndex={0} className="min-w-0 rounded-sm outline-offset-2">
        {body}
      </span>
    </Tip>
  );
}

function Time({ v }: { v: NonNullable<SummaryView['time']> }) {
  const pct = (n: number | null) => (n == null ? '' : ` · ${String(n).replace('.', ',')} %`);
  return (
    <div
      data-testid="summary-time"
      className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))]"
    >
      <Fact label="Шёл" value={v.wall ?? '—'} tip="От первого маркера батча до последнего." />
      <Fact label="Работал" value={v.live ?? '—'} tip="Время прогона без простоев." />
      {v.gaps ? (
        <Fact
          label="Простои"
          value={v.gaps.count ? `${v.gaps.span ?? '—'}${pct(v.gaps.share)}` : 'нет'}
          tip="Время, когда в батче ничего не происходило: ни скрипта, ни события."
        />
      ) : null}
      {v.waits ? (
        <Fact
          label="Ждал вас"
          value={v.waits.count ? (v.waits.span ?? '—') : 'нет'}
          tip="Сколько батч стоял, ожидая решения человека дольше 10 минут."
        />
      ) : null}
      {v.operator ? (
        <Fact
          label="Оператор думал"
          value={`${v.operator.span ?? '—'}${pct(v.operator.share)}`}
          tip="Время, которое операторы стадий провели между своими скриптами: читали, думали, писали."
        />
      ) : null}
    </div>
  );
}

function Funnel({ v }: { v: SummaryView }) {
  return (
    <div className="grid gap-1.5" data-testid="summary-funnel">
      <div className="text-xs text-muted-foreground">
        Темы
        {v.funnelLine ? <span data-testid="summary-funnel-line"> — {v.funnelLine}</span> : null}
      </div>
      <ol className="m-0 flex list-none flex-wrap items-center gap-x-1 gap-y-1.5 p-0 text-[13px]">
        {v.funnel.map((s, i) => (
          <li key={s.step} className="flex items-center gap-1" data-testid="summary-step">
            {i ? (
              <span aria-hidden className="text-muted-foreground">
                →
              </span>
            ) : null}
            <span className="rounded-sm border px-1.5 py-0.5 whitespace-nowrap">
              <b className="font-mono font-semibold">{s.count}</b> {s.label}
            </span>
          </li>
        ))}
      </ol>
      {v.losses.length ? (
        <ul
          className="m-0 grid list-none gap-0.5 p-0 text-[13px] text-muted-foreground"
          aria-label="Почему темы потеряны"
          data-testid="summary-losses"
        >
          {v.losses.map((l) => (
            <li key={l.code} data-testid="summary-loss" className="[overflow-wrap:anywhere]">
              {l.text}
              {l.count > 1 ? `\u00a0×\u00a0${l.count}` : ''}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Легенда значков «S × 1 · C × 1» (CC-0131): что значит буква и что число. */
const TIERS_TIP =
  'Буква — тир оценки ролика: S — лучший, дальше по алфавиту вниз; F — ролик не прошёл. Число после × — сколько роликов батча получили этот тир';

function Tiers({ v }: { v: SummaryView }) {
  return (
    <div className="grid gap-1.5" data-testid="summary-tiers">
      <Tip content={TIERS_TIP}>
        <span
          tabIndex={0}
          className="w-max text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
          data-testid="summary-tiers-legend"
        >
          Оценки роликов
        </span>
      </Tip>
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {v.tiers.map((t) => (
          <li
            key={t.tier}
            data-testid="summary-tier"
            aria-label={`Тир ${t.tier}: ${t.count}`}
            style={{ '--tier': tierColor(t.level) } as CSSProperties}
            className="rounded-sm border border-[color-mix(in_srgb,var(--tier)_45%,var(--border))] bg-[color-mix(in_srgb,var(--tier)_8%,transparent)] px-1.5 py-0.5 font-mono text-xs font-semibold text-[var(--tier)]"
          >
            {t.tier} × {t.count}
          </li>
        ))}
      </ul>
      {/* На телефоне наведения нет: короткая легенда видна всегда (CC-0131). */}
      <span className="text-xs text-muted-foreground" data-testid="summary-tiers-key">
        S — лучшая оценка, F — худшая; после × — сколько роликов
      </span>
    </div>
  );
}

function Attention({ v }: { v: SummaryView }) {
  return (
    <ul className="m-0 grid list-none gap-1 p-0 text-[13px]" data-testid="summary-attention">
      {v.attention.map((a) => (
        <li key={a.key} data-key={a.key} className="flex gap-2">
          <span aria-hidden className="font-semibold text-warning">
            !
          </span>
          {a.tip ? (
            <Tip content={a.tip}>
              <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
                {a.text}
              </span>
            </Tip>
          ) : (
            <span>{a.text}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

function Details({ s, v }: { s: BatchRunSummary; v: SummaryView | null }) {
  return (
    <More>
      {s.computed_at ? (
        <span>
          посчитано: {dateTimeMsk(s.computed_at)}
          {s.cached ? ' (батч с тех пор не менялся)' : ''}
        </span>
      ) : null}
      {v?.lines.map((l) => (
        <span key={l}>{l}</span>
      ))}
      {v?.losses.length ? (
        <span>потери: {v.losses.map((l) => `${l.code} ×${l.count}`).join(', ')}</span>
      ) : null}
      {s.file ? (
        <>
          <span>
            {s.file.name}, {sizeText(s.file.size)}, {dateTimeMsk(s.file.modified)}
          </span>
          <pre
            data-testid="summary-file"
            className="m-0 mt-1 max-h-80 overflow-auto rounded-sm border bg-background p-2.5 text-[11.5px] leading-[1.45] break-all whitespace-pre-wrap text-foreground"
          >
            {s.file.text}
          </pre>
        </>
      ) : s.file_note ? (
        <span>{s.file_note}</span>
      ) : null}
    </More>
  );
}

/** Скелетон той же формы: заголовок, строка фактов, воронка, тиры. */
function SummarySkeleton() {
  return (
    <Pending label="Считаю сводку прогона…" className="mt-3 gap-3 rounded-sm border p-3">
      <Skeleton className="h-3.5 w-32" />
      <span className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <span key={i} className="grid gap-1.5">
            <Skeleton className="h-3 w-14" />
            <Skeleton className="h-3.5 w-20" />
          </span>
        ))}
      </span>
      <Skeleton className="h-6 w-full max-w-[34rem]" />
      <Skeleton className="h-5 w-48" />
    </Pending>
  );
}

export function RunSummaryBlock({ batch }: { batch: string }) {
  const q = useRunSummary(batch);
  if (q.isPending) return <SummarySkeleton />;
  if (q.isError)
    return (
      <section data-testid="run-summary" className="mt-3">
        <Refusal error={q.error} title="Сводка прогона не читается" />
      </section>
    );
  const s = q.data;
  const v = summaryView(s.data, s.funnel_reasons_ru);
  const empty = !v || (!v.time && !v.funnel.length && !v.tiers.length && !v.attention.length);
  return (
    <section
      data-testid="run-summary"
      aria-labelledby={`summary-${batch}`}
      className="mt-3 grid min-w-0 gap-3 rounded-sm border p-3"
    >
      <h3 id={`summary-${batch}`} className="m-0 text-[13px] font-semibold">
        Сводка прогона
      </h3>
      {s.data_error ? (
        <Refusal
          error={new Error(s.data_error)}
          title="Сводку не посчитать"
          message="Фабрика не смогла собрать сводку из журнала прогона — ошибка под «подробнее»."
        />
      ) : empty ? (
        <p className="m-0 text-[13px] text-muted-foreground" data-testid="summary-note">
          {s.data_note ? 'Сводки ещё нет: у батча пока нет событий прогона.' : 'Сводка пуста.'}
        </p>
      ) : (
        <>
          {v.time ? <Time v={v.time} /> : null}
          {v.funnel.length ? <Funnel v={v} /> : null}
          {v.tiers.length ? <Tiers v={v} /> : null}
          {v.attention.length ? <Attention v={v} /> : null}
        </>
      )}
      <Details s={s} v={v} />
    </section>
  );
}
