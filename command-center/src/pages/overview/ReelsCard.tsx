// «Ролики ждут решения» главной (CC-0062): ролики последнего батча истории без вердикта —
// счёт и обложки 9:16, каждая ведёт в ролик на экране «Ролики». Счёт — только по последнему
// батчу: сводного адреса «ролики на приёмке по всем батчам» в API нет (нужна отдельная задача).
import { Link } from 'react-router';

import type { BatchRun } from '@/api/batches';
import { posterOf, videoTitle } from '@/api/videos';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/button';
import { dateTimeMsk } from '@/pages/batches/format';
import { batchIdIso } from '@/pages/batches/going';
import { useChannelNames } from '@/pages/batches/names';
import { Cover } from '@/pages/videos/Cover';
import { timecode } from '@/pages/videos/format';
import { ScoreBadge } from '@/pages/videos/Score';

import { useWaitingReels } from './waitingReels';
import { Pending, SkeletonText } from '@/components/common/Skeletons';

const SHOWN = 3;

function batchName(batch: string, run: BatchRun | undefined, name: (id?: string | null) => string) {
  const [dir, id] = batch.split('/');
  return `${name(run?.channel ?? dir)} · ${dateTimeMsk(run?.started ?? batchIdIso(id)) ?? id}`;
}

export function ReelsCard({ className }: { className?: string }) {
  const r = useWaitingReels();
  const name = useChannelNames();
  const total = r.list.data?.videos.length ?? 0;
  const href = (slug?: string) =>
    r.batch
      ? `/videos?batch=${encodeURIComponent(r.batch)}${slug ? `&v=${encodeURIComponent(slug)}` : ''}`
      : '/videos';
  return (
    <Card
      aria-labelledby="reels-title"
      className={className}
      data-testid="reels-card"
      data-waiting={r.list.data ? r.waiting.length : undefined}
    >
      <CardHead
        eyebrow="На приёмке"
        title="Ролики ждут решения"
        titleId="reels-title"
        actions={
          <Button asChild variant="ghost">
            <Link to={href()}>Все ролики</Link>
          </Button>
        }
      />
      {r.error ? (
        <ErrorState title="Не удалось прочитать ролики" error={r.error} onRetry={r.retry} />
      ) : r.isPending ? (
        <Pending label="Смотрю ролики последнего батча…" className="gap-3">
          <SkeletonText bare lines={1} lineHeight={37} widths={[48]} />
          <SkeletonText bare lines={1} lineHeight={16} widths={[18]} />
        </Pending>
      ) : r.none || !r.batch ? (
        <p className="m-0 text-muted-foreground">Батчей ещё не было — роликов на приёмке нет.</p>
      ) : (
        <div className="grid gap-3">
          <p className="m-0" data-testid="reels-count">
            {r.waiting.length ? (
              <>
                <strong className="font-display text-[22px] font-semibold">
                  {r.waiting.length}
                </strong>{' '}
                из {total} — без вердикта в последнем батче
              </>
            ) : total && r.replaced ? (
              <>В последнем батче решения не ждёт ни один ролик.</>
            ) : total ? (
              <>В последнем батче у всех роликов уже есть вердикт.</>
            ) : (
              <>В последнем батче роликов нет.</>
            )}
            <span className="block text-xs text-muted-foreground" data-testid="reels-batch">
              {batchName(r.batch, r.run, name)}
            </span>
          </p>
          {r.waiting.length ? (
            <ul className="-mx-card m-0 flex list-none snap-x snap-mandatory scroll-px-card gap-3 overflow-x-auto px-card py-0 sm:mx-0 sm:grid sm:grid-cols-3 sm:gap-3.5 sm:overflow-visible sm:px-0">
              {r.waiting.slice(0, SHOWN).map((v) => (
                <li
                  key={v.slug}
                  className="w-full max-w-[200px] shrink-0 basis-[46%] snap-start sm:basis-auto"
                  data-testid="reels-item"
                  data-slug={v.slug}
                >
                  <Link to={href(v.slug)} className="grid gap-1.5 rounded-sm outline-offset-2">
                    <Cover
                      poster={posterOf(v.preview)}
                      caption={videoTitle(v)}
                      time={timecode(v.duration)}
                    />
                    <span className="text-xs leading-[1.35] [overflow-wrap:anywhere]">
                      {videoTitle(v)}
                    </span>
                  </Link>
                  {r.list.data && r.batch ? (
                    <ScoreBadge
                      className="mt-1"
                      score={v.score}
                      tiers={r.list.data.score_model.tiers}
                      below={r.list.data.score_model.below}
                      batch={r.batch}
                      slug={v.slug}
                      href={href(v.slug)}
                    />
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {r.replaced ? (
            <p className="m-0 text-[13px] text-muted-foreground" data-testid="reels-replaced">
              Заменены принятой пересборкой: {r.replaced} — их не спрашиваем, подробности на экране
              «Ролики».
            </p>
          ) : null}
          {r.waiting.length > SHOWN ? (
            <p className="m-0 text-[13px] text-muted-foreground">
              Ещё {r.waiting.length - SHOWN} — на экране «Ролики».
            </p>
          ) : null}
          {r.list.data?.acceptance_error ? (
            <p className="m-0 text-[13px] text-danger">
              Журнал приёмки не читается — счёт неполный.
            </p>
          ) : null}
          <More className="mt-0">
            <span>батч: {r.batch}</span>
            <span>
              счёт — только по последнему батчу: сводного адреса «ролики на приёмке по всем батчам»
              в API нет
            </span>
            {r.list.data?.acceptance_error ? <span>{r.list.data.acceptance_error}</span> : null}
          </More>
        </div>
      )}
    </Card>
  );
}
