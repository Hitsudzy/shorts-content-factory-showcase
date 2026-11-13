// Просьбы оператору (CC-0019; API — CC-0018, договор 0.21.0; журнал фабрики —
// `shared/operator_requests.py`). Вы пишете просьбу словами — её берёт сессия-оператор (CLI
// `next`/`answer`), центр сам ничего не исполняет. Ответ приходит сюда и в Telegram.
// `GET /api/requests?status=` — `live` (по умолчанию: open + taken + answered), `open`, `taken`,
// `answered`, `closed`, `cancelled`, `all`. Записи центра — прямые, без плана и токена:
// `POST /api/requests {text, channel?, context?}` (кто — ставит API), `POST …/{rid}/close`
// (answered → closed) и `POST …/{rid}/cancel` (open/taken → cancelled). Отказы фабрики —
// `RequestProblem {detail, code, text_ru}`: `text_ru` показывается человеку как есть, `detail`
// (строка по-английски) — только под «подробнее»; вне рабочей фабрики — 409 `WritesProblem`.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, NOT_WORKING_FACTORY, type Schemas } from './client';

export type OperatorRequest = Schemas['OperatorRequest'];
export type OperatorRequests = Schemas['OperatorRequests'];
export type OperatorRequestIn = Schemas['OperatorRequestIn'];
export type RequestStatus = OperatorRequest['status'];
export type RequestNotify = Schemas['RequestNotify'];
export type RequestProblemCode = Schemas['RequestProblem']['code'];
export type RequestsFilter = 'live' | RequestStatus | 'all';

/** Потолок текста просьбы и её контекста (`TEXT_MAX`, `CONTEXT_MAX` фабрики), знаков. */
export const REQUEST_TEXT_MAX = 4000;
export const REQUEST_CONTEXT_MAX = 4000;

/** Как часто перечитывать список, пока вкладка открыта: ответ оператора приходит сам, мс. */
export const REQUESTS_POLL_MS = 60_000;

export const requestKeys = {
  all: ['requests'] as const,
  list: (status: RequestsFilter) => ['requests', status] as const,
};

/** Отказ записи или чтения просьбы: `code` фабрики, `textRu` — строка для человека. */
export class RequestError extends ApiError {
  /** Код фабрики (`text_empty`, `already_closed`…), `not_working_factory` или `null`. */
  readonly code: RequestProblemCode | typeof NOT_WORKING_FACTORY | null;
  /** Строка для человека от фабрики (`text_ru` или «Только смотреть: …»); `null` — её нет. */
  readonly textRu: string | null;
  /** Строка фабрики по-английски — только под «подробнее». */
  readonly detail: string | null;

  constructor(
    status: number,
    message: string,
    code: RequestError['code'],
    textRu: string | null,
    detail: string | null,
  ) {
    super(status, message);
    this.name = 'RequestError';
    this.code = code;
    this.textRu = textRu;
    this.detail = detail;
  }

  get readOnly(): boolean {
    return this.code === NOT_WORKING_FACTORY;
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

const str = (o: Record<string, unknown>, k: string) =>
  typeof o[k] === 'string' ? (o[k] as string) : null;

/** Данные успешного ответа или `RequestError` с кодом и строкой фабрики. */
export function takeRequest<T>({ data, error, response }: Result<T>): T {
  if (response.ok && data !== undefined) return data;
  const e = typeof error === 'object' && error !== null ? (error as Record<string, unknown>) : {};
  const code = str(e, 'code') as RequestError['code'];
  const readOnly = code === NOT_WORKING_FACTORY;
  const textRu = readOnly ? str(e, 'message') : str(e, 'text_ru');
  // 422 FastAPI (`{detail: [{msg}]}`) и охрана API (`{detail}`) — тоже строкой.
  const detail = Array.isArray(e.detail)
    ? e.detail
        .map((d: unknown) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : ''))
        .filter(Boolean)
        .join('; ')
    : str(e, 'detail');
  const where = `${response.status} ${new URL(response.url || 'http://x/').pathname}`;
  throw new RequestError(
    response.status,
    detail ? `${where}: ${detail}` : where,
    code,
    textRu,
    readOnly ? null : detail,
  );
}

export async function getRequests(
  status: RequestsFilter = 'live',
  signal?: AbortSignal,
): Promise<OperatorRequests> {
  return takeRequest(await api.GET('/api/requests', { params: { query: { status } }, signal }));
}

export async function createRequest(body: OperatorRequestIn): Promise<OperatorRequest> {
  return takeRequest(await api.POST('/api/requests', { body }));
}

export async function closeRequest(rid: string): Promise<OperatorRequest> {
  return takeRequest(await api.POST('/api/requests/{rid}/close', { params: { path: { rid } } }));
}

export async function cancelRequest(rid: string): Promise<OperatorRequest> {
  return takeRequest(await api.POST('/api/requests/{rid}/cancel', { params: { path: { rid } } }));
}

/** Просьбы с фильтром статуса; перечитываются раз в минуту и при возврате на вкладку. */
export function useRequests(status: RequestsFilter = 'live', enabled = true) {
  return useQuery({
    queryKey: requestKeys.list(status),
    queryFn: ({ signal }) => getRequests(status, signal),
    enabled,
    refetchInterval: REQUESTS_POLL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

/**
 * Сколько просьб с пришедшим ответом ещё не закрыты (`answered`). `null` — список не пришёл
 * или не читается: счётчик тогда не рисуется. Тот же запрос `live`, что у экрана.
 */
export function useAnsweredCount(): number | null {
  const q = useRequests('live');
  return q.data ? q.data.requests.filter((r) => r.status === 'answered').length : null;
}

/** После любой записи (и отказа) — перечитать все списки просьб, не дожидаясь перечитки. */
function useRefresh() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: requestKeys.all });
  };
}

export function useCreateRequest() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: createRequest, onSettled: refresh });
}

export function useCloseRequest() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: closeRequest, onSettled: refresh });
}

export function useCancelRequest() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: cancelRequest, onSettled: refresh });
}

export type RequestAction = 'create' | 'close' | 'cancel';

const FAILED: Record<RequestAction, string> = {
  create: 'Просьба не отправлена',
  close: 'Просьба не закрыта',
  cancel: 'Просьба не отменена',
};

/**
 * Отказ словами: заголовок, строка фабрики для человека (`text_ru`) и что под «подробнее».
 * `gone` — просьбы в этом состоянии больше нет (закрыли или отменили с другой стороны, пропала):
 * её карточка уйдёт со списком, поэтому отказ ещё и тостом.
 */
export function requestErrorText(
  e: unknown,
  action: RequestAction,
): { title: string; text: string; detail: string | null; gone: boolean } {
  const title = FAILED[action];
  if (e instanceof RequestError) {
    const gone =
      e.code === 'not_found' ||
      e.code === 'already_closed' ||
      e.code === 'already_cancelled' ||
      e.code === 'cancel_answered' ||
      e.code === 'not_answered';
    if (e.readOnly)
      return {
        title,
        text: e.textRu ?? 'Только смотреть: API запущен не на рабочей фабрике.',
        detail: null,
        gone: false,
      };
    if (e.textRu) return { title, text: e.textRu, detail: e.message, gone };
    if (e.status === 403)
      return {
        title,
        text: 'API не пустил запрос (сессия центра устарела). Нажмите ещё раз.',
        detail: e.message,
        gone: false,
      };
    return {
      title,
      text: 'Фабрика не смогла записать. Попробуйте ещё раз; если повторится — причина ниже.',
      detail: e.message,
      gone: false,
    };
  }
  return {
    title,
    text: 'Нет связи с API фабрики. Проверьте, что он запущен, и нажмите ещё раз.',
    detail: e instanceof Error ? e.message : e ? String(e) : null,
    gone: false,
  };
}
