// Отказы API батчей и расписания (CC-0044…0048 фабрики): `BatchProblem {message, code,
// details}`. `message` — по-русски для человека, показывается как есть; `details` —
// технические строки, только под «подробнее». Общий для экрана «Батчи» (CC-0050…0052).
import { ApiError, type Schemas } from './client';

/**
 * CC-0183: отказ `namesakes` словами центра: оператор батч не называет, он выбирает строку копилки.
 * Одни слова на всех записях и на карточке (там же — ссылка на копилку).
 */
export const NAMESAKES_TEXT =
  'Роликов с этим именем несколько. Откройте нужный в копилке: у каждого своя метка батча.';

export type BatchProblem = Schemas['BatchProblem'];
export type BatchProblemCode = BatchProblem['code'];

/** Отказ API батчей: `problem` — тело `BatchProblem`, если пришло оно. */
export class BatchError extends ApiError {
  readonly problem: BatchProblem | null;

  constructor(status: number, message: string, problem: BatchProblem | null) {
    super(status, message);
    this.name = 'BatchError';
    this.problem = problem;
  }
}

function isProblem(x: unknown): x is BatchProblem {
  return (
    typeof x === 'object' &&
    x !== null &&
    'code' in x &&
    'message' in x &&
    typeof (x as { message: unknown }).message === 'string'
  );
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Данные успешного ответа или `BatchError` (с телом отказа, если оно пришло). */
export function takeBatch<T>({ data, error, response }: Result<T>): T {
  if (response.ok && data !== undefined) return data;
  const problem = isProblem(error) ? error : null;
  const where = `${response.status} ${new URL(response.url || 'http://x/').pathname}`;
  const refusal =
    typeof error === 'object' && error !== null && 'detail' in error
      ? String((error as { detail: unknown }).detail)
      : null;
  throw new BatchError(
    response.status,
    problem ? problem.message : refusal ? `${where}: ${refusal}` : where,
    problem,
  );
}

/** Код отказа фабрики, если ошибка — её отказ. */
export function problemCode(e: unknown): BatchProblemCode | null {
  return e instanceof BatchError ? (e.problem?.code ?? null) : null;
}
