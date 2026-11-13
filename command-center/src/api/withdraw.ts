// Снять ролик окончательно (CC-0107 фабрики, CC-0115 шаг 3 центра):
// `POST /api/batches/{c}/{b}/videos/{slug}/withdraw/plan` ничего не пишет — тема ролика, что о ней
// говорят записи сейчас и после снятия, какие исходники пула снятие отпустит (уберёт их месячный
// архив, с диска сейчас ничего не уходит) и какие ещё держат. «Да» — `{confirm, answer}`: ответ
// пользователя его словами, по-русски и с именем ролика (правило фабрики `check_answer`), —
// центр его не подставляет; без кириллицы — 422 `answer_required`, без имени —
// `answer_without_name` (токен цел).
import { useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { batchPath } from './batches';
import { api, type Schemas } from './client';
import { writeProblemText } from './publishWrites';

export type WithdrawPlan = Schemas['WithdrawPlan'];
export type WithdrawResult = Schemas['WithdrawResult'];

const writeCall = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

function pathOf(batch: string, slug: string) {
  const p = batchPath(batch);
  if (!p) throw new Error(`не путь батча: ${batch}`);
  return { ...p, slug };
}

export const planWithdraw = (batch: string, slug: string) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/videos/{slug}/withdraw/plan', {
        params: { path: pathOf(batch, slug) },
        signal,
      }),
    ),
  );

/** «Да»: токен плана и ответ, набранный пользователем, — как есть. */
export const withdraw = (batch: string, slug: string, confirm: string, answer: string) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/videos/{slug}/withdraw', {
        params: { path: pathOf(batch, slug) },
        body: { confirm, answer },
        signal,
      }),
    ),
  );

/** После снятия (и отказа) — перечитать ролики батчей. */
export function useAfterWithdraw() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ['api', 'videos'] });
}

const CYRILLIC = /[А-Яа-яЁё]/;

/** Годится ли ответ так, как его проверит фабрика: по-русски и называет ролик (`slug`). */
export const withdrawAnswerOk = (answer: string, slug: string) =>
  CYRILLIC.test(answer) && answer.toLowerCase().includes(slug.toLowerCase());

/** Чего не хватает ответу (null — годится или ещё пусто). */
export function withdrawAnswerHint(answer: string, slug: string): string | null {
  if (!answer.trim()) return null;
  if (!CYRILLIC.test(answer)) return 'Напишите по-русски';
  if (!answer.toLowerCase().includes(slug.toLowerCase())) return 'Впишите имя из подписи выше';
  return null;
}

/** Что записи говорят о теме ролика (`topic_status`). */
export const TOPIC_STATUS_TEXT: Record<string, string> = {
  published: 'опубликован',
  withdrawn: 'снят окончательно',
  accepted_not_published: 'принят, но не опубликован',
  rejected_not_withdrawn: 'отклонён, но не снят',
  no_video: 'ролика нет',
};

export const topicStatusText = (status: Record<string, unknown> | null | undefined) => {
  const s = typeof status?.status === 'string' ? status.status : null;
  return s ? (TOPIC_STATUS_TEXT[s] ?? 'состояние не распознано') : 'неизвестно';
};

const WITHDRAW_TEXT: Record<string, string> = {
  answer_required: 'Нужен ваш ответ по-русски — ролик не снят',
  answer_without_name: 'Ответ не называет ролик — ролик не снят',
  busy: 'Идёт другое снятие ролика — подождите и нажмите ещё раз',
  refused: 'Фабрика отказала — ролик не снят',
  check_changed: 'С момента плана что-то изменилось — посмотрите план заново',
  factory_broken: 'Фабрика ответила ошибкой — посмотрите журнал пула, прежде чем повторять',
  unknown_video: 'Такого ролика в батче нет',
  unknown_batch: 'Такого батча нет',
  confirm_channel: 'Подтверждение было выдано другому ролику и сгорело — нужен новый план',
};

export const withdrawProblemText = (code: string | null | undefined): string =>
  (code && WITHDRAW_TEXT[code]) || writeProblemText(code);
