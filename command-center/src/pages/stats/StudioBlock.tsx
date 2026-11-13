// Чтение Studio (`GET …/studio`): пора ли читать (строка фабрики), какие ролики прочитать со
// ссылками в Studio, последнее чтение и что оно сказало по каждому ролику. Под списком — ввод
// прочитанных цифр (./StudioEntry, CC-0077): план фабрики и «да» с отсчётом.
import { BatchError } from '@/api/batchProblem';
import { useAnalyticsStudio, type AnalyticsStudio } from '@/api/analytics';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { dateTimeMsk } from '@/pages/batches/format';

import { dueText, pct, shortDay, videoName } from './format';
import { StudioEntry } from './StudioEntry';
import { SkeletonText } from '@/components/common/Skeletons';

type Visit = { read_at?: string; videos_read?: number };

function Body({ s }: { s: AnalyticsStudio }) {
  if (s.no_pipeline)
    return (
      <EmptyState title="У канала нет конвейера">
        Канал оформлен, но роликов не делает — читать в Studio нечего.
      </EmptyState>
    );
  if (!s.settings)
    return (
      <div data-testid="studio-no-settings">
        <EmptyState title="Чтение Studio для канала не настроено">
          В настройках канала нет раздела про чтение Studio — фабрика не знает, сколько роликов
          читать и как часто. Его добавляют в настройках канала.
        </EmptyState>
        {s.settings_error ? (
          <More>
            <span>{s.settings_error}</span>
          </More>
        ) : null}
      </div>
    );
  const visit = s.last_visit as Visit | null;
  const reads = new Map(s.latest_reads.map((r) => [r.video_id, r]));
  return (
    <>
      {s.due ? (
        <div className="mb-3 flex flex-wrap items-center gap-2" data-testid="studio-due">
          <StatusBadge
            tone={s.due.due ? 'warn' : 'ok'}
            tip={
              s.due.due
                ? 'Studio пора прочитать: страховочный срок с последнего чтения вышел'
                : 'Читать рано: последнее чтение ещё свежее'
            }
          >
            {s.due.due ? 'пора читать' : 'рано'}
          </StatusBadge>
          <span className="text-muted-foreground">{dueText(s.due.line)}</span>
        </div>
      ) : null}
      <p className="m-0 mb-2 text-muted-foreground">
        {visit?.read_at
          ? `Последнее чтение — ${dateTimeMsk(visit.read_at) ?? visit.read_at}, роликов: ${visit.videos_read ?? '—'}.`
          : 'Studio по этому каналу ещё ни разу не читали.'}
      </p>
      <h3 className="mt-3 mb-1.5 text-sm font-semibold">
        <Tip content="Столько последних роликов просит прочитать настройка канала">
          <span tabIndex={0} className="cursor-help">
            Что прочитать: последние {s.n ?? s.last_videos.length}
          </span>
        </Tip>
      </h3>
      {s.last_videos.length ? (
        <ul className="m-0 grid list-none gap-1.5 p-0" data-testid="studio-videos">
          {s.last_videos.map((v) => {
            const r = reads.get(v.video_id);
            return (
              <li
                key={v.video_id}
                data-testid="studio-video"
                className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5"
              >
                <span className="min-w-0">
                  <span className="font-semibold">{videoName(v)}</span>{' '}
                  <span className="text-xs text-muted-foreground">
                    вышел {shortDay(v.published.slice(0, 10))} ·{' '}
                    {r
                      ? r.note
                        ? 'у Studio мало данных'
                        : `досмотрели ${pct(r.viewed_pct)}`
                      : 'ещё не читали'}
                  </span>
                </span>
                <a
                  href={v.studio_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-primary-text underline-offset-4 hover:underline"
                >
                  Открыть в Studio
                </a>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="m-0 text-muted-foreground">Опубликованных роликов пока нет.</p>
      )}
      <StudioEntry key={s.channel} channel={s.channel} videos={s.last_videos} />
      <More>
        <span>
          analyst.studio_read: {JSON.stringify(s.settings)}
          {s.due ? ` · ${s.due.line}` : ''}
        </span>
        {s.latest_reads.map((r) => (
          <span key={r.video_id}>
            {r.video_id}: {r.read_at} · {r.hook} · viewed {String(r.viewed_pct)} · swiped{' '}
            {String(r.swiped_pct)}
            {r.note ? ` · ${r.note}` : ''}
          </span>
        ))}
      </More>
    </>
  );
}

export function StudioBlock({ channel }: { channel: string }) {
  const q = useAnalyticsStudio(channel);
  return (
    <Card aria-labelledby="stats-studio-title" data-testid="stats-studio">
      <CardHead
        eyebrow="Studio · чтение и ввод"
        title="Чтение Studio"
        titleId="stats-studio-title"
      />
      {q.isPending ? (
        <SkeletonText lines={4} label="Читаю, что прочитано в Studio…" />
      ) : q.isError ? (
        <ErrorState
          title="Чтение Studio не получить"
          error={q.error}
          onRetry={() => void q.refetch()}
        >
          {q.error instanceof BatchError && q.error.problem
            ? q.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : (
        <Body s={q.data} />
      )}
    </Card>
  );
}
