// Кандидаты в банк мемов (CC-0103 фабрики, CC-0115 центра): `GET /api/memes/{c}/candidates` —
// candidates.json банка канала (`meme_desk.py candidates`): шаблоны, предложенные в банк и ждущие
// «да» пользователя, проходят ли они по растяжке, что скачать и что скопировать из банка Reel, и
// `accept` — кого «да» возьмёт сейчас.
//
// Приём (CC-0114 API, CC-0115 шаг 3 центра): `…/candidates/accept/plan {ids, details}` ничего не
// пишет — кого возьмёт, кого нет и почему, вопрос пользователю; «да» — `{confirm, answer}`, где
// `answer` пользователь набрал сам (центр его не подставляет; не «да» — 422 `bad_answer`, токен
// цел). Список кандидатов сдвинулся с плана — `list_changed`: план заново.
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { writeProblemText } from './publishWrites';

export type MemeCandidates = Schemas['MemeCandidates'];
export type MemeCandidate = Schemas['MemeCandidate'];
export type MemeAcceptPlanIn = Schemas['MemeAcceptPlanIn'];
export type MemeAcceptPlan = Schemas['MemeAcceptPlan'];
export type MemeAcceptResult = Schemas['MemeAcceptResult'];

const writeCall = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

export const planMemeAccept = (channel: string, body: MemeAcceptPlanIn) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/candidates/accept/plan', {
        params: { path: { channel } },
        body,
        signal,
      }),
    ),
  );

/** «Да»: токен плана и ответ, набранный пользователем, — как есть. */
export const memeAccept = (channel: string, confirm: string, answer: string) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/candidates/accept', {
        params: { path: { channel } },
        body: { confirm, answer },
        signal,
      }),
    ),
  );

/** После приёма (и отказа «да») — перечитать кандидатов и стол мемов канала. */
export function useAfterMemeAccept(channel: string) {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ['api', 'memes', channel] });
}

const MEME_ACCEPT_TEXT: Record<string, string> = {
  list_changed: 'Список кандидатов изменился, откройте заново',
  check_changed: 'Список кандидатов изменился, откройте заново',
  bad_answer: 'Нужно ваше «да» — кандидаты не приняты',
  bad_ids: 'Выберите хотя бы одного кандидата',
  bad_details: 'Описание, теги или заметки не приняты — поправьте их',
  no_candidates: 'У банка нет списка кандидатов',
  bad_candidates: 'Список кандидатов не читается',
  busy: 'Идёт другая запись банка мемов — подождите и нажмите ещё раз',
  duplicate_id: 'Такой шаблон уже есть в банке',
  invalid_entry: 'Запись банка не прошла проверку фабрики',
  bad_entry: 'Запись банка не прошла проверку фабрики',
  invalid_index: 'Указатель банка не читается',
  factory_broken: 'Стол мемов ответил ошибкой — посмотрите банк, прежде чем повторять',
};

export const memeAcceptProblemText = (code: string | null | undefined): string =>
  (code && MEME_ACCEPT_TEXT[code]) || writeProblemText(code);

export async function getMemeCandidates(
  channel: string,
  signal?: AbortSignal,
): Promise<MemeCandidates> {
  return takeBatch(
    await api.GET('/api/memes/{channel}/candidates', { params: { path: { channel } }, signal }),
  );
}

export const memeCandidatesKey = (channel: string) =>
  ['api', 'memes', channel, 'candidates'] as const;

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;

export function useMemeCandidates(channel: string) {
  return useQuery({
    queryKey: memeCandidatesKey(channel),
    queryFn: ({ signal }) => getMemeCandidates(channel, signal),
    retry,
  });
}
