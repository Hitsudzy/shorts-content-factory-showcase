// Подставные действия над батчами (CC-0046/0047 фабрики) — с состоянием: план запуска канала
// с проверками и токеном, запуск, остановить и продолжить батч (и пересборку). Токены — как
// у `api/batches.py`: одноразовые, со сроком `expires_in_s` (по настоящим часам), привязаны к
// действию, цели и `also_step`; `busy` токен не тратит. Ручки теста: срок токена, «следующий
// ответ — отказ», исход остановки (исполнитель пережил SIGTERM, шаг не умер), «сегодня батч
// уже был» (1 батч в сутки). Ни одного настоящего сигнала и запуска — это подставка.
import type { components } from '../api/schema.gen';
import type { BatchReply } from './schedule';
import { MOCK_BREAKER, MOCK_NOW, MOCK_QUOTA_DAY } from './schedule';

/**
 * Допуск по бюджету поиска проверки ручного запуска (`launch_check.budget`, CF-0830): второй батч
 * ExampleTech в сегодняшних сутках квоты — потрачено 82 + ожидается 18 = 100 > 95.
 */
export const LAUNCH_BUDGET: S['BudgetAdmission'] = {
  task: 'CF-0830',
  channel: 'example-tech',
  quota_day: MOCK_QUOTA_DAY,
  window_start: '2026-10-10T14:00:00Z',
  start: MOCK_NOW,
  nth: 2,
  batches: 1,
  max_batches: 2,
  limit: 100,
  margin: 5,
  spent: 82,
  spent_recorded: 82,
  spent_unrecorded: 0,
  spent_planned: 0,
  expected: 18,
  expected_n: 3,
  expected_line: '18 (медиана 3 последн. батчей: 15, 18, 22)',
  after: 100,
  left: 18,
  admitted: false,
  reason: 'budget',
  why: '2-й батч в сутки квоты YouTube 10.10 не допущен по бюджету поиска: потрачено 82 + ожидается 18 (example-tech: 18 (медиана 3 последн. батчей: 15, 18, 22)) = 100 > 95 (100 − запас 5); остаток 18',
};

type S = components['schemas'];
type Code = S['BatchProblem']['code'];

/** Вход Claude перед запуском (CC-0176, CF-0899 `batch_schedule.login_state`): залогинен. */
export const LOGIN_OK: S['LoginState'] = { ok: true, checked: true, line: 'claude залогинен' };
/** Не залогинен: план предупреждает, «да» получит 409 `not_logged_in` (токен потрачен). */
export const LOGIN_NO: S['LoginState'] = {
  ok: false,
  checked: true,
  line: 'claude не залогинен (`claude auth status`: loggedIn false)',
};
/** Неизвестно: вход не проверить — запуск идёт, строка — предупреждение. */
export const LOGIN_UNKNOWN: S['LoginState'] = {
  ok: null,
  checked: false,
  line: 'claude не найден - вход не проверен',
};
/** Сообщение отказа `not_logged_in` — как у cc/api (`batches.launch`). */
export const NOT_LOGGED_IN_MESSAGE =
  'claude не залогинен - войди в claude: в терминале `claude`, затем /login - батч не открыт.';

/** Корень подставной фабрики, как его называют ответы: с договора 0.35.0 (CC-0098 фабрики)
 *  абсолютных путей в ответах нет — внутри корня путь относительный, сам корень — `.../<имя>`. */
export const MOCK_ROOT = '.../shorts-content-factory';
const BY = 'user (центр)';
const TODAY = '2026-10-10';
const CHANNELS = ['example-film', 'example-science', 'example-tech'];
const PIPELINE = new Set(['example-film']);

/** Что о батче нужно действиям: живые объекты подставных батчей (src/mocks/batches.ts). */
export type ActionTarget = {
  going: S['BatchesGoing']['batches'][number];
  state: S['RunState'];
  /**
   * Исполнитель умер, не записав конца (перезагрузка, kill -9; CC-0094): `status` в run-state
   * остался `running`, живых процессов нет.
   */
  dead?: boolean;
  /** Фабрика отказывает продолжить (`resume/plan` ok:false) — её словами (CC-0089). */
  refuse?: string;
};

export type ActionStore = {
  list(): ActionTarget[];
  find(batch: string): ActionTarget | undefined;
  /** Новый идущий батч канала (после запуска). */
  launched(channel: string, batchId: string): void;
  /** Упавший батч продолжен — снова открыт (CC-0089). */
  resumed?(batch: string): void;
  /** Упавшие батчи канала, что держат сегодняшний день (`holds_day`, CC-0089). */
  holdingDay?(channel: string): S['BatchesGoing']['batches'][number][];
  /** У канала есть план прогона (у него был батч), хоть он и не в `PIPELINE`. */
  hasRunPlan?(channel: string): boolean;
};

type Action = 'launch' | 'stop' | 'resume' | 'rerun';
type Token = {
  action: Action;
  target: string;
  alsoStep: boolean;
  /** Стадия повтора (CC-0123): токен `rerun` привязан к ней. */
  stage?: string;
  expires: number;
};

/** Исход «сразу продолжить» после повтора со стадии: продолжил / не смог (`resume_failed`). */
export type RerunResume = 'ok' | 'failed';

/** Что после стадии остаётся на диске при повторе (CF-0739 `kept`): файлы готовых стадий до неё. */
const STAGE_FILES: Record<string, string> = {
  'rights-check': 'rights-check.json',
  'pool-maintenance': 'pool-maintenance.json',
  'trend-hunter': 'trends.json',
  'compliance-shortlist': 'shortlist-check.json',
  'footage-indexer': 'footage-pool.json',
  'content-researcher': 'scripts.json',
  'compliance-scripts': 'scripts-check.json',
  'video-editor': 'renders.json',
  'frame-judge': 'frame-judge.json',
};

/** Исход остановки: остановлен; исполнитель пережил SIGTERM; шаг (с «и шаг») не умер. */
export type StopOutcome = 'stopped' | 'survived' | 'step_survived';

type ResumeCode = 'executor_alive' | 'batch_finished' | 'refused';
/** Строки центра для кодов отказа продолжить (cc/api `batches.RESUME_CODES`). */
const RESUME_LINES: Record<ResumeCode, string> = {
  executor_alive: 'Батч идёт - исполнитель жив, продолжать нечего.',
  batch_finished:
    'Батч не стоит, а закончен - продолжать нечего; его можно повторить со стадии или пересобрать ролики.',
  refused: 'Фабрика отказала в продолжении батча.',
};

const problem = (
  status: 404 | 409 | 422,
  code: Code,
  message: string,
  details: string[] = [],
): BatchReply<never> => ({ status, body: { message, code, details } });

export function createActions(store: ActionStore) {
  const EXECUTOR_PID: Record<string, number> = {};
  let pidSeq = 4170;
  const executorPid = (batch: string) => (EXECUTOR_PID[batch] ??= pidSeq++);
  const tokens = new Map<string, Token>();
  let seq = 0;
  let ttl = 120;
  const fails: Partial<Record<Action, { code: Code; message?: string }[]>> = {};
  let stopOutcome: StopOutcome = 'stopped';
  const doneToday = new Set<string>();
  /** Записи действий (план и «да»): адрес и тело. */
  const writes: { path: string; body: unknown }[] = [];
  let launches = 0;
  /** Проверка запуска (CC-0152): запись размыкателя и допуск по бюджету — по каналу. */
  const breakers = new Map<string, S['PlanBreaker']>();
  const budgets = new Map<string, S['BudgetAdmission']>();

  let rerunResume: RerunResume = 'ok';
  /** Вход Claude (CC-0176): его видят и план, и «да» — сменить можно между ними. */
  let login: S['LoginState'] = LOGIN_OK;
  const issue = (action: Action, target: string, alsoStep = false, stage?: string) => {
    const confirm = `mock-${action}-${++seq}`;
    tokens.set(confirm, { action, target, alsoStep, stage, expires: Date.now() + ttl * 1000 });
    return { confirm, expires_in_s: ttl, fingerprint: `sha256:${action}:${target}:${seq}` };
  };

  /** Проверка токена как у `_spend`; busy — до траты (токен цел). */
  const spend = (
    action: Action,
    target: string,
    confirm: unknown,
    alsoStep = false,
    stage?: string,
  ): BatchReply<never> | null => {
    const queued = fails[action]?.[0];
    if (queued?.code === 'busy') {
      fails[action]!.shift();
      return problem(
        409,
        'busy',
        queued.message ??
          (action === 'launch'
            ? 'Идёт другой запуск - подождите и запросите план заново.'
            : `Над батчем ${target} уже идёт остановка или продолжение - подождите.`),
      );
    }
    const t = typeof confirm === 'string' ? tokens.get(confirm) : undefined;
    if (!t)
      return problem(
        409,
        'confirm_unknown',
        'Подтверждение не найдено или уже использовано - запросите план заново.',
      );
    tokens.delete(confirm as string);
    if (t.expires <= Date.now())
      return problem(
        409,
        'confirm_expired',
        `Подтверждение устарело (живёт ${ttl} с) - запросите план заново.`,
      );
    if (t.action === 'launch' && action === 'launch' && t.target !== target)
      return problem(
        409,
        'confirm_channel',
        `Подтверждение выдано для канала ${t.target}, а не ${target}.`,
      );
    if (
      t.action !== action ||
      t.target !== target ||
      t.alsoStep !== alsoStep ||
      (stage !== undefined && t.stage !== stage)
    )
      return problem(
        409,
        'confirm_mismatch',
        `Подтверждение выдано для другого действия - запросите план заново.`,
      );
    const f = fails[action]?.shift();
    if (f?.code === 'check_changed')
      return problem(
        409,
        'check_changed',
        f.message ?? 'Проверка изменилась с момента плана - запросите план заново.',
      );
    if (f) return problem(409, f.code, f.message ?? 'Фабрика отказала.', [f.message ?? '']);
    return null;
  };

  // --- запуск ---------------------------------------------------------------------------
  const guards = (ch: string): S['LaunchGuard'][] => {
    const open = store
      .list()
      .find(
        (b) =>
          b.going.channel === ch &&
          b.going.status !== 'done' &&
          b.going.dir !== 'pipeline/rebuilds',
      );
    const planned = PIPELINE.has(ch) || !!store.hasRunPlan?.(ch);
    const held = store.holdingDay?.(ch) ?? [];
    const today = !doneToday.has(ch) && held.length === 0;
    return [
      {
        name: 'channel',
        ok: CHANNELS.includes(ch),
        line: CHANNELS.includes(ch) ? `канал ${ch} есть` : `канала ${ch} нет`,
      },
      {
        name: 'run_plan',
        ok: planned,
        line: planned ? 'план прогона читается: 11 стадий' : 'конвейера нет - батча не будет',
      },
      {
        name: 'open',
        ok: !open,
        line: open
          ? `открыт батч ${open.going.batch} (${open.going.status}) - второй не запускаю`
          : 'открытых батчей канала нет',
        batches: open ? [open.going.batch] : [],
      },
      {
        name: 'today',
        ok: today,
        // CF-0724: батчи, что держат день, фабрика называет сама (`batches`), не только в строке.
        line: held[0]
          ? `сегодня батч уже был: ${ch} ${held[0].batch_id} (pipeline/) - 1 батч в сутки (квота YouTube Search)`
          : doneToday.has(ch)
            ? `сегодня (${TODAY}) батч канала уже был - 1 батч в сутки (квота YouTube Search)`
            : `сегодня (${TODAY}) батча канала ещё не было`,
        batches: held.length ? held.map((h) => h.batch) : null,
      },
      { name: 'pause', ok: true, line: 'паузы нет' },
    ];
  };

  function launchPlan(body: unknown): BatchReply<S['LaunchPlan']> {
    const ch = (body as { channel?: unknown } | null)?.channel;
    writes.push({ path: 'launch/plan', body });
    if (typeof ch !== 'string' || !ch) return problem(422, 'invalid', 'Канал не указан.');
    const g = guards(ch);
    const bad = g.find((x) => !x.ok);
    const tok = bad ? null : issue('launch', ch);
    return {
      status: 200,
      body: {
        channel: ch,
        ok: !bad,
        why: bad ? bad.line : 'все защиты пройдены',
        guards: g,
        argv: ['python3', 'shared/run_executor.py', 'run', ch, '--root', MOCK_ROOT],
        today: TODAY,
        quota_day: MOCK_QUOTA_DAY,
        skipped: [
          'окно канала (ручной запуск — в любое время)',
          'рубильник расписания',
          'порог батча (batch_feed_days)',
          // CF-0822: строка размыкателя, когда он держит канал, — ручной запуск он не держит.
          ...(breakers.get(ch)?.line ? [breakers.get(ch)!.line!] : []),
        ],
        breaker: breakers.get(ch) ?? null,
        budget: budgets.get(ch) ?? null,
        // CC-0176: вход — только сведения, не защита и не в отпечатке.
        login,
        fingerprint: tok?.fingerprint ?? `sha256:launch:${ch}:refused`,
        confirm: tok?.confirm ?? null,
        expires_in_s: tok ? tok.expires_in_s : null,
      },
    };
  }

  function launch(body: unknown): BatchReply<S['LaunchResult']> {
    const { channel, confirm } = (body ?? {}) as { channel?: unknown; confirm?: unknown };
    writes.push({ path: 'launch', body });
    const ch = typeof channel === 'string' ? channel : '';
    const refused = spend('launch', ch, confirm);
    if (refused) return refused;
    const bad = guards(ch).find((x) => !x.ok);
    if (bad) return problem(409, 'refused', bad.line, [bad.line]);
    // CC-0176: вход проверяется после траты токена — после входа нужен новый план.
    if (login.ok === false)
      return problem(409, 'not_logged_in', NOT_LOGGED_IN_MESSAGE, [
        `login: ${login.line}`,
        `checked: ${login.checked}`,
      ]);
    const id = `${TODAY}T07${String(++launches).padStart(2, '0')}Z`;
    const pid = 5100 + launches;
    const log = `schedule/logs/${id}-${ch}.log`;
    doneToday.add(ch);
    store.launched(ch, id);
    return {
      status: 200,
      body: {
        ok: true,
        line: `батч ${ch} запущен вручную (${BY}): исполнитель работает, журнал — в schedule/logs`,
        channel: ch,
        pid,
        log,
        row: { at: MOCK_NOW, day: TODAY, channel: ch, by: BY, kind: 'manual', why: null },
        login,
      },
    };
  }

  // --- остановить и продолжить -----------------------------------------------------------
  const alive = (b: ActionTarget) => b.going.status === 'running' && !b.dead;
  const stepOf = (b: ActionTarget): S['ControlStep'] | null => {
    const runs = b.state.runs ?? {};
    const key = Object.keys(runs).find((k) => runs[k]!.alive);
    if (!key) return null;
    const r = runs[key]!;
    return {
      stage: r.stage ?? null,
      run: key,
      pid: r.pid ?? null,
      pgid: r.pgid ?? null,
      alive: true,
      exit: null,
      log: r.log ?? null,
    };
  };
  const common = (b: ActionTarget, action: 'stop' | 'resume') => {
    const batch = b.going.batch;
    const pid = executorPid(batch);
    return {
      action,
      batch: `${b.going.dir}/${b.going.batch_id}`,
      batch_id: b.going.batch_id,
      channel: b.going.channel ?? null,
      status: b.going.status ?? null,
      stage: b.going.stage ?? null,
      executor_pid: pid,
      executor_pgid: pid,
      executor_alive: alive(b),
      lock_held: alive(b),
      step: stepOf(b),
      posix: true,
    };
  };

  function stopPlan(batch: string, body: unknown): BatchReply<S['StopPlan']> {
    writes.push({ path: `${batch}/stop/plan`, body });
    const b = store.find(batch);
    if (!b) return problem(404, 'unknown_batch', `Батча «${batch}» нет.`);
    const alsoStep = !!(body as { also_step?: unknown } | null)?.also_step;
    const c = common(b, 'stop');
    const ok = alive(b);
    const tok = ok ? issue('stop', batch, alsoStep) : null;
    return {
      status: 200,
      body: {
        ...c,
        ok,
        reason: ok
          ? `исполнитель pid ${c.executor_pid} жив, стадия ${c.stage} - можно остановить`
          : `исполнитель не жив (статус ${c.status}) - батч уже стоит; продолжить: resume`,
        also_step: alsoStep,
        fingerprint: tok?.fingerprint ?? `sha256:stop:${batch}:no`,
        confirm: tok?.confirm ?? null,
        expires_in_s: tok?.expires_in_s ?? null,
      },
    };
  }

  function stop(batch: string, body: unknown): BatchReply<S['StopResult']> {
    writes.push({ path: `${batch}/stop`, body });
    const b = store.find(batch);
    if (!b) return problem(404, 'unknown_batch', `Батча «${batch}» нет.`);
    const { confirm, also_step } = (body ?? {}) as { confirm?: unknown; also_step?: unknown };
    const alsoStep = !!also_step;
    const refused = spend('stop', batch, confirm, alsoStep);
    if (refused) return refused;
    if (!alive(b))
      return problem(409, 'refused', 'исполнитель не жив - батч уже стоит', ['not alive']);
    const c = common(b, 'stop');
    const step = c.step;
    const pid = c.executor_pid;
    const base = {
      ...c,
      by: BY,
      also_step: alsoStep,
      executor_signalled: `группа ${pid}`,
      step_killed: false,
      step_left_running: false,
    };
    if (stopOutcome === 'survived') {
      return {
        status: 200,
        body: {
          ...base,
          ok: false,
          stopped: false,
          reason: `исполнитель pid ${pid} не умер за 30 с после SIGTERM (группа ${pid}); SIGKILL не послан - решить руками: kill -9 -${pid} (docs/running-a-batch.md)`,
        },
      };
    }
    const killed = alsoStep && !!step && stopOutcome !== 'step_survived';
    const left = !!step && !killed;
    const row: S['StopRow'] = {
      at: MOCK_NOW,
      by: BY,
      executor_pid: pid,
      previous_status: 'running',
      stage: c.stage,
      also_step: alsoStep,
      step: step ? { run: step.run, pid: step.pid, killed, left_running: left } : null,
    };
    b.going = {
      ...b.going,
      status: 'stopped',
      halt_reason: `остановлен пользователем (центр): ждёт «продолжить»`,
    };
    b.state = { ...b.state, status: 'stopped', stops: [...(b.state.stops ?? []), row] };
    if (killed && step?.run && b.state.runs?.[step.run]) {
      b.state.runs[step.run] = { ...b.state.runs[step.run]!, alive: false, exit: -15 };
    }
    const words = killed
      ? 'шаг остановлен'
      : left
        ? `шаг ${step!.run} pid ${step!.pid} работает дальше, --resume его дождётся`
        : 'шага в работе не было';
    return {
      status: 200,
      body: {
        ...base,
        status: 'stopped',
        executor_alive: false,
        ok: true,
        stopped: true,
        step_killed: killed,
        step_left_running: left,
        stop: row,
        reason: `батч ${b.going.batch_id} остановлен на ${c.stage} (${BY}); ${words}; продолжить: resume`,
        resume_hint: `python3 shared/batch_control.py resume --batch ${c.batch} --by ${BY} --confirm`,
        reason_step:
          alsoStep && left && step
            ? `шаг ${step.run} pid ${step.pid} не умер за 30 с после SIGTERM; SIGKILL не послан - kill -9 -${step.pgid} руками, иначе --resume его дождётся`
            : null,
      },
    };
  }

  const resumable = (b: ActionTarget) =>
    ['stopped', 'halted', 'paused', 'failed'].includes(b.going.status ?? '') ||
    (b.going.status === 'running' && !!b.dead);
  /** Почему батч стоит — словами фабрики (`batch_control.resume_check`). */
  const whyStands = (b: ActionTarget, status: string | null) =>
    b.dead
      ? `исполнитель умер, не записав конца (статус ${status}: kill -9 или сбой)`
      : (b.going.halt_reason ?? `статус ${status}`);

  /**
   * Код отказа продолжить (контракт 0.54: коды фабрики CF-0739) — `refused`, когда фабрика
   * кода не дала (`refuse` батча: строка старой фабрики), null — продолжить можно.
   */
  const resumeCode = (b: ActionTarget): ResumeCode | null =>
    b.refuse ? 'refused' : alive(b) ? 'executor_alive' : resumable(b) ? null : 'batch_finished';

  function resumePlan(batch: string): BatchReply<S['ResumePlan']> {
    writes.push({ path: `${batch}/resume/plan`, body: null });
    const b = store.find(batch);
    if (!b) return problem(404, 'unknown_batch', `Батча «${batch}» нет.`);
    const c = common(b, 'resume');
    const code = resumeCode(b);
    const ok = code == null;
    const tok = ok ? issue('resume', batch) : null;
    const reason = b.refuse
      ? b.refuse
      : ok
        ? `${whyStands(b, c.status)} - можно продолжить с ${b.going.next ?? 'того же места'}`
        : alive(b)
          ? `исполнитель pid ${c.executor_pid} жив - батч идёт, продолжать нечего`
          : `батч не стоит, а закончен (статус ${c.status}) - продолжать нечего`;
    return {
      status: 200,
      body: {
        ...c,
        ok,
        reason,
        code,
        message: code ? RESUME_LINES[code] : reason,
        root: MOCK_ROOT,
        argv: ok
          ? [
              'python3',
              'shared/run_executor.py',
              'run',
              c.channel ?? '',
              '--root',
              MOCK_ROOT,
              '--resume',
              c.batch,
            ]
          : null,
        fingerprint: tok?.fingerprint ?? `sha256:resume:${batch}:no`,
        confirm: tok?.confirm ?? null,
        expires_in_s: tok?.expires_in_s ?? null,
      },
    };
  }

  function resume(batch: string, body: unknown): BatchReply<S['ResumeResult']> {
    writes.push({ path: `${batch}/resume`, body });
    const b = store.find(batch);
    if (!b) return problem(404, 'unknown_batch', `Батча «${batch}» нет.`);
    const refused = spend('resume', batch, (body as { confirm?: unknown } | null)?.confirm);
    if (refused) return refused;
    const code = resumeCode(b);
    if (code) {
      const why = b.refuse ?? (alive(b) ? 'батч идёт - продолжать нечего' : 'батч закончен');
      return problem(409, code, `${RESUME_LINES[code]} Фабрика: ${why}`, [why]);
    }
    const c = common(b, 'resume');
    const { pid, log } = startExecutor(b, batch);
    return {
      status: 200,
      body: {
        ...c,
        status: 'running',
        executor_pid: pid,
        executor_pgid: pid,
        executor_alive: true,
        ok: true,
        by: BY,
        resumed: true,
        pid,
        log,
        exit: null,
        row: { at: MOCK_NOW, day: TODAY, channel: c.channel, by: BY, kind: 'resume', why: null },
        reason: `батч ${b.going.batch_id} продолжен (${BY}): исполнитель pid ${pid}, журнал ${log}`,
        code: null,
        message: `батч ${b.going.batch_id} продолжен (${BY}): исполнитель pid ${pid}, журнал ${log}`,
      },
    };
  }

  /** Исполнитель запущен заново с `next` (как `run_executor --resume`): батч снова идёт. */
  function startExecutor(b: ActionTarget, batch: string) {
    EXECUTOR_PID[batch] = pidSeq++;
    const pid = EXECUTOR_PID[batch];
    const log = `schedule/logs/${b.going.batch_id}-resume.log`;
    b.dead = false;
    b.going = { ...b.going, status: 'running', halt_reason: null, fresh: true };
    // Как у живой фабрики: продолживший исполнитель сразу запускает шаг стадии, с которой
    // продолжил, — у батча снова есть живой процесс (иначе центр спросил бы, жив ли
    // исполнитель, CC-0094).
    const stage = b.going.next ?? b.going.stage ?? 'batch-start';
    const runs = b.state.runs ?? {};
    const attempt = Object.keys(runs).filter((k) => k.startsWith(`${stage}.`)).length;
    const key = `${stage}.s0.a${attempt}`;
    const step = pidSeq++;
    b.state = {
      ...b.state,
      status: 'running',
      halt_reason: null,
      current: { stage, run: key },
      runs: {
        ...runs,
        [key]: {
          stage,
          pid: step,
          pgid: step,
          started: MOCK_NOW,
          ended: null,
          log: `logs/${key}.log`,
          exit: null,
          restarts: 0,
          alive: true,
        },
      },
    };
    store.resumed?.(batch);
    return { pid, log };
  }

  // --- повторить со стадии (CC-0123, CF-0739) --------------------------------------------
  const orderOf = (b: ActionTarget): string[] =>
    b.state.order?.length
      ? (b.state.order as string[])
      : (b.going.stages ?? []).map((s) => s.id ?? '').filter(Boolean);
  const statusOf = (b: ActionTarget, id: string) =>
    (b.going.stages ?? []).find((s) => s.id === id)?.status ?? 'pending';
  const ran = (status: string) => !/^(pending|waiting|skipped|)$/.test(status);

  /** Можно ли повторить батч со стадии `stage` — словами фабрики (`rerun_from_check`). */
  function rerunCheck(
    b: ActionTarget,
    stage: string,
  ): { can: boolean; why: string; code: S['RerunStage']['code'] } {
    const order = orderOf(b);
    const i = order.indexOf(stage);
    if (i < 0)
      return { can: false, why: `стадии ${stage} нет в плане прогона`, code: 'stage_unknown' };
    if (alive(b))
      return {
        can: false,
        why: `исполнитель pid ${executorPid(b.going.batch)} жив — сначала остановите батч`,
        code: 'executor_alive',
      };
    const start = order.indexOf('batch-start');
    if (i <= start)
      return {
        can: false,
        why: 'стадия batch-start или раньше — повторять нечего, запустите новый батч',
        code: 'stage_opens_batch',
      };
    const failed = order.findIndex((id) => /^(failed|halted|error)$/.test(statusOf(b, id)));
    if (failed >= 0 && failed < i)
      return {
        can: false,
        why: `раньше упала стадия ${order[failed]} — повторите с неё`,
        code: 'earlier_failed',
      };
    if (!ran(statusOf(b, stage)))
      return { can: false, why: 'стадия ещё не шла — повторять нечего', code: 'stage_not_run' };
    return { can: true, why: 'можно повторить с этой стадии', code: null };
  }

  const stagesForRerun = (b: ActionTarget): S['RerunStage'][] =>
    orderOf(b).map((stage) => ({ stage, status: statusOf(b, stage), ...rerunCheck(b, stage) }));

  /** Что сбросит повтор со стадии: она и всё после неё, что уже шло; что останется — до неё. */
  const rerunScope = (b: ActionTarget, stage: string) => {
    const order = orderOf(b);
    const i = order.indexOf(stage);
    const reset = order.slice(Math.max(0, i)).filter((id) => ran(statusOf(b, id)));
    const dir = `${b.going.dir}/${b.going.batch_id}`;
    const kept: S['RerunKept'][] = order
      .slice(0, Math.max(0, i))
      .filter((id) => STAGE_FILES[id] && statusOf(b, id) === 'done')
      .map((id) => ({ stage: id, path: `${dir}/${STAGE_FILES[id]}` }));
    const runs = b.state.runs ?? {};
    const runKeys = Object.keys(runs).filter((k) => reset.includes(runs[k]!.stage ?? ''));
    return {
      reset,
      reset_status: Object.fromEntries(reset.map((id) => [id, statusOf(b, id)])),
      keys: { runs: runKeys, reruns: [] as string[] },
      logs: runKeys.map((k) => `${dir}/logs/${k}.log`),
      kept,
      lines: [
        `rerun-from ${stage}: reset ${reset.length} stage(s): ${reset.join(', ') || '-'}`,
        `kept ${kept.length} file(s) of earlier stages`,
        `status ${b.going.status ?? '-'} -> stopped, next ${stage}`,
      ],
    };
  };

  const rerunCommon = (b: ActionTarget, stage: string | null) => ({
    ...common(b, 'resume'),
    action: 'rerun-from' as const,
    task: 'CF-0739',
    from_stage: stage,
    root: MOCK_ROOT,
  });

  function rerunStages(batch: string): BatchReply<S['RerunFromStages']> {
    const b = store.find(batch);
    if (!b) return problem(404, 'unknown_batch', `Батча «${batch}» нет.`);
    return {
      status: 200,
      body: {
        batch: `${b.going.dir}/${b.going.batch_id}`,
        channel: b.going.channel ?? null,
        batch_id: b.going.batch_id,
        status: b.going.status ?? null,
        has_state: true,
        executor_alive: alive(b),
        lock_held: alive(b),
        executor_why: alive(b) ? `исполнитель pid ${executorPid(batch)} жив` : 'исполнитель не жив',
        stages_for_rerun: stagesForRerun(b),
      },
    };
  }

  function rerunPlan(batch: string, body: unknown): BatchReply<S['RerunFromPlan']> {
    writes.push({ path: `${batch}/rerun-from/plan`, body });
    const b = store.find(batch);
    if (!b) return problem(404, 'unknown_batch', `Батча «${batch}» нет.`);
    const stage = (body as { stage?: unknown } | null)?.stage;
    if (typeof stage !== 'string' || !stage) return problem(422, 'invalid', 'Стадия не указана.');
    const check = rerunCheck(b, stage);
    const scope = rerunScope(b, stage);
    const tok = check.can ? issue('rerun', batch, false, stage) : null;
    return {
      status: 200,
      body: {
        ...rerunCommon(b, stage),
        ok: check.can,
        reason: check.can
          ? `rerun from ${stage}: ${scope.reset.length} stage(s) reset, earlier files kept`
          : check.why,
        code: check.code,
        message: check.can
          ? `Можно повторить батч со стадии: сбросится ${scope.reset.length}, ранние файлы останутся.`
          : `Повторить с этой стадии нельзя: ${check.why}.`,
        ...scope,
        why: check.why,
        stages_for_rerun: stagesForRerun(b),
        fingerprint: tok?.fingerprint ?? `sha256:rerun:${batch}:${stage}:no`,
        confirm: tok?.confirm ?? null,
        expires_in_s: tok?.expires_in_s ?? null,
      },
    };
  }

  function rerun(batch: string, body: unknown): BatchReply<S['RerunFromResult']> {
    writes.push({ path: `${batch}/rerun-from`, body });
    const b = store.find(batch);
    if (!b) return problem(404, 'unknown_batch', `Батча «${batch}» нет.`);
    const {
      confirm,
      note,
      resume: again,
    } = (body ?? {}) as { confirm?: unknown; note?: unknown; resume?: unknown };
    const stage = (typeof confirm === 'string' ? tokens.get(confirm)?.stage : undefined) ?? '';
    const refused = spend('rerun', batch, confirm, false, stage);
    if (refused) return refused;
    const check = rerunCheck(b, stage);
    if (!check.can) return problem(409, 'refused', `Повторить нельзя: ${check.why}.`, [check.why]);
    const scope = rerunScope(b, stage);
    const dir = `${b.going.dir}/${b.going.batch_id}`;
    const backup = `${dir}/run-state.before-rerun-20261010T0700Z.json`;
    const previous = b.going.status ?? null;
    const words = typeof note === 'string' && note.trim() ? note.trim() : null;
    const stages = (b.going.stages ?? []).map((s) =>
      scope.reset.includes(s.id ?? '') ? { ...s, status: 'pending', reason: null } : s,
    );
    const halt = `повтор со стадии ${stage} (${BY}): ждёт «продолжить»`;
    b.dead = false;
    b.refuse = undefined;
    b.going = { ...b.going, status: 'stopped', stages, stage, next: stage, halt_reason: halt };
    b.state = {
      ...b.state,
      status: 'stopped',
      next: stage,
      halt_reason: halt,
      stages: Object.fromEntries(stages.map((s) => [s.id ?? '', { status: s.status }])),
      runs: Object.fromEntries(
        Object.entries(b.state.runs ?? {}).filter(([k]) => !scope.keys.runs.includes(k)),
      ),
    };
    const row: S['RerunResetRow'] = {
      at: MOCK_NOW,
      by: BY,
      via: 'center',
      task: 'CF-0739',
      reset: scope.reset,
      previous_status: previous,
      backup,
      why: words,
    };
    const base = {
      ...rerunCommon(b, stage),
      ...scope,
      ok: true,
      by: 'user',
      via: 'center',
      note: words,
      done: true,
      backup,
      row,
      resume_asked: !!again,
      exit: null,
    };
    const resetText = `batch ${b.going.batch_id} reset to ${stage}: ${scope.reset.length} stage(s) pending`;
    if (!again)
      return {
        status: 200,
        body: {
          ...base,
          reason: `${resetText}; resume: --resume`,
          code: null,
          message: 'Батч сброшен до стадии — продолжите его кнопкой «Продолжить».',
          resume: null,
          resumed: false,
          pid: null,
          log: null,
          resume_ok: null,
          resume_code: null,
          resume_reason: null,
        },
      };
    if (rerunResume === 'failed') {
      const why = 'замок батча держит другой процесс — продолжите позже кнопкой «Продолжить»';
      return {
        status: 200,
        body: {
          ...base,
          reason: `${resetText}; resume failed: lock held`,
          code: 'resume_failed',
          message: `Батч сброшен до стадии, но продолжить не вышло: ${why}.`,
          resume: { ok: false, reason: 'lock held by another process', code: 'locked' },
          resumed: false,
          pid: null,
          log: null,
          resume_ok: false,
          resume_code: 'locked',
          resume_reason: why,
        },
      };
    }
    const { pid, log } = startExecutor(b, batch);
    return {
      status: 200,
      body: {
        ...base,
        status: 'running',
        executor_pid: pid,
        executor_pgid: pid,
        executor_alive: true,
        lock_held: true,
        reason: `${resetText}; resumed: executor pid ${pid}`,
        code: null,
        message: 'Батч сброшен до стадии и продолжен: исполнитель снова работает.',
        resume: { ok: true, resumed: true },
        resumed: true,
        pid,
        log,
        resume_ok: true,
        resume_code: null,
        resume_reason: null,
      },
    };
  }

  return {
    writes,
    /** Срок жизни следующих токенов, с. */
    setTtl(s: number) {
      ttl = s;
    },
    /** Все выданные токены устарели (как будто прошло 120 с). */
    expireTokens() {
      for (const t of tokens.values()) t.expires = 0;
    },
    /** Следующее «да» этого действия получит отказ `code` (busy — не тратя токен). */
    failNext(action: Action, code: Code, message?: string) {
      (fails[action] ??= []).push({ code, message });
    },
    setStopOutcome(o: StopOutcome) {
      stopOutcome = o;
    },
    /** «Сразу продолжить» после повтора со стадии: продолжит или не сможет (`resume_failed`). */
    setRerunResume(o: RerunResume) {
      rerunResume = o;
    },
    /** Размыкатель повторов держит канал (CF-0822): по умолчанию — ExampleFilm сцены `breaker`. */
    setBreaker(b: S['PlanBreaker'] | null = MOCK_BREAKER, channel = b?.channel ?? 'example-film') {
      if (b) breakers.set(channel, b);
      else breakers.delete(channel);
    },
    /** Допуск по бюджету поиска проверки запуска канала (CF-0830); null — убрать. */
    setBudget(
      a: S['BudgetAdmission'] | null = LAUNCH_BUDGET,
      channel = a?.channel ?? 'example-tech',
    ) {
      if (a) budgets.set(channel, a);
      else budgets.delete(channel);
    },
    /** Вход Claude (CC-0176): `LOGIN_OK` / `LOGIN_NO` / `LOGIN_UNKNOWN` или свой. */
    setLogin(state: S['LoginState'] = LOGIN_OK) {
      login = state;
    },
    /** Сегодня батч канала уже был (тик успел): запуск откажет «1 батч в сутки». */
    startedToday(channel: string) {
      doneToday.add(channel);
    },
    launchPlan,
    launch,
    stopPlan,
    stop,
    resumePlan,
    resume,
    rerunStages,
    rerunPlan,
    rerun,
  };
}

export type BatchActions = ReturnType<typeof createActions>;

/** POST действий: null — адрес не их. */
export function routeActions(
  a: BatchActions,
  method: string,
  url: URL,
  body: unknown,
): BatchReply<unknown> | null {
  const p = url.pathname;
  const rr = p.match(/\/api\/batches\/([^/]+)\/([^/]+)\/rerun-from(\/plan)?$/);
  if (rr) {
    const target = `${decodeURIComponent(rr[1]!)}/${decodeURIComponent(rr[2]!)}`;
    if (method === 'GET' && !rr[3]) return a.rerunStages(target);
    if (method === 'POST') return rr[3] ? a.rerunPlan(target, body) : a.rerun(target, body);
    return null;
  }
  if (method !== 'POST') return null;
  if (p.endsWith('/api/batches/launch/plan')) return a.launchPlan(body);
  if (p.endsWith('/api/batches/launch')) return a.launch(body);
  const m = p.match(/\/api\/batches\/([^/]+)\/([^/]+)\/(stop|resume)(\/plan)?$/);
  if (!m) return null;
  const [, dir, id, what, plan] = m;
  const batch = `${decodeURIComponent(dir!)}/${decodeURIComponent(id!)}`;
  if (what === 'stop') return plan ? a.stopPlan(batch, body) : a.stop(batch, body);
  return plan ? a.resumePlan(batch) : a.resume(batch, body);
}
