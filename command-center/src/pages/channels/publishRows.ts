// Строки «Ближайшая публикация» и «Пауза» в обзоре канала (CC-0138) — словами, по тем же данным,
// что у экрана «Публикация»: лента слотов канала (`…/queue`) и пауза публикаций (`…/pause`).
import { problemCode } from '@/api/batchProblem';
import { isAhead, type ChannelPause, type ChannelQueue, type QueueSlot } from '@/api/publish';
import { dateTimeMsk } from '@/pages/batches/format';
import { mskDay, slotDay, slotTime } from '@/pages/publishing/format';

export type Nearest =
  | { kind: 'no-slot' }
  | { kind: 'empty' }
  | { kind: 'slot'; slot: QueueSlot; slug: string; text: string };

/** Ближайший занятый слот впереди: «завтра, 01:00 МСК»; слота нет — «слот не задан»; пусто. */
export function nearestOf(q: ChannelQueue): Nearest {
  if (!q.slot) return { kind: 'no-slot' };
  const s = q.slots.find((x) => x.taken_by && isAhead(q, x));
  if (!s?.taken_by) return { kind: 'empty' };
  const { time, zone } = slotTime(s);
  return {
    kind: 'slot',
    slot: s,
    slug: s.taken_by,
    text: `${slotDay(s.day, mskDay(q.as_of))}, ${time} ${zone}`.trim(),
  };
}

export const NEAREST_WORDS = { 'no-slot': 'слот не задан', empty: 'в очереди пусто' } as const;

export type PauseView = {
  text: string;
  /** Что сделать в «Публикации»: подпись ссылки. */
  action: string;
  tone: 'warn' | 'idle' | 'ok';
};

/** Пауза публикаций словами: «на паузе до 20.10, 01:00», «на паузе, без срока», «нет». */
export function pauseView(p: ChannelPause): PauseView {
  if (p.state === 'paused') {
    const until = p.row?.until ? dateTimeMsk(p.row.until) : null;
    return {
      text: until ? `на паузе до ${until}` : 'на паузе, без срока',
      action: 'снять',
      tone: 'warn',
    };
  }
  if (p.state === 'expired') return { text: 'срок паузы прошёл', action: 'открыть', tone: 'idle' };
  return { text: 'нет', action: 'поставить', tone: 'ok' };
}

/** Канала нет среди каналов публикации (`unknown_channel`) — это не ошибка чтения. */
export const notPublished = (e: unknown) => problemCode(e) === 'unknown_channel';

/** Адрес «Публикации» этого канала (и слота). */
export function publishingHref(channel: string, slot?: { day: string; slug: string }) {
  const p = new URLSearchParams({ channel });
  if (slot) p.set('slot', `${slot.day}/${slot.slug}`);
  return `/publishing?${p.toString()}`;
}

export const TIPS = {
  pause:
    'Пока стоит пауза, фабрика не ставит ролики канала в слоты публикации. Поставить и снять её можно в разделе «Публикация» этого канала',
  nearest:
    'Ближайший ролик в очереди публикации канала: день и время слота по Москве. Вся лента слотов — в разделе «Публикация»',
} as const;
