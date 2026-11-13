// Сводка аналитика (`GET …/summary`, сохранённая — `…/summary/{day}`): группы роликов по стилю
// (схема, ритм, первая фраза, о чём факт, оценка) с медианами словами, предупреждение о малой
// выборке, пробелы («нет профиля», «нет метрик», «нет чтения Studio»). Всё посчитано фабрикой —
// центр только пересказывает.
import { BatchError } from '@/api/batchProblem';
import { analyticsCode, useSummary, type AnalystSummary, type SummaryGroup } from '@/api/analytics';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { useLiveSearchParams } from '@/lib/useLiveSearchParams';
import { videosWord } from '@/pages/batches/format';

import { count, DIMENSION, leadLine, median, pct, shortDay, styleValue, videoName } from './format';
import { SkeletonText } from '@/components/common/Skeletons';

function Group({ g, minSample }: { g: SummaryGroup; minSample: number }) {
  return (
    <li
      data-testid="summary-group"
      data-value={g.value}
      className="grid gap-1 border-b py-2 last:border-b-0 sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)] sm:gap-3"
    >
      <div className="min-w-0">
        <div className="font-semibold">{styleValue(g.value)}</div>
        <div className="text-xs text-muted-foreground">{videosWord(g.videos)}</div>
      </div>
      <div className="grid min-w-0 gap-1">
        <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-muted-foreground">
          <span>
            вовлечённых <b className="text-foreground">{count(median(g, 'engagedViews'))}</b>
          </span>
          <span>
            % просмотра <b className="text-foreground">{pct(median(g, 'averageViewPercentage'))}</b>
          </span>
          <span>
            досмотрели <b className="text-foreground">{pct(median(g, 'viewed_pct'))}</b>
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {g.small_sample ? (
            <StatusBadge
              tone="warn"
              tip={`Чтобы на группу можно было опираться, в ней нужно хотя бы ${minSample} роликов с числами`}
            >
              мало роликов
            </StatusBadge>
          ) : null}
          {g.not_final ? (
            <StatusBadge tone="idle" tip="У этих роликов числа YouTube ещё могут поменяться">
              не окончательные: {g.not_final}
            </StatusBadge>
          ) : null}
          {g.incomplete ? (
            <StatusBadge tone="idle" tip="Этим роликам меньше 7 дней — окно ещё набирается">
              окно неполное: {g.incomplete}
            </StatusBadge>
          ) : null}
        </div>
      </div>
    </li>
  );
}

type Gap = { video_id?: unknown; entry_id?: unknown; why?: unknown };

function Gaps({ s }: { s: AnalystSummary }) {
  const byId = new Map(s.videos.map((v) => [v.video_id ?? v.entry_id ?? '', v]));
  const nameOf = (g: Gap) => {
    const key = String(g.video_id ?? g.entry_id ?? '');
    return videoName(byId.get(key) ?? { video_id: key, entry_id: String(g.entry_id ?? '') });
  };
  const lists = [
    [
      'no_profile',
      'Нет профиля',
      'Стиль ролика не записан при приёмке — в группах он «не указано»',
    ],
    ['no_metrics', 'Нет метрик', 'У ролика нет окна YouTube — в медианах его чисел нет'],
    ['no_studio', 'Нет чтения Studio', 'Studio по ролику ещё не читали — «досмотрели» нет'],
  ] as const;
  const any = lists.some(([k]) => s.gaps[k]?.length);
  if (!any)
    return <p className="m-0 text-muted-foreground">Пробелов нет: у всех роликов есть всё.</p>;
  return (
    <div className="grid gap-3 md:grid-cols-3" data-testid="summary-gaps">
      {lists.map(([k, title, tip]) => {
        const items = (s.gaps[k] ?? []) as Gap[];
        return (
          <div key={k} data-testid={`gap-${k}`} className="min-w-0 rounded-sm border p-3">
            <div className="mb-1 flex items-center justify-between gap-2">
              <Tip content={tip}>
                <span tabIndex={0} className="cursor-help font-semibold">
                  {title}
                </span>
              </Tip>
              <span className="font-mono text-xs text-muted-foreground">{items.length}</span>
            </div>
            {items.length ? (
              <ul className="m-0 grid list-none gap-0.5 p-0 text-muted-foreground">
                {items.map((g, i) => (
                  <li key={i}>
                    <span className="text-foreground">{nameOf(g)}</span>
                    {typeof g.why === 'string' && g.why && k !== 'no_metrics' ? ` — ${g.why}` : ''}
                    {typeof g.why === 'string' && k === 'no_metrics' ? (
                      <Tip content={g.why}>
                        <span tabIndex={0} className="ml-1 cursor-help text-xs underline">
                          почему
                        </span>
                      </Tip>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-muted-foreground">нет</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Report({ s }: { s: AnalystSummary }) {
  const c = s.counts;
  const groups = Object.values(s.aggregates).flat();
  const allSmall = groups.length > 0 && groups.every((g) => g.small_sample);
  return (
    <>
      <p className="m-0 mb-3" data-testid="summary-counts">
        {c.videos ? (
          <>
            В сводке {videosWord(c.videos ?? 0)}: вышли {c.published ?? 0}, со стилем{' '}
            {c.with_profile ?? 0}, с числами YouTube {c.with_api ?? 0}, с чтением Studio{' '}
            {c.with_studio ?? 0}
            {c.not_final ? `; у ${c.not_final} числа ещё не окончательные` : ''}.
          </>
        ) : (
          'Роликов в сводке пока нет — канал ещё ничего не опубликовал.'
        )}
      </p>
      {allSmall ? (
        <p
          data-testid="small-sample"
          className="m-0 mb-3 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] p-3 text-muted-foreground"
        >
          <b className="text-warning">Роликов пока мало.</b> В каждой группе меньше {s.min_sample}{' '}
          роликов с числами — сравнения ниже стоит читать как первые наблюдения, а не как выводы.
        </p>
      ) : null}
      {c.published ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {s.dimensions.map((d) => {
            const gs = s.aggregates[d] ?? [];
            const dim = DIMENSION[d] ?? { label: d, tip: d };
            return (
              <section key={d} data-testid="summary-dimension" data-dimension={d}>
                <h3 className="m-0 text-sm font-semibold">
                  <Tip content={dim.tip}>
                    <span tabIndex={0} className="cursor-help">
                      {dim.label}
                    </span>
                  </Tip>
                </h3>
                <p className="m-0 mt-0.5 mb-1 text-muted-foreground">
                  {leadLine(gs, s.min_sample)}
                </p>
                <ul className="m-0 list-none p-0">
                  {gs.map((g) => (
                    <Group key={g.value} g={g} minSample={s.min_sample} />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      ) : null}
      <h3 className="mt-4 mb-1.5 text-sm font-semibold">Пробелы</h3>
      <Gaps s={s} />
      {s.videos.length ? (
        <details className="mt-3" data-testid="summary-videos">
          <summary className="w-max cursor-pointer text-primary-text">
            Ролики сводки и их стиль
          </summary>
          <ul className="m-0 mt-2 grid list-none gap-1.5 p-0">
            {s.videos.map((v) => (
              <li key={v.video_id ?? v.entry_id} className="min-w-0">
                <span className="font-semibold">{videoName(v)}</span>{' '}
                <span className="text-xs text-muted-foreground">
                  вышел {shortDay(v.published)} ·{' '}
                  {s.dimensions.map((d) => styleValue(v.style[d] ?? 'unknown')).join(' · ')}
                </span>
                {v.marks.length ? (
                  <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
                    {v.marks.map((m) => (
                      <StatusBadge key={m} tone="idle">
                        {m}
                      </StatusBadge>
                    ))}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <More>
        <span>{s.aggregates_note}</span>
        <span>
          {s.task} · day {s.day} · first_days {s.first_days} · min_sample {s.min_sample} · computed
          by {s.aggregates_computed_by} · метрики: {s.metrics.join(', ')}
        </span>
        {Object.entries(s.sources).map(([k, v]) => (
          <span key={k}>
            {k}: {v}
          </span>
        ))}
      </More>
    </>
  );
}

export function Summary({ channel, savedDays }: { channel: string; savedDays: string[] }) {
  // CC-0163: день пишется в текущий адрес роутера, а не в отрисованный: иначе ролик, выбранный
  // перед этим до перерисовки, теряется. Новый шаг истории, как и раньше.
  const [params, setParams] = useLiveSearchParams();
  const day = params.get('day');
  const q = useSummary(channel, day);
  const pick = (d: string) =>
    setParams(
      (p) => {
        if (d) p.set('day', d);
        else p.delete('day');
        return p;
      },
      { replace: false },
    );
  const days = q.data?.saved_days ?? savedDays;
  return (
    <Card aria-labelledby="stats-summary-title" data-testid="stats-summary">
      <CardHead
        eyebrow={`Сводка аналитика · ${q.data ? `за ${shortDay(q.data.day)}` : '…'} · первые ${q.data?.first_days ?? 7} дней`}
        title="Что работает лучше"
        titleId="stats-summary-title"
        actions={
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            День
            <select
              data-testid="summary-day"
              value={day ?? ''}
              onChange={(e) => pick(e.target.value)}
              className="h-[28px] rounded-sm border bg-card px-2 text-foreground"
            >
              <option value="">свежая (за вчера)</option>
              {days.map((d) => (
                <option key={d} value={d}>
                  сохранённая за {shortDay(d)}
                </option>
              ))}
            </select>
          </label>
        }
      />
      {q.isPending ? (
        <SkeletonText lines={5} label="Считаю сводку…" />
      ) : q.isError ? (
        analyticsCode(q.error) === 'no_saved_summary' && q.error instanceof BatchError ? (
          <EmptyState title="Сводки за этот день нет">{q.error.message}</EmptyState>
        ) : (
          <ErrorState title="Сводку не получить" error={q.error} onRetry={() => void q.refetch()}>
            {q.error instanceof BatchError && q.error.problem
              ? q.error.problem.message
              : 'Проверьте, что API фабрики запущен.'}
          </ErrorState>
        )
      ) : (
        <Report s={q.data} />
      )}
    </Card>
  );
}
