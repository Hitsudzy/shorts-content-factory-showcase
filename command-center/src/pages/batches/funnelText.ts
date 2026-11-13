// CC-0172 (договор 0.75.0, CC-0171): где батч спас ролик или тему, а где нет — словами.
// Ремонт ролика после судьи кадров (CF-0881, `VideoRepair`): «Отремонтирован: блоки 5, 14
// (полоса)» / «Ремонт не удался — отказ (…)». Добор тем ниже шорт-листа (CF-0882,
// `BatchRefill` / `TopicRefill`): пометка «добор», отказ добора с причиной, сводка раундов.
// У старых батчей полей нет (null) — функции отдают null, плашек нет. Коды и пути — только под
// «подробнее»; виды брака (`kind`) — по-русски здесь, их строк фабрика не отдаёт. CC-0175
// (договор 0.76.0): исход раунда — строкой фабрики `outcome_ru`, свой перевод кода — запасной;
// пустой добор без записи раундов (`rounds: []`, подано 0) — без сводки.
import type { Schemas } from '@/api/client';

import { plural } from './format';

export type VideoRepair = Schemas['VideoRepair'];
export type RepairBlock = Schemas['RepairBlock'];
export type BatchRepairs = Schemas['BatchRepairs'];
export type BatchRefill = Schemas['BatchRefill'];
export type RefillRound = Schemas['RefillRound'];
export type TopicRefill = Schemas['TopicRefill'];

const NB = '\u00a0';
const hasCyrillic = (s: string) => /[а-яё]/i.test(s);
const clean = (s: string | null | undefined) => s?.trim().replace(/\.$/, '') || null;
/** Причина на виду — только по-русски; английская — под «подробнее». */
const ru = (s: string | null | undefined) => {
  const c = clean(s);
  return c && hasCyrillic(c) ? c : null;
};

/** Вид брака блока, который чинил ремонт (`RepairBlock.kind`). */
export const REPAIR_KIND_RU: Record<string, string> = {
  thin_strip: 'полоса',
  smeared: 'смаз',
  cut_subject: 'обрезан объект',
  wrong_person: 'чужое лицо',
  foreign_in_hook: 'чужое в хуке',
  foreign_share: 'доля чужого',
};

export const repairKind = (kind: string | null | undefined): string | null =>
  kind ? (REPAIR_KIND_RU[kind] ?? kind) : null;

/** Номер блока: `block`, без него — из записи судьи `block-14` / `block-5-meme`. */
function blockNo(b: RepairBlock): number | null {
  if (typeof b.block === 'number') return b.block;
  const m = b.entry?.match(/block-(\d+)/);
  return m ? Number(m[1]) : null;
}

/** «блоки 5, 14 (полоса)», «блок 5 (полоса, смаз)»; блоков нет — null. */
export function repairBlocksText(blocks: RepairBlock[] | null | undefined): string | null {
  const list = blocks ?? [];
  const nums = [...new Set(list.map(blockNo).filter((n): n is number => n != null))].sort(
    (a, b) => a - b,
  );
  const kinds = [...new Set(list.map((b) => repairKind(b.kind)).filter(Boolean))];
  if (!nums.length && !kinds.length) return null;
  const head = nums.length
    ? `${nums.length > 1 ? 'блоки' : 'блок'}${NB}${nums.join(', ')}`
    : list.length > 1
      ? 'блоки'
      : 'блок';
  return kinds.length ? `${head} (${kinds.join(', ')})` : head;
}

/**
 * Итог ремонта одной строкой: «Отремонтирован: блоки 5, 14 (полоса)» или «Ремонт не удался —
 * отказ (замены для блока 9 не нашлось)». Ремонта не было — null.
 */
export function repairLine(r: VideoRepair | null | undefined): string | null {
  if (!r?.outcome) return null;
  if (r.outcome === 'repaired') {
    const blocks = repairBlocksText(r.blocks);
    return blocks ? `Отремонтирован: ${blocks}` : 'Отремонтирован';
  }
  const why = ru(r.reason) ?? ru(r.after?.reason_ru);
  return `Ремонт не удался — отказ${why ? ` (${why})` : ''}`;
}

/** Подробности ремонта для «подробнее»: записи судьи, коды до и после, итог монтажа. */
export function repairDetails(r: VideoRepair | null | undefined): string[] {
  if (!r?.outcome) return [];
  const code = (c: VideoRepair['before']) =>
    c ? [c.gate, c.reason_code, c.score_line].filter(Boolean).join(', ') : null;
  const before = code(r.before);
  const after = code(r.after);
  return [
    `ремонт: ${r.outcome}${r.editor_outcome ? `, монтаж: ${r.editor_outcome}` : ''}`,
    ...(r.blocks ?? []).map(
      (b) =>
        `${b.entry ?? `блок ${b.block ?? '—'}`}${b.target ? ` (${b.target})` : ''}: ${b.kind ?? '—'}${b.why ? ` — ${b.why}` : ''}`,
    ),
    before ? `до ремонта: ${before}` : null,
    after ? `после ремонта: ${after}` : null,
    r.changed_blocks?.length ? `перерисованы блоки: ${r.changed_blocks.join(', ')}` : null,
    r.reason && !ru(r.reason) ? `причина: ${r.reason}` : null,
  ].filter((x): x is string => !!x);
}

/** Сводка ремонтов батча: «Ремонт роликов: удался 1, не удался 1»; ремонтов не было — null. */
export function repairsText(r: BatchRepairs | null | undefined): string | null {
  if (!r || !r.videos) return null;
  return `удался${NB}${r.repaired}, не удался${NB}${r.repair_failed}`;
}

const searchesWord = (n: number) => `${n}${NB}${plural(n, 'поиск', 'поиска', 'поисков')}`;

/**
 * Сводка добора у батча: «подано 1, поисков 4»; добора не было — null. CC-0175: записи раундов
 * нет (`rounds` пуст) и ничего не подано — тоже null: «подано 0, поисков 0» ничего не говорит.
 */
export function refillText(r: BatchRefill | null | undefined): string | null {
  if (!r || (!r.rounds.length && !r.admitted)) return null;
  return `подано${NB}${r.admitted}, поисков${NB}${r.searches}`;
}

export const ROUND_RU: Record<string, string> = {
  first: 'первый раунд',
  late: 'поздний раунд',
  judge: 'после судьи кадров',
};

export const ROUND_OUTCOME_RU: Record<string, string> = {
  admitted: 'темы поданы',
  not_needed: 'не понадобился',
  queue_empty: 'тем ниже шорт-листа не осталось',
  search_quota: 'не хватило квоты поиска',
  seam_failed: 'не удалось подать темы в батч',
  none_eligible: 'ни одна тема не прошла',
  no_pool: 'тем ниже шорт-листа нет',
};

/**
 * Исход раунда словами: CC-0175 — строка фабрики `outcome_ru` (договор 0.76.0), её нет (старая
 * фабрика, исход вне её словаря) — свой перевод кода, кода нет — «итога нет».
 */
export function roundOutcomeText(r: Pick<RefillRound, 'outcome' | 'outcome_ru'>): string {
  const own = r.outcome_ru?.trim();
  if (own) return own;
  return r.outcome ? (ROUND_OUTCOME_RU[r.outcome] ?? r.outcome) : 'итога нет';
}

const roundName = (r: RefillRound, i: number) => (r.round && ROUND_RU[r.round]) ?? `раунд ${i + 1}`;

/**
 * Раунд добора одной строкой: «первый раунд: темы поданы — Partition; нужно 1 — шорт-лист дал
 * 2 темы из 3; 3 поиска». `title` — название темы по её id.
 */
export function roundLine(r: RefillRound, i: number, title: (id: string) => string): string {
  const outcome = roundOutcomeText(r);
  const admitted = r.admitted.length ? ` — ${r.admitted.map(title).join(', ')}` : '';
  const why = ru(r.why);
  const need =
    r.need != null ? `нужно${NB}${r.need}${ru(r.need_why) ? ` — ${ru(r.need_why)}` : ''}` : null;
  const parts = [
    `${roundName(r, i)}: ${outcome}${admitted}${why && r.outcome !== 'admitted' ? ` (${why})` : ''}`,
    need,
    searchesWord(r.searches),
  ];
  return parts.filter(Boolean).join('; ');
}

/** Тема попала в батч добором: поднята в список тем или подана в резерв с пометкой. */
export const refillAdmitted = (r: TopicRefill | null | undefined): boolean =>
  !!r && (r.admitted || r.promoted || r.outcome === 'admitted' || r.outcome === 'promoted');

/** Подсказка пометки «добор». */
export function refillTip(r: TopicRefill): string {
  const round = r.round ? ROUND_RU[r.round] : null;
  return `Тема была ниже шорт-листа — батч добрал её${round ? ` (${round})` : ''}`;
}

const REFUSED_BY_RU: Record<string, string> = {
  compliance: 'проверка темы',
  trend_hunter: 'трендхантер',
};

/** Причина отказа добора: слова фабрики проверки темы, иначе русская строка футажа или темы. */
function refusalWhy(r: TopicRefill): string | null {
  return (
    clean(r.compliance?.reason_ru) ??
    ru(r.compliance?.reason) ??
    ru(r.reason) ??
    ru(r.footage?.reason) ??
    null
  );
}

/**
 * Что добор сделал с темой, если не добрал её: «добор: отказ (проверка темы) — права на трейлер
 * не подтверждены». Добрал (это пометка «добор») или добора не было — null.
 */
export function refillLine(r: TopicRefill | null | undefined): string | null {
  if (!r || refillAdmitted(r)) return null;
  const why = r.outcome === 'refused' ? refusalWhy(r) : ru(r.reason);
  const tail = why ? ` — ${why}` : '';
  switch (r.outcome) {
    case 'refused': {
      const by = r.refused_by ? REFUSED_BY_RU[r.refused_by] : null;
      return `добор: отказ${by ? ` (${by})` : ''}${tail || ' — причина без описания'}`;
    }
    case 'quota':
      return `добор: не хватило квоты поиска${tail}`;
    case 'error':
      return `добор: сбой${tail}`;
    case 'not_walked':
      return `добор: до темы не дошли${tail}`;
    case 'eligible':
      return `добор: прошла проверку, футаж не искали${tail}`;
    case 'not_judged':
      return `добор: проверку не проходила${tail}`;
    case 'considered':
      return `добор: рассмотрена${tail}`;
    default:
      return `добор: ${r.outcome}${tail}`;
  }
}

/** Подробности добора темы — для «подробнее» (коды и строки этапов как есть). */
export function refillDetails(r: TopicRefill | null | undefined): string[] {
  if (!r) return [];
  const c = r.compliance;
  const f = r.footage;
  return [
    `добор: ${r.outcome}${r.round ? `, раунд ${r.round}` : ''}${r.refused_by ? `, отказал ${r.refused_by}` : ''}`,
    c
      ? `проверка темы: ${[c.outcome, c.verdict, c.reason_code].filter(Boolean).join(', ')}${c.reason ? ` — ${c.reason}` : ''}`
      : null,
    f
      ? `футаж: ${f.outcome ?? '—'}${f.searches != null ? `, поисков ${f.searches}` : ''}${f.reason ? ` — ${f.reason}` : ''}`
      : null,
    r.reason ? `причина: ${r.reason}` : null,
    r.restored ? 'тема восстановлена по сводке строки резерва' : null,
  ].filter((x): x is string => !!x);
}
