// Оценка ролика (CC-0125, решение пользователя 13.10): значок «A · 86» цвета тира — по клику окно
// «Оценка ролика» с разбором: тир и баллы крупно, старт и порог канала, прошёл ли, остановлен ли
// досрочно; по стадиям — сколько снято и баллы после; находки — жёсткие сверху (красным), штрафы
// по цене, прогноз отдельно («в счёт не идёт»); у находки со временем — «к моменту ▶» (на странице
// ролика — плеер на это время, в других местах — ссылка на ролик с `?t=`); статус цен; строка
// фабрики и коды — под «Подробнее». Цвет тира — токены темы по месту тира в модели (`tierLevel`):
// буква видна всегда, цвет её только подкрепляет.
import { useState, type CSSProperties, type ReactNode } from 'react';
import { Link } from 'react-router';

import { BatchError } from '@/api/batchProblem';
import {
  fmtPoints,
  scoreLabel,
  tierLevel,
  tierOf,
  useVideoScore,
  type ScoreTier,
  type TierLevel,
  type VideoScore,
  type VideoScoreFinding,
  type VideoScoreShort,
  type VideoScoreStage,
} from '@/api/score';
import { InfoDialog } from '@/components/common/InfoDialog';
import { More } from '@/components/common/More';
import { cn } from '@/lib/utils';

import { timecode } from './format';
import {
  cleanNote,
  groupFindings,
  momentHref,
  price,
  pricesText,
  ruleName,
  noteRu,
  shotFile,
  shotOf,
  STAGE_TEXT,
  tierColor,
  whereText,
} from './scoreWords';
import { SkeletonText } from '@/components/common/Skeletons';

const tierStyle = (level: TierLevel) => ({ '--tier': tierColor(level) }) as CSSProperties;

const TIER_BOX =
  'border-[color-mix(in_srgb,var(--tier)_45%,var(--border))] bg-[color-mix(in_srgb,var(--tier)_8%,transparent)] text-[var(--tier)]';

/** Маленькая буква тира (после стадии) — без кнопки. */
function TierMark({ tier, tiers }: { tier: string | null | undefined; tiers: ScoreTier[] }) {
  if (!tier) return null;
  return (
    <span
      data-testid="tier-mark"
      data-tier={tier}
      style={tierStyle(tierLevel(tier, tiers))}
      className={cn('rounded-sm border px-1 font-mono text-[11px] font-semibold', TIER_BOX)}
    >
      {tier}
    </span>
  );
}

type Seek = { onSeek?: (t: number) => void; href: string; close: () => void };

function Moment({ t, seek }: { t: number; seek: Seek }) {
  const cls =
    'inline-flex w-max items-center gap-1 rounded-sm text-xs font-medium text-primary-text underline-offset-4 hover:underline';
  if (seek.onSeek)
    return (
      <button
        type="button"
        data-testid="score-moment"
        data-t={t}
        className={cls}
        onClick={() => {
          seek.onSeek!(t);
          seek.close();
        }}
      >
        к моменту {timecode(t)} ▶
      </button>
    );
  return (
    <Link to={momentHref(seek.href, t)} data-testid="score-moment" data-t={t} className={cls}>
      к моменту {timecode(t)} ▶
    </Link>
  );
}

function Finding({
  f,
  kind,
  cap,
  seek,
}: {
  f: VideoScoreFinding;
  kind: 'hard' | 'penalty' | 'forecast';
  cap: number | null;
  seek: Seek;
}) {
  const where = whereText(f);
  return (
    <li
      data-testid="score-finding"
      data-kind={kind}
      data-rule={f.rule ?? undefined}
      className="grid gap-0.5 border-t py-2 first:border-t-0"
    >
      <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <span className={cn('font-semibold', kind === 'hard' && 'text-danger')}>{ruleName(f)}</span>
        {kind === 'penalty' && typeof f.price === 'number' ? (
          <span className="font-mono text-[13px] font-semibold" data-testid="score-price">
            {price(f.price)}
          </span>
        ) : kind === 'hard' ? (
          <span className="text-xs font-semibold text-danger">ролик — F</span>
        ) : null}
      </span>
      {noteRu(f) ? (
        <span className="text-[13px]" data-testid="score-note-ru">
          {noteRu(f)}
        </span>
      ) : null}
      {where ? (
        <span className="text-xs text-muted-foreground" data-testid="score-where">
          {where}
        </span>
      ) : null}
      {f.capped ? (
        <span className="text-xs text-warning" data-testid="score-capped">
          потолок правила{cap != null ? `: больше ${fmtPoints(Math.abs(cap))} не снимается` : ''}
        </span>
      ) : null}
      {typeof f.t === 'number' ? <Moment t={f.t} seek={seek} /> : null}
      {f.note || f.rule || shotOf(f) ? (
        <More className="mt-0" label="подробнее">
          {f.rule ? <span>правило: {f.rule}</span> : null}
          {f.stage ? <span>стадия: {f.stage}</span> : null}
          {shotOf(f) ? <span>шот: {shotFile(shotOf(f)!)}</span> : null}
          {f.note ? (
            <span data-testid="score-note" className="font-sans">
              {cleanNote(f.note)}
            </span>
          ) : null}
        </More>
      ) : null}
    </li>
  );
}

function Stages({
  stages,
  start,
  tiers,
}: {
  stages: VideoScoreStage[];
  start: number;
  tiers: ScoreTier[];
}) {
  return (
    <ol className="m-0 grid list-none gap-1.5 p-0" data-testid="score-stages">
      {stages.map((s, i) => {
        const after = typeof s.score_after === 'number' ? s.score_after : null;
        const width =
          after == null || start <= 0 ? 0 : Math.max(0, Math.min(100, (after / start) * 100));
        return (
          <li
            key={`${s.stage ?? i}`}
            data-testid="score-stage"
            data-stage={s.stage ?? undefined}
            className="grid gap-1"
          >
            <span className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span>{s.label_ru || (s.stage && STAGE_TEXT[s.stage]) || 'стадия'}</span>
              <span className="flex items-center gap-1.5 font-mono text-xs">
                <span className="text-muted-foreground" data-testid="score-stage-charged">
                  {typeof s.charged === 'number' && s.charged !== 0
                    ? price(s.charged)
                    : 'без снятий'}
                </span>
                {after != null ? <b className="font-semibold">→ {fmtPoints(after)}</b> : null}
                <TierMark tier={s.tier_after} tiers={tiers} />
              </span>
            </span>
            <span aria-hidden className="block h-1.5 overflow-hidden rounded-full bg-muted">
              <span
                className="block h-full rounded-full bg-[var(--tier)]"
                style={{ ...tierStyle(tierLevel(s.tier_after, tiers)), width: `${width}%` }}
              />
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function Section({
  title,
  testId,
  tone,
  children,
}: {
  title: string;
  testId: string;
  tone?: 'danger';
  children: ReactNode;
}) {
  return (
    <section
      data-testid={testId}
      className={cn(
        'grid gap-1 rounded-sm border p-3',
        tone === 'danger' &&
          'border-[color-mix(in_srgb,var(--danger)_45%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_6%,var(--card))]',
      )}
    >
      <h3 className={cn('m-0 text-[13px] font-semibold', tone === 'danger' && 'text-danger')}>
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Разбор оценки: всё, что `VideoScore` знает о ролике. */
export function ScoreBody({ score, seek }: { score: VideoScore; seek: Seek }) {
  const tiers = score.tiers;
  const tier = score.tier ?? tierOf(score.score, tiers);
  const level = tierLevel(tier, tiers);
  const start = typeof score.start === 'number' ? score.start : 100;
  const { hard, penalties, forecast } = groupFindings(score.findings);
  const capOf = (f: VideoScoreFinding) => {
    const r = f.rule ? (score.by_rule as Record<string, { cap?: number | null }>)[f.rule] : null;
    return typeof r?.cap === 'number' ? r.cap : null;
  };
  const prices = pricesText(score.prices_status);
  return (
    <div className="grid gap-3 text-[13px]" data-testid="score-body" data-tier={tier ?? undefined}>
      <div className="flex flex-wrap items-center gap-4">
        <span
          data-testid="score-big"
          style={tierStyle(level)}
          className={cn(
            'grid min-w-[84px] justify-items-center rounded-md border px-3 py-1.5 leading-none',
            TIER_BOX,
          )}
        >
          <span className="font-display text-[40px] font-semibold">{tier ?? '?'}</span>
          <span className="font-mono text-[15px] font-semibold">
            {typeof score.score === 'number' ? fmtPoints(score.score) : '—'}
          </span>
        </span>
        <span className="grid gap-0.5">
          <span
            data-testid="score-passed"
            data-passed={score.passed == null ? undefined : String(score.passed)}
          >
            {score.passed === true ? (
              <b className="font-semibold text-success">Прошёл порог канала</b>
            ) : score.passed === false ? (
              <b className="font-semibold text-danger">Не прошёл порог канала</b>
            ) : (
              <b className="font-semibold">Порог не сравнивали</b>
            )}
          </span>
          <span className="text-muted-foreground" data-testid="score-frame">
            старт {fmtPoints(start)}
            {typeof score.threshold === 'number'
              ? ` · порог канала ${fmtPoints(score.threshold)}`
              : ''}
            {typeof score.score === 'number' ? ` · итог ${fmtPoints(score.score)}` : ''}
          </span>
          {score.stopped_at ? (
            <span className="text-warning" data-testid="score-stopped">
              Остановлен досрочно: {score.stopped_at_ru || score.stopped_at} — дальше баллы не
              считали.
            </span>
          ) : null}
        </span>
      </div>
      {score.model_error ? (
        <p className="m-0 text-warning" data-testid="score-model-error">
          Таблица цен фабрики не читается — цвета тиров могут быть неточны.
        </p>
      ) : null}
      {hard.length ? (
        <Section
          title="Жёсткие находки — ролик F при любых баллах"
          testId="score-hard"
          tone="danger"
        >
          <ul className="m-0 grid list-none p-0">
            {hard.map((f, i) => (
              <Finding key={i} f={f} kind="hard" cap={null} seek={seek} />
            ))}
          </ul>
        </Section>
      ) : null}
      {score.stages.length ? (
        <Section title="По стадиям" testId="score-stages-block">
          <Stages stages={score.stages} start={start} tiers={tiers} />
        </Section>
      ) : score.source === '05' ? (
        <p className="m-0 text-muted-foreground" data-testid="score-no-stages">
          По стадиям фабрика оценку не разложила — разбор взят из итога монтажа.
        </p>
      ) : null}
      <Section
        title={penalties.length ? `Штрафы — ${penalties.length}, дорогие первыми` : 'Штрафов нет'}
        testId="score-penalties"
      >
        {penalties.length ? (
          <ul className="m-0 grid list-none p-0">
            {penalties.map((f, i) => (
              <Finding key={i} f={f} kind="penalty" cap={capOf(f)} seek={seek} />
            ))}
          </ul>
        ) : (
          <p className="m-0 text-muted-foreground">Фабрика ничего не сняла.</p>
        )}
      </Section>
      {forecast.length ? (
        <Section title="Прогноз — в счёт не идёт" testId="score-forecast">
          <p className="m-0 text-xs text-muted-foreground">
            Так фабрика оценила бы ролик на следующих стадиях; баллы от этого не меняются.
          </p>
          <ul className="m-0 grid list-none p-0">
            {forecast.map((f, i) => (
              <Finding key={i} f={f} kind="forecast" cap={null} seek={seek} />
            ))}
          </ul>
        </Section>
      ) : null}
      {prices ? (
        <p className="m-0 text-xs text-muted-foreground" data-testid="score-prices">
          {prices}
        </p>
      ) : null}
      <More className="mt-0">
        {score.score_line ? <span data-testid="score-line">{score.score_line}</span> : null}
        <span>
          источник: {score.source === '05' ? '05 (итог монтажа)' : (score.path ?? score.source)}
        </span>
        {score.forecast_ignored ? (
          <span>прогнозных находок вне счёта: {score.forecast_ignored}</span>
        ) : null}
        {score.model_error ? <span>{score.model_error}</span> : null}
      </More>
    </div>
  );
}

function ScoreLoad({
  batch,
  slug,
  seek,
  open,
}: {
  batch: string;
  slug: string;
  seek: Seek;
  open: boolean;
}) {
  const q = useVideoScore(batch, slug, open);
  if (q.isPending) return <SkeletonText lines={6} label="Читаю разбор оценки…" />;
  if (q.isError)
    return (
      <div role="alert" className="grid gap-1 text-[13px]" data-testid="score-error">
        <p className="m-0 text-danger">
          {q.error instanceof BatchError && q.error.problem
            ? q.error.problem.message
            : 'Разбор оценки не прочитать — проверьте, что API фабрики запущен.'}
        </p>
        <More className="mt-0">
          <span>{q.error instanceof Error ? q.error.message : String(q.error)}</span>
        </More>
      </div>
    );
  return <ScoreBody score={q.data} seek={seek} />;
}

/**
 * Значок оценки ролика: «A · 86» цвета тира — кнопка, открывает разбор. Без оценки — ничего.
 * `onSeek` — на странице ролика (плеер на время находки); иначе «к моменту» ведёт на `href`.
 */
export function ScoreBadge({
  score,
  tiers,
  below = 'F',
  batch,
  slug,
  onSeek,
  href,
  className,
}: {
  score: VideoScoreShort | null | undefined;
  tiers: readonly ScoreTier[] | null | undefined;
  below?: string | null;
  batch: string;
  slug: string;
  onSeek?: (t: number) => void;
  /** Страница ролика для «к моменту ▶» вне её; по умолчанию — `/videos?batch=…&v=…`. */
  href?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!score || (score.tier == null && score.score == null)) return null;
  const tier = score.tier ?? tierOf(score.score, tiers, below ?? 'F');
  const level = tierLevel(tier, tiers, below ?? 'F');
  const label = scoreLabel({ tier, score: score.score });
  const to = href ?? `/videos?${new URLSearchParams({ batch, v: slug }).toString()}`;
  const spoken = `Оценка ролика: тир ${tier ?? 'неизвестен'}${typeof score.score === 'number' ? `, ${fmtPoints(score.score)} баллов` : ''}${score.passed === false ? ', порог не прошёл' : ''} — подробнее`;
  return (
    <InfoDialog
      open={open}
      onOpenChange={setOpen}
      tip="Оценка ролика — подробнее"
      title="Оценка ролика"
      testId="score-dialog"
      wide
      trigger={
        <button
          type="button"
          data-testid="score-badge"
          data-tier={tier ?? undefined}
          data-level={level ?? undefined}
          data-passed={score.passed == null ? undefined : String(score.passed)}
          aria-label={spoken}
          style={tierStyle(level)}
          className={cn(
            'inline-flex w-max items-center rounded-sm border px-1.5 py-0.5 font-mono text-xs font-semibold whitespace-nowrap outline-offset-2 hover:bg-[color-mix(in_srgb,var(--tier)_16%,transparent)]',
            TIER_BOX,
            className,
          )}
        >
          {label}
        </button>
      }
    >
      {open ? (
        <ScoreLoad
          batch={batch}
          slug={slug}
          open={open}
          seek={{ onSeek, href: to, close: () => setOpen(false) }}
        />
      ) : null}
    </InfoDialog>
  );
}
