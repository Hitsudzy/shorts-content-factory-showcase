import { describe, expect, it } from 'vitest';

import { FUNNEL_REPAIRS } from '@/mocks/batchTopics';

import {
  REPAIR_KIND_RU,
  refillAdmitted,
  refillLine,
  refillText,
  repairBlocksText,
  repairDetails,
  repairKind,
  repairLine,
  repairsText,
  roundLine,
  roundOutcomeText,
  type RefillRound,
  type TopicRefill,
  type VideoRepair,
} from './funnelText';

/** Неразрывные пробелы — обычными: сравниваем слова. */
const plain = (s: string | null) => s?.replace(/\u00a0/g, ' ') ?? null;

const repair = (r: Partial<VideoRepair>): VideoRepair => ({
  outcome: 'repaired',
  reason: null,
  at: null,
  blocks: [],
  before: null,
  after: null,
  editor_outcome: null,
  changed_blocks: [],
  ...r,
});

const refill = (r: Partial<TopicRefill>): TopicRefill => ({
  outcome: 'refused',
  round: 'first',
  promoted: false,
  restored: null,
  admitted: false,
  refused_by: null,
  reason: null,
  compliance: null,
  footage: null,
  ...r,
});

describe('ремонт ролика после судьи кадров (CC-0172)', () => {
  it('виды брака — по-русски, неизвестный — как есть', () => {
    expect(REPAIR_KIND_RU).toEqual({
      thin_strip: 'полоса',
      smeared: 'смаз',
      cut_subject: 'обрезан объект',
      wrong_person: 'чужое лицо',
      foreign_in_hook: 'чужое в хуке',
      foreign_share: 'доля чужого',
    });
    expect(repairKind('new_defect')).toBe('new_defect');
    expect(repairKind(null)).toBeNull();
  });

  it('«Отремонтирован: блоки 5, 14 (полоса)»', () => {
    expect(plain(repairLine(FUNNEL_REPAIRS['vanguards-doomsday']))).toBe(
      'Отремонтирован: блоки 5, 14 (полоса)',
    );
    // Номер блока — из записи судьи, если `block` нет; виды — без повторов, по порядку.
    expect(
      plain(
        repairBlocksText([
          { block: null, entry: 'block-5-meme', target: 'meme', kind: 'smeared', why: null },
          { block: 5, entry: 'block-5', target: 'shot', kind: 'thin_strip', why: null },
        ]),
      ),
    ).toBe('блок 5 (смаз, полоса)');
    expect(repairLine(repair({ blocks: [] }))).toBe('Отремонтирован');
  });

  it('«Ремонт не удался — отказ»: причина по-русски — в скобках, английская — под «подробнее»', () => {
    expect(plain(repairLine(FUNNEL_REPAIRS.delver))).toBe(
      'Ремонт не удался — отказ (замены для блока 9 в пуле не нашлось)',
    );
    const en = repair({ outcome: 'repair_failed', reason: 'render_failed' });
    expect(repairLine(en)).toBe('Ремонт не удался — отказ');
    expect(repairDetails(en)).toContain('причина: render_failed');
  });

  it('старый батч: ремонта нет — ни строки, ни подробностей, ни сводки', () => {
    expect(repairLine(null)).toBeNull();
    expect(repairLine(undefined)).toBeNull();
    expect(repairLine(repair({ outcome: null }))).toBeNull();
    expect(repairDetails(null)).toEqual([]);
    expect(repairsText(null)).toBeNull();
    expect(repairsText({ repaired: 0, repair_failed: 0, videos: 0 })).toBeNull();
    expect(plain(repairsText({ repaired: 1, repair_failed: 1, videos: 2 }))).toBe(
      'удался 1, не удался 1',
    );
  });

  it('подробности: записи судьи, коды до и после, итог монтажа', () => {
    expect(repairDetails(FUNNEL_REPAIRS['vanguards-doomsday'])).toEqual([
      'ремонт: repaired, монтаж: rendered',
      'block-5 (shot): thin_strip — thin black strip along the top edge',
      'block-14 (shot): thin_strip — letterbox strip at the bottom',
      'до ремонта: reject, judge_footage_defect, кадры 0.52',
      'после ремонта: pass, кадры 0.88',
      'перерисованы блоки: 5, 14',
    ]);
  });
});

describe('добор тем ниже шорт-листа (CC-0172)', () => {
  it('сводка батча: подано N, поисков M; добора не было — null', () => {
    expect(plain(refillText({ record: 'x', rounds: [], admitted: 2, searches: 7 }))).toBe(
      'подано 2, поисков 7',
    );
    expect(refillText(null)).toBeNull();
    expect(refillText(undefined)).toBeNull();
  });

  it('CC-0175: записи раундов нет и ничего не подано — сводки нет', () => {
    expect(refillText({ record: 'x', rounds: [], admitted: 0, searches: 0 })).toBeNull();
    expect(refillText({ record: 'x', rounds: [], admitted: 0, searches: 3 })).toBeNull();
    expect(plain(refillText({ record: 'x', rounds: [], admitted: 1, searches: 0 }))).toBe(
      'подано 1, поисков 0',
    );
  });

  it('CC-0175: исход раунда — строка фабрики outcome_ru, её нет — свой перевод кода', () => {
    expect(roundOutcomeText({ outcome: 'search_quota', outcome_ru: 'квота кончилась' })).toBe(
      'квота кончилась',
    );
    expect(roundOutcomeText({ outcome: 'search_quota', outcome_ru: null })).toBe(
      'не хватило квоты поиска',
    );
    expect(roundOutcomeText({ outcome: 'search_quota', outcome_ru: '  ' })).toBe(
      'не хватило квоты поиска',
    );
    expect(roundOutcomeText({ outcome: 'search_quota' })).toBe('не хватило квоты поиска');
    expect(roundOutcomeText({ outcome: 'brand_new', outcome_ru: null })).toBe('brand_new');
    expect(roundOutcomeText({ outcome: null, outcome_ru: null })).toBe('итога нет');
  });

  it('добрана — пометка, а не строка; отказ — с причиной словами фабрики', () => {
    expect(refillAdmitted(refill({ outcome: 'admitted', admitted: true }))).toBe(true);
    expect(refillAdmitted(refill({ outcome: 'promoted', promoted: true }))).toBe(true);
    expect(refillLine(refill({ outcome: 'admitted', admitted: true }))).toBeNull();
    expect(
      refillLine(
        refill({
          refused_by: 'compliance',
          reason: 'rights not confirmed',
          compliance: {
            outcome: 'refused',
            verdict: 'refuse',
            reason_code: 'rights_unconfirmed',
            reason_ru: 'права на трейлер не подтверждены',
            reason: null,
          },
        }),
      ),
    ).toBe('добор: отказ (проверка темы) — права на трейлер не подтверждены');
    // Без русских слов — код не на виду.
    expect(refillLine(refill({ refused_by: 'trend_hunter', reason: 'sieve: thin' }))).toBe(
      'добор: отказ (трендхантер) — причина без описания',
    );
    expect(refillLine(refill({ outcome: 'quota', reason: 'quota left: 0' }))).toBe(
      'добор: не хватило квоты поиска',
    );
    expect(refillLine(null)).toBeNull();
    expect(refillAdmitted(null)).toBe(false);
  });

  it('раунд одной строкой: что подано, сколько нужно, поиски', () => {
    const r: RefillRound = {
      round: 'first',
      at: null,
      at_code: null,
      need: 1,
      need_why: 'шорт-лист дал 2 темы из 3',
      outcome: 'admitted',
      why: null,
      queue: [],
      judged: [],
      footage: [],
      admitted: ['partition-s3'],
      searches: 3,
      spent_after: null,
      budget_line: null,
    };
    const title = (id: string) => (id === 'partition-s3' ? 'Partition' : id);
    expect(plain(roundLine(r, 0, title))).toBe(
      'первый раунд: темы поданы — Partition; нужно 1 — шорт-лист дал 2 темы из 3; 3 поиска',
    );
    expect(
      plain(
        roundLine(
          {
            ...r,
            round: null,
            outcome: 'search_quota',
            why: 'квоты не хватило',
            admitted: [],
            need: null,
            searches: 1,
          },
          1,
          title,
        ),
      ),
    ).toBe('раунд 2: не хватило квоты поиска (квоты не хватило); 1 поиск');
    expect(
      plain(
        roundLine(
          { ...r, outcome: 'search_quota', outcome_ru: 'квота на сегодня кончилась', admitted: [] },
          0,
          title,
        ),
      ),
    ).toBe(
      'первый раунд: квота на сегодня кончилась; нужно 1 — шорт-лист дал 2 темы из 3; 3 поиска',
    );
  });
});
