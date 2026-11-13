// Лента слотов канала на 14 дней (`GET /api/publish/{c}/queue?days=14`): время и день слота,
// кто его занял (название — из карточки в папке дня), готов ли ролик, загружен ли он уже,
// ближайший свободный слот. Занятый слот открывает карточку для Studio (`?slot=<день>/<имя>`).
// Поставить ролик в слот — CC-0068; перенести размещённый на другой день, вернуть в копилку и
// сдвинуть очередь на день — CC-0166 (./MoveWrites). CC-0180: снять ролик из ленты в запас, блок
// «Снято из ленты» (строки журнала с `withdrawn`), горизонт: свободный день дальше него — не пропуск.
// CC-0183 (CF-0920): у ролика ленты может быть тёзка в копилке, у снятых — тёзка в запасе: строки
// различает батч, ссылка на заметку — `?slot=_reserve/<имя>&batch=<id>`, записи шлют адрес с батчем.
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import {
  FEED_DAYS,
  isAhead,
  isUploaded,
  occupantOf,
  useSlotNotes,
  useStudio,
  type ChannelQueue,
  type QueueSlot,
  type SlotNote,
  type WithdrawnRow,
} from '@/api/publish';
import { useStash, type StashHorizon } from '@/api/stash';
import { Card, CardHead, Keep } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState } from '@/components/common/States';
import { StatusBadge, type Tone } from '@/components/common/Status';
import { cn } from '@/lib/utils';
import { daysWord } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';

import { reasonsText } from './cardWords';
import { emptyDays, emptyDaysText, JOURNAL_NO_ROWS } from './emptyDays';
import { freeText, slotTitle } from './feedWords';
import { mskDay, slotDay, slotKey, slotRuleText, slotTime } from './format';
import {
  MoveDone,
  ReturnFromReserve,
  RowMoves,
  ShiftQueue,
  type MoveDoneState,
} from './MoveWrites';
import { daysAhead, placedOf, type Placed } from './moveWords';
import {
  namesakesOf,
  stashKeyOf,
  stashTitles,
  withoutBatchTail,
  type NameOf as StashNameOf,
} from './stashWords';

// Одна сетка для занятых и свободных строк (CC-0139): у занятой её несёт ссылка, у свободной — div.
// Левая колонка фиксированной ширины — названия всех строк начинаются на одной линии.
const ROW =
  'grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-x-3 gap-y-1.5 py-2.5 sm:grid-cols-[6.5rem_minmax(0,1fr)_auto]';

type RowState = { label: string; tone: Tone; tip: string };

const ddmm = (day: string) => `${day.slice(8, 10)}.${day.slice(5, 7)}`;

function rowState(
  q: ChannelQueue,
  slot: QueueSlot,
  card: SlotNote | undefined,
  horizon: StashHorizon | null,
): RowState {
  if (!slot.taken_by) {
    if (!isAhead(q, slot)) return { label: 'прошёл', tone: 'idle', tip: 'Время слота уже прошло' };
    if (q.paused)
      return { label: 'пауза', tone: 'warn', tip: 'Канал на паузе: в слот ничего не встанет' };
    if (horizon && slot.day > horizon.last_day)
      return {
        label: 'за горизонтом',
        tone: 'idle',
        tip: `Лента ведётся на ${horizon.days} дн. вперёд, до ${ddmm(horizon.last_day)}: сюда ролик сам не встанет, день можно занять только руками`,
      };
    if (slot.next_free)
      return {
        label: 'ближайший свободный',
        tone: 'live',
        tip: 'Сюда встанет следующий принятый ролик',
      };
    return { label: 'свободен', tone: 'idle', tip: 'Слот пока никем не занят' };
  }
  if (isUploaded(occupantOf(q, slot)))
    return {
      label: 'загружен',
      tone: 'ok',
      tip: 'Ролик уже в YouTube и запланирован на это время',
    };
  if (card?.pending) return { label: 'читаю…', tone: 'idle', tip: 'Читаю карточку ролика' };
  if (!card?.note)
    return {
      label: 'нет карточки',
      tone: 'danger',
      tip: 'Карточка ролика в папке дня не читается',
    };
  // CC-0127: по состоянию карточки — собирается, готова, принята вашим решением, не готова.
  const st = card.note.card;
  if (st?.state === 'building')
    return { label: 'собирается…', tone: 'live', tip: 'Карточку собирает фабрика' };
  if (st?.state === 'ruled')
    return {
      label: 'готов вашим решением',
      tone: 'ok',
      tip: 'Проверка утверждений не прошла, карточку приняли вашим решением: поля для Studio собраны',
    };
  return (st ? st.placeable : card.note.ready)
    ? { label: 'готов', tone: 'ok', tip: 'Карточка готова: поля для Studio собраны' }
    : {
        label: 'не готов',
        tone: 'warn',
        tip: `Карточка не готова: ${reasonsText(st) ?? 'поля для Studio не собраны'} (причина — в карточке)`,
      };
}

function sourceText(q: ChannelQueue, slot: QueueSlot): string | null {
  const o = occupantOf(q, slot);
  if (!o) return null;
  const inDay = o.sources.some((s) => s.startsWith('publish/'));
  if (isUploaded(o)) return inDay ? 'в YouTube · карточка в папке дня' : 'в YouTube';
  return inDay ? 'карточка в папке дня' : null;
}

/**
 * Под правилом слота (CC-0142, как в пульте 2.2): пустые дни за окно ленты; графика нет — ничего.
 * «Журнала загрузок нет» — не здесь: журнал один на фабрику, предупреждение одно над каналами (CC-0148).
 * Журнал есть, а строк этого канала в нём нет — приглушённая строка (CC-0149).
 */
function FeedChecks({ q, horizon }: { q: ChannelQueue; horizon: StashHorizon | null }) {
  const empty = emptyDays(q, horizon?.last_day);
  const studio = useStudio(q.channel).data;
  const noRows = studio?.journal_exists === true && studio.rows === 0;
  if (!empty && !noRows) return null;
  return (
    <div className="mb-3 grid gap-1 text-[13px]">
      {empty ? (
        <p
          className={cn('m-0 text-pretty', empty.length ? 'text-warning' : 'text-muted-foreground')}
          data-testid="empty-days"
          data-count={empty.length}
        >
          {emptyDaysText(empty, horizon?.days || q.days || FEED_DAYS)}
        </p>
      ) : null}
      {noRows ? (
        <p className="m-0 text-pretty text-muted-foreground" data-testid="journal-no-rows">
          {JOURNAL_NO_ROWS}
        </p>
      ) : null}
    </div>
  );
}

/** «Снято из ленты» (CC-0180): ролики журнала, снятые в запас; вернуть — переносом на день. */
function Withdrawn({
  q,
  rows,
  titleOf,
  placed,
  days,
  today,
  lastDay,
  onDone,
  hrefOf,
  batchOf,
}: {
  q: ChannelQueue;
  rows: (WithdrawnRow & { slug: string })[];
  titleOf: StashNameOf;
  placed: Placed[];
  days: string[];
  today: string;
  lastDay: string | null;
  onDone: (d: MoveDoneState) => void;
  hrefOf: (w: WithdrawnRow & { slug: string }) => { search: string };
  /** CC-0183: батч, если у ролика есть тёзка; иначе null — запрос прежний. */
  batchOf: (w: WithdrawnRow & { slug: string }) => string | null;
}) {
  return (
    <section className="mt-4 grid gap-2" data-testid="feed-withdrawn">
      <h3 className="eyebrow">Снято из ленты: {rows.length}</h3>
      <ul className="m-0 grid list-none gap-2 p-0">
        {rows.map((w) => (
          <li
            key={stashKeyOf(w)}
            data-testid="feed-withdrawn-row"
            data-slug={w.slug}
            data-batch={w.batch_id ?? undefined}
            className="grid gap-2 rounded-sm border p-2.5 text-[13px]"
          >
            <span className="grid min-w-0 gap-0.5">
              <Link
                to={hrefOf(w)}
                data-testid="feed-withdrawn-title"
                className="font-semibold [overflow-wrap:anywhere] hover:text-primary-text hover:underline"
              >
                {titleOf(w.slug, w.batch_id)}
              </Link>
              <span className="text-xs text-muted-foreground" data-testid="feed-withdrawn-sub">
                {w.withdrawn.from_day ? `Стоял на ${slotDay(w.withdrawn.from_day, today)} · ` : ''}в
                запасе копилки · в Studio должно стоять: {w.withdrawn.studio}
              </span>
              <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                <Link
                  to={hrefOf(w)}
                  data-testid="feed-withdrawn-note"
                  className="text-primary-text underline-offset-4 hover:underline"
                >
                  Заметка ролика
                </Link>
                {w.url ? (
                  <a
                    href={w.url}
                    target="_blank"
                    rel="noreferrer"
                    data-testid="feed-withdrawn-link"
                    className="text-primary-text underline-offset-4 hover:underline"
                  >
                    Ролик на YouTube
                  </a>
                ) : null}
              </span>
            </span>
            {q.slot ? (
              <ReturnFromReserve
                channel={q.channel}
                slug={w.slug}
                batchId={batchOf(w)}
                title={titleOf(w.slug, w.batch_id)}
                days={days}
                placed={placed}
                titleOf={titleOf}
                today={today}
                lastDay={lastDay}
                onDone={onDone}
              />
            ) : null}
          </li>
        ))}
      </ul>
      <More className="mt-0" label="Подробнее: снято из ленты">
        {rows.map((w) => (
          <span key={stashKeyOf(w)}>
            {w.slug} · {w.video_id} · снят {w.withdrawn.at} · {w.withdrawn.by}/{w.withdrawn.via} ·{' '}
            {w.withdrawn.task} · {withoutBatchTail(w.withdrawn.from_note ?? '—')} →{' '}
            {withoutBatchTail(w.note ?? '—')}
          </span>
        ))}
      </More>
    </section>
  );
}

export function Feed({ q, selected }: { q: ChannelQueue; selected: string | null }) {
  const [params] = useSearchParams();
  const today = mskDay(q.as_of);
  const card = useSlotNotes(q.channel, q);
  const name = useChannelNames();
  const hrefOf = (s: QueueSlot) => {
    const p = new URLSearchParams(params);
    p.set('slot', slotKey(s));
    p.delete('batch');
    return { search: `?${p.toString()}` };
  };
  const taken = q.slots.filter((s) => s.taken_by).length;
  // CC-0166: кто размещён впереди — для переноса и сдвига; форма переноса открыта у одной строки.
  const titles = new Map(
    q.slots
      .filter((s) => s.taken_by)
      .map((s) => [s.taken_by!, slotTitle(s, card(s.day, s.taken_by!)) ?? s.taken_by!]),
  );
  const titleOf = (slug: string) => titles.get(slug) ?? slug;
  // CC-0180: горизонт и названия снятых — из копилки (один кэш с блоком «Копилка»).
  const stash = useStash(q.channel).data;
  const horizon = stash?.horizon ?? null;
  const stashTitle = stashTitles(stash?.videos ?? []);
  const inPile = stash?.videos ?? [];
  const names = namesakesOf(inPile);
  const withdrawn = (q.withdrawn ?? []).filter(
    (w): w is WithdrawnRow & { slug: string } => !!w.slug,
  );
  // CC-0183: ролик ленты с тёзкой в копилке записи называют батчем из его карточки дня.
  const placed = placedOf(q, titleOf, (slug, day) =>
    inPile.some((v) => v.slug === slug) ? card(day, slug)?.note?.batch?.batch_id : null,
  );
  const batchOfWithdrawn = (w: WithdrawnRow & { slug: string }) =>
    names.has(w.slug) || placed.some((p) => p.slug === w.slug) ? (w.batch_id ?? null) : null;
  const ahead = daysAhead(q);
  const [moving, setMoving] = useState<string | null>(null);
  const [done, setDone] = useState<MoveDoneState | null>(null);
  const moved = (d: MoveDoneState) => {
    setMoving(null);
    setDone(d);
  };
  return (
    <Card
      aria-labelledby="feed-title"
      data-testid="slot-feed"
      data-tour="slots"
      data-channel={q.channel}
    >
      <CardHead
        eyebrow={
          <>
            Лента слотов · <Keep data-testid="feed-channel">{name(q.channel)}</Keep> ·{' '}
            {daysWord(q.days || FEED_DAYS)}
          </>
        }
        title={q.slots.length ? `Занято ${taken} из ${q.slots.length}` : 'Слотов нет'}
        titleId="feed-title"
      />
      {q.slot ? (
        <p className="m-0 mb-3 text-[13px] text-muted-foreground" data-testid="slot-rule">
          {slotRuleText(q.slot)}
        </p>
      ) : null}
      <FeedChecks q={q} horizon={horizon} />
      {q.slot && placed.length ? (
        <ShiftQueue
          channel={q.channel}
          channelName={name(q.channel)}
          placed={placed}
          titleOf={titleOf}
          today={today}
          onDone={moved}
        />
      ) : null}
      {done ? (
        <div className="mb-3">
          <MoveDone done={done} today={today} onClose={() => setDone(null)} />
        </div>
      ) : null}
      {!q.slot ? (
        <EmptyState title="У канала нет слота публикации">
          Пока слот не задан в настройках канала, очереди и ленты у него нет.
        </EmptyState>
      ) : !q.slots.length ? (
        <EmptyState title="Слотов впереди нет">Фабрика не нашла слотов на эти дни.</EmptyState>
      ) : (
        <ul className="m-0 grid list-none p-0" data-testid="slots">
          {q.slots.map((s) => {
            const note = s.taken_by ? card(s.day, s.taken_by) : undefined;
            const state = rowState(q, s, note, horizon);
            const beyond = !!horizon && isAhead(q, s) && s.day > horizon.last_day;
            const { time, zone } = slotTime(s);
            const title = slotTitle(s, note);
            const sub = `${sourceText(q, s) ?? freeText(q, s, zone, beyond)}${
              beyond && s.taken_by ? ' · за горизонтом ленты' : ''
            }`;
            const key = slotKey(s);
            const isSel = !!s.taken_by && selected === key;
            const day = slotDay(s.day, today);
            const at = `${time} ${zone}`.trim();
            const video =
              s.taken_by && isAhead(q, s)
                ? placed.find((p) => p.slug === s.taken_by && p.day === s.day)
                : undefined;
            const body = (
              <>
                {/* CC-0139: сначала день (важнее), под ним время — как в «Ближайших публикациях»
                    главной. Колонка одной ширины во всех строках, под самую длинную подпись
                    («пн 12.10», «01:00 МСК»): названия занятых и свободных слотов — на одной линии. */}
                <span className="grid gap-0.5 whitespace-nowrap">
                  <b
                    className="text-[15px] leading-tight font-semibold text-foreground"
                    data-testid="slot-day"
                  >
                    {day}
                  </b>
                  <span
                    className="font-mono text-[12.5px] text-muted-foreground"
                    data-testid="slot-time"
                  >
                    {at}
                  </span>
                </span>
                <span className="grid min-w-0 gap-0.5">
                  <span
                    data-testid="slot-title"
                    className={cn(
                      'leading-tight font-semibold text-pretty [overflow-wrap:anywhere]',
                      !s.taken_by && 'font-normal text-muted-foreground',
                    )}
                  >
                    {title ?? 'Свободный слот'}
                  </span>
                  <span className="text-xs text-muted-foreground" data-testid="slot-sub">
                    {sub}
                  </span>
                </span>
                {/* Значок — по правому краю строки; на узком экране — своей строкой под названием,
                    с той же линии, что и название: текст не жмётся и не наезжает. */}
                <span
                  className="col-start-2 justify-self-start sm:col-start-3 sm:justify-self-end"
                  data-testid="slot-state"
                >
                  <StatusBadge tone={state.tone} tip={state.tip}>
                    {state.label}
                  </StatusBadge>
                </span>
              </>
            );
            return (
              <li
                key={s.at}
                data-testid="slot"
                data-day={s.day}
                data-slug={s.taken_by ?? ''}
                data-state={state.label}
                className={cn(
                  'border-t first:border-t-0',
                  isSel && 'bg-[color-mix(in_srgb,var(--primary)_10%,transparent)]',
                )}
              >
                {s.taken_by ? (
                  <Link
                    to={hrefOf(s)}
                    aria-current={isSel ? 'true' : undefined}
                    aria-label={`${day}, ${at}: ${title}`}
                    className={cn(ROW, 'rounded-sm outline-offset-2 hover:text-primary-text')}
                  >
                    {body}
                  </Link>
                ) : (
                  <div className={ROW}>{body}</div>
                )}
                {video ? (
                  <RowMoves
                    key={`${key}-${video.slug}`}
                    channel={q.channel}
                    video={video}
                    days={ahead}
                    placed={placed}
                    titleOf={titleOf}
                    today={today}
                    lastDay={horizon?.last_day ?? null}
                    open={moving === key}
                    onOpen={(v) => setMoving(v ? key : null)}
                    onDone={moved}
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {withdrawn.length ? (
        <Withdrawn
          q={q}
          rows={withdrawn}
          titleOf={stashTitle}
          placed={placed}
          days={ahead}
          today={today}
          lastDay={horizon?.last_day ?? null}
          onDone={moved}
          batchOf={batchOfWithdrawn}
          hrefOf={(w) => {
            const p = new URLSearchParams(params);
            p.set('slot', `_reserve/${w.slug}`);
            const batch = batchOfWithdrawn(w);
            if (batch) p.set('batch', batch);
            else p.delete('batch');
            return { search: `?${p.toString()}` };
          }}
        />
      ) : null}
      <More>
        <span>журнал загрузок: {q.journal}</span>
        {q.tomorrow ? <span>завтра: {q.tomorrow.line}</span> : null}
        {q.next_free ? <span>ближайший свободный: {q.next_free.label}</span> : null}
        {q.next_free_error ? <span>{q.next_free_error}</span> : null}
        {q.pause_notices.map((n) => (
          <span key={n}>{n}</span>
        ))}
        {q.waiting.length ? (
          <span data-testid="waiting">
            ждут слота (это ролики копилки выше): {q.waiting.join(', ')}
          </span>
        ) : null}
        {q.occupants.map((o) => (
          <span key={`${o.day}/${o.slug}`}>
            {o.day} {o.slug}: {o.sources.join(', ')}
          </span>
        ))}
      </More>
    </Card>
  );
}
