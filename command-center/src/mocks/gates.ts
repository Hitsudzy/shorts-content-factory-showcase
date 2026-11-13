// Подставная цена воротец (CC-0115 → CC-0100, `GET /api/gate-prices`): правила как у живой
// фабрики на окне из 5 батчей — с ценой, без замера («не цена ноль»), подписанные и с решением;
// одно предложение подписи и одна строка леджера без замера. `broken` — фабрика не ответила
// (409 `factory_broken`). Записи (CC-0115 шаг 3): подпись цены и решение plan → confirm с
// `base_sha256` — см. `createGatesBackend`. Общий для Vitest, Playwright и тренировки; импорты —
// относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];
type Reply<T> = { status: number; body: T };

const WINDOW = [
  'example-film/2026-10-04T1825Z',
  'example-film/2026-10-05T0701Z',
  'example-film/2026-10-07T0200Z',
  'example-film/2026-10-08T0215Z',
  'example-film/2026-10-09T0215Z',
];

const USER = 'Example Reviewer';

const actions = (over: Partial<S['GateActions']> = {}): S['GateActions'] => ({
  in_ledger: true,
  measured_price: null,
  signable: true,
  sign: false,
  sign_refusal: { code: 'not_measured', message: 'Цена не измерена — подписывать нечего.' },
  decide: true,
  decide_refusal: null,
  ...over,
});

const batch = (b: string, price: number | null, killed: string[] = []): S['GatePriceBatch'] => ({
  batch: b,
  basis: price == null ? null : 'the gate ran as warn and rendered anyway',
  no_basis: price == null ? 'no video carries a record of this gate' : null,
  ready: ['a-script1', 'b-script1', 'c-script1'],
  refused: killed.map((s) => `${s}-script1`),
  killed: killed.map((slug) => ({ item: `${slug}-script1`, slug, key: null, reason: 'the rule' })),
  price: price == null ? null : killed.length,
});

type Rule = {
  rule: string;
  what: 'video' | 'topic';
  price: number | null;
  ready: number;
  measured: number;
  verdict: S['GatePriceResult']['verdict'];
  why: string;
  killed?: Record<string, string[]>;
  signature?: Record<string, unknown> | null;
  decision?: Record<string, unknown> | null;
  mode?: 'measure' | 'warn' | null;
  actions?: Partial<S['GateActions']>;
};

const RULES: Rule[] = [
  {
    rule: 'content_researcher.tail_after_last_anchor',
    what: 'video',
    price: 3,
    ready: 15,
    measured: 5,
    verdict: 'warn',
    why: '3 ready video(s) would have died across 5 priceable batch(es) - it lands as a warning until the user signs it',
    killed: { [WINDOW[0]!]: ['delver'], [WINDOW[1]!]: ['harbourlights', 'vanguards-endgame'] },
    actions: { measured_price: 3, sign: true, sign_refusal: null },
  },
  {
    rule: 'frame_judge.foreign_core',
    what: 'video',
    price: 1,
    ready: 8,
    measured: 2,
    verdict: 'enforce',
    why: `1 ready video(s) would have died, and ${USER} signed the rule at a price of 1 on 2026-10-05`,
    killed: { [WINDOW[1]!]: ['weekend-night-live'] },
    signature: { user: USER, date: '2026-10-05', price: 1, note: 'Решение в чате: «да, отказ».' },
    actions: {
      measured_price: 1,
      sign_refusal: { code: 'already_signed', message: 'Цена уже подписана.' },
    },
  },
  {
    rule: 'footage_indexer.no_second_source',
    what: 'topic',
    price: null,
    ready: 0,
    measured: 0,
    verdict: 'warn',
    why: 'no basis: none of the 5 batch(es) in the window could carry a video this rule refuses, so nothing was measured - and nothing measured is not a price of zero',
    decision: {
      mode: 'warn',
      user: USER,
      date: '2026-09-28',
      note: 'CF-0419: «переносим в предупреждение».',
    },
  },
  {
    rule: 'orchestrator.stopcock',
    what: 'video',
    price: 0,
    ready: 15,
    measured: 5,
    verdict: 'enforce',
    why: '0 of 5 priceable batch(es) in the window lost a ready video to this rule - it lands as a refusal',
    actions: { measured_price: 0, sign: true, sign_refusal: null },
  },
  {
    rule: 'video_editor.two_source_gate',
    what: 'video',
    price: 0,
    ready: 15,
    measured: 4,
    verdict: 'enforce',
    why: '0 of 4 priceable batch(es) in the window lost a ready video to this rule - it lands as a refusal',
    decision: {
      user: USER,
      date: '2026-09-23',
      mode: 'warn',
      task: 'CF-0330',
      note: '«предупреждение»',
    },
    mode: 'measure',
  },
];

function result(r: Rule): S['GatePriceResult'] {
  return {
    rule: r.rule,
    what: r.what,
    note: `${r.rule}: the rule's own words (CF-0000)`,
    before: null,
    window: WINDOW,
    batches: WINDOW.map((b) =>
      batch(b, r.price == null ? null : (r.killed?.[b]?.length ?? 0), r.killed?.[b] ?? []),
    ),
    ready: r.ready,
    price: r.price,
    measured_on: r.measured,
    of: WINDOW.length,
    verdict: r.verdict,
    why: r.why,
    signature: r.signature ?? null,
    decision: r.decision ?? null,
    headline: `GATE PRICE ${r.rule}: ${r.price ?? '?'} of ${r.ready} ready video(s)`,
    mode: r.mode ?? null,
    actions: actions(r.actions),
  };
}

/** Записанное из центра поверх правил окна: подпись — отказ и «уже подписано», решение — режим. */
type Written = {
  signed: Record<string, Record<string, unknown>>;
  decided: Record<string, Record<string, unknown>>;
  sha: string;
};

const SHA0 = 'c0ffee'.repeat(10) + 'beef';

function withWritten(r: Rule, w: Written | undefined): Rule {
  const sig = w?.signed[r.rule];
  const dec = w?.decided[r.rule];
  if (!sig && !dec) return r;
  return {
    ...r,
    ...(sig
      ? {
          signature: sig,
          verdict: 'enforce' as const,
          actions: {
            ...r.actions,
            sign: false,
            sign_refusal: { code: 'already_signed', message: 'Цена уже подписана.' },
          },
        }
      : {}),
    ...(dec ? { decision: dec } : {}),
  };
}

/** `noProposals` — блок предложений пуст (CF-0743: последнее предложение убрано решением 14.10). */
export function gatePricesReply(noProposals = false, written?: Written): S['GatePrices'] {
  const results = RULES.map((r) => result(withWritten(r, written)));
  const signed = new Set(Object.keys(written?.signed ?? {}));
  return {
    rules: [...RULES.map((r) => r.rule), 'video_editor.meme_captions'],
    asked: RULES.map((r) => r.rule),
    window: WINDOW.length,
    before: null,
    window_default: 5,
    pool: 'pipeline',
    ledger: 'shared/gate-prices.json',
    ledger_exists: true,
    ledger_sha256: written?.sha ?? SHA0,
    results,
    all_land: results.every((r) => r.verdict !== 'warn'),
    unregistered: [
      {
        rule: 'video_editor.subtitle_overlap',
        note: 'measured by hand on 2026-09-20',
        measured: { price: 2, of: 6, date: '2026-09-20' },
        signature: null,
        decision: { user: USER, date: '2026-09-21', mode: 'warn', note: '«пусть предупреждает»' },
        actions: actions(),
      },
    ],
    proposals: (noProposals
      ? []
      : [
          {
            rule: 'content_researcher.tail_after_last_anchor',
            line: 'sign content_researcher.tail_after_last_anchor at a price of 3 (of 15 ready videos)',
            mode_until_signed: 'warn',
          },
        ]
    ).filter((p) => !signed.has(p.rule)),
    signing: {
      available: true,
      what: 'Подписать цену не ниже измеренной и записать решение measure/warn по правилу.',
      how_today: 'Из центра (plan → confirm) или правкой shared/gate-prices.json.',
      factory_function: 'gate_price.sign / gate_price.decide',
      task: 'CF-0721',
    },
    computed_at: '2026-10-14T06:30:00Z',
    cached: false,
  };
}

type Problem = S['GatePriceProblemW'];
type Code = Problem['code'];
type Kind = 'sign' | 'decide';

const NOTHING = 'ничего не записано';

/** Отказы фабрики (`gate_price.SIGN_REFUSALS`) — статус и строка API (api/gate_prices.py). */
export const GATE_REFUSALS: Partial<Record<Code, [number, string]>> = {
  empty_note: [422, 'Нужна ваша заметка - подпись и решение без ваших слов не пишутся.'],
  no_such_rule: [
    404,
    'Этого правила нет в леджере shared/gate-prices.json - подписывать нечего: цену сначала измеряют (runlog gate-price --write).',
  ],
  not_signable: [
    409,
    'Это правило модели оценок (hard / penalty) - его подписывают вместе с таблицей оценок, не здесь.',
  ],
  not_measured: [
    409,
    'Цена правила в леджере не измерена - подпись не покрывает то, что никто не мерил.',
  ],
  bad_price: [422, 'Цена - это число готовых роликов, 0 или больше.'],
  below_measured: [
    409,
    'Цена ниже измеренной - такая подпись ничего бы не покрыла; подпишите не меньше измеренной.',
  ],
  already_signed: [
    409,
    'Правило уже подписано ценой, которая покрывает измеренную: новая подпись не нужна, а решение подпись не снимает.',
  ],
  bad_mode: [
    422,
    'Решение - только measure (мерить) или warn (предупреждать): отказ делает только подпись.',
  ],
  bad_task: [422, 'Нужен номер задачи вида CF-0330.'],
  batch_open: [
    409,
    'Пока идёт батч, цены не подписываются - батчи читают shared/; повторите после батча.',
  ],
  check_changed: [
    409,
    `Леджер цен изменился с тех пор, как вы его открыли - откройте заново, ${NOTHING}.`,
  ],
  locked: [
    409,
    'Леджер цен сейчас пишет кто-то другой (замер цен или другая подпись) - подождите и повторите.',
  ],
  commit_refused: [409, 'Git не принял коммит леджера - файл возвращён как был.'],
  write_failed: [500, 'Леджер не записался - посмотрите диск, прежде чем повторять.'],
};

const ORDER: Code[] = [
  'empty_note',
  'no_such_rule',
  'not_signable',
  'not_measured',
  'bad_price',
  'below_measured',
  'already_signed',
  'bad_mode',
  'bad_task',
  'batch_open',
  'check_changed',
  'locked',
  'commit_refused',
  'write_failed',
];

const problem = (status: number, code: Code, message: string, details: string[] = []) => ({
  status,
  body: { message, code, details } satisfies Problem,
});

const refusalOf = (code: Code): S['GateWriteRefusal'] => ({
  code,
  line: `gate_price: ${code}`,
  message: GATE_REFUSALS[code]?.[1] ?? code,
});

const today = () => new Date().toISOString().slice(0, 10);

type Bound = Record<string, unknown>;

/**
 * Подставная фабрика цен воротец с записями (CC-0115 шаг 3). Переключатели теста: `refuse` — код
 * отказа плана (`batch_open`, `locked`…), `actRefuse` — код отказа «да» (`commit_refused`…),
 * `busy` — «да» отвечает `busy` (токен цел), `changeLedger()` — кто-то другой переписал леджер
 * (план со старым `base_sha256` и «да» — `check_changed`), `expireTokens()` — токены устарели.
 */
export function createGatesBackend() {
  const state = {
    broken: false,
    noProposals: false,
    calls: 0,
    life: 120,
    refuse: null as Code | null,
    actRefuse: null as Code | null,
    busy: false,
    version: 0,
    written: { signed: {}, decided: {}, sha: SHA0 } as Written,
    /** Тела планов, как их прислал центр (последний — в конце). */
    plans: [] as { kind: Kind; rule: string; body: unknown }[],
  };
  const tokens = new Map<
    string,
    { kind: Kind; rule: string; bound: Bound; base: string; expires: number }
  >();
  let seq = 0;
  const sha = () => state.written.sha;
  const bump = () => {
    state.version += 1;
    state.written.sha = `${state.version.toString(16).padStart(4, '0')}${SHA0.slice(4)}`;
  };

  function refusals(kind: Kind, rule: string, b: Bound, base: string): Code[] {
    const out: Code[] = [];
    const r = RULES.find((x) => x.rule === rule);
    if (typeof b.note !== 'string' || !b.note.trim()) out.push('empty_note');
    if (!r) out.push('no_such_rule');
    else {
      const a = actions(withWritten(r, state.written).actions);
      if (kind === 'sign') {
        if (!a.sign && a.sign_refusal) out.push(a.sign_refusal.code as Code);
        const price = b.price;
        if (typeof price !== 'number' || !Number.isInteger(price) || price < 0)
          out.push('bad_price');
        else if (a.measured_price != null && price < a.measured_price) out.push('below_measured');
      } else {
        if (!a.decide && a.decide_refusal) out.push(a.decide_refusal.code as Code);
        if (b.mode !== 'measure' && b.mode !== 'warn') out.push('bad_mode');
        if (typeof b.task !== 'string' || !/^CF-\d{4}$/.test(b.task)) out.push('bad_task');
      }
    }
    if (state.refuse) out.push(state.refuse);
    if (base !== sha()) out.push('check_changed');
    return [...new Set(out)].sort((x, y) => ORDER.indexOf(x) - ORDER.indexOf(y));
  }

  function blockOf(kind: Kind, bound: Bound): Record<string, unknown> {
    const who = { user: USER, date: today(), via: 'center' };
    return kind === 'sign'
      ? { ...who, price: bound.price, note: bound.note }
      : { ...who, mode: bound.mode, task: bound.task, note: bound.note };
  }

  function common(kind: Kind, rule: string, bound: Bound, base: string, codes: Code[]) {
    return {
      action: kind === 'sign' ? ('gate_price_sign' as const) : ('gate_price_decide' as const),
      kind,
      rule,
      key: kind === 'sign' ? ('signature' as const) : ('decision' as const),
      task: 'CF-0721',
      ok: codes.length === 0,
      path: 'shared/gate-prices.json',
      base_sha256: base,
      sha256: sha(),
      new_sha256: codes.length ? null : `beef${sha().slice(4)}`,
      block: codes.length ? null : blockOf(kind, bound),
      refusals: codes.map(refusalOf),
      lines: [
        `GATE ${kind.toUpperCase()} ${rule}${codes.length ? ` refused: ${codes.join(', ')}` : ''}`,
      ],
      by: 'user',
      via: 'center',
    };
  }

  return {
    state,
    prices(): Reply<S['GatePrices'] | S['GatePriceProblem']> {
      state.calls += 1;
      if (state.broken)
        return {
          status: 409,
          body: {
            message: 'Фабрика не посчитала цену воротец.',
            code: 'factory_broken',
            details: ['gate_price.price: KeyError: funnel'],
          },
        };
      return { status: 200, body: gatePricesReply(state.noProposals, state.written) };
    },
    plan(kind: Kind, rule: string, raw: unknown): Reply<S['GateWritePlan'] | Problem> {
      const b = (raw ?? {}) as Bound;
      state.plans.push({ kind, rule, body: raw });
      const base = typeof b.base_sha256 === 'string' ? b.base_sha256 : sha();
      const bound: Bound =
        kind === 'sign'
          ? { price: b.price, note: b.note }
          : { mode: b.mode, task: b.task, note: b.note };
      const codes = refusals(kind, rule, b, base);
      let confirm: string | null = null;
      if (!codes.length) {
        confirm = `gate-${kind}-${++seq}`;
        tokens.set(confirm, { kind, rule, bound, base, expires: Date.now() + state.life * 1000 });
      }
      return {
        status: 200,
        body: {
          ...common(kind, rule, bound, base, codes),
          dry_run: true,
          why: codes.length ? refusalOf(codes[0]!).message : null,
          confirm,
          expires_in_s: confirm ? state.life : null,
        },
      };
    },
    act(kind: Kind, rule: string, raw: unknown): Reply<S['GateWriteResult'] | Problem> {
      if (state.busy)
        return problem(
          409,
          'busy',
          'Идёт другая подпись цены - подождите и запросите план заново.',
          ['the gate-price write lock was not free in 5 s; the token is not spent'],
        );
      const token = (raw as { confirm?: string } | null)?.confirm ?? '';
      const got = tokens.get(token);
      tokens.delete(token);
      if (!got || got.kind !== kind || got.rule !== rule)
        return problem(
          409,
          'confirm_unknown',
          'Подтверждение не найдено - запросите план заново.',
          ['no such confirm token in this API process (used, unknown, or the server restarted)'],
        );
      if (got.expires <= Date.now())
        return problem(409, 'confirm_expired', 'Подтверждение устарело - запросите план заново.', [
          'expired',
        ]);
      const codes = refusals(kind, rule, got.bound, got.base);
      if (state.actRefuse) codes.unshift(state.actRefuse);
      if (codes.length) {
        const first = codes[0]!;
        const [status, message] = GATE_REFUSALS[first] ?? [500, first];
        return problem(
          status,
          first,
          message,
          codes.map((c) => `${c}: gate_price: ${c}`),
        );
      }
      const block = blockOf(kind, got.bound);
      if (kind === 'sign') state.written.signed[rule] = block;
      else state.written.decided[rule] = block;
      const base = got.base;
      bump();
      return {
        status: 200,
        body: {
          ...common(kind, rule, got.bound, base, []),
          block,
          dry_run: false,
          written: true,
          commit: 'a1b2c3d',
        },
      };
    },
    /** Кто-то другой переписал леджер: старый `base_sha256` больше не совпадает. */
    changeLedger() {
      bump();
    },
    /** Все выданные токены устарели — «да» получит `confirm_expired`. */
    expireTokens() {
      for (const t of tokens.values()) t.expires = 0;
    },
  };
}

export type GatesBackend = ReturnType<typeof createGatesBackend>;

const WRITE = /\/api\/gate-prices\/([^/]+)\/(sign|decide)(\/plan)?$/;

/** Цена воротец подставной фабрики: чтение, подпись и решение; null — адрес не этот. */
export function routeGates(
  backend: GatesBackend,
  method: string,
  url: URL,
  body: unknown = null,
): Reply<unknown> | null {
  if (method === 'GET' && /\/api\/gate-prices$/.test(url.pathname)) return backend.prices();
  const m = method === 'POST' ? url.pathname.match(WRITE) : null;
  if (!m) return null;
  const rule = decodeURIComponent(m[1]!);
  const kind = m[2] as Kind;
  return m[3] ? backend.plan(kind, rule, body) : backend.act(kind, rule, body);
}
