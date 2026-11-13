// Подставная пересборка роликов (CC-0048/0049 фабрики, договор 0.17.0) — с состоянием: режимы
// из плана канала, секунды ролика → блоки раскадровки (`blocks_at`: `near` у склейки, `note`
// там, где монтаж исключение отклонит), план с одноразовым токеном на `expires_in_s` и сама
// пересборка по токену: `busy` (токен цел), `confirm_*`/`check_changed`, старт не удался
// (200 `ok:false`, каталог и `state` есть — продолжить). Часть подставных роликов
// (./videos.ts); общий для Vitest (MSW) и Playwright. Данные выдуманные, форма — фабрики.
import type { components } from '../api/schema.gen';
import type { BatchReply } from './schedule';

type S = components['schemas'];

const BY = 'user (центр)';
// С договора 0.35.0 корень фабрики в ответах — `.../<имя>` (CC-0098), не абсолютный путь.
const ROOT = '.../shorts-content-factory';

export const MODES: S['RebuildMode'][] = [
  {
    id: 'reedit',
    title: 'Перемонтаж — тот же сценарий, другие кадры',
    from_stage: 'video-editor',
    doc: 'Монтаж заново по тому же сценарию; можно убрать кадры, которые не понравились.',
  },
  {
    id: 'rewrite',
    title: 'Новый сценарий',
    from_stage: 'content-researcher',
    doc: 'Сценарий пишется заново, потом монтаж; кадры старого монтажа не участвуют.',
  },
];

/** `refused` режимов и плана — ворота отказа, без них — его код (CC-0116). */
const refusedOf = (v: S['Video']) =>
  v.refused ? (v.refused.gate ?? v.refused.reason_code ?? 'refused') : null;

/** Режимы, которые начинают с плана монтажа ролика (как EXCLUDE_MODES центра). */
const EXCLUDE_MODES_MOCK = new Set(['reedit']);

const LAYOUT: Record<string, S['RebuildLayout']> = {
  reedit: {
    copied: [
      'pool-maintenance',
      'trend-hunter',
      'compliance-shortlist',
      'footage-indexer',
      'content-researcher',
      'compliance-scripts',
    ],
    run: ['batch-start', 'video-editor', 'frame-judge', 'batch-done'],
    skipped: ['monitors'],
  },
  rewrite: {
    copied: ['pool-maintenance', 'trend-hunter', 'compliance-shortlist', 'footage-indexer'],
    run: [
      'batch-start',
      'content-researcher',
      'compliance-scripts',
      'video-editor',
      'frame-judge',
      'batch-done',
    ],
    skipped: ['monitors'],
  },
};

const COPY: Record<string, string[]> = {
  reedit: [
    '01-trend-hunter.json',
    '02-compliance-shortlist.json',
    '03-footage-indexer.json',
    '04-content-researcher.json',
    '04b-compliance-scripts.json',
  ],
  rewrite: ['01-trend-hunter.json', '02-compliance-shortlist.json', '03-footage-indexer.json'],
};

/** Раскадровка Delver 1824Z, как её видит `blocks_at`: 12 с — блок 4 (рядом 5), 18 — 7, 24 — 9. */
type Block = { n: number; start: number; end: number; kind: string; shot: string | null };
const DELVER_BLOCKS: Block[] = [
  { n: 1, start: 0, end: 2.6, kind: 'clip', shot: 'wIM1PDRvKSE:3' },
  { n: 2, start: 2.6, end: 5.4, kind: 'clip', shot: 'wIM1PDRvKSE:11' },
  { n: 3, start: 5.4, end: 8.9, kind: 'still', shot: 'wIM1PDRvKSE:18' },
  { n: 4, start: 8.9, end: 12.3, kind: 'clip', shot: 'wIM1PDRvKSE:32' },
  { n: 5, start: 12.3, end: 15, kind: 'clip', shot: 'wIM1PDRvKSE:40' },
  { n: 6, start: 15, end: 17.2, kind: 'sequence', shot: 'wIM1PDRvKSE:47' },
  { n: 7, start: 17.2, end: 20.6, kind: 'clip', shot: 'wIM1PDRvKSE:55' },
  { n: 8, start: 20.6, end: 23.1, kind: 'clip', shot: 'ZLXL1L0TfsI:7' },
  { n: 9, start: 23.1, end: 26.4, kind: 'clip', shot: 'ZLXL1L0TfsI:19' },
  { n: 10, start: 26.4, end: 29.8, kind: 'split', shot: 'ZLXL1L0TfsI:24' },
  { n: 11, start: 29.8, end: 33, kind: 'card', shot: null },
  { n: 12, start: 33, end: 40.9, kind: 'clip', shot: 'ZLXL1L0TfsI:31' },
];
const DELVER_ENDING = 40.9;
const NEAR_S = 0.5;

export const NOTES_RU = {
  split: 'Сплит-экран: монтаж не исключает кадр из половины экрана.',
  card: 'Карточка с текстом — кадра из исходников здесь нет.',
  ending: 'Концовка канала — её кадры не исключаются.',
  past: (d: number) => `Секунда за концом ролика (${String(d).replace('.', ',')} с).`,
};

const excludeOf = (b: Block) =>
  b.shot && b.kind !== 'split' && b.kind !== 'card' ? `${b.n}=${b.shot}` : null;

/** Раскадровка ролика длины `duration`: у Delver — своя, у прочих — та же, растянутая. */
function storyboard(slug: string, duration: number) {
  if (slug === 'delver') return { blocks: DELVER_BLOCKS, ending: DELVER_ENDING };
  const k = duration / 44.9;
  const r = (x: number) => Math.round(x * k * 10) / 10;
  return {
    blocks: DELVER_BLOCKS.map((b) => ({ ...b, start: r(b.start), end: r(b.end) })),
    ending: r(DELVER_ENDING),
  };
}

export function blocksAt(slug: string, duration: number, at: number[]) {
  const { blocks, ending } = storyboard(slug, duration);
  const moments: S['BlockMoment'][] = at.map((t) => {
    if (t >= duration)
      return {
        at: t,
        block: null,
        window: null,
        kind: null,
        shots: [],
        ending: false,
        exclude: null,
        near: [],
        note: NOTES_RU.past(duration),
      };
    if (t >= ending)
      return {
        at: t,
        block: null,
        window: [ending, duration],
        kind: 'end_card',
        shots: [],
        ending: true,
        exclude: null,
        near: [],
        note: NOTES_RU.ending,
      };
    const i = blocks.findIndex((b) => t >= b.start && t < b.end);
    const b = blocks[i]!;
    const near: S['BlockNear'][] = [];
    const prev = blocks[i - 1];
    const next = blocks[i + 1];
    if (prev && t - b.start < NEAR_S) near.push({ block: prev.n, exclude: excludeOf(prev) });
    if (next && b.end - t < NEAR_S) near.push({ block: next.n, exclude: excludeOf(next) });
    const exclude = excludeOf(b);
    return {
      at: t,
      block: b.n,
      window: [b.start, b.end],
      kind: b.kind,
      shots: b.shot ? [b.shot] : [],
      ending: false,
      exclude,
      near,
      ...(exclude ? {} : { note: b.kind === 'split' ? NOTES_RU.split : NOTES_RU.card }),
    };
  });
  return {
    moments,
    exclude: [...new Set(moments.map((m) => m.exclude).filter((x): x is string => !!x))],
  };
}

/** Чем ответит «да» пересборки: запущена / идёт другая / проверка изменилась / не стартовала. */
export type RebuildOutcome = 'ok' | 'busy' | 'check_changed' | 'start_failed';

type Source = { batch: string; channel: string | null; batch_id: string; videos: S['Video'][] };
type Token = { batch: string; body: S['RebuildPlanIn']; expires: number; plan: S['RebuildPlan'] };

const problem = (status: number, code: string, message: string, details: string[] = []) => ({
  status,
  body: { message, code, details } as unknown as S['BatchProblem'],
});

export function createRebuild(sourceOf: (batch: string) => Source | null) {
  const tokens = new Map<string, Token>();
  let n = 0;
  const state = {
    /** Ответ на следующее «да» (тесты переключают). */
    next: 'ok' as RebuildOutcome,
    /** Сколько живёт токен плана, с. */
    life: 120,
    /** Каждый план и каждое «да» — тела запросов, как пришли. */
    plans: [] as { batch: string; body: unknown }[],
    confirms: [] as { batch: string; body: unknown }[],
    /** Каждый запрос секунд (тесты проверяют, что ушло в `at`). */
    blockCalls: [] as string[],
  };
  const unknown = (batch: string) =>
    problem(404, 'unknown_batch', `Батча «${batch}» нет.`, [`no pipeline/${batch}`]);

  const modes = (batch: string): BatchReply<S['RebuildModes']> => {
    const src = sourceOf(batch);
    if (!src) return unknown(batch) as BatchReply<never>;
    const empty = !src.videos.length;
    return {
      status: 200,
      body: {
        batch: `pipeline/${batch}`,
        channel: src.channel,
        batch_id: src.batch_id,
        modes: empty ? [] : MODES,
        reason: empty ? 'У батча нет роликов — пересобирать нечего.' : null,
        seconds_to_blocks: true,
        // CC-0116 (договор 0.42.0): что план может назвать — ролики батча, и отказанные после
        // монтажа (`refused` — ворота); `plan` — есть ли план монтажа (у ролика без файла — нет).
        videos: src.videos.map((v) => ({
          slug: v.slug,
          script_id: v.script_id ?? v.slug,
          topic_id: 7,
          refused: refusedOf(v),
          plan: v.mp4.exists,
        })),
      },
    };
  };

  const blocks = (batch: string, slug: string, raw: string): BatchReply<S['VideoBlocks']> => {
    state.blockCalls.push(raw);
    const src = sourceOf(batch);
    if (!src) return unknown(batch) as BatchReply<never>;
    const v = src.videos.find((x) => x.slug === slug || x.script_id === slug);
    if (!v)
      return problem(
        404,
        'unknown_video',
        `Ролика «${slug}» в батче ${batch} нет.`,
      ) as BatchReply<never>;
    const parts = raw.split(',').map((x) => x.trim());
    const at = parts.map(Number);
    if (!raw.trim() || parts.length > 20 || at.some((x) => !Number.isFinite(x) || x < 0))
      return problem(422, 'invalid', 'Секунды ролика — от 1 до 20 чисел не меньше нуля.', [
        `at ${JSON.stringify(raw)}`,
      ]) as BatchReply<never>;
    const r = blocksAt(v.slug, v.duration ?? 40, at);
    return {
      status: 200,
      body: {
        ok: true,
        reason: `Секунд: ${at.length}, исключений: ${r.exclude.length}.`,
        batch: `pipeline/${batch}`,
        slug: v.slug,
        plan: `pipeline/${batch}/work/${v.slug}/plan.json`,
        duration: v.duration ?? null,
        moments: r.moments,
        exclude: r.exclude,
      },
    };
  };

  const plan = (batch: string, raw: unknown): BatchReply<S['RebuildPlan']> => {
    state.plans.push({ batch, body: raw });
    const src = sourceOf(batch);
    if (!src) return unknown(batch) as BatchReply<never>;
    const body = (raw ?? {}) as S['RebuildPlanIn'];
    const mode = MODES.find((m) => m.id === body.mode);
    const notes = typeof body.notes === 'object' && body.notes ? body.notes : null;
    const base: S['RebuildPlan'] = {
      action: 'rebuild',
      ok: false,
      reason: '',
      batch: `pipeline/${batch}`,
      batch_id: src.batch_id,
      channel: src.channel,
      mode: body.mode ?? null,
      title: mode?.title ?? null,
      from_stage: mode?.from_stage ?? null,
      layout: mode ? LAYOUT[mode.id]! : null,
      copy: mode ? COPY[mode.id]! : [],
      only_videos: mode ? COPY[mode.id]!.slice(-1) : [],
      work: [],
      videos: [],
      notes: notes?.text ?? (typeof body.notes === 'string' ? body.notes : null),
      rebuild_of: null,
      root: ROOT,
      posix: true,
      fingerprint: '',
      confirm: null,
      expires_in_s: null,
    };
    const refuse = (reason: string) => ({
      status: 200 as const,
      body: { ...base, reason, fingerprint: `f${'0'.repeat(63)}` },
    });
    if (!mode) return refuse(`Режима «${body.mode}» в плане канала нет.`);
    const videos: S['RebuildVideo'][] = [];
    for (const id of body.videos ?? []) {
      const v = src.videos.find((x) => x.slug === id || x.script_id === id);
      if (!v) return refuse(`Ролика «${id}» в 05 батча нет.`);
      if (EXCLUDE_MODES_MOCK.has(mode.id) && !v.mp4.exists)
        return refuse(
          `У ролика «${v.slug}» нет плана монтажа — перемонтажу не с чего начать; выберите «${MODES[1]!.title}».`,
        );
      const note = notes?.videos?.[id] ?? notes?.videos?.[v.slug];
      const obj = typeof note === 'object' && note ? note : null;
      const ex =
        obj?.exclude == null ? [] : Array.isArray(obj.exclude) ? obj.exclude : [obj.exclude];
      videos.push({
        slug: v.slug,
        script_id: v.script_id ?? v.slug,
        topic_id: 7,
        exclude: ex.map(String),
        note: (typeof note === 'string' ? note : obj?.note) ?? '',
        refused: refusedOf(v),
        plan: v.mp4.exists,
      });
    }
    if (!videos.length) return refuse('Не выбран ни один ролик.');
    if (mode.id !== 'reedit' && videos.some((v) => v.exclude?.length))
      return refuse(
        `Исключения кадров — только для режима «${MODES[0]!.title}»: «${mode.title}» пишет сценарий заново.`,
      );
    const tok = `rb-${++n}`;
    const out: S['RebuildPlan'] = {
      ...base,
      ok: true,
      reason: `Можно пересобрать: ${videos.map((v) => v.slug).join(', ')} — ${mode.title.toLowerCase()}, с шага «${mode.from_stage}».`,
      videos,
      fingerprint: `${n}`.padStart(64, 'a'),
      confirm: tok,
      expires_in_s: state.life,
    };
    tokens.set(tok, { batch, body, expires: Date.now() + state.life * 1000, plan: out });
    return { status: 200, body: out };
  };

  const confirm = (batch: string, raw: unknown): BatchReply<S['RebuildResult']> => {
    state.confirms.push({ batch, body: raw });
    const c = ((raw ?? {}) as { confirm?: string }).confirm ?? '';
    const t = tokens.get(c);
    if (!t || t.batch !== batch)
      return problem(409, 'confirm_unknown', 'Подтверждение не найдено — запросите план заново.', [
        `token ${c}`,
      ]) as BatchReply<never>;
    if (state.next === 'busy')
      return problem(
        409,
        'busy',
        'Идёт запуск или другая пересборка - подождите и запросите план пересборки заново.',
        ['the launch lock was not free in 5 s; the token is not spent'],
      ) as BatchReply<never>;
    tokens.delete(c);
    if (Date.now() > t.expires)
      return problem(409, 'confirm_expired', 'Подтверждение устарело — запросите план заново.', [
        `token ${c} expired`,
      ]) as BatchReply<never>;
    if (state.next === 'check_changed') {
      state.next = 'ok';
      return problem(
        409,
        'check_changed',
        'Проверка изменилась с момента плана - пересборка не начата; посмотрите план заново.',
        ["the fingerprint of rebuild_check differs from the plan's"],
      ) as BatchReply<never>;
    }
    const ts = '2026-10-10T1930Z';
    const dir = `pipeline/rebuilds/${ts}`;
    const failed = state.next === 'start_failed';
    return {
      status: 200,
      body: {
        ...t.plan,
        ok: !failed,
        reason: failed
          ? 'Каталог пересборки создан, но исполнитель не стартовал (код 1) — продолжите её.'
          : `Пересборка ${ts} запущена.`,
        by: BY,
        started: !failed,
        rebuild_id: ts,
        rebuild_dir: dir,
        pid: failed ? null : 48213,
        log: failed ? null : `schedule/logs/rebuild-${ts}.log`,
        exit: failed ? 1 : null,
        state: `${dir}/run-state.json`,
        argv: ['python3', 'shared/run_executor.py', '--resume', dir],
      } as S['RebuildResult'],
    };
  };

  return { state, modes, blocks, plan, confirm };
}

export type RebuildBackend = ReturnType<typeof createRebuild>;
