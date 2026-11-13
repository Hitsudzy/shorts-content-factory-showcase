// Ролик, отказанный после монтажа (CC-0116): вместо приёмки — причина словами человека
// («Не прошёл проверку качества: 24 из 40 — первый блок застыл») и «Пересобрать…» (тот же
// план → подтверждение, ./Rebuild). Вердикт не предлагается: фабрика его не примет (409
// `video_refused`). Коды причины, ворота, строка оценки и строка монтажа — под «подробнее».
import { codeWithWords } from '@/api/reasonRu';
import type { BatchVideos, Video, VideoRefusal } from '@/api/videos';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { dateTimeMsk } from '@/pages/batches/format';

import { REFUSED_VIEW } from './format';
import { penaltiesOf, reasonLeftOut, refusalSentence, scoreLogLines } from './refusal';
import { ScoreBadge } from './Score';

export function RefusedState({
  video,
  batch,
  model,
  refusal,
  rebuilding,
  onRebuild,
}: {
  video: Video;
  /** CC-0125: батч ролика и модель счёта — для значка оценки с разбором. */
  batch: string;
  model: BatchVideos['score_model'];
  refusal: VideoRefusal;
  rebuilding: boolean;
  onRebuild: () => void;
}) {
  const left = reasonLeftOut(refusal);
  const penalties = penaltiesOf(refusal);
  const when = dateTimeMsk(refusal.at);
  return (
    <Card
      aria-labelledby="refused-title"
      data-testid="refused"
      className="grid content-start gap-3"
    >
      <CardHead
        eyebrow="Приёмка"
        title="Вердикт не нужен"
        titleId="refused-title"
        actions={
          <span data-testid="acceptance-verdict">
            <StatusBadge tone={REFUSED_VIEW.tone} tip={REFUSED_VIEW.tip}>
              {REFUSED_VIEW.label}
            </StatusBadge>
          </span>
        }
      />
      <p
        data-testid="refused-reason"
        className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-2.5 text-[13px] font-medium"
      >
        {refusalSentence(refusal)}.
      </p>
      {penalties.length > 1 ? (
        <div className="grid gap-1 text-[13px]" data-testid="refused-penalties">
          <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            Штрафы оценки
            <ScoreBadge
              score={video.score}
              tiers={model.tiers}
              below={model.below}
              batch={batch}
              slug={video.slug}
            />
          </span>
          <ul className="m-0 grid list-none gap-0.5 p-0">
            {penalties.map((p, i) => (
              <li key={i} className="[overflow-wrap:anywhere]">
                {p.raw}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="m-0 text-[13px] text-muted-foreground">
        Ролик собран, но фабрика сама отклонила его после монтажа — в публикацию он не пойдёт и
        вашего решения не ждёт. Его можно пересобрать: перемонтажом или новым сценарием.
        {when ? ` Отказан ${when}.` : ''}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Tip content="Подготовить пересборку: режим, замечания, кадры, которые убрать">
          <Button
            size="sm"
            variant={rebuilding ? 'default' : 'outline'}
            aria-expanded={rebuilding}
            data-testid="refused-rebuild"
            onClick={onRebuild}
          >
            Пересобрать…
          </Button>
        </Tip>
      </div>
      <More>
        {refusal.reason_code ? <span>код причины: {codeWithWords(refusal)}</span> : null}
        {refusal.gate ? <span>проверка: {refusal.gate}</span> : null}
        {refusal.score_line ? <span>оценка: {refusal.score_line}</span> : null}
        {refusal.score && typeof refusal.score.threshold === 'number' ? (
          <span>порог: {refusal.score.threshold}</span>
        ) : null}
        {scoreLogLines(refusal).map((l, i) => (
          <span key={i}>{l}</span>
        ))}
        {left ? <span>монтаж: {left}</span> : null}
        {refusal.at ? <span>отказан: {refusal.at}</span> : null}
        {video.acceptance ? <span>запись: {video.acceptance.entry_id}</span> : null}
        <span>вердикт — POST {video.accept_url}: фабрика ответит 409 video_refused</span>
      </More>
    </Card>
  );
}
