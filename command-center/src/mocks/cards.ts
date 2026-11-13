// Подставные карточки публикации без оператора (CC-0127; фабрика CF-0747/CF-0748, договор
// 0.56.0): состояние карточки каждого ролика (none / building / ready / ruled / not_ready),
// «Собрать заново» (план → «да» → опрос итога: два раза «собирается», на третий — итог) и
// «Принять своим решением» (только когда не прошли утверждения самого ролика; утверждение
// названия/описания — отказ `note_claim_failed`). Записи — как у фабрики: план ничего не пишет и
// даёт одноразовый токен на `life` секунд (120); «да» берёт только `{confirm}`.
// Ролики ExampleFilm: rapid-reckless-11 — готова; skyman-sequel — принята решением пользователя;
// wicked-for-good — не готова, не прошли слова ролика (комментарий и текст на экране);
// zootopia-2 — собирается сама после приёмки, готова через два опроса; vanguards-doomsday (батч
// 2026-10-09T0215Z) — не готова, не прошло утверждение названия. Сборка, которую запустила приёмка
// (`run-<slug>-auto`), опрашивается так же. `state.next` — исход «да» на выбор теста:
// `commit_refused`, `busy`, `check_changed`. Импорты — относительные (общий для Vitest и Playwright).
import type { components } from '../api/schema.gen';
import { namesakesMessage } from './stash';

type S = components['schemas'];

/** Ролики с картой состояний (те же, что в ./stash и ./videos). */
export const CARD_READY = 'rapid-reckless-11';
export const CARD_RULED = 'skyman-sequel';
export const CARD_OWN_FAIL = 'wicked-for-good';
export const CARD_BUILDING = 'zootopia-2';
export const CARD_TITLE_FAIL = 'vanguards-doomsday';
/** Слова решения, которым принята карточка skyman-sequel. */
export const RULED_WORDS =
  'Цифра сборов взята из пресс-релиза студии — беру под свою ответственность.';
export const AUTO_RUN = (slug: string) => `run-${slug}-auto`;

/**
 * CC-0175 (договор 0.76.0): приёмка не запустила автосборку карточки — `why` в виде фабрики
 * (`card_center.refusal_line`: «code: line; code: line», пути вырезаны). Первая строка — по-русски,
 * вторая — английская: центр показывает её кодом словами.
 */
export const ACCEPT_BUILD_WHY =
  'model_refused: модель не написала черновик карточки — ответ пустой; ' +
  'claims_failed: claim check failed: title says 2027, source says 2026';

/** CC-0175: автосборка на приёмке отказала (`launched: false`) — с причиной `why`. */
export const ACCEPT_BUILD_REFUSED: S['AcceptCardBuild'] = {
  ok: false,
  launched: false,
  skipped: null,
  run_id: null,
  log: null,
  refusals: ['model_refused', 'claims_failed'],
  error: null,
  why: ACCEPT_BUILD_WHY,
};

export type CardsReply =
  | { status: 200; body: unknown }
  | { status: 404 | 409 | 422 | 500; body: { message: string; code: string; details: string[] } };

export type CardsOutcome = 'commit_refused' | 'busy' | 'check_changed';

export type CardsWorld = {
  now: () => string;
  readOnly: () => boolean;
};

type Entry = {
  channel: string;
  slug: string;
  batch_id: string;
  state: S['CardState']['state'];
  reasons: string[];
  why: string | null;
  ruling: S['CardRuling'] | null;
  failing: S['CardFailing'][];
  build: S['CardBuildRun'] | null;
};

const STATE_RU: Record<S['CardState']['state'], string> = {
  none: 'нет карточки',
  building: 'собирается',
  ready: 'готова',
  ruled: 'готова решением пользователя',
  not_ready: 'не готова',
};

const OUTCOME_WORDS: Record<S['CardBuildOutcome']['code'], string> = {
  ready: 'готова',
  not_ready: 'не готова',
  refused: 'отказ',
  not_asked: 'не запрашивалась',
  error: 'сбой',
  running: 'собирается',
};

const OUTCOME_RU: Record<S['CardBuildOutcome']['code'], string> = {
  ready: 'Карточка собрана и готова к публикации.',
  not_ready: 'Карточка собрана, но не готова: проверка утверждений не прошла.',
  refused: 'Фабрика отказалась собирать карточку.',
  not_asked: 'Сборку не запрашивали.',
  error: 'Сборка сорвалась — посмотрите журнал сборки.',
  running: 'Карточка собирается…',
};

const OWN_FAILING: S['CardFailing'][] = [
  {
    code: 'no_source',
    where: 'claims/commentary',
    video: true,
    text: 'Вторая часть собрала больше первой уже за первые выходные.',
  },
  {
    code: 'unsupported',
    where: 'claims/on_screen',
    video: true,
    text: '$300 млн за три дня',
  },
];

const TITLE_FAILING: S['CardFailing'][] = [
  {
    code: 'contradicted',
    where: 'claims/title',
    video: null,
    text: 'Vanguards: Doomsday moved to 2027',
  },
];

function seeds(): Entry[] {
  const base = (
    slug: string,
    batch_id: string,
    state: Entry['state'],
    more: Partial<Entry> = {},
  ): Entry => ({
    channel: 'example-film',
    slug,
    batch_id,
    state,
    reasons: [],
    why: null,
    ruling: null,
    failing: [],
    build: null,
    ...more,
  });
  return [
    base(CARD_READY, '2026-10-09T0200Z', 'ready'),
    base(CARD_RULED, '2026-09-24T0200Z', 'ruled', {
      reasons: ['claims_failed'],
      ruling: { by: 'user', via: 'center', words: RULED_WORDS, at: '2026-09-26T09:00:00Z' },
    }),
    base(CARD_OWN_FAIL, '2026-10-09T0200Z', 'not_ready', {
      reasons: ['claims_failed'],
      why: 'claims failed: 2 of the video’s own claims have no source',
      failing: OWN_FAILING,
    }),
    base(CARD_BUILDING, '2026-10-09T0200Z', 'building', {
      build: {
        run_id: AUTO_RUN(CARD_BUILDING),
        log: `logs/publish-card/${CARD_BUILDING}.log`,
        code: 'running',
        word: OUTCOME_WORDS.running,
        started_at: '2026-10-10T06:55:00Z',
        by: 'factory',
        via: 'acceptance',
        auto: true,
      },
    }),
    base(CARD_TITLE_FAIL, '2026-10-09T0215Z', 'not_ready', {
      reasons: ['claims_failed'],
      why: 'claims failed: the title claim is contradicted by the source',
      failing: TITLE_FAILING,
    }),
  ];
}

/** Состояние карточки по записи (как `card_center.card_info`). */
function stateOf(e: Entry): S['CardState'] {
  return {
    state: e.state,
    state_ru: STATE_RU[e.state],
    placeable: e.state === 'ready' || e.state === 'ruled',
    why: e.state === 'ready' || e.state === 'ruled' ? null : e.why,
    reasons: e.state === 'not_ready' ? e.reasons : [],
    ruling: e.state === 'ruled' ? e.ruling : null,
    build: e.build,
  };
}

/** Состояние по готовности карточки — для роликов без своей записи. */
export function plainState(ready: boolean | null, present = true): S['CardState'] {
  const state = !present ? 'none' : ready ? 'ready' : 'not_ready';
  return {
    state,
    state_ru: STATE_RU[state],
    placeable: state === 'ready',
    why: state === 'not_ready' ? 'publish section missing' : null,
    reasons: state === 'not_ready' ? ['no_publish_section'] : [],
    ruling: null,
    build: null,
  };
}

/** Исходное состояние карточки ролика (для списков ./videos, где своего учёта нет). */
export function seedState(channel: string, batchId: string, slug: string): S['CardState'] | null {
  const e = seeds().find((x) => x.channel === channel && x.slug === slug && x.batch_id === batchId);
  return e ? stateOf(e) : null;
}

class Fault extends Error {
  readonly status: 404 | 409 | 422 | 500;
  readonly code: string;
  readonly details: string[];
  constructor(
    status: 404 | 409 | 422 | 500,
    code: string,
    message: string,
    details: string[] = [],
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Token = { action: 'build' | 'ruling'; key: string; words: string | null; expires: number };
type Run = {
  run_id: string;
  channel: string;
  slug: string;
  batch_id: string | null;
  polls: number;
  final: 'ready' | 'not_ready';
  started_at: string;
};

const REFUSAL_RU: Record<string, string> = {
  running: 'Карточка уже собирается — второй раз сборку не запускаю.',
  building: 'Карточка ещё собирается — решение можно дать после сборки.',
  card_ready: 'Карточка уже готова — решение не нужно.',
  no_card: 'У ролика нет карточки — сначала соберите её.',
  note_claim_failed:
    'Не прошло утверждение названия карточки, а не слова ролика — это решением не принять, карточку надо собрать заново.',
  claims_not_failed: 'Проверка утверждений не провалена — решать нечего.',
};

export function createCards(world: CardsWorld) {
  const entries = new Map<string, Entry>(seeds().map((e) => [`${e.channel}|${e.slug}`, e]));
  const tokens = new Map<string, Token>();
  const runs = new Map<string, Run>();
  let n = 0;
  const state = {
    entries,
    runs,
    /** Опрос сборки, секунд (`poll_s`): в тестах — коротко. */
    pollS: 1,
    life: 120,
    next: null as CardsOutcome | null,
    calls: [] as { kind: 'get' | 'plan' | 'confirm' | 'run'; action: string; body: unknown }[],
    /** CC-0183: тёзки копилки: «канал|имя» → батчи; без батча — 409 `namesakes`. */
    twins: new Map<string, string[]>(),
  };

  const fail = (e: unknown): CardsReply => {
    if (e instanceof Fault)
      return { status: e.status, body: { message: e.message, code: e.code, details: e.details } };
    throw e;
  };
  const find = (c: string, slug: string, batchId?: string | null): Entry => {
    const twins = state.twins.get(`${c}|${slug}`);
    if (twins && !batchId)
      throw new Fault(409, 'namesakes', namesakesMessage(slug, twins), [
        `${slug}: ${twins.join(', ')}`,
      ]);
    // Тёзки: у каждого своя запись; старший — с не готовой карточкой, младший — с готовой.
    if (twins && batchId && twins.includes(batchId)) {
      const key = `${c}|${slug}@${batchId}`;
      const known = entries.get(key);
      if (known) return known;
      const first = twins[0] === batchId;
      const twin: Entry = {
        channel: c,
        slug,
        batch_id: batchId,
        state: first ? 'not_ready' : 'ready',
        reasons: first ? ['claims_failed'] : [],
        why: first ? 'claims failed: 1 of the video’s own claims has no source' : null,
        ruling: null,
        failing: [],
        build: null,
      };
      entries.set(key, twin);
      return twin;
    }
    const e = entries.get(`${c}|${slug}`);
    if (!e || (batchId && e.batch_id && e.batch_id !== batchId))
      throw new Fault(404, 'unknown_video', `Ролика «${slug}» в канале ${c} нет среди принятых.`, [
        `${c}/${batchId ?? '?'}/${slug}: no accepted video`,
      ]);
    return e;
  };
  const refusal = (code: string, line: string): S['CardCenterRefusal'] => ({
    code,
    line,
    message: REFUSAL_RU[code] ?? code,
  });
  const readOnly = () =>
    new Fault(
      409,
      'not_working_factory',
      'Только смотреть: рабочая копия на ветке cc-api, а не main',
      ['CC_API_WRITES is off'],
    );
  const cardPath = (e: Entry) =>
    `pipeline/${e.channel}/${e.batch_id}/work/publish-card/${e.slug}.md`;

  /** Итог сборки `run_id`: два опроса — «собирается», на третий — итог, карточка меняется. */
  function outcome(run: Run): S['CardBuildOutcome'] {
    run.polls += 1;
    const e = entries.get(`${run.channel}|${run.slug}`);
    const done = run.polls > 2;
    const code: S['CardBuildOutcome']['code'] = done ? run.final : 'running';
    if (done && e && e.state === 'building') {
      e.state = run.final;
      if (run.final === 'not_ready' && !e.reasons.length) e.reasons = ['claims_failed'];
      e.build = e.build ? { ...e.build, code, word: OUTCOME_WORDS[code] } : null;
    }
    return {
      run_id: run.run_id,
      log: `logs/publish-card/${run.slug}.log`,
      code,
      word: OUTCOME_WORDS[code],
      text_ru: OUTCOME_RU[code],
      done,
      line: done ? `card ${run.slug}: ${code}` : `card ${run.slug}: building (poll ${run.polls})`,
      detail: null,
      state: done ? run.final : 'building',
      reasons: done && run.final === 'not_ready' ? ['claims_failed'] : [],
      path: e ? cardPath(e) : null,
      channel: run.channel,
      slug: run.slug,
      batch_id: run.batch_id,
      started_at: run.started_at,
      finished_at: done ? world.now() : null,
      poll_s: state.pollS,
    };
  }

  function info(c: string, slug: string, batchId: string | null): CardsReply {
    state.calls.push({ kind: 'get', action: 'info', body: { c, slug, batchId } });
    try {
      // Принятый ролик без своей записи (её ведёт фабрика при приёмке): карточка готова.
      if (!state.twins.has(`${c}|${slug}`) && !entries.has(`${c}|${slug}`) && batchId)
        entries.set(`${c}|${slug}`, {
          channel: c,
          slug,
          batch_id: batchId,
          state: 'ready',
          reasons: [],
          why: null,
          ruling: null,
          failing: [],
          build: null,
        });
      const e = find(c, slug, batchId);
      const body: S['CardInfo'] = {
        ...stateOf(e),
        channel: c,
        slug,
        batch_id: e.batch_id || null,
        path: cardPath(e),
        refusals: [],
      };
      return { status: 200, body };
    } catch (err) {
      return fail(err);
    }
  }

  function run(c: string, runId: string): CardsReply {
    state.calls.push({ kind: 'run', action: 'build', body: runId });
    let r = runs.get(runId);
    // Сборка, которую запустила приёмка (`AcceptCardBuild.run_id`), — по имени ролика.
    const auto = /^run-(.+)-auto$/.exec(runId);
    if (!r && auto) {
      const slug = auto[1]!;
      let e = entries.get(`${c}|${slug}`);
      // Принятый только что ролик: учёта ещё нет — карточка собирается с этой минуты.
      if (!e) {
        e = {
          channel: c,
          slug,
          batch_id: '',
          state: 'building',
          reasons: [],
          why: null,
          ruling: null,
          failing: [],
          build: null,
        };
        entries.set(`${c}|${slug}`, e);
      }
      if (e.state !== 'building' && !e.build) e.state = 'building';
      e.build ??= {
        run_id: runId,
        log: `logs/publish-card/${slug}.log`,
        code: 'running',
        word: OUTCOME_WORDS.running,
        started_at: world.now(),
        by: 'factory',
        via: 'acceptance',
        auto: true,
      };
      r = {
        run_id: runId,
        channel: c,
        slug,
        batch_id: e.batch_id || null,
        polls: 0,
        final: 'ready',
        started_at: world.now(),
      };
      runs.set(runId, r);
    }
    if (!r || r.channel !== c)
      return fail(new Fault(404, 'unknown_run', `Сборки ${runId} фабрика не знает.`, [runId]));
    return { status: 200, body: outcome(r) };
  }

  function buildPlan(c: string, slug: string, raw: unknown): CardsReply {
    state.calls.push({ kind: 'plan', action: 'build', body: raw });
    try {
      if (world.readOnly()) throw readOnly();
      const b = (raw ?? {}) as { batch_id?: string | null };
      const e = find(c, slug, b.batch_id);
      const refusals =
        e.state === 'building' ? [refusal('running', `${slug}: a build is running`)] : [];
      const ok = !refusals.length;
      const replaces =
        e.state === 'ruled'
          ? 'Сейчас карточка принята вашим решением — после сборки решение пропадёт, карточку проверят заново.'
          : e.state === 'ready'
            ? 'Готовая карточка будет собрана заново и проверена ещё раз.'
            : e.state === 'not_ready'
              ? 'Не готовая карточка будет заменена новой сборкой.'
              : null;
      let confirm: string | null = null;
      if (ok) {
        confirm = `card-build-${++n}`;
        tokens.set(confirm, {
          action: 'build',
          key: `${c}|${slug}`,
          words: null,
          expires: Date.now() + state.life * 1000,
        });
      }
      const body: S['CardBuildLaunchPlan'] = {
        action: 'card_build_launch',
        channel: c,
        slug,
        batch_id: e.batch_id,
        ok,
        dry_run: true,
        draft: null,
        with_draft: false,
        what: 'Модель заново напишет черновик карточки и проверит утверждения — это займёт несколько минут, сборка идёт сама.',
        replaces,
        card: { ...stateOf(e), path: cardPath(e) },
        problems: [],
        refusals,
        why: ok ? null : refusals[0]!.message,
        by: 'user',
        via: 'center',
        fingerprint: `sha256:${slug}-${n}`,
        confirm,
        expires_in_s: confirm ? state.life : null,
      };
      return { status: 200, body };
    } catch (err) {
      return fail(err);
    }
  }

  function take(raw: unknown, action: Token['action'], c: string, slug: string) {
    const token = ((raw ?? {}) as { confirm?: string }).confirm ?? '';
    const got = tokens.get(token);
    if (!got)
      throw new Fault(409, 'confirm_unknown', 'Подтверждение не найдено или уже использовано.', [
        'no such confirm token',
      ]);
    const next = state.next;
    state.next = null;
    if (next === 'busy')
      throw new Fault(409, 'busy', 'Идёт другая запись публикации — подождите.', [
        'the publication write lock was not free in 30.0 s; the token is not spent',
      ]);
    tokens.delete(token);
    if (got.action !== action || got.key !== `${c}|${slug}`)
      throw new Fault(409, 'confirm_mismatch', 'Подтверждение выдано другому действию.', [
        `token of ${got.action} ${got.key}`,
      ]);
    if (got.expires <= Date.now())
      throw new Fault(409, 'confirm_expired', 'Подтверждение устарело (живёт 120 с).', ['expired']);
    if (next === 'check_changed')
      throw new Fault(409, 'check_changed', 'Карточка изменилась с момента плана.', [
        'the card sha256 differs from the plan',
      ]);
    return { got, next };
  }

  function build(c: string, slug: string, raw: unknown): CardsReply {
    state.calls.push({ kind: 'confirm', action: 'build', body: raw });
    try {
      if (world.readOnly()) throw readOnly();
      take(raw, 'build', c, slug);
      const e = find(c, slug);
      const runId = `run-${slug}-${++n}`;
      const now = world.now();
      e.state = 'building';
      e.ruling = null;
      e.build = {
        run_id: runId,
        log: `logs/publish-card/${slug}.log`,
        code: 'running',
        word: OUTCOME_WORDS.running,
        started_at: now,
        by: 'user',
        via: 'center',
        auto: false,
      };
      runs.set(runId, {
        run_id: runId,
        channel: c,
        slug,
        batch_id: e.batch_id,
        polls: 0,
        final: slug === CARD_TITLE_FAIL ? 'not_ready' : 'ready',
        started_at: now,
      });
      const body: S['CardBuildStarted'] = {
        action: 'card_build_launch',
        channel: c,
        slug,
        batch_id: e.batch_id,
        ok: true,
        launched: true,
        skipped: null,
        run_id: runId,
        pid: 4242,
        log: `logs/publish-card/${slug}.log`,
        draft: null,
        card: { state: 'not_ready', path: cardPath(e) },
        lines: [`card_build_launch ${c} ${slug}: launched ${runId}`],
        by: 'user',
        via: 'center',
        result_url: `/api/publish/${c}/cards/build/${runId}`,
        poll_s: state.pollS,
      };
      return { status: 200, body };
    } catch (err) {
      return fail(err);
    }
  }

  function rulingCheck(e: Entry) {
    if (e.state === 'building') return refusal('building', `${e.slug}: a build is running`);
    if (e.state === 'ready') return refusal('card_ready', `${e.slug}: card is ready`);
    if (e.state === 'none') return refusal('no_card', `${e.slug}: no card`);
    if (e.state === 'not_ready' && !e.failing.length)
      return refusal('claims_not_failed', `${e.slug}: claims did not fail`);
    if (e.failing.some((f) => f.video !== true))
      return refusal(
        'note_claim_failed',
        `${e.slug}: ${e.failing.find((f) => f.video !== true)!.where} failed - not the video's own words`,
      );
    return null;
  }

  function rulingBody(c: string, e: Entry, words: string, refusals: S['CardCenterRefusal'][]) {
    return {
      action: 'card_ruling' as const,
      channel: c,
      slug: e.slug,
      batch_id: e.batch_id,
      by: 'user',
      via: 'center',
      words,
      base_sha256: null,
      sha256: `sha256:${e.slug}-card`,
      failing: e.failing,
      card: cardPath(e),
      path: `publish/${c}/_queue/${e.slug}.md`,
      state: e.state,
      state_ru: STATE_RU[e.state],
      scope:
        'Ваше решение покрывает только слова самого ролика — комментарий, хук, развязку, текст на экране. Название и описание карточки фабрика проверяет как обычно.',
      refusals,
      lines: e.failing.map((f) => `${f.where}: ${f.code} - ${f.text}`),
    };
  }

  function rulingPlan(c: string, slug: string, raw: unknown): CardsReply {
    state.calls.push({ kind: 'plan', action: 'ruling', body: raw });
    try {
      if (world.readOnly()) throw readOnly();
      const b = (raw ?? {}) as { batch_id?: string | null; words?: string };
      const words = (b.words ?? '').trim();
      if (!words || words.length > 1000)
        throw new Fault(422, 'bad_words', 'Решение — от 1 до 1000 знаков вашими словами.', [
          `words: ${words.length} chars`,
        ]);
      const e = find(c, slug, b.batch_id);
      const r = rulingCheck(e);
      const refusals = r ? [r] : [];
      const ok = !r;
      let confirm: string | null = null;
      if (ok) {
        confirm = `card-ruling-${++n}`;
        tokens.set(confirm, {
          action: 'ruling',
          key: `${c}|${slug}`,
          words,
          expires: Date.now() + state.life * 1000,
        });
      }
      const body: S['CardRulingPlan'] = {
        ...rulingBody(c, e, words, refusals),
        ok,
        dry_run: true,
        why: ok ? null : r!.message,
        fingerprint: `sha256:${slug}-ruling-${n}`,
        confirm,
        expires_in_s: confirm ? state.life : null,
      };
      return { status: 200, body };
    } catch (err) {
      return fail(err);
    }
  }

  function ruling(c: string, slug: string, raw: unknown): CardsReply {
    state.calls.push({ kind: 'confirm', action: 'ruling', body: raw });
    try {
      if (world.readOnly()) throw readOnly();
      const { got, next } = take(raw, 'ruling', c, slug);
      const e = find(c, slug);
      const words = got.words ?? '';
      e.state = 'ruled';
      e.ruling = { by: 'user', via: 'center', words, at: world.now() };
      const touched = [cardPath(e), `publish/${c}/_queue/${slug}.md`];
      if (next === 'commit_refused')
        throw new Fault(
          409,
          'commit_refused',
          'Решение записано в карточку, но коммит не прошёл: правки остались незакоммиченными.',
          ['git commit: pre-commit hook refused (exit 1)', ...touched],
        );
      const body: S['CardRulingResult'] = {
        ...rulingBody(c, e, words, []),
        ok: true,
        dry_run: false,
        written: true,
        new_sha256: `sha256:${slug}-card-2`,
        touched,
        committed: touched,
        commit: '5e1d2c3b4a59',
      };
      return { status: 200, body };
    } catch (err) {
      return fail(err);
    }
  }

  /** Состояние карточки ролика для копилки и ленты (null — своего учёта нет). */
  const cardOf = (c: string, slug: string): S['CardState'] | null => {
    const e = entries.get(`${c}|${slug}`);
    return e ? stateOf(e) : null;
  };

  const expireTokens = () => {
    for (const t of tokens.values()) t.expires = 0;
  };

  return { state, info, run, buildPlan, build, rulingPlan, ruling, cardOf, expireTokens };
}

export type CardsBackend = ReturnType<typeof createCards>;

/**
 * `GET …/{c}/cards/{slug}`, `GET …/{c}/cards/build/{run_id}`, `POST …/{c}/cards/{slug}/
 * {build|ruling}[/plan]`; null — не адрес карточек.
 */
export function routeCards(
  s: CardsBackend,
  method: string,
  rest: string[],
  query: URLSearchParams,
  body: unknown,
): CardsReply | null {
  const [c, what, a, b, d] = rest;
  if (!c || what !== 'cards' || !a) return null;
  if (method === 'GET') {
    if (a === 'build' && b && rest.length === 4) return s.run(c, b);
    if (rest.length === 3) return s.info(c, a, query.get('batch_id'));
    return null;
  }
  if (method !== 'POST' || (b !== 'build' && b !== 'ruling')) return null;
  const plan = d === 'plan' && rest.length === 5;
  if (!plan && rest.length !== 4) return null;
  if (b === 'build') return plan ? s.buildPlan(c, a, body) : s.build(c, a, body);
  return plan ? s.rulingPlan(c, a, body) : s.ruling(c, a, body);
}
