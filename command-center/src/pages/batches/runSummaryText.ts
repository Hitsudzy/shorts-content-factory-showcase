// Сводка прогона словами (CC-0115 → CC-0099): `data` ответа — разделы `runlog summary --json`
// без схемы (контракт отдаёт их как есть), поэтому каждый читается осторожно: чего нет или что
// не того вида — того на экране нет, а не ошибка. Человеку — время, воронка тем, оценки роликов
// и то, на что стоит посмотреть; строки фабрики, коды и имена — под «подробнее».
import { reasonOf } from '@/api/reasonRu';

import { plural } from './format';
import { spanText } from './going';

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Obj) : null;
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

/** Шаги воронки тем фабрики (`funnel.steps[].step`) — словами. */
const FUNNEL_STEP: Record<string, string> = {
  before_selection: 'найдено',
  selected: 'отобрано',
  after_compliance: 'прошли проверку тем',
  two_sources: 'с двумя источниками',
  scripts: 'сценарии',
  ready: 'смонтировано',
  frame_judge: 'прошли проверку кадров',
};

export type SummaryTime = {
  /** От первого маркера до последнего. */
  wall: string | null;
  /** Без простоев. */
  live: string | null;
  gaps: { count: number; span: string | null; share: number | null } | null;
  waits: { count: number; span: string | null } | null;
  operator: { span: string | null; share: number | null } | null;
};

export type FunnelStep = { step: string; label: string; count: number; lost: number };
/** Причина потери тем словами фабрики (`funnel_reasons_ru`, CC-0113) и сколько тем по ней. */
export type FunnelLoss = { code: string; text: string; count: number };
export type TierCount = { tier: string; count: number; level: 1 | 2 | 3 | 4 | 5 | 'f' | null };
export type Attention = { key: string; text: string; tip?: string };

export type SummaryView = {
  time: SummaryTime | null;
  funnel: FunnelStep[];
  /** «1 из 5 тем потеряна» — от первого шага после отбора до последнего. */
  funnelLine: string | null;
  /** Почему темы потеряны — по `funnel.losses`, больше — выше. */
  losses: FunnelLoss[];
  tiers: TierCount[];
  attention: Attention[];
  /** Строки фабрики (`*_line`) — под «подробнее». */
  lines: string[];
};

const share = (part: number | null, whole: number | null) =>
  part != null && whole ? Math.round((part / whole) * 1000) / 10 : null;

function timeOf(d: Obj): SummaryTime | null {
  const t = obj(d.times);
  if (!t) return null;
  const wallS = num(obj(t.wall)?.seconds);
  const gaps = obj(d.gaps);
  const waits = obj(d.waits);
  const gapsS = num(gaps?.seconds) ?? num(t.gaps_s);
  const opS = num(obj(d.operator)?.seconds) ?? num(t.operator_s);
  return {
    wall: spanText(wallS),
    live: spanText(num(t.live_s)),
    gaps:
      gaps || gapsS != null
        ? { count: num(gaps?.count) ?? 0, span: spanText(gapsS), share: share(gapsS, wallS) }
        : null,
    waits: waits
      ? { count: num(waits.count) ?? 0, span: spanText(num(waits.seconds) ?? num(t.waits_s)) }
      : null,
    operator: opS != null ? { span: spanText(opS), share: share(opS, wallS) } : null,
  };
}

function funnelOf(d: Obj): FunnelStep[] {
  const f = obj(d.funnel);
  if (!f || f.available === false) return [];
  return arr(f.steps).flatMap((s): FunnelStep[] => {
    const o = obj(s);
    const step = str(o?.step);
    const count = num(o?.count);
    if (!o || !step || count == null) return [];
    return [
      {
        step,
        label: FUNNEL_STEP[step] ?? str(o.label) ?? step,
        count,
        lost: arr(o.lost).length,
      },
    ];
  });
}

const stripNull = (m: Record<string, string | null> | null | undefined) =>
  Object.fromEntries(Object.entries(m ?? {}).filter(([, v]) => !!v));

/**
 * Потери воронки (`funnel.losses` «код → сколько»): слова — из `funnel_reasons_ru` ответа, иначе
 * из `reason_ru` строк `lost` шагов, иначе сам код (CC-0113: своих подписей нет).
 */
function lossesOf(d: Obj, words: Record<string, string | null> | null | undefined): FunnelLoss[] {
  const f = obj(d.funnel);
  if (!f || f.available === false) return [];
  const inline: Record<string, string | null> = {};
  for (const s of arr(f.steps))
    for (const l of arr(obj(s)?.lost)) {
      const code = str(obj(l)?.reason_code);
      const ru = str(obj(l)?.reason_ru);
      if (code && ru && !inline[code]) inline[code] = ru;
    }
  return Object.entries(obj(f.losses) ?? {})
    .flatMap(([code, n]): FunnelLoss[] => {
      const count = num(n);
      if (!count) return [];
      return [{ code, text: reasonOf({ ...inline, ...stripNull(words) }, code), count }];
    })
    .sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
}

function funnelLineOf(steps: FunnelStep[]): string | null {
  const sel = steps.find((s) => s.step === 'selected') ?? steps[0];
  const last = steps[steps.length - 1];
  if (!sel || !last || sel === last) return null;
  const lost = Math.max(0, sel.count - last.count);
  if (!sel.count) return 'в работу не взято ни одной темы';
  if (!lost) return `все ${sel.count} ${plural(sel.count, 'тема', 'темы', 'тем')} дошли до конца`;
  return `${lost} из ${sel.count} ${plural(sel.count, 'темы', 'тем', 'тем')} ${plural(lost, 'потеряна', 'потеряны', 'потеряно')} по пути`;
}

const TIERS = ['S', 'A', 'B', 'C', 'D', 'E', 'F'];
/** Ступень цвета тира (`--tier-N`, как значок оценки на «Роликах»). */
const TIER_LEVEL: Record<string, TierCount['level']> = {
  S: 1,
  A: 2,
  B: 2,
  C: 3,
  D: 4,
  E: 5,
  F: 'f',
};

function tiersOf(d: Obj): TierCount[] {
  const n = new Map<string, number>();
  for (const s of arr(d.scores)) {
    const t = str(obj(s)?.tier);
    if (t) n.set(t, (n.get(t) ?? 0) + 1);
  }
  const rank = (t: string) => (TIERS.includes(t) ? TIERS.indexOf(t) : TIERS.length);
  return [...n]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([tier, count]) => ({ tier, count, level: TIER_LEVEL[tier] ?? null }));
}

function attentionOf(d: Obj): Attention[] {
  const out: Attention[] = [];
  const nw = obj(d.no_waiting);
  const gaps = obj(d.gaps);
  const unknown = obj(obj(gaps?.by_cause)?.unknown);
  if (nw?.verdict === 'incident' && (num(unknown?.count) ?? 0) > 0) {
    out.push({
      key: 'stood',
      text: `Батч стоял без причины: ${spanText(num(unknown?.seconds)) ?? 'неизвестно сколько'}`,
      tip: 'Простой, который фабрика не объяснила ни лимитом, ни ожиданием человека, — на такой она заводит задачу.',
    });
  }
  const m = obj(d.monitors);
  const red = num(m?.red) ?? 0;
  if (m && red > 0) {
    const all = red + (num(m.green) ?? 0) + (num(m.not_checked) ?? 0);
    out.push({
      key: 'monitors',
      text: `Проверки после батча: ${red} из ${all} не зелёные`,
      tip: 'Живые проверки фабрики, которые запускаются после батча на настоящих данных.',
    });
  }
  const drift = arr(d.code_drift).length;
  if (drift > 0) {
    out.push({
      key: 'drift',
      text: `Код фабрики менялся во время прогона: ${drift} ${plural(drift, 'раз', 'раза', 'раз')}`,
      tip: 'Ролики этого прогона собраны не одной версией кода.',
    });
  }
  const watchdog = arr(d.watchdog).length;
  if (watchdog > 0) {
    out.push({
      key: 'watchdog',
      text: `Сторожевой таймер срабатывал: ${watchdog} ${plural(watchdog, 'раз', 'раза', 'раз')}`,
    });
  }
  if (obj(d.consistency)?.ok === false) {
    out.push({
      key: 'consistency',
      text: 'Учёт времени не сходится — цифры времени приблизительные',
    });
  }
  return out;
}

export function summaryView(
  data: Record<string, unknown> | null | undefined,
  words?: Record<string, string | null> | null,
): SummaryView | null {
  const d = obj(data);
  if (!d) return null;
  const funnel = funnelOf(d);
  const lines = ['gaps_line', 'waits_line', 'operator_line', 'quota_line', 'sieve_answers_line']
    .map((k) => str(d[k]))
    .filter((x): x is string => !!x);
  return {
    time: timeOf(d),
    funnel,
    funnelLine: funnelLineOf(funnel),
    losses: lossesOf(d, words),
    tiers: tiersOf(d),
    attention: attentionOf(d),
    lines,
  };
}
