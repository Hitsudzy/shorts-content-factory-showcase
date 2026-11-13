// Подставная оценка роликов (CC-0125; фабрика CF-0434, договор 0.55.0+): кратко — `Video.score`
// из строки оценки ролика («B · 74 — …»), разбор — `GET …/videos/{slug}/score` (`VideoScore`).
// Тиры — у каждого свой ролик: S quiet-keyboards (93), A rink-rivals (82), B delver (74,
// полный журнал plan.score.json: пять стадий, находка со временем, потолок правила, прогноз),
// C vanguards-doomsday (58), D usb-c-myths (44), F sophie-adenot (24, отказан после монтажа:
// разбор из 05, жёсткая находка). У ролика без оценки (jwst-little-red-dots) — 404 `no_score`.
// Импорты — относительные (общий для Vitest и Playwright).
import type { components } from '../api/schema.gen';

type S = components['schemas'];

/** Модель счёта (`shared/score/score.py` `load_model`): старт 100, порог 40, тиры S…D, ниже — F. */
export const SCORE_MODEL: S['ScoreModel'] = {
  start: 100,
  threshold: 40,
  tiers: [
    { name: 'S', floor: 90 },
    { name: 'A', floor: 80 },
    { name: 'B', floor: 65 },
    { name: 'C', floor: 50 },
    { name: 'D', floor: 40 },
  ],
  below: 'F',
  status: 'signed',
  error: null,
};

/** Ролик с полным журналом (стадии, время, потолок, прогноз). */
export const SCORE_FULL = 'delver';
/** Время находки «полоса удержания» у delver — на него встаёт плеер по «к моменту ▶». */
export const SCORE_MOMENT_T = 12.4;
/** Отказанный после монтажа с жёсткой находкой: разбор из 05. */
export const SCORE_HARD = 'sophie-adenot';

const parse = (line: string | null) => {
  const m = line ? /^([A-Z])\s*·\s*(\d+(?:\.\d+)?)(?:\s*—\s*(.*))?$/.exec(line) : null;
  return m ? { tier: m[1]!, score: Number(m[2]), tail: m[3] ?? null } : null;
};

export const scoreUrl = (batch: string, slug: string) =>
  `/api/batches/${batch}/videos/${slug}/score`;

/** Кратко для `Video.score`: из строки оценки; отказанный — из 05 и с этапом, где упал. */
export function scoreShort(
  batch: string,
  slug: string,
  line: string | null,
  refused: boolean,
): S['VideoScoreShort'] | null {
  const p = parse(line);
  if (!p) return null;
  const threshold = SCORE_MODEL.threshold!;
  return {
    tier: p.tier,
    score: p.score,
    threshold,
    passed: p.tier !== 'F' && p.score >= threshold,
    stopped_at: refused ? 'qc' : null,
    source: refused ? '05' : 'plan.score.json',
    url: scoreUrl(batch, slug),
  };
}

const STAGE_RU: Record<string, string> = {
  '6b': 'проверка сценария',
  plan: 'план монтажа',
  render: 'рендер',
  qc: 'проверка качества',
  judge: 'судья кадров',
};

const tierAt = (n: number) => SCORE_MODEL.tiers.find((t) => n >= t.floor)?.name ?? 'F';

function stagesOf(charges: [string, number][]): S['VideoScoreStage'][] {
  let left = SCORE_MODEL.start!;
  return charges.map(([stage, charged], i) => {
    left += charged;
    return {
      stage,
      label_ru: STAGE_RU[stage] ?? stage,
      charged,
      score_after: left,
      tier_after: tierAt(left),
      at: `2026-10-09T0${2 + i}:10:00Z`,
    };
  });
}

const finding = (f: Partial<S['VideoScoreFinding']>): S['VideoScoreFinding'] => ({
  rule: null,
  label_ru: null,
  stage: null,
  block: null,
  t: null,
  shot: null,
  shot_ru: null,
  where: {},
  price: null,
  units: null,
  hook: false,
  capped: false,
  source: 'metric',
  note: null,
  note_ru: null,
  hard: false,
  forecast: false,
  ...f,
});

const CLIPS = '~/factory/pool/example-film/clips';

/** Кадр для показа, как `shot_ru` фабрики (0.58.0): имя файла без `aNN_` и расширения. */
const shotRu = (shot: string | null | undefined) =>
  shot
    ? (shot.split('/').at(-1) ?? shot)
        .replace(/\.[a-z0-9]{2,4}$/i, '')
        .replace(/^a\d+_/i, '')
        .replace(/[_-]+/g, ' ')
    : null;

/** `note_ru` по правилу (шаблоны фабрики CF-0751); `score.blurry_background` — без шаблона. */
const NOTE_RU: Record<string, string> = {
  'score.framing': 'главное в кадре смещено от центра',
  'score.resolution': 'исходник 640×360 — ниже 1080p',
  'score.frozen_block': 'блок отрендерен стоп-кадром',
  'score.retention_strip': 'зритель уходит: три блока подряд без смены кадра',
};

function full(batch: string, slug: string, line: string): S['VideoScore'] {
  const findings = [
    finding({
      rule: 'score.retention_strip',
      label_ru: 'полоса удержания',
      stage: 'judge',
      block: 3,
      t: SCORE_MOMENT_T,
      where: { blocks: [3, 4] },
      price: -10,
      units: 2,
      capped: true,
      note: 'retention strip: blocks 3-4 run without a cut (judge drop 0.41)',
      note_ru: 'зритель уходит на середине: два блока подряд без смены кадра',
    }),
    finding({
      rule: 'score.framing',
      label_ru: 'кадрирование',
      stage: 'qc',
      shot: 'a04_mine-cart.mp4',
      shot_ru: 'mine cart',
      t: 21.8,
      where: { shot: `${CLIPS}/a04_mine-cart.mp4` },
      price: -3,
      units: 1,
      note: `subject off-center: ${CLIPS}/a04_mine-cart.mp4`,
      note_ru: 'главное в кадре смещено от центра',
    }),
    finding({
      rule: 'score.weak_hook_line',
      label_ru: 'хук: слабая первая фраза',
      stage: '6b',
      block: 1,
      price: -6,
      units: 1,
      hook: true,
    }),
    finding({
      rule: 'score.thin_picture',
      label_ru: 'тонкая картинка',
      stage: 'plan',
      price: -7,
      units: 1,
      note: 'block 5: 1 shot for 9.4 s (min 2)',
      note_ru: 'мало планов на блок 5: один кадр на 9 секунд',
    }),
    finding({
      rule: 'score.music_drop',
      label_ru: 'музыка проваливается',
      stage: 'judge',
      t: 38.2,
      source: 'forecast',
      forecast: true,
      note: 'прогноз судьи: на 0:38 музыка тише голоса — на публикации снимут',
    }),
  ];
  return {
    batch,
    slug,
    script_id: `${slug}-s1`,
    source: 'plan.score.json',
    path: `pipeline/${batch}/work/${slug}/plan.score.json`,
    tier: 'B',
    score: 74,
    start: 100,
    threshold: SCORE_MODEL.threshold,
    passed: true,
    stopped_at: null,
    stopped_at_ru: null,
    prices_status: 'signed',
    forecast_ignored: 1,
    tiers: SCORE_MODEL.tiers,
    model_error: null,
    stages: stagesOf([
      ['6b', -6],
      ['plan', -7],
      ['render', 0],
      ['qc', -3],
      ['judge', -10],
    ]),
    findings,
    by_rule: {
      'score.retention_strip': { raw: -14, charged: -10, cap: -10, label_ru: 'полоса удержания' },
      'score.framing': { raw: -3, charged: -3, cap: null, label_ru: 'кадрирование' },
    },
    score_line: line,
  };
}

/** Разбор отказанного из 05: без стадий, с жёсткой находкой поверх штрафов журнала. */
function from05(batch: string, slug: string, refusal: S['VideoRefusal']): S['VideoScore'] {
  const sc = (refusal.score ?? {}) as {
    score?: number;
    threshold?: number;
    tier?: string;
    log?: { rule?: string; price?: number; hook?: boolean; where?: object; note?: string }[];
  };
  const LABEL: Record<string, string> = {
    'score.retention_strip': 'полоса удержания',
    'score.framing': 'кадрирование',
    'score.resolution': 'разрешение',
    'score.frozen_block': 'зависший кадр',
    // score.blurry_background — без подписи у фабрики: экран пишет «другое правило».
  };
  const findings = [
    finding({
      rule: 'score.hard.frozen_hook',
      label_ru: 'зависший кадр в хуке',
      stage: 'qc',
      t: 1.2,
      hard: true,
      note: 'hook block 1 rendered as a still (qc_render frozen_blocks)',
      note_ru: 'первый блок отрендерен стоп-кадром — ролик не выпускается при любых баллах',
    }),
    ...(sc.log ?? []).map((l) =>
      finding({
        rule: l.rule ?? null,
        label_ru: (l.rule && LABEL[l.rule]) || null,
        price: l.price ?? null,
        hook: l.hook ?? false,
        where: (l.where ?? {}) as Record<string, unknown>,
        shot_ru: shotRu((l.where as { shot?: string } | undefined)?.shot),
        note: l.note ?? null,
        note_ru: (l.rule && NOTE_RU[l.rule]) || null,
        stage: null,
      }),
    ),
  ];
  return {
    batch,
    slug,
    script_id: `${slug}-s1`,
    source: '05',
    path: null,
    tier: 'F',
    score: sc.score ?? null,
    start: 100,
    threshold: sc.threshold ?? SCORE_MODEL.threshold,
    passed: false,
    stopped_at: 'qc',
    stopped_at_ru: 'после проверки качества',
    prices_status: 'draft',
    forecast_ignored: 0,
    tiers: SCORE_MODEL.tiers,
    model_error: null,
    stages: [],
    findings,
    by_rule: {},
    score_line: refusal.score_line ?? null,
  };
}

/** Разбор по строке оценки (остальные ролики): одна стадия, одна находка. */
function brief(batch: string, slug: string, line: string): S['VideoScore'] {
  const p = parse(line)!;
  const charged = p.score - 100;
  return {
    batch,
    slug,
    script_id: `${slug}-s1`,
    source: 'plan.score.json',
    path: `pipeline/${batch}/work/${slug}/plan.score.json`,
    tier: p.tier,
    score: p.score,
    start: 100,
    threshold: SCORE_MODEL.threshold,
    passed: p.score >= SCORE_MODEL.threshold!,
    stopped_at: null,
    stopped_at_ru: null,
    prices_status: 'signed',
    forecast_ignored: 0,
    tiers: SCORE_MODEL.tiers,
    model_error: null,
    stages: stagesOf([
      ['plan', Math.round(charged / 2)],
      ['judge', charged - Math.round(charged / 2)],
    ]),
    findings: charged
      ? [
          finding({
            rule: 'score.judge_notes',
            label_ru: p.tail ?? 'замечания судьи',
            stage: 'judge',
            price: charged,
            units: 1,
          }),
        ]
      : [],
    by_rule: {},
    score_line: line,
  };
}

/** Разбор ролика; null — оценки нет (404 `no_score`). */
export function scoreOf(
  batch: string,
  v: Pick<S['Video'], 'slug' | 'score_line' | 'refused'>,
): S['VideoScore'] | null {
  if (v.refused?.score) return from05(batch, v.slug, v.refused);
  if (!v.score_line || !parse(v.score_line)) return null;
  return v.slug === SCORE_FULL && v.score_line.startsWith('B · 74')
    ? full(batch, v.slug, v.score_line)
    : brief(batch, v.slug, v.score_line);
}
