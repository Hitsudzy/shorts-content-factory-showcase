// Ролики последнего батча без вердикта — для карточки «Ролики ждут решения» и полосы «Ждут
// вас» главной (CC-0062). Только последний батч: сводного адреса по всем батчам в API нет.
// Ролик, заменённый принятой пересборкой, решения не ждёт (CC-0088, `waitingOf`).
import { useBatchHistory } from '@/api/batches';
import { latestBatchOf, replacementsOf, useVideos, waitingOf } from '@/api/videos';

/** Ролики последнего батча без вердикта (для карточки и полосы «Ждут вас»). */
export function useWaitingReels() {
  const history = useBatchHistory();
  const runs = history.data?.runs ?? [];
  const batch = latestBatchOf(runs) ?? null;
  const list = useVideos(batch);
  const waiting = list.data ? waitingOf(list.data) : [];
  const replaced = list.data ? replacementsOf(list.data).size : 0;
  return {
    batch,
    run: runs.find((r) => r.batch === batch),
    list,
    waiting,
    /** Без вердикта, но заменены принятой пересборкой — решения не ждут (CC-0088). */
    replaced,
    /** Батчей нет вовсе (история пришла пустой). */
    none: history.isSuccess && !batch,
    isPending: history.isPending || (!!batch && list.isPending),
    error: history.error ?? list.error,
    retry: () => void (history.isError ? history.refetch() : list.refetch()),
  };
}
