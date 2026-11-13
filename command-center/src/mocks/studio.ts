// Подставное чтение YouTube Studio по кнопке (CC-0120, фабрика CF-0735) — с состоянием: «пора
// ли» по хукам, план, запуск с одноразовым токеном и опрос итога. Как у `api/studio_center.py`:
// выключатель запуска STUDIO_READ_LAUNCH по умолчанию выключен (`launch.available: false`,
// «да» — 409 `launch_off`), план виден всегда. Ручки теста: включить запуск, исход сессии
// (прочитано / расширение не подключено / нужен вход / ошибка), сколько опросов сессия
// «читается», пора ли по хукам, отказ фабрики в плане, «не рабочая фабрика» у первого
// открытия. Ни одной настоящей сессии Claude и Chrome — это подставка.
import type { components } from '../api/schema.gen';
import { MOCK_NOW } from './schedule';

type S = components['schemas'];
type Problem = S['StudioCenterProblem'];
type Hook = NonNullable<S['StudioReadDue']['hook']>;

export type StudioReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: Problem | S['WritesProblem'] };

/** Исход сессии чтения (`StudioReadResult.code` без «читается»). */
export type StudioOutcome = 'read' | 'no_extension' | 'login_needed' | 'error';

export const STUDIO_CHANNELS = ['example-film', 'example-science', 'example-tech'];
const NAMES: Record<string, string> = {
  'example-film': 'Example Reel',
  'example-science': 'Example Science',
  'example-tech': 'Example Tech',
};

/** Слова фабрики (`OUTCOME_WORDS`). */
export const OUTCOME_WORDS: Record<S['StudioReadResult']['code'], string> = {
  read: 'прочитано',
  no_extension: 'расширение не подключено',
  login_needed: 'нужен вход',
  error: 'ошибка',
  running: 'читается',
};

const OUTCOME_DETAIL: Record<StudioOutcome, string> = {
  read: 'доля «досмотрели/пролистали» записана по всем каналам',
  no_extension: 'Claude in Chrome не ответил — откройте Chrome и включите расширение',
  login_needed: 'Studio просит войти в аккаунт — войдите в Chrome и нажмите ещё раз',
  error: 'сессия чтения завершилась с ошибкой (код 1)',
};

export const HOOK_WORDS: Record<Hook | 'none', string> = {
  'batch-start': 'запуск батча',
  upload: 'загрузка ролика',
  'center-first-open-of-day': 'первое открытие центра за день',
  none: 'без повода',
};

/** Строка выключателя запуска (`launch.why`). */
export const LAUNCH_OFF_WHY =
  'Запуск чтения из центра пока выключен: первый запуск делается вместе с вами.';

const REFUSAL_LINES: Record<S['StudioRefusal']['code'], string> = {
  bad_who: 'Кто читает — не «user».',
  no_channels: 'Читать нечего: у каналов нет страницы Studio.',
  running: 'Чтение Studio уже идёт — дождитесь итога.',
  no_claude: 'Claude Code не найден на этом компьютере.',
  spawn_failed: 'Сессию чтения не удалось запустить.',
};

const problem = (
  status: 404 | 409 | 422,
  code: Problem['code'],
  message: string,
  details: string[] = [],
): StudioReply => ({ status, body: { code, message, details } });

const iso = (hoursAgo: number) =>
  new Date(Date.parse(MOCK_NOW) - hoursAgo * 3_600_000).toISOString().replace('.000Z', 'Z');

export function createStudioBackend() {
  const state = {
    /** Выключатель STUDIO_READ_LAUNCH: по умолчанию выключен, как на проде. */
    available: false,
    /** Пора ли читать по хуку (`none` — без хука). */
    due: {
      'center-first-open-of-day': false,
      'batch-start': false,
      upload: false,
      none: false,
    } as Record<Hook | 'none', boolean>,
    /** Возраст последнего чтения, ч; null — ни разу не читали. */
    ageHours: 30 as number | null,
    /** Чем кончится следующая сессия. */
    outcome: 'read' as StudioOutcome,
    /** Сколько опросов сессия ещё «читается», прежде чем ответить итогом. */
    pollsToDone: 1,
    /** `poll_s` запуска и опроса. */
    pollS: 1,
    /** Отказ фабрики в плане (ok:false) — `refusals[0]`. */
    refuse: null as S['StudioRefusal']['code'] | null,
    /** Вне рабочей фабрики: первое открытие (пишет `center-opens.json`) — 409. */
    readOnly: false,
    /** Идущая сессия, о которой знает «пора ли» (`running`). */
    running: null as string | null,
  };
  /** Каждый запрос: «GET due?hook=…», «POST plan», «POST read», «GET run». */
  const calls: string[] = [];
  const tokens = new Map<string, number>();
  const runs = new Map<string, { polls: number; outcome: StudioOutcome }>();
  let n = 0;

  const channelRow = (c: string): S['StudioReadDueChannel'] => ({
    channel: c,
    due: state.ageHours == null || state.ageHours >= 24,
    why:
      state.ageHours == null
        ? `${NAMES[c]}: Studio ни разу не читали`
        : `${NAMES[c]}: последнее чтение ${Math.round(state.ageHours)} ч назад`,
    last_read_at: state.ageHours == null ? null : iso(state.ageHours),
    age_hours: state.ageHours,
  });

  const launch = (): S['StudioLaunch'] => ({
    available: state.available,
    why: state.available ? null : LAUNCH_OFF_WHY,
    switch: 'STUDIO_READ_LAUNCH',
  });

  return {
    state,
    calls,
    /** Включить или выключить запуск из центра (выключатель API). */
    setLaunch(available: boolean) {
      state.available = available;
    },
    /** Пора читать по хукам `hooks` (по умолчанию — по всем). */
    setDue(due: boolean, hooks: (Hook | 'none')[] = Object.keys(state.due) as Hook[]) {
      for (const h of hooks) state.due[h] = due;
    },
    setOutcome(outcome: StudioOutcome) {
      state.outcome = outcome;
    },
    /** Все токены плана истекли (как после `expires_in_s`). */
    expireTokens() {
      for (const k of tokens.keys()) tokens.set(k, 0);
    },

    due(hook: string | null, channel: string | null): StudioReply {
      calls.push(`GET due?hook=${hook ?? ''}`);
      if (hook && !(hook in HOOK_WORDS))
        return problem(422, 'bad_hook', `Неизвестный повод чтения: «${hook}».`);
      if (channel && !STUDIO_CHANNELS.includes(channel))
        return problem(422, 'bad_channel', `Канала «${channel}» нет.`);
      if (hook === 'center-first-open-of-day' && state.readOnly)
        return {
          status: 409,
          body: {
            code: 'not_working_factory',
            message: 'Только смотреть: рабочая копия разработки',
            details: [],
          } as unknown as S['WritesProblem'],
        };
      const key = (hook ?? 'none') as Hook | 'none';
      const due = state.due[key];
      const age = state.ageHours;
      const body: S['StudioReadDue'] = {
        task: 'CF-0735',
        channel,
        hook: (hook as Hook | null) ?? null,
        hooks: ['batch-start', 'upload', 'center-first-open-of-day'],
        hook_words: HOOK_WORDS,
        due,
        why: due
          ? age == null
            ? 'Studio ни разу не читали — пора прочитать доли «досмотрели».'
            : `Studio не читали ${Math.round(age)} ч — пора проверить досмотры.`
          : age == null
            ? 'Читать пока нечего.'
            : `Studio читали ${Math.round(age)} ч назад — свежо.`,
        last_read_at: age == null ? null : iso(age),
        age_hours: age,
        first_open_today: hook === 'center-first-open-of-day' ? due : null,
        running: state.running,
        channels: (channel ? [channel] : STUDIO_CHANNELS).map(channelRow),
        skipped: [],
        launch: launch(),
      };
      return { status: 200, body };
    },

    plan(): StudioReply {
      calls.push('POST plan');
      const refusal = state.refuse
        ? {
            code: state.refuse,
            line: `refused: ${state.refuse}`,
            message: REFUSAL_LINES[state.refuse],
          }
        : null;
      const ok = !refusal;
      const confirm = ok && state.available ? `studio-${++n}` : null;
      if (confirm) tokens.set(confirm, Date.now() + 120_000);
      const body: S['StudioReadPlan'] = {
        action: 'studio_read_launch',
        ok,
        why: refusal ? refusal.message : state.available ? null : LAUNCH_OFF_WHY,
        launched: false,
        confirmed: false,
        task: 'CF-0735',
        by: 'user',
        via: 'center',
        channels: STUDIO_CHANNELS,
        argv: ['claude', '-p', '--chrome', '--allowedTools', 'mcp__claude-in-chrome__*', '…'],
        run_id: null,
        pid: null,
        log: null,
        refusals: refusal ? [refusal] : [],
        lines: [
          `Прочитаю Studio каналов: ${STUDIO_CHANNELS.map((c) => NAMES[c]).join(', ')}.`,
          'Только studio.youtube.com, только чтение; итог запишет studio_read.py record.',
        ],
        launch: launch(),
        fingerprint: 'sha256:5a7d0c',
        confirm,
        expires_in_s: confirm ? 120 : null,
      };
      return { status: 200, body };
    },

    start(body: unknown): StudioReply {
      calls.push('POST read');
      if (!state.available) return problem(409, 'launch_off', LAUNCH_OFF_WHY);
      const token = (body as { confirm?: unknown } | null)?.confirm;
      if (typeof token !== 'string' || !tokens.has(token))
        return problem(409, 'confirm_unknown', 'Подтверждение не найдено — проверьте заново.');
      const expires = tokens.get(token)!;
      tokens.delete(token);
      if (expires < Date.now())
        return problem(409, 'confirm_expired', 'Подтверждение устарело — проверьте заново.');
      const runId = `20261010T0700Z-${++n}`;
      runs.set(runId, { polls: 0, outcome: state.outcome });
      state.running = runId;
      const started: S['StudioReadStarted'] = {
        ok: true,
        launched: true,
        run_id: runId,
        pid: 51200 + n,
        log: `schedule/studio-read/runs/${runId}.log`,
        channels: STUDIO_CHANNELS,
        argv: ['claude', '-p', '--chrome', '…'],
        by: 'user',
        via: 'center',
        lines: ['Сессия чтения запущена.'],
        poll_s: state.pollS,
      };
      return { status: 200, body: started };
    },

    result(runId: string): StudioReply {
      calls.push('GET run');
      const run = runs.get(runId);
      if (!run) return problem(404, 'unknown_run', `Сессии чтения «${runId}» нет.`);
      run.polls++;
      const done = run.polls > state.pollsToDone;
      const code = done ? run.outcome : 'running';
      if (done && state.running === runId) state.running = null;
      if (done && code === 'read') {
        state.ageHours = 0;
        for (const k of Object.keys(state.due) as Hook[]) state.due[k] = false;
      }
      const detail = done ? OUTCOME_DETAIL[run.outcome] : 'сессия ещё читает Studio';
      const body: S['StudioReadResult'] = {
        run_id: runId,
        log: `schedule/studio-read/runs/${runId}.log`,
        code,
        word: OUTCOME_WORDS[code],
        done,
        line: `${OUTCOME_WORDS[code]}: ${detail}`,
        detail,
        recorded: done && code === 'read' ? STUDIO_CHANNELS : [],
        poll_s: done ? null : state.pollS,
      };
      return { status: 200, body };
    },
  };
}

export type StudioBackend = ReturnType<typeof createStudioBackend>;

/** Ответ подставного чтения Studio на запрос, null — адрес не его. */
export function routeStudio(
  backend: StudioBackend,
  method: string,
  url: URL,
  body: unknown = null,
): StudioReply | null {
  const p = url.pathname;
  if (method === 'GET' && p.endsWith('/api/studio/due'))
    return backend.due(url.searchParams.get('hook'), url.searchParams.get('channel'));
  if (method === 'POST' && p.endsWith('/api/studio/read/plan')) return backend.plan();
  if (method === 'POST' && p.endsWith('/api/studio/read')) return backend.start(body);
  const m = p.match(/\/api\/studio\/read\/([^/]+)$/);
  if (method === 'GET' && m) return backend.result(decodeURIComponent(m[1]!));
  return null;
}
