// CC-0113: причины словами фабрики, без своих подписей кодов воронки.
import {
  codeWithWords,
  factFailureGroups,
  factFailureWords,
  hasReasonWords,
  reasonOf,
  reasonWords,
  undescribedTail,
} from './reasonRu';

describe('CC-0113: причина словами фабрики', () => {
  it('reason_ru — первым; русское уточнение — после «—»; английское — нет', () => {
    expect(
      reasonWords({
        reason_code: 'pool_too_thin',
        reason_ru: 'пул тоньше сценария',
        reason: 'пригодных кадров меньше порога: 7 из 12',
      }),
    ).toBe('пул тоньше сценария — пригодных кадров меньше порога: 7 из 12');
    expect(
      reasonWords({ reason_code: 'no_fact', reason_ru: 'нет факта.', reason: 'no fact found' }),
    ).toBe('нет факта');
    expect(reasonWords({ reason_code: 'x', reason_ru: 'одно', reason: 'Одно' })).toBe('одно');
  });

  it('без строки фабрики — уточнение, без него — «причина без описания»; пусто — null', () => {
    expect(reasonWords({ reason_code: 'batch_full', reason_ru: null, reason: 'батч набран' })).toBe(
      'батч набран',
    );
    expect(reasonWords({ reason_code: 'licence_refused', reason_ru: null, reason: 'bad' })).toBe(
      'причина без описания',
    );
    expect(reasonWords({ reason_code: null, reason_ru: null, reason: null })).toBeNull();
    expect(reasonWords(null)).toBeNull();
  });

  it('карта «код → строка»: null и нет кода — «причина без описания»', () => {
    const map = { pool_too_thin: 'пул тоньше сценария', event_footage_short: null };
    expect(reasonOf(map, 'pool_too_thin')).toBe('пул тоньше сценария');
    expect(reasonOf(map, 'event_footage_short')).toBe('причина без описания');
    expect(reasonOf(map, 'never_seen')).toBe('причина без описания');
    expect(reasonOf(undefined, 'no_source')).toBe('причина без описания');
    expect(hasReasonWords(map, 'pool_too_thin')).toBe(true);
    expect(hasReasonWords(map, 'event_footage_short')).toBe(false);
  });

  it('под «подробнее» — код и строка фабрики в скобках', () => {
    expect(codeWithWords({ reason_code: 'no_fact', reason_ru: 'нет факта' })).toBe(
      'no_fact (нет факта)',
    );
    expect(codeWithWords({ reason_code: 'low_signal', reason_ru: null })).toBe('low_signal');
    expect(codeWithWords({ reason_code: null })).toBeNull();
  });
});

describe('CC-0119: отказы кандидата факта словами фабрики', () => {
  it('группы: расшифрованные по одной, без слов — одной группой кодов', () => {
    expect(
      factFailureGroups({
        failures: ['no_specifics', 'tier', 'x'],
        failures_ru: [
          { code: 'no_specifics', ru: 'нет конкретики' },
          { code: 'tier', ru: null },
          { code: 'x', ru: null },
        ],
      }),
    ).toEqual({
      described: [{ code: 'no_specifics', words: 'нет конкретики' }],
      undescribed: ['tier', 'x'],
    });
    expect(undescribedTail(1)).toBe('и ещё одна причина без описания');
    expect(undescribedTail(3)).toBe('и ещё 3 без описания');
  });

  it('ru — по порядку кодов; null и нет слов — «причина без описания»', () => {
    expect(
      factFailureWords({
        failures: ['cut_short', 'tier'],
        failures_ru: [
          { code: 'cut_short', ru: 'предложение обрезано.' },
          { code: 'tier', ru: null },
        ],
      }),
    ).toEqual([
      { code: 'cut_short', words: 'предложение обрезано' },
      { code: 'tier', words: 'причина без описания' },
    ]);
  });

  it('старый ответ без failures_ru и сбитый порядок — по коду', () => {
    expect(factFailureWords({ failures: ['no_specifics'] })).toEqual([
      { code: 'no_specifics', words: 'причина без описания' },
    ]);
    expect(
      factFailureWords({
        failures: ['a', 'b'],
        failures_ru: [
          { code: 'b', ru: 'бэ' },
          { code: 'a', ru: 'а' },
        ],
      }).map((r) => r.words),
    ).toEqual(['а', 'бэ']);
    expect(factFailureWords({ failures: [], failures_ru: [] })).toEqual([]);
    expect(
      factFailureWords({
        failures: ['no_specifics'],
        failures_ru: [{ code: 'no_specifics', ru: 'нет конкретики - похоже на мнение' }],
      })[0]!.words,
    ).toBe('нет конкретики — похоже на мнение');
  });
});

/** Коды проверки факта фабрики (`fact_rule.FAIL_CODES`, `fact_rule_ru.FAIL_CODES_RU`, CF-0752). */
const FACT_RULE_CODES = [
  'no_text',
  'no_url',
  'source_banned',
  'source_unlisted',
  'tier2_without_primary',
  'interview_without_quote',
  'no_specifics',
  'retells_news',
  'person_not_major_outlet',
  'person_unattributed',
  'cut_short',
  // старый код до FAIL_CODES — у фабрики для него слов нет
  'tier',
];

/** Коды воронки фабрики (`funnel.REASONS_RU`, CF-0714, 43 кода) и коды нехватки футажа. */
const FUNNEL_CODES = [
  'already_published',
  'below_shortlist',
  'claim_unsupported',
  'compliance_review',
  'compliance_review_hold',
  'contribution_blocked',
  'fetch_failed',
  'footage_evidence_quota',
  'frame_judge_failed',
  'held_back',
  'index_failed',
  'judge_footage_defect',
  'judge_foreign_core',
  'kept_on_own_graphics',
  'needs_you',
  'no_fact',
  'no_second_source',
  'no_source',
  'no_support_text',
  'not_built',
  'not_screened',
  'nothing_to_check',
  'pattern_undeliverable',
  'person_without_work',
  'plan_unassembled',
  'plot_claim_failed',
  'pool_too_thin',
  'qc_failed',
  'reserve_exhausted',
  'reserve_substituted',
  'reserve_unused',
  'rights_exclusion',
  'scale_unsupported',
  'score_below_threshold',
  'search_quota_exhausted',
  'source_burned_text',
  'source_foreign',
  'source_host_unlisted',
  'source_too_long',
  'story_claim_failed',
  'thin_scene',
  'unexplained',
  'video_too_short',
  // footage_wanted.REASONS — их слова тоже приходят от фабрики (`reasons_ru`)
  'anchor_no_picture',
  'anchor_short',
  'frame_contradicts',
  'frame_foreign',
  'visual_claim_uncovered',
  'event_footage_short',
];

/** Бывшие свои подписи центра (карта `REASON` stats/format.ts и `KIND` videos/refusal.ts). */
const OLD_LABELS = [
  'монтажу не хватило кадра для главного героя',
  'кадров главного героя хватило не на весь блок',
  'в кадре не то, что называет диктор',
  'блок закрыт чужим кадром',
  'сценарий показывает то, чего нет в пуле',
  'пул тоньше сценария',
  'всё из одного источника',
  'мало кадров самого события',
  'для темы не нашлось футажа',
  'источник исключён после отказа',
  'не прошёл проверку качества',
  'нет второго источника для факта',
];

/** Исходники центра текстом — без подставного API (src/mocks — его ответы), тестов и сгенерированного. */
const SOURCES = import.meta.glob<string>(
  [
    '../**/*.ts',
    '../**/*.tsx',
    '!../**/*.test.ts',
    '!../**/*.test.tsx',
    '!../mocks/**',
    '!./*.gen.ts',
  ],
  { query: '?raw', import: 'default', eager: true },
);

describe('CC-0113: своих подписей кодов воронки в src/ нет', () => {
  const files = Object.entries(SOURCES).map(([p, text]) => ({ p, text }));

  it('исходники найдены', () => {
    expect(files.some((f) => f.p.endsWith('reasonRu.ts'))).toBe(true);
  });

  // `footage_indexer.no_second_source` — имя правила воротец (gateWords), не код воронки.
  it('ни один код воронки не сопоставлен русской строке', () => {
    const re = new RegExp(
      `(?<![.\\w])(${FUNNEL_CODES.join('|')})\\b['"\`]?\\s*:\\s*['"\`][^'"\`\\n]*[а-яё]`,
      'i',
    );
    const hits = files.filter((f) => re.test(f.text)).map((f) => f.p);
    expect(hits).toEqual([]);
  });

  it('ни один код проверки факта (fact_rule) не сопоставлен русской строке', () => {
    const re = new RegExp(
      `(?<![.\\w])(${FACT_RULE_CODES.join('|')})\\b['"\`]?\\s*:\\s*['"\`][^'"\`\\n]*[а-яё]`,
      'gi',
    );
    // `no_text` у напоминаний (notify.ts) — свой код отказа API напоминаний, не fact_rule.
    const own = new Set(['./notify.ts:no_text']);
    const hits = files
      .flatMap((f) => [...f.text.matchAll(re)].map((m) => `${f.p}:${m[1]}`))
      .filter((h) => !own.has(h));
    expect(hits).toEqual([]);
    expect(files.some((f) => /FAIL_CODES_RU|FACT_FAIL|factRuleRu/.test(f.text))).toBe(false);
  });

  it('старых подписей карты REASON нет', () => {
    const hits = files.flatMap((f) =>
      OLD_LABELS.filter((l) => f.text.includes(l)).map((l) => `${f.p}: ${l}`),
    );
    expect(hits).toEqual([]);
    expect(files.some((f) => /export const REASON\b|reasonText/.test(f.text))).toBe(false);
  });
});
