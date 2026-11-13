// Блок «Темы» карточки батча (CC-0092): что нашёл трендхантер и что с каждой темой решили этапы
// дальше — с первого законченного этапа. Строка темы: название, сигнал, состояние одной строкой,
// источники; клик — подробности (сцены, факт и источник, вердикты проверок, футаж). Отсеянные
// при подборе тем — отдельным свёрнутым списком с причиной. Коды и пути — только под «подробнее».
import { useId, useState, type ReactNode } from 'react';

import { problemCode } from '@/api/batchProblem';
import {
  codeWithWords,
  factFailureGroups,
  NO_REASON_TEXT,
  reasonWords,
  undescribedTail,
} from '@/api/reasonRu';
import {
  useBatchTopic,
  type BatchTopic,
  type BatchTopics,
  type SkippedTopic,
  type TopicSummary,
} from '@/api/batchTopics';
import { scenesText } from '@/api/sensitivityScenes';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';

import { dateTimeMsk, timeMsk } from './format';
import {
  refillAdmitted,
  refillDetails,
  refillLine,
  refillText,
  refillTip,
  repairDetails,
  repairLine,
  repairsText,
  roundLine,
  type TopicRefill,
} from './funnelText';
import { Refusal } from './parts';
import {
  countsText,
  footageLine,
  kindText,
  PHASE_TIP,
  PHASE_TONE,
  PLACE_TEXT,
  quotaText,
  NB,
  ofText,
  sourceLabel,
} from './topicsText';
import { SkeletonText } from '@/components/common/Skeletons';

const SIGNAL_TIP =
  'Сигнал — популярность темы по оценке фабрики при подборе тем (0–100): чем выше, тем громче тема сейчас';

const linkClass =
  'text-primary-text underline-offset-4 hover:underline [overflow-wrap:anywhere] focus-visible:underline';

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className={linkClass}>
      {children}
    </a>
  );
}

function Signal({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  return (
    <Tip content={SIGNAL_TIP}>
      <span
        tabIndex={0}
        data-testid="topic-signal"
        className="font-mono text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
      >
        сигнал{NB}
        {Math.round(score)}
      </span>
    </Tip>
  );
}

function StateBadge({ state }: { state: TopicSummary['state'] }) {
  return (
    <span data-testid="topic-state" data-phase={state.phase} className="max-w-full min-w-0">
      {/* CC-0172: строки фабрики бывают длинными («…; ремонт не удался») — переносятся. */}
      <StatusBadge
        tone={PHASE_TONE[state.phase]}
        tip={PHASE_TIP[state.phase]}
        className="max-w-full whitespace-normal"
      >
        {state.line}
      </StatusBadge>
    </span>
  );
}

/** CC-0172: пометка темы, которую батч добрал из-под шорт-листа. */
function RefillMark({ refill }: { refill: TopicRefill | null | undefined }) {
  if (!refill || !refillAdmitted(refill)) return null;
  return (
    <span data-testid="topic-refill">
      <StatusBadge tone="live" tip={refillTip(refill)}>
        добор
      </StatusBadge>
    </span>
  );
}

/** CC-0172: что добор сделал с темой, которую не добрал (отказ с причиной и т. п.). */
function RefillNote({ refill, line }: { refill: TopicRefill | null | undefined; line?: string }) {
  const text = refillLine(refill);
  // Строка состояния фабрики уже говорит о доборе («…; добор: отказ (…)») — не повторяем.
  if (!text || line?.includes('добор')) return null;
  return (
    <span className="text-xs text-muted-foreground" data-testid="topic-refill-note">
      {text}
    </span>
  );
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid min-w-0 content-start gap-1">
      <h5 className="m-0 text-xs font-semibold tracking-[.04em] text-muted-foreground uppercase">
        {title}
      </h5>
      {children}
    </section>
  );
}

const yes = (v: boolean | null | undefined, ok: string, bad: string) =>
  v == null ? null : v ? ok : bad;

function Checks({ s }: { s: TopicSummary | null }) {
  const rows: { what: string; text: string; ok: boolean | null }[] = [];
  const c = s?.compliance;
  if (c) {
    rows.push({
      what: 'Проверка темы',
      text: [PLACE_TEXT[c.place], reasonWords(c)].filter(Boolean).join(': '),
      ok: c.place === 'batch' ? true : c.place === 'refused' ? false : null,
    });
    if (c.rights_reason) rows.push({ what: 'Права', text: c.rights_reason, ok: null });
    if (c.sensitivity_flagged) {
      // CC-0170: на каких сценах стоит флаг — «сцены s2, s3» / «вся тема»; null — не пишем.
      const scenes = scenesText(c.sensitivity_scenes, s?.topic_id);
      rows.push({
        what: 'Чувствительная тема',
        text: [c.sensitivity_notes ?? 'отмечена проверкой', scenes].filter(Boolean).join('; '),
        ok: false,
      });
    }
  }
  for (const sc of s?.scripts ?? []) {
    const one = (s?.scripts?.length ?? 0) > 1 ? ` ${sc.scene_id ?? ''}`.trimEnd() : '';
    if (sc.compliance)
      rows.push({
        what: `Сценарий${one}`,
        text: yes(sc.compliance.passes, 'прошёл проверку', 'не прошёл проверку') ?? 'проверен',
        ok: sc.compliance.passes ?? null,
      });
    if (sc.video)
      rows.push({
        what: 'Монтаж',
        text: sc.video.slug
          ? sc.video.qc_passed === false
            ? 'ролик собран, проверка качества не пройдена'
            : 'ролик собран'
          : (sc.video.refused?.reason ?? 'ролик не собран'),
        ok: sc.video.slug ? sc.video.qc_passed !== false : false,
      });
    if (sc.frame?.gate)
      rows.push({
        what: 'Проверка кадров',
        text:
          sc.frame.gate === 'pass'
            ? 'кадры прошли'
            : sc.frame.gate === 'reject'
              ? `не прошли${reasonWords(sc.frame) ? `: ${reasonWords(sc.frame)}` : ''}`
              : 'проверка не закончена',
        ok: sc.frame.gate === 'pass' ? true : sc.frame.gate === 'reject' ? false : null,
      });
    // CC-0172: ремонт ролика после судьи кадров — своей строкой, без «что:» (она уже итог).
    const repair = repairLine(sc.frame?.repair);
    if (repair) rows.push({ what: '', text: repair, ok: sc.frame?.repair?.outcome === 'repaired' });
  }
  if (!rows.length) return <p className="m-0 text-muted-foreground">Тему ещё не проверяли.</p>;
  return (
    <ul className="m-0 grid list-none gap-1 p-0" data-testid="topic-checks">
      {rows.map((r, i) => (
        <li key={i}>
          <span
            aria-hidden
            className={cn(
              'mr-1.5 font-mono',
              r.ok === true
                ? 'text-success'
                : r.ok === false
                  ? 'text-danger'
                  : 'text-muted-foreground',
            )}
          >
            {r.ok === true ? '✓' : r.ok === false ? '✕' : '·'}
          </span>
          {r.what ? <span className="text-muted-foreground">{r.what}: </span> : null}
          <span data-testid={r.what ? undefined : 'topic-repair'}>{r.text}</span>
        </li>
      ))}
    </ul>
  );
}

function Fact({ t }: { t: BatchTopic }) {
  const f = t.fact;
  const chosen = f.chosen[0];
  const best = f.candidates.find((c) => c.passes) ?? null;
  const fact = chosen ?? best;
  const url = fact?.url ?? f.probe?.article_url ?? null;
  const source = fact?.source ?? f.probe?.source ?? null;
  return (
    <div className="grid gap-1" data-testid="topic-fact">
      {fact?.text ? (
        <p className="m-0">«{fact.text}»</p>
      ) : (
        <p className="m-0 text-muted-foreground">
          {f.probe?.has_fact === false
            ? `Факта нет${f.probe.detail ? `: ${f.probe.detail}` : ''}`
            : 'Факт ещё не выбран.'}
        </p>
      )}
      {source || url ? (
        <p className="m-0 text-muted-foreground">
          источник: {url ? <Ext href={url}>{source ?? sourceLabel({ url })}</Ext> : source}
        </p>
      ) : null}
      {chosen ? <p className="m-0 text-xs text-muted-foreground">этот факт взял сценарий</p> : null}
      {f.search && f.search.found != null ? (
        <p className="m-0 text-xs text-muted-foreground">
          кандидатов{NB}
          {f.search.found}, проверку прошли {ofText(f.search.passing ?? 0, f.search.found)}
        </p>
      ) : null}
      {f.support?.detail ? (
        <p className="m-0 text-xs text-muted-foreground">подтверждение: {f.support.detail}</p>
      ) : null}
      <FactFailed t={t} />
    </div>
  );
}

/** Кандидаты факта, не прошедшие проверку (CC-0119): причины словами фабрики, код — в подсказке. */
function FactFailed({ t }: { t: BatchTopic }) {
  const failed = t.fact.candidates.filter((c) => c.passes !== true && c.failures.length);
  if (!failed.length) return null;
  return (
    <div className="mt-1 space-y-1 text-xs" data-testid="fact-failed">
      <p className="m-0 font-medium">Отклонённые кандидаты — не прошли проверку факта:</p>
      <ul className="m-0 list-none space-y-1 p-0 pl-2">
        {failed.map((c, i) => {
          const { described, undescribed } = factFailureGroups(c);
          return (
            <li
              key={i}
              className="flex min-w-0 gap-1.5 text-muted-foreground"
              data-testid="fact-failed-candidate"
            >
              <span aria-hidden="true">✕</span>
              <span className="min-w-0 break-words">
                {c.text ? <>«{c.text}» — </> : null}
                {described.map((r, j) => (
                  <span key={r.code}>
                    {j ? '; ' : null}
                    <Tip content={`код проверки факта: ${r.code}`}>
                      <span
                        tabIndex={0}
                        data-testid="fact-failure"
                        data-code={r.code}
                        className="underline decoration-dotted underline-offset-2"
                      >
                        {r.words}
                      </span>
                    </Tip>
                  </span>
                ))}
                {undescribed.length ? (
                  <>
                    {described.length ? ' ' : null}
                    <Tip
                      content={`${undescribed.length > 1 ? 'коды' : 'код'} проверки факта: ${undescribed.join(', ')}`}
                    >
                      <span
                        tabIndex={0}
                        data-testid="fact-failure-undescribed"
                        data-codes={undescribed.join(' ')}
                        className="underline decoration-dotted underline-offset-2"
                      >
                        {described.length ? undescribedTail(undescribed.length) : NO_REASON_TEXT}
                      </span>
                    </Tip>
                  </>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Footage({ t }: { t: BatchTopic }) {
  const s = t.summary;
  const line = s ? footageLine(s) : null;
  const ix = s?.footage.indexer;
  const searches = Object.values(t.searches).reduce((a, b) => a + b, 0);
  return (
    <div className="grid gap-1" data-testid="topic-footage">
      <p className="m-0">{line ?? 'Футаж ещё не мерили.'}</p>
      {ix ? (
        <p className="m-0 text-xs text-muted-foreground">
          {ix.indexed_at
            ? `индексатор разметил ${dateTimeMsk(ix.indexed_at)}`
            : 'индексатор разметил'}
          {ix.depth?.usable_seconds != null
            ? ` · годного видео ≈${NB}${Math.round(ix.depth.usable_seconds)}${NB}с`
            : ''}
          {ix.failed_downloads ? ` · не скачалось${NB}${ix.failed_downloads}` : ''}
          {ix.substituted ? ' · тема взята из резерва на замену' : ''}
        </p>
      ) : s?.footage.pool ? (
        <p className="m-0 text-xs text-muted-foreground">
          мера при подборе тем, разметка футажа ещё не была
        </p>
      ) : null}
      {searches ? (
        <p className="m-0 text-xs text-muted-foreground">
          поисков YouTube на тему:{NB}
          {searches}
        </p>
      ) : null}
      {t.videos.length ? (
        <ul className="m-0 grid list-none gap-0.5 p-0 text-xs">
          {t.videos.slice(0, 5).map((v, i) => (
            <li key={v.video_id ?? i} className="min-w-0">
              {v.url ? <Ext href={v.url}>{v.title ?? v.url}</Ext> : (v.title ?? '—')}
              {v.channel_title ? (
                <span className="text-muted-foreground"> · {v.channel_title}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Scenes({ t }: { t: BatchTopic }) {
  if (!t.scenes.length) return <p className="m-0 text-muted-foreground">Сцен нет.</p>;
  return (
    <ol className="m-0 grid gap-1 pl-5" data-testid="topic-scenes">
      {t.scenes.map((sc, i) => (
        <li key={sc.scene_id ?? i}>
          {sc.description ?? '—'}
          {sc.tags.length ? (
            <span className="text-xs text-muted-foreground"> · {sc.tags.join(', ')}</span>
          ) : null}
          {sc.source_url ? (
            <>
              {' '}
              <span className="text-xs">
                <Ext href={sc.source_url}>видео</Ext>
              </span>
            </>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

/** Подробности темы — по клику на неё; без опроса, обновляется вместе с экраном батча. */
export function TopicDetails({ batch, topicId }: { batch: string; topicId: string }) {
  const q = useBatchTopic(batch, topicId);
  if (q.isPending) return <SkeletonText lines={4} label="Читаю тему…" />;
  if (q.isError && !q.data) return <Refusal error={q.error} title="Тема не читается" />;
  const t = q.data;
  const s = t.summary;
  const refill = s?.refill ?? t.skipped?.refill ?? null;
  return (
    <div data-testid="topic-details" className="grid gap-3 text-[13px]">
      {t.skipped ? (
        <p className="m-0">
          Отсеяна при подборе тем: {t.skipped.state.line.replace(/^отсеяна:\s*/, '')}.
          {t.fact.probe?.detail ? ` ${t.fact.probe.detail}.` : ''}
        </p>
      ) : null}
      <div className="grid gap-3 md:grid-cols-2">
        <Part title="Сцены">
          <Scenes t={t} />
        </Part>
        <Part title="Факт и источник">
          <Fact t={t} />
        </Part>
        <Part title="Проверки">
          <Checks s={s} />
        </Part>
        <Part title="Футаж">
          <Footage t={t} />
        </Part>
        {refill ? (
          <Part title="Добор">
            <p className="m-0" data-testid="topic-refill-detail">
              {refillAdmitted(refill)
                ? `${refillTip(refill)}.`
                : `${(refillLine(refill) ?? 'добор').replace(/^добор: /, '')}.`.replace(/^./, (c) =>
                    c.toUpperCase(),
                  )}
            </p>
          </Part>
        ) : null}
      </div>
      <More className="mt-0" label="Подробнее о теме">
        <span>тема {t.topic_id}</span>
        {t.title_ref.kind ? <span>вид {t.title_ref.kind}</span> : null}
        {s?.state.reason_code ? <span>код состояния {codeWithWords(s.state)}</span> : null}
        {s?.compliance?.verdict ? <span>вердикт 02: {s.compliance.verdict}</span> : null}
        {s?.compliance?.reason_code ? <span>код 02: {codeWithWords(s.compliance)}</span> : null}
        {s?.compliance?.reason ? <span>02: {s.compliance.reason}</span> : null}
        {t.fact.support?.state ? <span>support_check: {t.fact.support.state}</span> : null}
        {t.fact.candidates
          .filter((c) => c.failures.length)
          .map((c, i) => (
            <span key={i}>
              кандидат «{c.text}»: {c.failures.join(', ')}
            </span>
          ))}
        {(s?.footage.indexer?.warnings ?? []).map((w) => (
          <span key={w}>01b: {w}</span>
        ))}
        {(s?.scripts ?? []).map((sc, i) => (
          <span key={i}>
            сценарий {sc.script_id ?? '—'}
            {sc.video?.slug ? `, ролик ${sc.video.slug}` : ''}
            {sc.frame?.reason_code ? `, кадры: ${sc.frame.reason_code}` : ''}
            {sc.frame?.reason ? ` — ${sc.frame.reason}` : ''}
          </span>
        ))}
        {(s?.scripts ?? []).flatMap((sc, i) =>
          repairDetails(sc.frame?.repair).map((line, j) => <span key={`r${i}-${j}`}>{line}</span>),
        )}
        {refillDetails(refill).map((line, i) => (
          <span key={`f${i}`}>{line}</span>
        ))}
      </More>
    </div>
  );
}

function TopicRow({
  batch,
  t,
  open,
  onToggle,
}: {
  batch: string;
  t: TopicSummary;
  open: boolean;
  onToggle: () => void;
}) {
  const panel = useId();
  const kind = kindText(t.kind ?? t.type);
  return (
    <li
      data-testid="topic"
      data-topic={t.topic_id ?? undefined}
      className="grid min-w-0 gap-1.5 border-t py-2.5 first:border-t-0 first:pt-0"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          disabled={!t.topic_id}
          onClick={onToggle}
          data-testid="topic-open"
          className="flex min-w-0 flex-1 basis-[14rem] items-baseline gap-2 text-left"
        >
          <span
            aria-hidden
            className={cn(
              'inline-block w-3 shrink-0 text-center text-[19px] leading-[13px] font-semibold text-foreground transition-transform',
              open && 'rotate-90',
            )}
          >
            ›
          </span>
          <span className="min-w-0 [overflow-wrap:anywhere]">
            <b className="font-semibold">{t.title ?? 'Без названия'}</b>
            {kind || t.year ? (
              <span className="ml-2 text-xs text-muted-foreground">
                {[kind, t.year].filter(Boolean).join(' · ')}
              </span>
            ) : null}
          </span>
        </button>
        <Signal score={t.popularity_score} />
        <RefillMark refill={t.refill} />
        <StateBadge state={t.state} />
      </div>
      {refillLine(t.refill) && !t.state.line.includes('добор') ? (
        <p className="m-0 pl-5">
          <RefillNote refill={t.refill} line={t.state.line} />
        </p>
      ) : null}
      {t.sources.length ? (
        <p className="m-0 pl-5 text-xs text-muted-foreground" data-testid="topic-sources">
          {t.sources.length === 1 ? 'источник: ' : 'источники: '}
          {t.sources.slice(0, 4).map((s, i) => (
            <span key={s.url}>
              {i ? ', ' : ''}
              <Ext href={s.url}>{sourceLabel(s)}</Ext>
            </span>
          ))}
          {t.sources.length > 4 ? ` и ещё ${t.sources.length - 4}` : ''}
        </p>
      ) : null}
      <div id={panel} hidden={!open} className="pl-5">
        {open && t.topic_id ? <TopicDetails batch={batch} topicId={t.topic_id} /> : null}
      </div>
    </li>
  );
}

function Skipped({ list }: { list: SkippedTopic[] }) {
  if (!list.length) return null;
  return (
    <details data-testid="topics-skipped" className="text-[13px]">
      <summary className="w-max cursor-pointer text-primary-text">
        Отсеяны при подборе тем:{NB}
        {list.length}
      </summary>
      <ul className="m-0 mt-1.5 grid list-none gap-1 p-0">
        {list.map((s, i) => (
          <li
            key={s.topic_id ?? i}
            data-testid="skipped-topic"
            className="flex flex-wrap items-center gap-x-3 gap-y-1"
          >
            <b className="min-w-0 font-semibold [overflow-wrap:anywhere]">{s.title ?? '—'}</b>
            <Signal score={s.popularity_score} />
            <RefillMark refill={s.refill} />
            <span className="text-muted-foreground" data-testid="skipped-state">
              {s.state.line}
            </span>
            <RefillNote refill={s.refill} line={s.state.line} />
          </li>
        ))}
      </ul>
      <More className="mt-1.5" label="Подробнее об отсеянных">
        {list.map((s, i) => (
          <span key={s.topic_id ?? i}>
            {s.topic_id}: {codeWithWords(s) ?? '—'}
            {s.reason ? ` — ${s.reason}` : ''}
            {refillDetails(s.refill).length ? ` · ${refillDetails(s.refill).join(' · ')}` : ''}
          </span>
        ))}
      </More>
    </details>
  );
}

/**
 * CC-0172: что батч спас — ремонт роликов после судьи кадров и добор тем ниже шорт-листа:
 * «Добор ниже шорт-листа: подано 1, поисков 4», раунды — по раскрытию. Старый батч (оба поля
 * null) — ничего.
 */
function Funnel({ t }: { t: BatchTopics }) {
  const repairs = repairsText(t.repairs);
  const refill = refillText(t.refill);
  if (!repairs && !refill) return null;
  const titles = new Map<string, string>();
  for (const x of [...t.topics, ...t.skipped])
    if (x.topic_id) titles.set(x.topic_id, x.title ?? x.topic_id);
  const title = (id: string) => titles.get(id) ?? id;
  const rounds = t.refill?.rounds ?? [];
  return (
    <div
      className="grid min-w-0 gap-1 text-[13px] [overflow-wrap:anywhere]"
      data-testid="topics-funnel"
    >
      {repairs ? (
        <p className="m-0" data-testid="topics-repairs">
          <span className="text-muted-foreground">Ремонт роликов после проверки кадров: </span>
          {repairs}
        </p>
      ) : null}
      {refill ? (
        rounds.length ? (
          <details data-testid="topics-refill">
            <summary className="cursor-pointer">
              <span className="text-muted-foreground">Добор ниже шорт-листа: </span>
              <span data-testid="topics-refill-text">{refill}</span>
              <span className="text-primary-text">
                {' '}
                · раундов{'\u00a0'}
                {rounds.length}
              </span>
            </summary>
            <ol className="m-0 mt-1 grid gap-0.5 pl-5 text-xs">
              {rounds.map((r, i) => (
                <li key={i} data-testid="refill-round" className="[overflow-wrap:anywhere]">
                  {timeMsk(r.at) ? (
                    <span className="text-muted-foreground">{timeMsk(r.at)} · </span>
                  ) : null}
                  {roundLine(r, i, title)}
                </li>
              ))}
            </ol>
            <More className="mt-1" label="Подробнее о доборе">
              <span>{t.refill?.record}</span>
              {rounds.map((r, i) => (
                <span key={i}>
                  {r.round ?? i + 1}: {r.outcome ?? '—'}
                  {r.at_code ? `, ${r.at_code}` : ''}
                  {r.queue.length ? `, очередь ${r.queue.join(', ')}` : ''}
                  {r.budget_line ? ` · ${r.budget_line}` : ''}
                </span>
              ))}
            </More>
          </details>
        ) : (
          <p className="m-0" data-testid="topics-refill">
            <span className="text-muted-foreground">Добор ниже шорт-листа: </span>
            <span data-testid="topics-refill-text">{refill}</span>
          </p>
        )
      ) : null}
    </div>
  );
}

function Quota({ t }: { t: BatchTopics }) {
  const q = t.search_quota;
  const text = quotaText(q);
  if (!text) return null;
  const reset = timeMsk(q?.resets_at);
  return (
    <p className="m-0 text-xs text-muted-foreground" data-testid="topics-quota">
      <Tip
        content={`Поиск YouTube (search.list) за этот батч и дневная квота канала${reset ? `; квота обновится в ${reset} по Москве` : ''}`}
      >
        <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
          Поиск YouTube:
        </span>
      </Tip>{' '}
      {text}
    </p>
  );
}

/**
 * Блок «Темы»: `topics` — ответ сводки (из карточки батча, она же даёт итоги кадрам киноленты);
 * `error` — отказ сводки. Пока трендхантер не закончил — блока нет.
 */
export function TopicsBlock({
  batch,
  topics,
  error,
  id,
}: {
  batch: string;
  topics: BatchTopics | undefined;
  error: unknown;
  id?: string;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (!topics) {
    if (!error) return null;
    return (
      <section id={id} tabIndex={-1} data-testid="topics" className="mt-3 scroll-mt-24">
        <Refusal error={error} title="Темы батча не читаются" />
        {problemCode(error) === 'stage_broken' ? (
          <p
            className="mt-1.5 mb-0 text-[13px] text-muted-foreground"
            data-testid="topics-broken-hint"
          >
            Темы появятся сами, когда этап перезапишет свои данные. Если батч уже закрыт или ошибка
            не уходит — попросите оператора разобраться.
          </p>
        ) : null}
      </section>
    );
  }
  if (!topics.trend_hunter_done) return null;
  const counts = countsText(topics);
  return (
    <section
      id={id}
      tabIndex={-1}
      data-testid="topics"
      aria-label="Темы батча"
      className="mt-3 grid scroll-mt-24 gap-2 rounded-sm border p-3 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="m-0 text-[13px] font-semibold">
          Темы
          <span className="ml-2 font-normal text-muted-foreground">
            {topics.topics.length ? counts : 'в работу не взято ни одной'}
          </span>
        </h3>
        <Quota t={topics} />
      </div>
      {error ? <Refusal error={error} title="Темы не обновились — показаны прежние" /> : null}
      <Funnel t={topics} />
      {topics.topics.length ? (
        <ul className="m-0 grid list-none gap-0 p-0 text-[13px]">
          {topics.topics.map((t, i) => (
            <TopicRow
              key={t.topic_id ?? i}
              batch={batch}
              t={t}
              open={!!t.topic_id && open === t.topic_id}
              onToggle={() => setOpen((v) => (v === t.topic_id ? null : (t.topic_id ?? null)))}
            />
          ))}
        </ul>
      ) : null}
      <Skipped list={topics.skipped} />
      <More className="mt-0" label="Подробнее о данных этапов">
        {topics.files.map((f) => (
          <span key={f.file}>
            {f.file}: {f.present ? `записан ${f.written_at ?? ''}` : 'ещё нет'}
          </span>
        ))}
        {topics.search_quota?.summary_line ? <span>{topics.search_quota.summary_line}</span> : null}
      </More>
    </section>
  );
}
