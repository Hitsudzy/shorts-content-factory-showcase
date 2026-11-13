// Внутри открытого батча (CC-0045, `GET /api/batches/{batch}`): что ждёт человека, вопросы
// канала, процессы исполнителя с «жив», остановки и продолжения, блок пересборки и лента
// событий. Номера процессов, pid и пути — только под «подробнее»; коды стадий, причин и
// источников — словами (CC-0118, `words.ts`), сами коды — тоже под «подробнее».
import type { ReactNode } from 'react';

import { useBatch, type BatchDetail, type BatchQuestion } from '@/api/batches';
import type { BatchTopics } from '@/api/batchTopics';
import { readableSlug, useVideos, videoTitle } from '@/api/videos';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';

import { EventsFeed } from './EventsFeed';
import { dateTimeMsk, whoText } from './format';
import { batchIdIso } from './going';
import { Refusal } from './parts';
import { exitText, nameOf, needsLine, tookText } from './words';

type Rec = Record<string, unknown>;
const str = (v: unknown) => (typeof v === 'string' && v ? v : null);
const rec = (v: unknown): Rec | null =>
  typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Rec) : null;

function Block({
  title,
  testId,
  children,
}: {
  title: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <section data-testid={testId} className="mt-3 grid gap-1.5">
      <h3 className="text-[13px] font-semibold">{title}</h3>
      {children}
    </section>
  );
}

/** Что исполнитель отложил до человека (`needs_human`): из run-state, иначе — строки списка. */
function NeedsHuman({ detail, fallback }: { detail?: BatchDetail; fallback: string[] }) {
  const rows = (detail?.state?.needs_human ?? []).map((h) => {
    const stage = str(h.stage);
    const took = str(h.took);
    const question = str(h.question);
    return {
      stage,
      text: question ?? (took ? `${nameOf(stage)}: ${tookText(took)}` : nameOf(stage)),
      took: question && took ? tookText(took) : null,
      raw: [stage, str(h.key), took].filter(Boolean).join(' · '),
    };
  });
  const items = rows.length
    ? rows
    : fallback.map((s) => ({
        stage: null,
        text: needsLine(s),
        took: null as string | null,
        raw: needsLine(s) !== s ? s : '',
      }));
  if (!items.length) return null;
  const raw = items.map((h) => h.raw).filter(Boolean);
  return (
    <Block title="Ждёт вас" testId="needs-human">
      <ul className="m-0 grid list-none gap-1.5 p-0">
        {items.map((h, i) => (
          <li
            key={i}
            className="rounded-sm border border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_7%,var(--card))] p-2.5 text-[13px]"
          >
            {h.text}
            {h.took ? (
              <span className="block text-xs text-muted-foreground">
                исполнитель пошёл дальше: {h.took}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {raw.length ? (
        <More className="mt-0">
          {raw.map((r, i) => (
            <span key={i}>{r}</span>
          ))}
        </More>
      ) : null}
    </Block>
  );
}

function Questions({ qs }: { qs: BatchQuestion[] }) {
  if (!qs.length) return null;
  return (
    <Block title="Вопросы канала" testId="batch-questions">
      <ul className="m-0 grid list-none gap-1.5 p-0">
        {qs.map((q) => (
          <li key={q.id} className="grid gap-1 rounded-sm border p-2.5 text-[13px]">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge
                tone={q.status === 'open' ? 'warn' : 'ok'}
                tip={
                  q.status === 'open'
                    ? 'Вопрос ждёт вашего ответа (раздел «Вопросы»)'
                    : 'Вы ответили, фабрика ещё не закрыла вопрос'
                }
              >
                {q.status === 'open' ? 'ждёт ответа' : 'отвечен'}
              </StatusBadge>
              <span className="text-xs text-muted-foreground">
                спросил: {nameOf(q.source)}
                {q.created ? ` · ${dateTimeMsk(q.created)}` : ''}
              </span>
            </div>
            <p className="m-0">{q.text}</p>
            {q.answer ? <p className="m-0 text-muted-foreground">Ответ: {q.answer}</p> : null}
          </li>
        ))}
      </ul>
      <More className="mt-0">
        {qs.map((q) => (
          <span key={q.id}>
            вопрос {q.id}: источник {q.source}
            {q.key ? `, ключ ${q.key}` : ''}
            {q.created_by && q.created_by !== q.source ? `, записал ${q.created_by}` : ''}
          </span>
        ))}
      </More>
    </Block>
  );
}

function Processes({ detail }: { detail: BatchDetail }) {
  const runs = Object.entries(detail.state?.runs ?? {});
  if (!runs.length) return null;
  return (
    <Block title="Процессы исполнителя" testId="batch-processes">
      <ul className="m-0 grid list-none gap-0 p-0 text-[13px]">
        {runs.map(([key, r]) => {
          const done = exitText(r.exit);
          return (
            <li
              key={key}
              data-testid="process"
              data-alive={r.alive}
              className="flex flex-wrap items-center justify-between gap-2 border-t py-1.5 first:border-t-0"
            >
              <span>{nameOf(r.stage)}</span>
              {r.alive ? (
                <StatusBadge
                  tone="live"
                  tip="Процесс жив: фабрика проверила его по списку процессов"
                >
                  работает
                </StatusBadge>
              ) : (
                <StatusBadge
                  tone={done.tone}
                  tip={
                    r.exit == null
                      ? 'Процесс не работает, код выхода исполнитель не записал'
                      : r.exit === 0
                        ? 'Процесс завершился штатно'
                        : 'Процесс завершился с ошибкой; код выхода — под «подробнее»'
                  }
                >
                  {done.label}
                </StatusBadge>
              )}
            </li>
          );
        })}
      </ul>
      <More className="mt-0">
        {runs.map(([key, r]) => (
          <span key={key}>
            {key}: стадия {r.stage ?? '—'}, pid {r.pid ?? '—'}
            {r.exit != null ? `, код выхода ${r.exit}` : ''}
            {r.restarts ? `, перезапусков ${r.restarts}` : ''}
            {r.log ? `, журнал ${r.log}` : ''}
          </span>
        ))}
      </More>
    </Block>
  );
}

function Stops({ detail }: { detail: BatchDetail }) {
  const stops = detail.state?.stops ?? [];
  if (!stops.length) return null;
  return (
    <Block title="Остановки и продолжения" testId="batch-stops">
      <ul className="m-0 grid list-none gap-1 p-0 text-[13px]">
        {stops.map((s, i) => {
          const step = rec(s.step);
          const resumed = str(s.action) === 'resume' || 'resumed' in s;
          return (
            <li key={i}>
              {resumed ? 'Продолжен' : 'Остановлен'} {dateTimeMsk(str(s.at)) ?? ''}
              {str(s.by) ? ` — ${whoText(str(s.by))}` : ''}
              {str(s.stage) ? `, на стадии «${nameOf(str(s.stage))}»` : ''}
              {s.also_step ? ', вместе с шагом' : ''}
              {step?.left_running ? ' — шаг остался работать' : ''}
            </li>
          );
        })}
      </ul>
      <More className="mt-0">
        {stops.map((s, i) => (
          <span key={i}>{JSON.stringify(s)}</span>
        ))}
      </More>
    </Block>
  );
}

/**
 * Решения, что план прогона сделал тихо (CC-0120, CF-0735: `notify: quiet`): строки журнала,
 * не тревога — исполнитель взял значение по умолчанию и пошёл дальше, уведомления не было.
 */
function Quiet({ detail }: { detail: BatchDetail }) {
  const rows = detail.quiet ?? [];
  if (!rows.length) return null;
  return (
    <Block title="Решено тихо" testId="batch-quiet">
      <ul className="m-0 grid list-none gap-1 p-0 text-[13px] text-muted-foreground">
        {rows.map((q, i) => (
          <li key={`${q.key ?? ''}-${i}`} data-testid="batch-quiet-line" data-stage={q.stage}>
            {dateTimeMsk(q.at) ? <span>{dateTimeMsk(q.at)} · </span> : null}
            пропущено тихо: <span className="text-foreground">{nameOf(q.stage)}</span>
            {q.line ? ` — ${q.line}` : q.took ? ` — ${tookText(q.took)}` : ''}
          </li>
        ))}
      </ul>
      <More className="mt-0">
        {rows.map((q, i) => (
          <span key={i}>{[q.stage, q.key, q.took, q.at].filter(Boolean).join(' · ')}</span>
        ))}
      </More>
    </Block>
  );
}

function Rebuild({ detail }: { detail: BatchDetail }) {
  const r = rec(detail.state?.rebuild);
  return r ? <RebuildBody r={r} /> : null;
}

function RebuildBody({ r }: { r: NonNullable<ReturnType<typeof rec>> }) {
  const of = rec(r.of);
  const slugs = Array.isArray(r.videos)
    ? r.videos
        .map((v) => ({ slug: str(rec(v)?.slug) ?? str(v), title: str(rec(v)?.title) }))
        .filter((v): v is { slug: string; title: string | null } => !!v.slug)
    : [];
  // Названия роликов — из карточек исходного батча; нет карточки — имя ролика словами.
  const source =
    of && str(of.channel) && str(of.batch_id) ? `${str(of.channel)}/${str(of.batch_id)}` : null;
  const cards = useVideos(slugs.length ? source : null).data?.videos;
  const videos = slugs.map((v) => {
    const card = cards?.find((x) => x.slug === v.slug);
    return v.title ?? (card ? videoTitle(card) : readableSlug(v.slug));
  });
  return (
    <Block title="Пересборка" testId="batch-rebuild">
      <p className="m-0 text-[13px]">
        {str(r.title) ?? str(r.mode) ?? 'Пересборка'}
        {of ? ` батча от ${dateTimeMsk(batchIdIso(str(of.batch_id))) ?? str(of.batch_id)}` : ''}
        {videos.length ? ` · ролики: ${videos.join(', ')}` : ''}
      </p>
      {str(r.notes) ? (
        <p className="m-0 text-[13px] text-muted-foreground">Замечание: {str(r.notes)}</p>
      ) : null}
      {str(r.by) ? (
        <p className="m-0 text-xs text-muted-foreground">
          запустил: {whoText(str(r.by))}
          {str(r.at) ? `, ${dateTimeMsk(str(r.at))}` : ''}
        </p>
      ) : null}
      <More className="mt-0">
        {str(r.mode) ? <span>режим {str(r.mode)}</span> : null}
        {of && str(of.path) ? <span>исходный батч {str(of.path)}</span> : null}
        {str(r.task) ? <span>задача {str(r.task)}</span> : null}
        {slugs.length ? <span>ролики: {slugs.map((v) => v.slug).join(', ')}</span> : null}
      </More>
    </Block>
  );
}

/** Подробности батча под кинолентой; `live` — лента событий раскрыта сразу. */
export function BatchInside({
  batch,
  needsHuman,
  live,
  topics,
}: {
  batch: string;
  needsHuman: string[];
  live: boolean;
  /** Темы батча (CC-0092): названия тем для ленты событий вместо слагов. */
  topics?: BatchTopics;
}) {
  const detail = useBatch(batch);
  return (
    <div data-testid="batch-inside">
      <NeedsHuman detail={detail.data} fallback={needsHuman} />
      {detail.isError && !detail.data ? (
        <Refusal className="mt-3" error={detail.error} title="Подробности батча не читаются" />
      ) : null}
      {detail.data ? (
        <>
          <Questions qs={detail.data.questions} />
          <Rebuild detail={detail.data} />
          <Stops detail={detail.data} />
          <Quiet detail={detail.data} />
          <Processes detail={detail.data} />
          {detail.data.state_error ? (
            <p className="mt-3 mb-0 text-[13px] text-danger">{detail.data.state_error}</p>
          ) : null}
        </>
      ) : null}
      <EventsFeed batch={batch} open={live} topics={topics} />
    </div>
  );
}
