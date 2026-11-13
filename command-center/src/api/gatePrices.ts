// Цена воротец (CC-0100 фабрики, CC-0115 центра): `GET /api/gate-prices` — что даёт
// `runlog gate-price --json`: сколько готовых роликов окна (последние N батчей) убил бы отказ по
// каждому правилу, вердикт (отказ, предупреждение, штраф к оценке), подпись цены и решение
// пользователя. Считается по всему окну — без опроса, ответ фабрики кэшируется по состоянию окна
// и леджера.
//
// Записи (CC-0114 API, CC-0115 шаг 3 центра): подпись цены `…/{rule}/sign/plan {price, note,
// base_sha256}` → `…/sign {confirm}` и решение `…/{rule}/decide/plan {mode, task, note,
// base_sha256}` → `…/decide {confirm}`. `base_sha256` — `ledger_sha256` из чтения, которое
// смотрел пользователь: леджер сменился — `check_changed` («Цены изменились, откройте заново»).
// План отказа не бросает: `ok: false`, `refusals [{code, line, message}]`, `why` — первая причина.
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { writeProblemText } from './publishWrites';

export type GatePrices = Schemas['GatePrices'];
export type GatePriceResult = Schemas['GatePriceResult'];
export type GatePriceUnregistered = Schemas['GatePriceUnregistered'];
export type GateSignPlanIn = Schemas['GateSignPlanIn'];
export type GateDecidePlanIn = Schemas['GateDecidePlanIn'];
export type GateWritePlan = Schemas['GateWritePlan'];
export type GateWriteResult = Schemas['GateWriteResult'];

export async function getGatePrices(signal?: AbortSignal): Promise<GatePrices> {
  return takeBatch(await api.GET('/api/gate-prices', { signal }));
}

export const gatePricesKey = ['api', 'gate-prices'] as const;

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;

export function useGatePrices() {
  return useQuery({
    queryKey: gatePricesKey,
    queryFn: ({ signal }) => getGatePrices(signal),
    retry,
    staleTime: 5 * 60_000,
  });
}

const writeCall = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);
const ruleParam = (rule: string) => ({ path: { rule } });

export const planGateSign = (rule: string, body: GateSignPlanIn) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/gate-prices/{rule}/sign/plan', {
        params: ruleParam(rule),
        body,
        signal,
      }),
    ),
  );

export const gateSign = (rule: string, confirm: string) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/gate-prices/{rule}/sign', {
        params: ruleParam(rule),
        body: { confirm },
        signal,
      }),
    ),
  );

export const planGateDecide = (rule: string, body: GateDecidePlanIn) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/gate-prices/{rule}/decide/plan', {
        params: ruleParam(rule),
        body,
        signal,
      }),
    ),
  );

export const gateDecide = (rule: string, confirm: string) =>
  writeCall(async (signal) =>
    takeBatch(
      await api.POST('/api/gate-prices/{rule}/decide', {
        params: ruleParam(rule),
        body: { confirm },
        signal,
      }),
    ),
  );

/** После подписи или решения (и отказа «да») — перечитать цену воротец. */
export function useAfterGateWrite() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: gatePricesKey });
}

/** Сменившийся леджер цен — словами экрана. */
export const GATE_CHANGED = 'Цены изменились, откройте заново';

const GATE_PROBLEM_TEXT: Record<string, string> = {
  check_changed: GATE_CHANGED,
  empty_note: 'Напишите заметку — без ваших слов подпись и решение не пишутся',
  bad_price: 'Цена — число готовых роликов, 0 или больше',
  below_measured: 'Цена ниже измеренной',
  already_signed: 'Правило уже подписано',
  not_measured: 'Цена правила не измерена — подписывать нечего',
  not_signable: 'Это правило подписывают вместе с таблицей оценок, не здесь',
  no_such_rule: 'Этого правила нет в журнале цен',
  bad_mode: 'Решение — только «мерить» или «предупреждать»',
  bad_task: 'Нужен номер задачи фабрики',
  batch_open: 'Идёт батч — цены не подписываются до его конца',
  locked: 'Леджер цен сейчас пишет кто-то другой — подождите и повторите',
  busy: 'Идёт другая подпись цены — подождите и нажмите ещё раз',
  not_repo: 'Леджер не сохранить в истории фабрики — ничего не записано',
  commit_refused: 'История фабрики не приняла запись журнала цен — файл возвращён как был',
  write_failed: 'Леджер не записался',
  ledger_unreadable: 'Леджер цен не читается',
  factory_broken: 'Фабрика ответила ошибкой — посмотрите цены, прежде чем повторять',
};

export const gateProblemText = (code: string | null | undefined): string =>
  (code && GATE_PROBLEM_TEXT[code]) || writeProblemText(code);
