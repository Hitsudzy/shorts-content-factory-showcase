// «Мемы» (CC-0025): банки мемов каналов и стол разбора. Банк выбирается по каналу (у Reel и
// Science он общий — банк по умолчанию, у Tech свой); по умолчанию открыт тот, где больше всего
// ждут решения. Канал и открытый мем — в адресе (`?channel=…&m=…`). Вырезать фон и обрезать поля
// — на столе (CC-0132), там же добавить мем по ссылке и лист кадров видео (CC-0133).
import { useSearchParams } from 'react-router';

import { BatchError } from '@/api/batchProblem';
import { useMemesOverview } from '@/api/memes';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { cn } from '@/lib/utils';
import { useChannelNames } from '@/pages/batches/names';

import { defaultChannel, groupsOf, type Group } from './banks';
import { Candidates } from './Candidates';
import { Desk } from './Desk';
import { layerText, memesWord } from './format';
import { Pending, SkeletonCard, SkeletonTiles } from '@/components/common/Skeletons';

function BankPicker({
  groups,
  channel,
  onPick,
}: {
  groups: Group[];
  channel: string | null;
  onPick: (c: string) => void;
}) {
  const name = useChannelNames();
  return (
    <ul
      className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2 lg:grid-cols-3"
      aria-label="Банки мемов"
      data-testid="bank-picker"
    >
      {groups.map((g) => {
        const head = g.rows[0]!;
        const on = g.rows.some((r) => r.channel === channel);
        const label = g.rows.map((r) => name(r.channel)).join(' и ');
        if (head.error || !g.bank)
          return (
            <li
              key={head.channel}
              data-testid="bank-option"
              data-bank=""
              className="grid gap-1 rounded-lg border border-dashed p-3 text-[13px]"
            >
              <b className="font-semibold">{label}</b>
              <span className="text-danger">{head.error?.message ?? 'Банк не открывается.'}</span>
              {head.error ? (
                <More className="mt-0">
                  <span>код: {head.error.code}</span>
                  {head.error.details.map((d, i) => (
                    <span key={i}>{d}</span>
                  ))}
                </More>
              ) : null}
            </li>
          );
        return (
          <li key={g.bank} className="min-w-0">
            <button
              type="button"
              data-testid="bank-option"
              data-bank={g.bank}
              aria-pressed={on}
              onClick={() => onPick(on && channel ? channel : head.channel)}
              className={cn(
                'grid h-full w-full gap-1 rounded-lg border bg-card p-3 text-left text-[13px] outline-offset-2 hover:border-muted-foreground',
                on && 'border-primary ring-1 ring-primary',
              )}
            >
              <span className="eyebrow">
                {head.default_bank ? 'Банк по умолчанию' : 'Свой банк'}
                {g.rows.length > 1 ? ' · общий' : ''}
              </span>
              <b className="font-semibold">{label}</b>
              <span>
                {memesWord(head.entries)} ·{' '}
                <b className={cn(head.pending ? 'text-primary-text' : 'font-normal')}>
                  ждут разбора: {head.pending}
                </b>
              </span>
              <span className="text-muted-foreground">
                отмечено оставить: {head.keep} · убрать: {head.drop}
                {head.cut_diff ? ` · вырезка поменяется: ${head.cut_diff}` : ''}
              </span>
              {g.rows.map((r) => (
                <span key={r.channel} className="text-xs text-muted-foreground" data-testid="layer">
                  {g.rows.length > 1 ? `${name(r.channel)}: ` : ''}
                  {layerText(r.layer_enabled)}
                </span>
              ))}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function Memes() {
  const overview = useMemesOverview();
  const [params, setParams] = useSearchParams();
  const name = useChannelNames();
  const groups = groupsOf(overview.data?.channels ?? []);
  const asked = params.get('channel');
  const channel = asked ?? defaultChannel(groups);
  const group = groups.find((g) => g.rows.some((r) => r.channel === channel));
  const bankLabel = group ? group.rows.map((r) => name(r.channel)).join(' и ') : (channel ?? '');
  return (
    <>
      <div>
        <div className="eyebrow">Разбор и библиотека</div>
        <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">Мемы</h1>
      </div>
      {overview.isPending ? (
        <Pending label="Читаю банки мемов…" className="gap-(--space-gap)">
          <SkeletonCard bare rows={2} />
          <SkeletonCard bare rows={0}>
            <SkeletonTiles
              bare
              count={8}
              aspect="4 / 3"
              badge={false}
              className="grid-cols-2 sm:grid-cols-3 lg:grid-cols-4"
            />
          </SkeletonCard>
        </Pending>
      ) : overview.isError ? (
        <ErrorState
          title="Банки мемов не прочитать"
          error={overview.error}
          onRetry={() => void overview.refetch()}
        >
          {overview.error instanceof BatchError && overview.error.problem
            ? overview.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : !groups.length ? (
        <EmptyState title="Каналов с мемами нет">Банки появятся вместе с каналами.</EmptyState>
      ) : (
        <BankPicker groups={groups} channel={channel} onPick={(c) => setParams({ channel: c })} />
      )}
      {channel && (group || asked) ? (
        <>
          {group && group.rows.length > 1 ? (
            <p className="m-0 text-[13px] text-muted-foreground" data-testid="bank-shared">
              Банк общий у {bankLabel}: отметки и разбор у них одни на всех.
            </p>
          ) : null}
          <Desk key={channel} channel={channel} bankLabel={bankLabel} />
          <Candidates key={`c-${channel}`} channel={channel} bankLabel={bankLabel} />
        </>
      ) : null}
    </>
  );
}
