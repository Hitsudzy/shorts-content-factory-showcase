// Лента слотов словами (CC-0128): кто в слоте и подпись под свободным слотом.
import { isAhead, type ChannelQueue, type QueueSlot, type SlotNote } from '@/api/publish';
import { readableSlug, withoutHashtags } from '@/api/videos';

/**
 * Кто в слоте словами (CC-0128): название карточки дня без « #shorts»; карточка не прочиталась
 * (или ещё читается) — слаг словами, никогда не голый слаг; свободный — null.
 */
export function slotTitle(s: QueueSlot, card: SlotNote | undefined): string | null {
  if (!s.taken_by) return null;
  const t = card?.note?.title ? withoutHashtags(card.note.title) : '';
  return t || readableSlug(s.taken_by);
}

/** Подпись под слотом без источника: занятый — пояс; прошедший — «слот прошёл», не «ждёт». */
export function freeText(q: ChannelQueue, s: QueueSlot, zone: string, beyond = false): string {
  if (s.taken_by) return zone;
  if (!isAhead(q, s)) return `${zone} · слот прошёл`;
  if (beyond) return `${zone} · дальше горизонта ленты`;
  return `${zone} · ждёт принятый ролик`;
}
