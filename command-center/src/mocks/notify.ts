// Подставные «Уведомления и напоминания» (CC-0026 фабрики, договор 0.27.0; экран — CC-0027). Общий
// для Vitest (MSW, src/mocks/handlers.ts), Playwright (tests/e2e/fixtures.ts) и тренировки
// (src/training/demo.ts). Данные — ./notifyData. Чтения: журнал (`kind` / `channel` / `limit`,
// неизвестный вид — 422 `bad_kind`), напоминания (`all`), сухая проверка каналов (строки CLI).
// Запись одна — поставить напоминание: `…/reminders/plan {at, text}` — упрощённые `parse_when` и
// `one_line` фабрики по часам `state.now` (МСК — UTC+3), одноразовый токен на `life` секунд;
// `…/reminders {confirm}` — токен сгорает при любом исходе, время пересчитывается (`check_changed`,
// если сдвинулось), тот же текст на то же время в очереди — `created: false`. Отменить (CC-0087):
// `…/{rid}/cancel/plan` — нет такого — 404 `no_reminder`, отправлено или отменено — 409
// `not_cancellable`; `…/{rid}/cancel {confirm}` — отменяет (by user, via center). Ручки теста:
// `refuse` (чтение → 500 `factory_broken`), `next` (исход следующего «да»: `check_changed`,
// `factory_broken`, `sent_meanwhile` — напоминание ушло до «да»), `readOnly` (каждый POST —
// 409 `not_working_factory`), `life`, `check`, `calls`, `written`. Пробное сообщение (CC-0109,
// CC-0115 шаг 3): `…/test-send/plan` — каналы из `state.check.preview` по имени, сухой прогон
// (`would`), токен; `…/test-send {confirm}` — каналы сменились с плана (`check_changed`), иначе
// строка `test` в журнале и ответ по каналам (`state.testAnswers` — свой ответ канала, например
// `error: HTTP 502`). Импорты — относительные.
import type { components } from '../api/schema.gen';
import { CHECK, JOURNAL, KINDS, MAX_ATTEMPTS, NOTIFY_NOW, REMINDERS } from './notifyData';

type S = components['schemas'];
type Code = S['NotifyProblem']['code'] | 'not_working_factory';

export type NotifyReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: Code; details: string[] } };

export type NotifyPart = 'journal' | 'reminders' | 'check';
export type NotifyOutcome = 'check_changed' | 'factory_broken' | 'sent_meanwhile';

class Fault extends Error {
  readonly status: 404 | 409 | 422 | 500;
  readonly code: Code;
  readonly details: string[];
  constructor(status: 404 | 409 | 422 | 500, code: Code, message: string, details: string[]) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const fault = (e: Fault): NotifyReply => ({
  status: e.status,
  body: { message: e.message, code: e.code, details: e.details },
});

const MSK_MS = 3 * 3600_000;
const pad = (n: number) => String(n).padStart(2, '0');
const iso = (ms: number) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

/** `notify.msk_text`: «2026-10-12 21:00 МСК». */
export function mskText(utc: string | null | undefined): string {
  const t = utc ? Date.parse(utc) : NaN;
  if (Number.isNaN(t)) return String(utc);
  const d = new Date(t + MSK_MS);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} МСК`;
}

const WHEN_RE = /^\s*(?:(\d{4}-\d{2}-\d{2})[ T])?(\d{1,2}):(\d{2})\s*(?:МСК|MSK|мск|msk)?\s*$/;

/** `notify.parse_when`: время по Москве → UTC ISO; ошибка — строка фабрики (по-английски). */
export function parseWhen(text: string, now: string): string {
  const m = WHEN_RE.exec(text);
  if (!m) throw new Error(`--at '${text}': expected «ЧЧ:ММ» or «YYYY-MM-DD ЧЧ:ММ», Moscow time`);
  const [, day, h, mi] = m;
  const hh = Number(h);
  const mm = Number(mi);
  if (hh > 23 || mm > 59) throw new Error(`--at '${text}': no such time`);
  const nowMs = Date.parse(now);
  const local = new Date(nowMs + MSK_MS);
  if (day) {
    const [y, mo, d] = day.split('-').map(Number) as [number, number, number];
    const due = Date.UTC(y, mo - 1, d, hh, mm) - MSK_MS;
    const back = new Date(due + MSK_MS);
    if (back.getUTCMonth() !== mo - 1 || back.getUTCDate() !== d)
      throw new Error(`--at '${text}': no such date`);
    if (due < nowMs)
      throw new Error(
        `--at '${text}': that time has passed (${mskText(now).slice(0, 16)} МСК now)`,
      );
    return iso(due);
  }
  let due =
    Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate(), hh, mm) - MSK_MS;
  if (due <= nowMs) due += 86_400_000;
  return iso(due);
}

/** `notify.one_line`: одна строка, пробелы схлопнуты, не длиннее `limit`. */
export function oneLine(text: string, limit = 1000): string {
  const t = text.replace(/\s+/g, ' ').trim();
  return t.length > limit ? `${t.slice(0, limit - 1)}…` : t;
}

const deep = <T>(x: T): T => structuredClone(x);

export function createNotifyBackend() {
  const tokens = new Map<string, { at: string; text: string; fp: string; expires: number }>();
  let n = 0;
  const state = {
    now: NOTIFY_NOW,
    journal: deep(JOURNAL),
    reminders: deep(REMINDERS),
    check: deep(CHECK),
    /** Сломанные чтения: часть → 500 `factory_broken`. */
    refuse: {} as Partial<Record<NotifyPart, true>>,
    /** Исход следующего «да» (одноразово). */
    next: null as NotifyOutcome | null,
    /** API не на рабочей фабрике: каждый POST — 409 `not_working_factory`. */
    readOnly: false,
    /** Срок жизни токена, секунд (у фабрики — 120). */
    life: 120,
    /** Каждый запрос: «МЕТОД путь?запрос». */
    calls: [] as string[],
    /** Поставленные из центра напоминания (id). */
    written: [] as string[],
    /** Ответ канала на пробное сообщение (нет — «ok» у готового, «skipped: …» у прочих). */
    testAnswers: {} as Record<string, string>,
    /** Отправленные пробные сообщения (ключи журнала). */
    testSent: [] as string[],
  };
  const tests = new Map<string, { fp: string; expires: number }>();

  const withMsk = (r: S['NotifyReminder']): S['NotifyReminder'] => ({
    ...r,
    due_msk: mskText(r.due),
  });

  const broken = (part: NotifyPart) => {
    if (!state.refuse[part]) return;
    if (part === 'check')
      throw new Fault(500, 'factory_broken', 'Проверка уведомлений фабрики не прошла.', [
        'notify.py test: exit 1',
        'backends on: log, telegram (NOTIFY_BACKENDS; default log)',
      ]);
    throw new Fault(
      500,
      'factory_broken',
      'Фабрика ответила ошибкой: уведомления не прочитать - посмотрите notify/, прежде чем повторять.',
      ['PermissionError: [Errno 13] Permission denied: notify/'],
    );
  };

  function journal(q: URLSearchParams): NotifyReply {
    broken('journal');
    const kind = q.get('kind');
    const channel = q.get('channel');
    const limit = q.has('limit') ? Number(q.get('limit')) : 20;
    if (kind && !(KINDS as readonly string[]).includes(kind))
      throw new Fault(422, 'bad_kind', `Нет такого вида уведомлений: «${kind}».`, [
        `kind '${kind}': one of ${KINDS.join(', ')}`,
      ]);
    const got = state.journal.filter(
      (r) => (!kind || r.kind === kind) && (!channel || r.channel === channel),
    );
    const shown = limit > 0 ? got.slice(-limit) : got;
    return {
      status: 200,
      body: {
        path: 'notify/sent.jsonl',
        kinds: [...KINDS],
        total: got.length,
        events: deep(shown),
      } satisfies S['NotifyJournal'],
    };
  }

  function reminders(q: URLSearchParams): NotifyReply {
    broken('reminders');
    const all = q.get('all') === 'true';
    const shown = all
      ? state.reminders
      : state.reminders.filter((r) => r.status !== 'sent' && r.status !== 'cancelled');
    return {
      status: 200,
      body: {
        path: 'notify/reminders.jsonl',
        all,
        max_attempts: MAX_ATTEMPTS,
        reminders: shown.map(withMsk),
      } satisfies S['NotifyReminders'],
    };
  }

  function check(): NotifyReply {
    broken('check');
    return { status: 200, body: deep(state.check) };
  }

  const guard = () => {
    if (state.readOnly)
      throw new Fault(
        409,
        'not_working_factory',
        'Только смотреть: рабочая копия на ветке cc-api, а не main',
        ['CC_API_WRITES is off'],
      );
  };

  /** (due, text) или отказ — как `_plan` API. */
  const planOf = (at: string, text: string): { due: string; line: string } => {
    let due: string;
    try {
      due = parseWhen(at, state.now);
    } catch (e) {
      throw new Fault(
        422,
        'bad_time',
        `Время «${at}» не подходит: нужно «ЧЧ:ММ» или «ГГГГ-ММ-ДД ЧЧ:ММ» по Москве, не в прошлом.`,
        [(e as Error).message],
      );
    }
    const line = oneLine(text);
    if (!line)
      throw new Fault(422, 'no_text', 'Напишите, о чём напомнить.', ['a reminder needs a text']);
    return { due, line };
  };

  function plan(raw: unknown): NotifyReply {
    guard();
    const b = (raw ?? {}) as { at?: unknown; text?: unknown };
    const at = typeof b.at === 'string' ? b.at : '';
    const text = typeof b.text === 'string' ? b.text : '';
    const { due, line } = planOf(at, text);
    const fp = JSON.stringify([due, line]);
    const confirm = `notify-${++n}`;
    tokens.set(confirm, { at, text, fp, expires: Date.now() + state.life * 1000 });
    return {
      status: 200,
      body: {
        action: 'notify_reminder_add',
        ok: true,
        why: null,
        at,
        due,
        due_msk: mskText(due),
        text: line,
        by: 'user',
        via: 'center',
        now: state.now,
        fingerprint: `sha256:${fp.length}-${n}`,
        confirm,
        expires_in_s: state.life,
      } satisfies S['NotifyReminderPlan'],
    };
  }

  function confirm(raw: unknown): NotifyReply {
    guard();
    const token = (raw as { confirm?: string } | null)?.confirm ?? '';
    const got = tokens.get(token);
    tokens.delete(token);
    if (!got)
      throw new Fault(
        409,
        'confirm_unknown',
        'Подтверждение не найдено или уже использовано - запросите план напоминания заново.',
        ['no such confirm token in this API process (used, unknown, or the server restarted)'],
      );
    if (got.expires <= Date.now())
      throw new Fault(
        409,
        'confirm_expired',
        'Подтверждение устарело (живёт 120 с) - запросите план напоминания заново.',
        ['expired'],
      );
    const next = state.next;
    state.next = null;
    const { due, line } = planOf(got.at, got.text);
    if (next === 'check_changed' || JSON.stringify([due, line]) !== got.fp)
      throw new Fault(
        409,
        'check_changed',
        'Время напоминания изменилось с момента плана - напоминание не поставлено; посмотрите план заново.',
        [`due ${due} differs from the plan's for --at '${got.at}'`],
      );
    if (next === 'factory_broken')
      throw new Fault(
        500,
        'factory_broken',
        'Фабрика ответила ошибкой: напоминание не записано - посмотрите notify/, прежде чем повторять.',
        ['OSError: [Errno 28] No space left on device'],
      );
    const same = state.reminders.find(
      (r) => (r.status === 'pending' || r.status === 'failed') && r.due === due && r.text === line,
    );
    if (same)
      return {
        status: 200,
        body: {
          action: 'notify_reminder_add',
          written: true,
          created: false,
          by: 'user',
          via: 'center',
          reminder: withMsk(same),
        } satisfies S['NotifyReminderResult'],
      };
    const id = `R${Math.max(0, ...state.reminders.map((r) => Number(r.id.slice(1)) || 0)) + 1}`;
    const r: S['NotifyReminder'] = {
      id,
      due,
      due_msk: '',
      text: line,
      created: state.now,
      by: 'user',
      via: 'center',
      status: 'pending',
      sent_at: null,
      cancelled_at: null,
      backends: null,
      attempts: 0,
      last_try: null,
      reason: null,
    };
    state.reminders.push(r);
    state.written.push(id);
    return {
      status: 200,
      body: {
        action: 'notify_reminder_add',
        written: true,
        created: true,
        by: 'user',
        via: 'center',
        reminder: withMsk(r),
      } satisfies S['NotifyReminderResult'],
    };
  }

  const cancels = new Map<string, { rid: string; fp: string; expires: number }>();

  /** Напоминание, которое можно отменить, или отказ фабрики. */
  const cancellable = (rid: string): S['NotifyReminder'] => {
    const r = state.reminders.find((x) => x.id === rid);
    if (!r)
      throw new Fault(404, 'no_reminder', `Напоминания ${rid} нет в очереди.`, [
        `notify.cancel_reminder: no ${rid}`,
      ]);
    if (r.status === 'sent' || r.status === 'cancelled')
      throw new Fault(
        409,
        'not_cancellable',
        r.status === 'sent'
          ? `Напоминание ${rid} уже отправлено - отменять нечего.`
          : `Напоминание ${rid} уже отменено.`,
        [`notify.cancel_reminder: ${rid} is ${r.status}`],
      );
    return r;
  };

  const cancelFp = (r: S['NotifyReminder']) => JSON.stringify([r.id, r.status, r.due, r.text]);

  function cancelPlan(rid: string): NotifyReply {
    guard();
    const r = cancellable(rid);
    const confirm = `notify-cancel-${++n}`;
    const fp = cancelFp(r);
    cancels.set(confirm, { rid, fp, expires: Date.now() + state.life * 1000 });
    return {
      status: 200,
      body: {
        action: 'notify_reminder_cancel',
        ok: true,
        why: null,
        id: r.id,
        status: r.status as S['NotifyCancelPlan']['status'],
        means:
          r.status === 'pending'
            ? 'Напоминание не уйдёт: фабрика уберёт его из очереди и запишет, кто отменил.'
            : 'Фабрика перестанет пробовать его отправить и запишет, кто отменил.',
        reminder: withMsk(r),
        by: 'user',
        via: 'center',
        fingerprint: `sha256:${fp.length}-${n}`,
        confirm,
        expires_in_s: state.life,
      } satisfies S['NotifyCancelPlan'],
    };
  }

  function cancel(rid: string, raw: unknown): NotifyReply {
    guard();
    const token = (raw as { confirm?: string } | null)?.confirm ?? '';
    const got = cancels.get(token);
    cancels.delete(token);
    if (!got || got.rid !== rid)
      throw new Fault(
        409,
        got ? 'confirm_mismatch' : 'confirm_unknown',
        'Подтверждение не найдено или выдано не этому напоминанию - запросите план отмены заново.',
        ['no such confirm token for this reminder'],
      );
    if (got.expires <= Date.now())
      throw new Fault(
        409,
        'confirm_expired',
        'Подтверждение устарело (живёт 120 с) - запросите план отмены заново.',
        ['expired'],
      );
    const next = state.next;
    state.next = null;
    if (next === 'sent_meanwhile') {
      const r = state.reminders.find((x) => x.id === rid);
      if (r) {
        r.status = 'sent';
        r.sent_at = state.now;
      }
    }
    const r = cancellable(rid);
    if (next === 'check_changed' || cancelFp(r) !== got.fp)
      throw new Fault(
        409,
        'check_changed',
        'Напоминание изменилось с момента плана - ничего не отменено; посмотрите план заново.',
        ["the fingerprint of the cancel plan differs from the plan's"],
      );
    if (next === 'factory_broken')
      throw new Fault(500, 'factory_broken', 'Фабрика ответила ошибкой посреди отмены.', [
        'OSError: [Errno 28] No space left on device',
      ]);
    r.status = 'cancelled';
    r.cancelled_at = state.now;
    r.cancelled_by = 'user';
    r.cancelled_via = 'center';
    state.written.push(`cancel ${rid}`);
    return {
      status: 200,
      body: {
        action: 'notify_reminder_cancel',
        written: true,
        by: 'user',
        via: 'center',
        cancelled_at: state.now,
        cancelled_by: 'user',
        cancelled_via: 'center',
        reminder: withMsk(r),
      } satisfies S['NotifyCancelResult'],
    };
  }

  // ------------------------------------------------------------ пробное сообщение
  const TEST_TEXT = 'проверка уведомлений фабрики';
  const testChannels = () =>
    state.check.preview.map((p) => ({
      name: p.name,
      known: p.known,
      external: p.external,
      ready: p.ready,
      skip_reason: p.skip_reason ?? null,
    }));
  const skipped = (c: { ready: boolean; skip_reason: string | null }) =>
    `skipped: ${c.skip_reason ?? 'not ready'}`;

  function testPlan(): NotifyReply {
    guard();
    const chans = testChannels();
    const fp = JSON.stringify(chans);
    const outside = chans.filter((c) => c.external && c.ready).map((c) => c.name);
    const confirm = `notify-test-${++n}`;
    tests.set(confirm, { fp, expires: Date.now() + state.life * 1000 });
    return {
      status: 200,
      body: {
        action: 'notify_test_send',
        ok: true,
        why: null,
        channels: chans,
        names: chans.map((c) => c.name),
        outside,
        note: outside.length
          ? null
          : 'Ни один внешний канал не готов - сообщение увидят только локальные (журнал, лог).',
        text: `${TEST_TEXT} -> http://127.0.0.1:8790/`,
        would: chans.map((c) => ({
          via: c.name,
          ok: c.ready,
          detail: c.ready ? 'would send' : skipped(c),
        })),
        would_deliver: outside.length > 0,
        delivery_reason: outside.length ? null : 'no outside channel is ready',
        by: 'user',
        via: 'center',
        fingerprint: `sha256:${fp.length}-${n}`,
        confirm,
        expires_in_s: state.life,
      } satisfies S['NotifyTestSendPlan'],
    };
  }

  function testSend(raw: unknown): NotifyReply {
    guard();
    const token = (raw as { confirm?: string } | null)?.confirm ?? '';
    const got = tests.get(token);
    tests.delete(token);
    if (!got)
      throw new Fault(
        409,
        'confirm_unknown',
        'Подтверждение не найдено или уже использовано - запросите план заново.',
        ['no such confirm token in this API process'],
      );
    if (got.expires <= Date.now())
      throw new Fault(
        409,
        'confirm_expired',
        'Подтверждение устарело (живёт 120 с) - запросите план заново.',
        ['expired'],
      );
    const next = state.next;
    state.next = null;
    const chans = testChannels();
    if (next === 'check_changed' || JSON.stringify(chans) !== got.fp)
      throw new Fault(
        409,
        'check_changed',
        'Каналы доставки изменились с момента плана - пробное сообщение не отправлено; посмотрите план заново.',
        [`channels now: ${chans.map((c) => c.name).join(', ') || '-'}`],
      );
    if (next === 'factory_broken')
      throw new Fault(
        500,
        'factory_broken',
        'Шина уведомлений не отправила пробное сообщение - посмотрите notify/.',
        ['notify.send: OSError: [Errno 28] No space left on device'],
      );
    const key = `test:${state.now}`;
    const results = chans.map((c) => {
      const detail = state.testAnswers[c.name] ?? (c.ready ? 'ok' : skipped(c));
      return { via: c.name, ok: detail === 'ok', detail };
    });
    const outside = results.filter(
      (r) => chans.find((c) => c.name === r.via)?.external && !r.detail.startsWith('skipped'),
    );
    const delivered = !outside.length || outside.some((r) => r.ok);
    const text = `${TEST_TEXT}`;
    state.journal.push({
      at: state.now,
      kind: 'test',
      channel: null,
      key,
      text,
      link: 'http://127.0.0.1:8790/',
      backends: Object.fromEntries(results.map((r) => [r.via, r.detail])),
    });
    state.testSent.push(key);
    return {
      status: 200,
      body: {
        action: 'notify_test_send',
        sent: true,
        key,
        at: state.now,
        text,
        results,
        delivered,
        delivery_reason: delivered ? null : outside.map((r) => `${r.via}: ${r.detail}`).join('; '),
        recorded_by: true,
        by: 'user',
        via: 'center',
      } satisfies S['NotifyTestSendResult'],
    };
  }

  /** Все выданные токены устарели (как будто прошло 120 с) — «да» получит `confirm_expired`. */
  const expireTokens = () => {
    for (const t of tokens.values()) t.expires = 0;
    for (const t of cancels.values()) t.expires = 0;
    for (const t of tests.values()) t.expires = 0;
  };

  return {
    state,
    journal,
    reminders,
    check,
    plan,
    confirm,
    cancelPlan,
    cancel,
    testPlan,
    testSend,
    expireTokens,
  };
}

export type NotifyBackend = ReturnType<typeof createNotifyBackend>;

/** Ответ на запрос к API уведомлений или `null`, если запрос не к нему. */
export function routeNotify(
  backend: NotifyBackend,
  method: string,
  url: URL,
  body: unknown,
): NotifyReply | null {
  const c = url.pathname.match(/\/api\/notify\/reminders\/([^/]+)\/cancel(\/plan)?$/);
  if (c) {
    if (method !== 'POST') return null;
    backend.state.calls.push(`${method} ${url.pathname}`);
    try {
      const rid = decodeURIComponent(c[1]!);
      return c[2] ? backend.cancelPlan(rid) : backend.cancel(rid, body);
    } catch (e) {
      if (e instanceof Fault) return fault(e);
      throw e;
    }
  }
  const m = url.pathname.match(
    /\/api\/notify\/(journal|reminders|reminders\/plan|check|test-send|test-send\/plan)$/,
  );
  if (!m) return null;
  backend.state.calls.push(`${method} ${url.pathname}${url.search}`);
  try {
    const what = m[1];
    if (method === 'GET') {
      if (what === 'journal') return backend.journal(url.searchParams);
      if (what === 'reminders') return backend.reminders(url.searchParams);
      if (what === 'check') return backend.check();
      return null;
    }
    if (method === 'POST') {
      if (what === 'reminders/plan') return backend.plan(body);
      if (what === 'reminders') return backend.confirm(body);
      if (what === 'test-send/plan') return backend.testPlan();
      if (what === 'test-send') return backend.testSend(body);
    }
    return null;
  } catch (e) {
    if (e instanceof Fault) return fault(e);
    throw e;
  }
}
