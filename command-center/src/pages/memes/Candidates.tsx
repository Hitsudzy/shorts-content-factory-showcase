// «Кандидаты в банк» на «Мемах» (CC-0115 → CC-0103, `GET /api/memes/{c}/candidates`): шаблоны,
// предложенные в банк канала и ждущие вашего «да», — проходят ли по растяжке, в каком они
// состоянии (в банке и ждут «да», уже в банке, не скачаны), что придётся скачать и что
// скопировать из банка ExampleFilm. «Принять в банк…» — план фабрики → ваше «да» (./AcceptCandidates).
// Пути, id шаблонов, намерения и строки фабрики — под «подробнее».
import { BatchError } from '@/api/batchProblem';
import { useMemeCandidates, type MemeCandidate, type MemeCandidates } from '@/api/memeCandidates';
import { Card, CardHead, Keep } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { SkeletonRows } from '@/components/common/Skeletons';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge, type Tone } from '@/components/common/Status';
import { plural } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { sizeText } from '@/pages/batches/going';

import { AcceptCandidates } from './AcceptCandidates';
import { filesWord } from './format';

const GROUP: Record<MemeCandidate['group'], { label: string; tone: Tone; tip: string }> = {
  pass: {
    label: 'проходит',
    tone: 'ok',
    tip: 'Картинку не придётся растягивать сильнее, чем позволяет правило мемов.',
  },
  fail: {
    label: 'мала',
    tone: 'danger',
    tip: 'Картинку пришлось бы растянуть сильнее, чем позволяет правило, — она выйдет мыльной.',
  },
  unknown: {
    label: 'размер неизвестен',
    tone: 'idle',
    tip: 'У шаблона нет размеров — проверить растяжку не по чему.',
  },
};

const STATUS: Record<string, string> = {
  ready: 'в банке, ждёт «да»',
  in_bank: 'уже в банке',
  not_downloaded: 'не скачан',
  outside_bank: 'файл вне банка',
};

const x = (n: number) => `×${String(Math.round(n * 100) / 100).replace('.', ',')}`;

function Row({
  c,
  ceiling,
  reel,
}: {
  c: MemeCandidate;
  ceiling: number | null | undefined;
  reel: string;
}) {
  const g = GROUP[c.group];
  const size = c.width && c.height ? `${c.width}×${c.height}` : null;
  const stretch = c.stretch_now ?? c.stretch;
  return (
    <li
      data-testid="candidate"
      data-id={c.id ?? undefined}
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t py-2 text-[13px] first:border-t-0"
    >
      <span className="min-w-0 flex-1 basis-[12rem] font-semibold">{c.name ?? 'Без имени'}</span>
      <span className="font-mono text-xs text-muted-foreground">
        {[
          size,
          stretch != null ? `растяжка ${x(stretch)}${ceiling ? ` из ${x(ceiling)}` : ''}` : null,
        ]
          .filter(Boolean)
          .join(' · ') || '—'}
      </span>
      <StatusBadge tone={g.tone} tip={g.tip}>
        {g.label}
      </StatusBadge>
      {c.status ? (
        <span className="text-xs text-muted-foreground" data-testid="candidate-status">
          {STATUS[c.status] ?? c.status}
          {c.in_reel_bank && c.status === 'not_downloaded' ? ` · есть в банке ${reel}` : ''}
        </span>
      ) : null}
    </li>
  );
}

function Body({ d }: { d: MemeCandidates }) {
  const name = useChannelNames();
  // Банк по умолчанию — банк ExampleFilm; его название — из списка каналов.
  const reel = name(d.copy_channel ?? 'example-film');
  if (d.missing || !d.candidates.length)
    return (
      <EmptyState title="Кандидатов нет">
        {d.missing ? 'У банка нет списка кандидатов — предлагать нечего.' : 'Список пуст.'}
      </EmptyState>
    );
  const groups = (['pass', 'fail', 'unknown'] as const)
    .map((g) => ({ g, rows: d.candidates.filter((c) => c.group === g) }))
    .filter((x) => x.rows.length);
  const ready = d.accept.ready.length;
  return (
    <div className="grid gap-3">
      <div className="grid gap-1 text-[13px]" data-testid="candidates-summary">
        <span>
          {d.accept.available ? (
            <b className={ready ? 'text-primary-text' : 'font-normal'}>Ждут вашего «да»: {ready}</b>
          ) : (
            <span className="text-muted-foreground">
              {d.accept.reason ?? 'Принять сейчас нельзя.'}
            </span>
          )}
          {' · '}проходят: {d.counts.pass} · малы: {d.counts.fail}
          {d.counts.unknown ? ` · без размеров: ${d.counts.unknown}` : ''}
        </span>
        <span className="text-muted-foreground">
          Скачать: {filesWord(d.download.files)}, {sizeText(d.download.bytes)}
          {d.copy.files
            ? ` · скопировать из банка ${reel}: ${filesWord(d.copy.files)}, без скачивания`
            : ''}
        </span>
      </div>
      {groups.map(({ g, rows }) => (
        <details key={g} open={g === 'pass'} data-testid="candidates-group" data-group={g}>
          <summary className="w-max cursor-pointer text-[13px] font-semibold">
            {g === 'pass' ? 'Проходят' : g === 'fail' ? 'Малы для ролика' : 'Без размеров'}:{' '}
            {rows.length} {plural(rows.length, 'шаблон', 'шаблона', 'шаблонов')}
          </summary>
          <ul className="m-0 mt-1 list-none p-0">
            {rows.map((c, i) => (
              <Row key={c.id ?? i} c={c} ceiling={d.ceiling} reel={reel} />
            ))}
          </ul>
        </details>
      ))}
      {d.accept.available ? <AcceptCandidates d={d} /> : null}
    </div>
  );
}

export function Candidates({ channel, bankLabel }: { channel: string; bankLabel: string }) {
  const q = useMemeCandidates(channel);
  return (
    <Card aria-labelledby="meme-candidates-title" data-testid="meme-candidates">
      <CardHead
        eyebrow={
          <>
            Предложено в банк · <Keep>{bankLabel}</Keep>
            {q.data?.listed
              ? ` · список от ${q.data.listed.split('-').reverse().slice(0, 2).join('.')}`
              : ''}
          </>
        }
        title="Кандидаты в банк"
        titleId="meme-candidates-title"
      />
      {q.isPending ? (
        <SkeletonRows rows={4} height={37} gap={1} bordered={false} label="Читаю кандидатов…" />
      ) : q.isError ? (
        <ErrorState
          title="Кандидатов не прочитать"
          error={q.error}
          onRetry={() => void q.refetch()}
        >
          {q.error instanceof BatchError && q.error.problem
            ? q.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : (
        <>
          <Body d={q.data} />
          <More>
            <span>список: {q.data.path}</span>
            {q.data.missing ? <span>{q.data.missing}</span> : null}
            {q.data.source && typeof q.data.source.name === 'string' ? (
              <span>источник: {q.data.source.name}</span>
            ) : null}
            {q.data.problems.map((p) => (
              <span key={p}>{p}</span>
            ))}
            {q.data.accept.ready.length ? (
              <span>«да» возьмёт: {q.data.accept.ready.join(', ')}</span>
            ) : null}
            {q.data.copy_error ? <span>банк по умолчанию: {q.data.copy_error}</span> : null}
          </More>
        </>
      )}
    </Card>
  );
}
