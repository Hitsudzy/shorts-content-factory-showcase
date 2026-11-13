// Вопросы фабрики к пользователю (CF-0652 фабрики, API — CC-0016, договор 0.20.0): журнал
// `needs-you/questions.jsonl` в корне фабрики. `GET /api/questions?status=` — `live` (по
// умолчанию: open + answered), `open`, `answered`, `resolved`, `all`; порядок — старые первыми.
// Записи прямые, без плана и токена: `POST …/{qid}/answer {text, by}` (open/answered →
// answered; можно ответить ещё раз) и `POST …/{qid}/resolve {note?, by}`. Отказы — `{detail}`
// (`Problem`, строка фабрики по-английски): 404 вопроса нет, 409 уже решён, 422 пустой ответ;
// вне рабочей фабрики — 409 `not_working_factory` (`WritesProblem`, CC-0058). Словами для
// человека их называет `questionErrorText`; строка фабрики — только под «подробнее».
// Новый вопрос фабрика сама шлёт в Telegram — центр этого не делает.
// CC-0086 (договор 0.42.0): у вопроса может быть предложенный ответ (`suggestion`, почему, кто и
// когда предложил). «Принять предложение» — `POST …/answer {accept: true, suggested_at}`: текст
// не шлём, API читает предложение заново; другое предложение сейчас — 409 `check_changed`,
// предложения нет — 409 `no_suggestion`, ничего не записано.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, NOT_WORKING_FACTORY, type Schemas } from './client';

export type Question = Schemas['Question'];
export type Questions = Schemas['Questions'];
export type QuestionStatus = Question['status'];
export type QuestionsFilter = 'live' | 'open' | 'answered' | 'resolved' | 'all';

/** Кто пишет ответ и «решено» из центра (`by` журнала). */
export const BY_USER = 'user';

/** Как часто перечитывать список, пока вкладка открыта: вопрос приходит от батча, мс. */
export const QUESTIONS_POLL_MS = 60_000;

export const questionKeys = {
  all: ['questions'] as const,
  list: (status: QuestionsFilter) => ['questions', status] as const,
};

/** Отказ записи вопроса: `kind` — что случилось, `detail` — строка фабрики как есть. */
export type QuestionErrorKind =
  'missing' | 'resolved' | 'empty' | 'readonly' | 'guard' | 'changed' | 'nosuggestion' | 'other';

/** Коды 409 ответа предложением (`Problem.code`, CC-0086). */
export const SUGGESTION_CHANGED = 'check_changed';
export const NO_SUGGESTION = 'no_suggestion';

export class QuestionError extends ApiError {
  readonly kind: QuestionErrorKind;
  readonly detail: string | null;

  constructor(status: number, message: string, kind: QuestionErrorKind, detail: string | null) {
    super(status, message);
    this.name = 'QuestionError';
    this.kind = kind;
    this.detail = detail;
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

function detailOf(error: unknown): string | null {
  if (typeof error !== 'object' || error === null) return null;
  const e = error as { detail?: unknown; message?: unknown };
  if (typeof e.message === 'string') return e.message;
  if (typeof e.detail === 'string') return e.detail;
  // 422 FastAPI: `{detail: [{msg, loc, …}]}` — пустая строка не прошла `min_length`.
  if (Array.isArray(e.detail))
    return e.detail
      .map((d: unknown) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : ''))
      .filter(Boolean)
      .join('; ');
  return null;
}

/** Данные успешного ответа или `QuestionError` с видом отказа. */
export function takeQuestion<T>({ data, error, response }: Result<T>): T {
  if (response.ok && data !== undefined) return data;
  const detail = detailOf(error);
  const code =
    typeof error === 'object' && error !== null && 'code' in error
      ? (error as { code: unknown }).code
      : null;
  const s = response.status;
  const kind: QuestionErrorKind =
    s === 409 && code === NOT_WORKING_FACTORY
      ? 'readonly'
      : s === 409 && code === SUGGESTION_CHANGED
        ? 'changed'
        : s === 409 && code === NO_SUGGESTION
          ? 'nosuggestion'
          : s === 404
            ? 'missing'
            : s === 409
              ? 'resolved'
              : s === 422
                ? 'empty'
                : s === 403
                  ? 'guard'
                  : 'other';
  const where = `${s} ${new URL(response.url || 'http://x/').pathname}`;
  throw new QuestionError(s, detail ? `${where}: ${detail}` : where, kind, detail);
}

export async function getQuestions(
  status: QuestionsFilter = 'live',
  signal?: AbortSignal,
): Promise<Questions> {
  return takeQuestion(await api.GET('/api/questions', { params: { query: { status } }, signal }));
}

export async function answerQuestion(qid: string, text: string): Promise<Question> {
  return takeQuestion(
    await api.POST('/api/questions/{qid}/answer', {
      params: { path: { qid } },
      body: { text, by: BY_USER, accept: false },
    }),
  );
}

/** Ответить предложением: `suggested_at` — то предложение, которое человек видел. */
export async function acceptSuggestion(qid: string, suggestedAt: string | null): Promise<Question> {
  return takeQuestion(
    await api.POST('/api/questions/{qid}/answer', {
      params: { path: { qid } },
      body: { by: BY_USER, accept: true, suggested_at: suggestedAt },
    }),
  );
}

export async function resolveQuestion(qid: string, note?: string | null): Promise<Question> {
  return takeQuestion(
    await api.POST('/api/questions/{qid}/resolve', {
      params: { path: { qid } },
      body: { note: note?.trim() || null, by: BY_USER },
    }),
  );
}

/** Вопросы с фильтром статуса; перечитываются раз в минуту и при возврате на вкладку. */
export function useQuestions(status: QuestionsFilter = 'live', enabled = true) {
  return useQuery({
    queryKey: questionKeys.list(status),
    queryFn: ({ signal }) => getQuestions(status, signal),
    enabled,
    refetchInterval: QUESTIONS_POLL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  });
}

/**
 * Сколько вопросов ждут ответа (`open`; отвеченные ждут уже не вас, а «решено»). `null` — список
 * ещё не пришёл или не читается: счётчик тогда не рисуется. Один запрос `live` на всё приложение.
 */
export function useOpenCount(): number | null {
  const q = useQuestions('live');
  return q.data ? q.data.questions.filter((x) => x.status === 'open').length : null;
}

/**
 * После любой записи (и отказа) — перечитать все списки вопросов: экран, таб, главную. Не ждём
 * перечитки: иначе колбэки `mutate` (тост, очистка поля) пришли бы уже после того, как карточка
 * переехала к отвеченным или в историю и размонтировалась, — и не пришли бы вовсе.
 */
function useRefresh() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: questionKeys.all });
  };
}

export function useAnswer() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ qid, text }: { qid: string; text: string }) => answerQuestion(qid, text),
    onSettled: refresh,
  });
}

export function useAccept() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ qid, suggestedAt }: { qid: string; suggestedAt: string | null }) =>
      acceptSuggestion(qid, suggestedAt),
    onSettled: refresh,
  });
}

export function useResolve() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ qid, note }: { qid: string; note?: string | null }) =>
      resolveQuestion(qid, note),
    onSettled: refresh,
  });
}

/** Отказ записи словами: заголовок и что делать; строка фабрики — `detail`, под «подробнее». */
export function questionErrorText(
  e: unknown,
  action: 'answer' | 'resolve',
): { title: string; text: string; detail: string | null } {
  const sent = action === 'answer' ? 'Ответ не отправлен' : 'Вопрос не отмечен решённым';
  if (e instanceof QuestionError) {
    switch (e.kind) {
      case 'readonly':
        return {
          title: sent,
          text: e.detail ?? 'Только смотреть: API запущен не на рабочей фабрике.',
          detail: null,
        };
      case 'missing':
        return {
          title: 'Такого вопроса больше нет',
          text: 'Фабрика не нашла его в журнале. Список вопросов обновлён.',
          detail: e.message,
        };
      case 'resolved':
        return {
          title: action === 'answer' ? 'Вопрос уже решён' : 'Вопрос уже отмечен решённым',
          text:
            action === 'answer'
              ? 'Ответить на решённый вопрос нельзя. Он теперь в истории.'
              : 'Его закрыли раньше — он теперь в истории.',
          detail: e.message,
        };
      case 'changed':
        return {
          title: 'Предложение изменилось',
          text: 'Пока вы читали, предложенный ответ обновили — ничего не записано. Посмотрите новое предложение в поле и примите его или напишите свой ответ.',
          detail: e.message,
        };
      case 'nosuggestion':
        return {
          title: 'Предложения больше нет',
          text: 'Его убрали, пока вы читали, — ничего не записано. Напишите ответ своими словами.',
          detail: e.message,
        };
      case 'empty':
        return {
          title: sent,
          text: 'Ответ пустой — напишите хотя бы пару слов.',
          detail: e.message,
        };
      case 'guard':
        return {
          title: sent,
          text: 'API не пустил запрос (сессия центра устарела). Нажмите ещё раз.',
          detail: e.message,
        };
      default:
        return {
          title: sent,
          text: 'Фабрика не смогла записать. Попробуйте ещё раз; если повторится — причина ниже.',
          detail: e.message,
        };
    }
  }
  return {
    title: sent,
    text: 'Нет связи с API фабрики. Проверьте, что он запущен, и нажмите ещё раз.',
    detail: e instanceof Error ? e.message : e ? String(e) : null,
  };
}
