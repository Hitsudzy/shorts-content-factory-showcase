// Жив ли исполнитель идущего батча (CC-0094 → CC-0110/CC-0115): строка списка идущих батчей
// (`executor_alive`, `lock_held`, `executor_why` по последнему скану фабрики) — без своего опроса
// и без фоновой проверки `resume/plan`. После «Продолжить» ответ фабрики новее строки списка:
// он ложится в кэш и решает, пока список не перечитан после него.
import { useQuery, useQueryClient } from '@tanstack/react-query';

import type { ResumeResult } from '@/api/batchActions';
import { batchKeys, type GoingBatch } from '@/api/batches';

import { answerCheck, executorGone, GONE_REASON, type ExecutorCheck } from './executor';

type Answer = { check: ExecutorCheck; at: number };

/** `b` null — батча нет (главная): ничего не решать. */
export function useExecutor(b: GoingBatch | null) {
  const qc = useQueryClient();
  const batch = b?.batch ?? '';
  // Ответ «Продолжить» (если был) — только из кэша, сам ничего не спрашивает.
  const answer = useQuery<Answer | null>({
    queryKey: batchKeys.executor(batch),
    queryFn: () => null,
    enabled: false,
    initialData: null,
  });
  const listAt = qc.getQueryState(batchKeys.going)?.dataUpdatedAt ?? 0;
  const fresh = answer.data && answer.data.at >= listAt ? answer.data.check : null;
  const gone = !!b && executorGone(fresh ?? b);
  return { gone, reason: gone ? (b?.executor_why ?? GONE_REASON) : null };
}

/** После «Продолжить»: ответ фабрики говорит, жив ли исполнитель, — он и ложится в проверку. */
export function useExecutorAnswer() {
  const qc = useQueryClient();
  return (batch: string, r: ResumeResult) => {
    const answer: Answer = { check: answerCheck(r), at: Date.now() };
    qc.setQueryData(batchKeys.executor(batch), answer);
  };
}
