// Уведомления и напоминания (CC-0026 фабрики, договор 0.27.0; экран — CC-0027): журнал уведомлений
// (`GET /api/notify/journal?kind&channel&limit` — `notify.py list`, новые в конце, по умолчанию
// последние 20, `0` — все), напоминания (`GET /api/notify/reminders?all` — `remind --list`, у каждого
// `due_msk`) и проверка каналов уведомлений (`GET /api/notify/check` — сухой `notify.py test`:
// строки CLI как напечатаны и какие бэкенды включены; ничего не отправляется). Поставить
// напоминание — в два вызова, как записи публикации: `…/reminders/plan {at, text}` ничего не пишет
// и показывает время и текст, как их поставит очередь, с токеном на `expires_in_s`;
// `…/reminders {confirm}` ставит (`add_reminder(by=user)`). Отменить — так же: `…/{rid}/cancel/plan`
// (что значит отмена, токен; отправленное и отменённое — 409 `not_cancellable`) и
// `…/{rid}/cancel {confirm}` (`cancel_reminder(by=user, via=center)`, CC-0081; экран — CC-0087).
// Проверка каналов — по `preview` (поля `notify.test_preview`), строки CLI — для «подробнее».
// Отказы — `NotifyProblem {message, code, details}` (разбирает `takeBatch`), словами —
// `notifyProblemText`.
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { BatchError, takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { writeProblemText } from './publishWrites';

export type NotifyJournal = Schemas['NotifyJournal'];
export type NotifyEvent = Schemas['NotifyEvent'];
export type NotifyReminders = Schemas['NotifyReminders'];
export type NotifyReminder = Schemas['NotifyReminder'];
export type NotifyCheck = Schemas['NotifyCheck'];
export type NotifyReminderPlan = Schemas['NotifyReminderPlan'];
export type NotifyReminderResult = Schemas['NotifyReminderResult'];
export type NotifyProblem = Schemas['NotifyProblem'];
export type NotifyBackendPreview = Schemas['NotifyBackendPreview'];
export type NotifyCancelPlan = Schemas['NotifyCancelPlan'];
export type NotifyCancelResult = Schemas['NotifyCancelResult'];
export type NotifyTestSendPlan = Schemas['NotifyTestSendPlan'];
export type NotifyTestSendResult = Schemas['NotifyTestSendResult'];

/** Код отказа API уведомлений, если ошибка — его отказ (`NotifyProblem`). */
export function notifyCode(e: unknown): NotifyProblem['code'] | null {
  return e instanceof BatchError
    ? ((e.problem?.code as NotifyProblem['code'] | undefined) ?? null)
    : null;
}

/** Что показать в журнале: вид, канал, сколько последних (`0` — все). */
export type JournalQuery = { kind: string | null; channel: string | null; limit: number };

/** Сколько последних строк журнала по умолчанию (как у `notify.py list`). */
export const JOURNAL_LIMIT = 20;

export async function getJournal(q: JournalQuery, signal?: AbortSignal): Promise<NotifyJournal> {
  return takeBatch(
    await api.GET('/api/notify/journal', {
      params: {
        query: {
          limit: q.limit,
          ...(q.kind ? { kind: q.kind } : {}),
          ...(q.channel ? { channel: q.channel } : {}),
        },
      },
      signal,
    }),
  );
}

export async function getReminders(all: boolean, signal?: AbortSignal): Promise<NotifyReminders> {
  return takeBatch(await api.GET('/api/notify/reminders', { params: { query: { all } }, signal }));
}

export async function getCheck(signal?: AbortSignal): Promise<NotifyCheck> {
  return takeBatch(await api.GET('/api/notify/check', { signal }));
}

const call = <T>(fn: (signal: AbortSignal) => Promise<T>) => within(PLAN_TIMEOUT_MS, fn);

/** Что вписано в форму напоминания. */
export type ReminderForm = { at: string; text: string };

export const planReminder = (f: ReminderForm) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/notify/reminders/plan', { body: f, signal })),
  );

export const addReminder = (confirm: string) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/notify/reminders', { body: { confirm }, signal })),
  );

export const planReminderCancel = (rid: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/notify/reminders/{rid}/cancel/plan', {
        params: { path: { rid } },
        signal,
      }),
    ),
  );

export const cancelReminder = (rid: string, confirm: string) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/notify/reminders/{rid}/cancel', {
        params: { path: { rid } },
        body: { confirm },
        signal,
      }),
    ),
  );

/**
 * Пробное сообщение (CC-0109): план — каналы по имени и сухой прогон фабрики, ничего не уходит;
 * «да» — `{confirm}`, тогда шина отправляет сообщение во все включённые каналы.
 */
export const planTestSend = () =>
  call(async (signal) => takeBatch(await api.POST('/api/notify/test-send/plan', { signal })));

export const testSend = (confirm: string) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/notify/test-send', { body: { confirm }, signal })),
  );

/** После пробного сообщения — перечитать журнал уведомлений. */
export function useAfterTestSend() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ['api', 'notify', 'journal'] });
}

export const notifyKeys = {
  all: ['api', 'notify'] as const,
  journal: (q: JournalQuery) =>
    ['api', 'notify', 'journal', q.kind ?? '', q.channel ?? '', q.limit] as const,
  reminders: (all: boolean) => ['api', 'notify', 'reminders', all] as const,
  check: ['api', 'notify', 'check'] as const,
};

/** Отказ 4xx (вид неизвестен) повтором не лечится; сеть и 5xx — до трёх раз. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Журнал и напоминания пишет фабрика по событиям: перечитываем раз в минуту и при возврате. */
const minute = { refetchInterval: 60_000, refetchIntervalInBackground: false, retry } as const;

export function useJournal(q: JournalQuery) {
  return useQuery({
    queryKey: notifyKeys.journal(q),
    queryFn: ({ signal }) => getJournal(q, signal),
    placeholderData: keepPreviousData,
    ...minute,
  });
}

/** Напоминания: `all` — ещё и отправленные и отменённые. */
export function useReminders(all: boolean) {
  return useQuery({
    queryKey: notifyKeys.reminders(all),
    queryFn: ({ signal }) => getReminders(all, signal),
    placeholderData: keepPreviousData,
    ...minute,
  });
}

/** Проверка каналов — сухой прогон: без опроса, заново — по кнопке. */
export function useCheck() {
  return useQuery({
    queryKey: notifyKeys.check,
    queryFn: ({ signal }) => getCheck(signal),
    staleTime: 300_000,
    retry,
  });
}

/** После записи (и отказа «да») перечитать напоминания. */
export function useAfterReminderWrite() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ['api', 'notify', 'reminders'] });
}

// ---------------------------------------------------------------- слова
const NOTIFY_PROBLEM_TEXT: Record<string, string> = {
  bad_kind: 'Такого вида уведомлений у фабрики нет',
  bad_time: 'Время не подходит — напоминание не поставлено',
  no_text: 'Напишите, о чём напомнить',
  refused: 'Фабрика не поставила напоминание',
  check_changed: 'Напоминание изменилось с момента плана — посмотрите план заново',
  no_reminder: 'Такого напоминания в очереди нет',
  not_cancellable: 'Отменять нечего — напоминание уже отправлено или отменено',
  factory_broken:
    'Фабрика ответила ошибкой — посмотрите состояние уведомлений, прежде чем повторять',
};

export const notifyProblemText = (code: string | null | undefined): string =>
  (code && NOTIFY_PROBLEM_TEXT[code]) || writeProblemText(code);

/** Отказ пробного сообщения словами: каналы сменились с плана — свой текст. */
export const testSendProblemText = (code: string | null | undefined): string =>
  code === 'check_changed'
    ? 'Каналы доставки изменились с момента плана — посмотрите план заново'
    : notifyProblemText(code);

/** Почему план спрашивать рано, или null. */
export function reminderWhy(f: ReminderForm): string | null {
  if (!f.at.trim() && !f.text.trim()) return 'Впишите, когда и о чём напомнить';
  if (!f.at.trim()) return 'Впишите время: «21:00» или «2026-10-13 21:00» по Москве';
  if (!f.text.trim()) return 'Напишите, о чём напомнить';
  return null;
}
