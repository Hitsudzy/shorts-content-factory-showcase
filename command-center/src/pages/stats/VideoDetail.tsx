// Ролик (`GET …/videos/{id}`): окно YouTube «первые 7 дней» плитками, график просмотров по дням
// (дневные строки как есть; неокончательные дни — бледнее) и чтения Studio.
import { BatchError } from '@/api/batchProblem';
import { useVideoSeries, type MetricDaily, type VideoSeries } from '@/api/analytics';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { dateTimeMsk } from '@/pages/batches/format';

import { count, METRIC, pct, shortDay, videoName } from './format';
import { SkeletonTable } from '@/components/common/Skeletons';

/** Высота области столбиков в единицах viewBox (ширина — 10 на день). */
const VH = 100;

/**
 * Лёгкий график просмотров по дням: столбик на день, неокончательные — бледнее. Столбики — SVG,
 * растянутый на ширину карточки; подписи осей — обычным текстом, чтобы не мельчали на телефоне.
 */
export function ViewsChart({ daily }: { daily: MetricDaily[] }) {
  const rows = [...daily].sort((a, b) => a.day.localeCompare(b.day));
  const max = Math.max(1, ...rows.map((r) => r.views ?? 0));
  const vw = Math.max(rows.length, 1) * 10;
  const total = rows.reduce((a, r) => a + (r.views ?? 0), 0);
  const label = `Просмотры по дням: ${rows.length} дн., всего ${count(total)}, больше всего за день ${count(max)}`;
  return (
    <figure className="m-0" data-testid="views-chart">
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-2">
        <div
          aria-hidden
          className="relative h-[160px] min-w-[3ch] font-mono text-[11px] text-muted-foreground tabular-nums"
        >
          {/* Подписи стоят абсолютно и ширины колонке не дают: самую длинную (верхнюю) кладём
              ещё и невидимо в поток — колонка по ней, и верхняя подпись не срезана слева. */}
          <span className="invisible block h-0 overflow-hidden whitespace-nowrap">
            {count(max)}
          </span>
          {[1, 0.5, 0].map((f) => (
            <span
              key={f}
              data-testid="chart-axis-label"
              className="absolute right-0 -translate-y-1/2 whitespace-nowrap"
              style={{ top: `${(1 - f) * 100}%` }}
            >
              {count(Math.round(max * f))}
            </span>
          ))}
        </div>
        <div className="min-w-0">
          <svg
            viewBox={`0 0 ${vw} ${VH}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={label}
            className="block h-[160px] w-full overflow-visible"
          >
            {[0, 0.5, 1].map((f) => (
              <line
                key={f}
                x1={0}
                x2={vw}
                y1={VH * f}
                y2={VH * f}
                stroke="var(--border)"
                strokeDasharray={f < 1 ? '3 3' : undefined}
                vectorEffect="non-scaling-stroke"
              />
            ))}
            {rows.map((r, i) => {
              const h = ((r.views ?? 0) / max) * VH;
              return (
                <rect
                  key={r.day}
                  data-testid="chart-bar"
                  data-final={r.final ? 'true' : 'false'}
                  x={i * 10 + 1.5}
                  y={VH - h}
                  width={7}
                  height={h}
                  fill="var(--primary)"
                  fillOpacity={r.final ? 1 : 0.45}
                >
                  <title>
                    {`${shortDay(r.day)}: ${count(r.views)} просмотров${r.final ? '' : ' (ещё не окончательно)'}`}
                  </title>
                </rect>
              );
            })}
          </svg>
          {rows.length ? (
            <div
              aria-hidden
              className="mt-1 flex justify-between font-mono text-[11px] text-muted-foreground"
            >
              <span>{shortDay(rows[0]!.day)}</span>
              {rows.length > 1 ? <span>{shortDay(rows[rows.length - 1]!.day)}</span> : null}
            </div>
          ) : null}
        </div>
      </div>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-[2px] bg-primary" /> окончательные
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-2.5 rounded-[2px] bg-primary opacity-45" /> ещё могут
          поменяться
        </span>
      </figcaption>
    </figure>
  );
}

const TILES = [
  'views',
  'engagedViews',
  'averageViewPercentage',
  'averageViewDuration',
  'likes',
  'subscribersGained',
] as const;

function Series({ s }: { s: VideoSeries }) {
  const w = s.windows.find((x) => x.first_days === 7) ?? s.windows[0] ?? null;
  const reads = [...s.studio].sort((a, b) => b.read_at.localeCompare(a.read_at));
  return (
    <>
      {w ? (
        <dl
          data-testid="window-tiles"
          className="m-0 mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3"
          aria-label={`Окно первых ${w.first_days} дней`}
        >
          {TILES.map((k) => (
            <div key={k} className="rounded-sm border px-3 py-2">
              <dt className="text-xs text-muted-foreground">
                <Tip content={METRIC[k]!.tip}>
                  <span tabIndex={0} className="cursor-help">
                    {METRIC[k]!.label}
                  </span>
                </Tip>
              </dt>
              <dd className="m-0 font-display text-xl font-semibold tabular-nums">
                {METRIC[k]!.show(w[k])}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="m-0 mb-3 text-muted-foreground" data-testid="no-window">
          Окна YouTube «первые 7 дней» у ролика нет — ниже только дневные строки как есть.
        </p>
      )}
      {s.daily.length ? (
        <ViewsChart daily={s.daily} />
      ) : (
        <EmptyState title="Дневных строк нет">YouTube по ролику ещё ничего не дал.</EmptyState>
      )}
      <h3 className="mt-4 mb-1.5 text-sm font-semibold">Studio</h3>
      {reads.length ? (
        <ul className="m-0 grid list-none gap-1 p-0" data-testid="video-studio">
          {reads.map((r) => (
            <li key={r.read_at} className="text-muted-foreground">
              {dateTimeMsk(r.read_at) ?? r.read_at}:{' '}
              {r.note ? (
                'у Studio пока мало данных'
              ) : (
                <>
                  досмотрели <b className="text-foreground">{pct(r.viewed_pct)}</b>
                  {typeof r.swiped_pct === 'number' ? `, пролистали ${pct(r.swiped_pct)}` : ''}
                  {r.period_text ? ` · ${r.period_text.toLowerCase()}` : ''}
                </>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-muted-foreground">Studio по этому ролику ещё не читали.</p>
      )}
      <More>
        <span>video_id: {s.video_id}</span>
        {w ? (
          <span>
            {w.window} {w.start}…{w.end} · final {String(w.final)} · complete {String(w.complete)} ·{' '}
            {w.source ?? '—'} · {w.collected_at}
          </span>
        ) : null}
        <span>дневных строк: {s.daily.length}</span>
      </More>
    </>
  );
}

export function VideoDetail({ channel, videoId }: { channel: string; videoId: string }) {
  const q = useVideoSeries(channel, videoId);
  const name = q.data
    ? videoName(q.data.windows[0] ?? q.data.daily[0] ?? { video_id: videoId })
    : null;
  return (
    <Card aria-labelledby="stats-video-title" data-testid="stats-video-detail">
      <CardHead eyebrow="Ролик · по дням" title={name ?? 'Ролик'} titleId="stats-video-title" />
      {q.isPending ? (
        <SkeletonTable rows={4} cols={4} label="Читаю числа ролика…" />
      ) : q.isError ? (
        <ErrorState
          title="Числа ролика не прочитать"
          error={q.error}
          onRetry={() => void q.refetch()}
        >
          {q.error instanceof BatchError && q.error.problem
            ? q.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : (
        <Series s={q.data} />
      )}
    </Card>
  );
}
