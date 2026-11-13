// Слова просьб оператору (CC-0019): состояние просьбы и доставка ответа в Telegram — словами,
// порядок в списках. Номер просьбы (`R<n>`) на экран не выходит — только под «подробнее».
import type { OperatorRequest, RequestNotify, RequestStatus } from '@/api/requests';
import type { Tone } from '@/components/common/Status';
import { dateTimeMsk } from '@/pages/batches/format';

export const REQUEST_STATUS: Record<RequestStatus, { label: string; tone: Tone; tip: string }> = {
  open: {
    label: 'открыта',
    tone: 'warn',
    tip: 'Просьба ждёт в очереди: оператор её ещё не взял. Пока не взял — её можно отменить',
  },
  taken: {
    label: 'взята оператором',
    tone: 'live',
    tip: 'Сессия-оператор взяла просьбу в работу. Ответ придёт сюда и в Telegram',
  },
  answered: {
    label: 'отвечена',
    tone: 'ok',
    tip: 'Оператор ответил. Прочитайте ответ и закройте просьбу — она уйдёт в историю',
  },
  closed: {
    label: 'закрыта',
    tone: 'idle',
    tip: 'Ответ прочитан, просьба закрыта и лежит в истории',
  },
  cancelled: {
    label: 'отменена',
    tone: 'idle',
    tip: 'Просьбу отменили — оператор её не исполняет',
  },
};

/** Доставка ответа в Telegram словами: метка, тон и подсказка. `null` — ответа ещё нет. */
export function notifyView(
  r: Pick<OperatorRequest, 'status' | 'answer' | 'notify'>,
): { label: string; tone: Tone; tip: string; state: RequestNotify['status'] | 'none' } | null {
  if (!r.answer) return null;
  const n = r.notify;
  if (!n)
    return {
      label: 'в Telegram ещё не отправлен',
      tone: 'idle',
      tip: 'Ответ записан, но в Telegram его ещё не отправляли. Он есть здесь',
      state: 'none',
    };
  const when = dateTimeMsk(n.at);
  if (n.status === 'sent')
    return {
      label: 'дошёл в Telegram',
      tone: 'ok',
      tip: `Ответ пришёл вам в Telegram${when ? ` ${when}` : ''}`,
      state: 'sent',
    };
  return {
    label: 'в Telegram не дошёл',
    tone: 'danger',
    tip: `Telegram не принял ответ${when ? ` ${when}` : ''}. Ответ есть здесь; отправить его ещё раз может оператор. Причина — в «подробнее»`,
    state: 'failed',
  };
}

const time = (iso: string | null) => (iso ? Date.parse(iso) || 0 : 0);

/** С ответом — по времени ответа, новые сверху. */
export function answeredOrder(a: OperatorRequest, b: OperatorRequest): number {
  return time(b.answered_at) - time(a.answered_at) || b.n - a.n;
}

/** В работе — новые сверху. */
export function pendingOrder(a: OperatorRequest, b: OperatorRequest): number {
  return time(b.created) - time(a.created) || b.n - a.n;
}

/** История — по времени «закрыта» / «отменена», новые сверху. */
export function requestHistoryOrder(a: OperatorRequest, b: OperatorRequest): number {
  const at = (r: OperatorRequest) => time(r.closed_at ?? r.cancelled_at ?? r.updated);
  return at(b) - at(a) || b.n - a.n;
}
