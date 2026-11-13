// Где залита пересборка, которой заменён ролик (CC-0088): номер ролика на YouTube. Связи
// «ролик батча → строка журнала загрузок» в договоре 0.28 нет, поэтому — из того, что API уже
// отдаёт публикации: лента канала знает, кто занимает день (`occupants`: имя ролика, день,
// `uploads.json:<id>`), а карточка дня (`…/notes/{slug}?day`) — из какого батча ролик (`batch`,
// `publish_card.batch_video` фабрики). Номер берётся, только если карточку дня собрал именно
// этот батч пересборки: по одному имени не угадываем — у ролика с тем же именем бывают загрузки
// из других батчей (delver залит трижды).
import { useQueries } from '@tanstack/react-query';

import { getNote, publishKeys, useQueue, type Occupant } from './publish';
import type { Replacement } from './videos';

const UPLOADS = 'uploads.json:';

/** Номер ролика на YouTube из источника занявшего день (`uploads.json:<id>`), null — не залит. */
export function uploadIdOf(o: Occupant): string | null {
  const s = o.sources.find((x) => x.startsWith(UPLOADS));
  const id = s?.slice(UPLOADS.length).trim();
  return id || null;
}

export type ReplacementUpload = {
  /** Залит: номер на YouTube и день публикации; null — в ленте его загрузки не видно. */
  upload: { videoId: string; day: string } | null;
  /** Лента или карточки дней ещё читаются. */
  pending: boolean;
  /** Лента публикации не читается — про загрузку не сказать. */
  failed: boolean;
};

/** Загрузка пересборки `r` канала `channel` (null — не спрашивать). */
export function useReplacementUpload(
  channel: string | null | undefined,
  r: Replacement | null,
): ReplacementUpload {
  const q = useQueue(r && channel ? channel : null);
  const slug = r?.video.slug;
  const candidates = (q.data?.occupants ?? []).filter(
    (o) => o.slug === slug && uploadIdOf(o) && o.sources.some((x) => x.startsWith('publish/')),
  );
  const notes = useQueries({
    queries: candidates.map((o) => ({
      queryKey: publishKeys.note(channel ?? '', o.slug!, o.day),
      queryFn: ({ signal }: { signal: AbortSignal }) => getNote(channel!, o.slug!, o.day, signal),
      enabled: !!channel,
      retry: false,
    })),
  });
  if (!r || !channel) return { upload: null, pending: false, failed: false };
  const i = candidates.findIndex((_, k) => notes[k]?.data?.batch?.batch_id === r.batch_id);
  const hit = i >= 0 ? candidates[i]! : null;
  return {
    upload: hit ? { videoId: uploadIdOf(hit)!, day: hit.day } : null,
    pending: !hit && (q.isPending || notes.some((n) => n.isPending)),
    failed: q.isError,
  };
}
