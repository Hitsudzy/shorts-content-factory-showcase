// Общие куски экрана каналов: строки обзора (расписание, пауза, ближайшая публикация).
// Аватар и метка состояния — в ./identity (их берёт и главная, без кода формы).
import type { ReactNode } from 'react';
import { Link } from 'react-router';

import type { ChannelDetail, ChannelSummary } from '@/api/channels';
import { occupantOf, useNote, usePause, useQueue } from '@/api/publish';
import { nbDashes } from '@/api/humanText';
import { readableSlug, withoutHashtags } from '@/api/videos';
import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';

import { scheduleText } from './fields';
import {
  NEAREST_WORDS,
  nearestOf,
  notPublished,
  pauseView,
  publishingHref,
  TIPS,
} from './publishRows';

export function InfoRow({
  label,
  tip,
  children,
}: {
  label: string;
  tip?: string;
  children: ReactNode;
}) {
  return (
    // Подпись слева, значение справа; длинное значение на узком экране уходит под подпись, а не
    // наезжает на неё (CC-0138).
    <li className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-t py-[9px] first:border-t-0 first:pt-0">
      {tip ? (
        <Tip content={tip}>
          <span
            tabIndex={0}
            className="w-max text-muted-foreground underline decoration-dotted underline-offset-4"
          >
            {label}
          </span>
        </Tip>
      ) : (
        <span className="text-muted-foreground">{label}</span>
      )}
      <span className="ml-auto min-w-0 text-right text-pretty">{children}</span>
    </li>
  );
}

/**
 * Строки обзора канала: расписание из конфига, пауза публикаций и ближайшая публикация (из тех же
 * данных, что у экрана «Публикация», CC-0138), правка настроек.
 */
export function OverviewRows({
  channel,
  summary,
  detail,
  loading,
  failed = false,
  fresh = null,
}: {
  /** Id канала — он же канал публикации. */
  channel: string;
  summary: Pick<ChannelSummary, 'no_pipeline' | 'locked'>;
  detail: ChannelDetail | undefined;
  loading: boolean;
  /** Карточку канала прочитать не удалось — расписание неизвестно. */
  failed?: boolean;
  /** Свежесть «открыта/закрыта»: «проверено 12 с назад» (договор 0.5.0). */
  fresh?: string | null;
}) {
  const schedule = scheduleText(detail);
  return (
    <>
      <InfoRow
        label="Расписание батчей"
        tip="Когда фабрика может начать батч канала — так, как это записано в его конфиге (блок batch schedule)"
      >
        {schedule ? (
          <span data-testid="schedule">{schedule}</span>
        ) : failed ? (
          <span className="text-warning">не удалось прочитать конфиг</span>
        ) : loading ? (
          <span className="animate-pulse text-muted-foreground">читаю конфиг…</span>
        ) : summary.no_pipeline ? (
          <span className="text-muted-foreground">нет — батча не будет</span>
        ) : (
          <span className="text-muted-foreground">в конфиге не задано</span>
        )}
      </InfoRow>
      <PauseRow channel={channel} />
      <NearestRow channel={channel} />
      <InfoRow
        label="Правка настроек"
        tip={`Пока идёт батч канала, его конфиг менять нельзя: батч читает его по ходу работы.${fresh ? ` Батчи: ${fresh}; при сохранении фабрика проверит заново.` : ''}`}
      >
        {summary.locked ? (
          <span className="text-warning">закрыта, идёт батч</span>
        ) : (
          <span>открыта</span>
        )}
      </InfoRow>
    </>
  );
}

const muted = 'text-muted-foreground';
const reading = 'animate-pulse text-muted-foreground';
const linkCls = 'text-primary-text underline-offset-4 hover:underline';

/** Пауза публикаций канала (`…/pause`) и ссылка туда, где её ставят и снимают. */
function PauseRow({ channel }: { channel: string }) {
  const p = usePause(channel);
  const v = p.data ? pauseView(p.data) : null;
  return (
    <InfoRow label="Пауза" tip={TIPS.pause}>
      {p.isPending ? (
        <span className={reading}>читаю паузу…</span>
      ) : p.isError ? (
        notPublished(p.error) ? (
          <span className={muted}>канала нет в публикации</span>
        ) : (
          <span className="text-warning">не удалось прочитать паузу</span>
        )
      ) : (
        <span data-testid="pause-row" data-state={p.data.state}>
          <span className={cn(v!.tone === 'warn' && 'text-warning')}>{v!.text}</span>
          {' · '}
          <Link
            to={publishingHref(channel)}
            className={linkCls}
            aria-label={`${v!.action} паузу в разделе «Публикация»`}
          >
            {v!.action}
          </Link>
        </span>
      )}
    </InfoRow>
  );
}

/** Ближайший занятый слот ленты канала (`…/queue`): день, время по Москве и ролик. */
function NearestRow({ channel }: { channel: string }) {
  const q = useQueue(channel);
  const n = q.data ? nearestOf(q.data) : null;
  const slot = n?.kind === 'slot' ? n : null;
  const hasCard =
    !!slot && !!occupantOf(q.data!, slot.slot)?.sources.some((x) => x.startsWith('publish/'));
  const note = useNote(channel, hasCard ? slot!.slug : null, slot?.slot.day ?? null);
  const title = slot
    ? nbDashes((note.data?.title && withoutHashtags(note.data.title)) || readableSlug(slot.slug))
    : null;
  return (
    <InfoRow label="Ближайшая публикация" tip={TIPS.nearest}>
      {q.isPending ? (
        <span className={reading}>читаю очередь…</span>
      ) : q.isError ? (
        notPublished(q.error) ? (
          <span className={muted}>канала нет в публикации</span>
        ) : (
          <span className="text-warning">не удалось прочитать очередь</span>
        )
      ) : slot ? (
        <Link
          to={publishingHref(channel, { day: slot.slot.day, slug: slot.slug })}
          data-testid="nearest-row"
          data-state="slot"
          className={cn(linkCls, 'underline [overflow-wrap:anywhere]')}
        >
          {slot.text} · {title}
        </Link>
      ) : (
        <span data-testid="nearest-row" data-state={n!.kind} className={muted}>
          {NEAREST_WORDS[n!.kind as 'no-slot' | 'empty']}
        </span>
      )}
    </InfoRow>
  );
}
