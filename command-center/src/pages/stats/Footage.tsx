// «Нужный футаж» (`GET …/footage-wanted`): чего не хватило батчам канала — работа, человек,
// событие или сцена, сколько раз и почему, есть ли уже в пуле и где добыть. Упакованные батчи
// (архив) фабрика читает долго — только по явной кнопке «Показать и упакованные».
import { useState } from 'react';

import { BatchError } from '@/api/batchProblem';
import { useFootageWanted, type FootageRow, type FootageWanted } from '@/api/analytics';
import { hasReasonWords, reasonOf } from '@/api/reasonRu';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';

import { batchDay, KIND, stageText } from './format';
import { SkeletonTable } from '@/components/common/Skeletons';

type Official = { title?: string | null; id?: string | null; for?: string | null };
type Candidate = {
  video_id?: string;
  title?: string | null;
  channel_title?: string | null;
  origin?: string | null;
  in_pool?: boolean;
};
type InPool = { id?: string; title?: string | null };

/**
 * «Где добыть» местами: официальный канал — с его роликами из кандидатов (тот же канал по имени),
 * прочие кандидаты — по одному. Имя канала одно: `for`, совпадающее с названием или кодом, не
 * повторяется (CC-0113, ревью экранов).
 */
function wherePlaces(
  official: Official[],
  candidates: Candidate[],
): { channel: string | null; videos: Candidate[] }[] {
  const used = new Set<Candidate>();
  const places = official.map((o) => {
    const name = o.title ?? o.id ?? '';
    const extra = o.for && o.for !== o.title && o.for !== o.id ? ` (${o.for})` : '';
    const videos = candidates.filter(
      (c) => !used.has(c) && !!c.channel_title && c.channel_title === o.title,
    );
    videos.forEach((c) => used.add(c));
    return { channel: `${name}${extra}`, videos };
  });
  return [
    ...places,
    ...candidates.filter((c) => !used.has(c)).map((c) => ({ channel: null, videos: [c] })),
  ];
}

/** «1 раз», «2 раза», «5 раз». */
const times = (n: number) => {
  const d = n % 10;
  const dd = n % 100;
  return `${n} ${d >= 2 && d <= 4 && (dd < 12 || dd > 14) ? 'раза' : 'раз'}`;
};

function Row({ r, words }: { r: FootageRow; words: FootageWanted['reasons_ru'] }) {
  const official = ((r.where.official_channels as Official[] | undefined) ?? []).filter(Boolean);
  const candidates = ((r.where.candidates as Candidate[] | undefined) ?? []).filter(Boolean);
  const pool = (r.in_pool_now ?? null) as InPool[] | null;
  return (
    <li
      data-testid="footage-row"
      data-name={r.name}
      className="grid gap-1.5 border-b py-3 last:border-b-0"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <span className="eyebrow mr-2">{KIND[r.kind] ?? r.kind}</span>
          <span className="font-semibold">{r.name}</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {pool?.length ? (
            <StatusBadge
              tone="ok"
              tip={`Уже в пуле: ${pool.map((p) => p.title ?? p.id).join('; ')}`}
            >
              уже в пуле
            </StatusBadge>
          ) : null}
          {r.packed_batches.length ? (
            <StatusBadge tone="idle" tip="Нехватка из упакованных (старых) батчей">
              из архива
            </StatusBadge>
          ) : null}
        </div>
      </div>
      <div className="text-xs text-muted-foreground">
        не хватило {times(r.misses)} · тем: {r.topics} · батчей: {r.batches} · последний раз{' '}
        {batchDay(r.last_seen)}
        {Object.keys(r.stages).length
          ? ` · где: ${Object.keys(r.stages).map(stageText).join(', ')}`
          : ''}
      </div>
      <ul className="m-0 grid list-none gap-0.5 p-0" aria-label="Почему">
        {Object.entries(r.reasons).map(([k, n]) => (
          <li key={k}>
            {reasonOf(words, k)}
            {n > 1 ? <span className="text-muted-foreground"> ×{n}</span> : null}
          </li>
        ))}
      </ul>
      {r.examples.length ? (
        <p className="m-0 text-muted-foreground">
          Например: {r.examples.map((e) => `«${e}»`).join(', ')}
        </p>
      ) : null}
      <div className="text-muted-foreground" data-testid="footage-where">
        Где добыть:{' '}
        {official.length || candidates.length ? (
          <>
            {wherePlaces(official, candidates).map((p, i) => (
              <span key={i}>
                {i ? '; ' : ''}
                {p.channel ? <span className="text-foreground">канал «{p.channel}»</span> : null}
                {p.channel && p.videos.length ? ': ' : ''}
                {p.videos.map((c, j) => (
                  <span key={j}>
                    {j ? ', ' : ''}
                    <span className="text-foreground">«{c.title ?? c.video_id}»</span>
                    {!p.channel && c.channel_title ? ` — ${c.channel_title}` : ''}
                    {!p.channel && c.origin === 'official' ? ', официальный' : ''}
                    {c.in_pool ? ', уже скачан' : ''}
                  </span>
                ))}
              </span>
            ))}
          </>
        ) : (
          'фабрика пока не знает'
        )}
      </div>
      <More className="mt-0">
        <span>key: {r.key}</span>
        <span>
          reasons:{' '}
          {Object.entries(r.reasons)
            .map(([k, n]) => `${k} ×${n}`)
            .join(', ')}
        </span>
        <span>topics: {r.topic_ids.join(', ') || '—'}</span>
        <span>batches: {r.batch_ids.join(', ') || '—'}</span>
        {r.packed_batches.length ? <span>packed: {r.packed_batches.join(', ')}</span> : null}
        {r.searched.length ? <span>searched: {r.searched.join(' | ')}</span> : null}
        {official.map((o, i) => (
          <span key={i}>
            official: {o.title} {o.id}
          </span>
        ))}
        {candidates.map((c, i) => (
          <span key={i}>
            candidate: {c.video_id} {c.origin}
          </span>
        ))}
      </More>
    </li>
  );
}

function List({ f }: { f: FootageWanted }) {
  if (!f.rows.length)
    return (
      <EmptyState title="Нужного футажа нет">
        {f.batches.read
          ? 'Прочитанные батчи ничего не просили: футажа хватило.'
          : 'Батчей канала пока нет — просить было некому.'}
      </EmptyState>
    );
  return (
    <>
      <div className="mb-1 flex flex-wrap gap-1.5" data-testid="footage-reasons">
        {Object.entries(f.by_reason).map(([k, n]) => (
          <StatusBadge
            key={k}
            tone="idle"
            tip={hasReasonWords(f.reasons_ru, k) ? undefined : `Код фабрики: ${k}`}
          >
            {reasonOf(f.reasons_ru, k)}: {n}
          </StatusBadge>
        ))}
      </div>
      <ul className="m-0 list-none p-0">
        {f.rows.map((r) => (
          <Row key={`${r.kind}/${r.key}`} r={r} words={f.reasons_ru} />
        ))}
      </ul>
    </>
  );
}

export function Footage({ channel }: { channel: string }) {
  const [packed, setPacked] = useState(false);
  const q = useFootageWanted(channel, packed);
  const f = q.data;
  const eyebrow = f
    ? `Нужный футаж · батчей прочитано: ${String(f.batches.read)}${f.packed_read ? `, из них упакованных ${String(f.batches.packed)}` : ''}`
    : 'Нужный футаж';
  return (
    <Card aria-labelledby="stats-footage-title" data-testid="stats-footage">
      <CardHead
        eyebrow={eyebrow}
        title="Чего не хватило батчам"
        titleId="stats-footage-title"
        actions={
          <Tip
            content={
              packed
                ? 'Показать только свежие батчи, что ещё лежат на диске'
                : 'Фабрика прочитает ещё и упакованные батчи из архива — это может занять минуту'
            }
          >
            <Button
              size="sm"
              data-testid="footage-packed"
              aria-pressed={packed}
              disabled={q.isFetching && packed}
              onClick={() => setPacked((p) => !p)}
            >
              {packed ? 'Только свежие' : 'Показать и упакованные'}
            </Button>
          </Tip>
        }
      />
      {f ? (
        <p className="m-0 mb-2 text-muted-foreground" data-testid="footage-total">
          {f.rows.length
            ? `Позиций: ${f.rows.length}, нехваток всего: ${f.needs}. Сверху — что нужно чаще и недавно.`
            : null}
        </p>
      ) : null}
      {q.isPending ? (
        <SkeletonTable
          rows={5}
          cols={4}
          label={
            packed
              ? 'Читаю и упакованные батчи — это может занять минуту…'
              : 'Читаю, чего не хватило батчам…'
          }
        />
      ) : q.isError ? (
        <ErrorState
          title="Список нужного футажа не получить"
          error={q.error}
          onRetry={() => void q.refetch()}
        >
          {q.error instanceof BatchError && q.error.problem
            ? q.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : (
        <List f={q.data} />
      )}
      {f ? (
        <More>
          <span>
            {f.task} · built_at {f.built_at} · since {f.since ?? '—'} · batches{' '}
            {String(f.batches.first ?? '—')}…{String(f.batches.last ?? '—')}
          </span>
          {f.notes.map((n, i) => (
            <span key={i}>{n}</span>
          ))}
        </More>
      ) : null}
    </Card>
  );
}
