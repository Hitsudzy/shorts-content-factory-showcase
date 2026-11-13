// Источники фактов по строкам (CC-0129): документ → строки правки → документ без потерь
// (неизвестные поля строки, `ai_policy`, `ai_output_terms`, прочие ключи файла); проверки словами
// по `fact_rule.validate_sources` и `channel_data.policy_errors_of`; строки фабрики — словами.
import {
  ANY_HOST_FIELDS,
  factDoc,
  factLineText,
  factProblems,
  factRowsOf,
  newOutlet,
  OUTLET_FIELDS,
} from './listSchemas';
import { itemOf, itemsOf, rowOf, type Item, type Row } from './rows';

const policy = (verdict = 'allowed', anyAgent = true) => ({
  verdict,
  checked_on: '2026-10-08',
  checks: [{ robots_url: 'https://x.org/robots.txt', any_agent: anyAgent }],
  terms_url: null,
});

const DOC = {
  version: 'CF-0561',
  note: 'заметка файла',
  kinds: ['measurement', 'other'],
  attributed_kinds: ['measurement'],
  tiers: {
    '1': [
      {
        id: 'nasa',
        kind: 'agency',
        hosts: ['nasa.gov', 'science.nasa.gov'],
        major_outlet: true,
        use: 'cite_only',
        note: null,
        ai_policy: policy('forbidden'),
        ai_output_terms: {
          terms_url: 'https://www.nasa.gov/terms',
          forbidden: [{ id: 'according', phrase: 'according to NASA', pattern: 'x', why: 'y' }],
        },
      },
      {
        id: 'arxiv',
        kind: 'preprint',
        hosts: ['arxiv.org'],
        major_outlet: false,
        use: 'cite_only',
        preprint: true,
        properties: { P1: 'x' },
        ai_policy: policy(),
      },
    ],
    '2': [
      {
        id: 'wiki',
        kind: 'encyclopedia',
        hosts: ['wikipedia.org'],
        use: 'read_text',
        ai_policy: policy(),
      },
    ],
  },
  any_host: [
    { source_type: 'creator_interview', tier: 1, requires: 'quote', note: 'интервью' },
    { source_type: 'studio_press', tier: 1, requires: null, note: 'пресса' },
  ],
  do_not_take: [{ id: 'reddit', hosts: ['reddit.com'] }],
};

function edit(doc: Record<string, unknown>) {
  const r = factRowsOf(doc);
  return {
    tier1: itemsOf(r.tier1, OUTLET_FIELDS),
    tier2: itemsOf(r.tier2, OUTLET_FIELDS),
    anyHost: itemsOf(r.anyHost, ANY_HOST_FIELDS),
    kinds: r.kinds,
  };
}

const rowsOf = (e: ReturnType<typeof edit>) => ({
  tier1: e.tier1.map((x) => rowOf(x, OUTLET_FIELDS)),
  tier2: e.tier2.map((x) => rowOf(x, OUTLET_FIELDS)),
  anyHost: e.anyHost.map((x) => rowOf(x, ANY_HOST_FIELDS)),
  kinds: e.kinds,
});

const set = (x: Item, key: string, v: string): Item => ({ ...x, text: { ...x.text, [key]: v } });

describe('источники фактов по строкам (CC-0129)', () => {
  it('не тронутый документ уходит как был: ai_policy, неизвестные поля, null, прочие ключи', () => {
    const e = edit(DOC);
    expect(e.tier1[0]!.text.kind).toBe('космическое или научное агентство');
    expect(factDoc(DOC, rowsOf(e))).toEqual(DOC);
  });

  it('правка полей: ai_policy и неизвестные поля строки остаются как есть', () => {
    const e = edit(DOC);
    e.tier1[1] = set(set(e.tier1[1]!, 'hosts', 'arxiv.org, export.arxiv.org'), 'note', 'препринты');
    e.tier2[0] = set(e.tier2[0]!, 'use', 'cite_only');
    e.anyHost[1] = set(e.anyHost[1]!, 'tier', '2');
    const out = factDoc(DOC, rowsOf(e)) as typeof DOC;
    expect(out.tiers['1'][1]).toEqual({
      ...DOC.tiers['1'][1],
      hosts: ['arxiv.org', 'export.arxiv.org'],
      note: 'препринты',
    });
    expect(out.tiers['1'][0]).toEqual(DOC.tiers['1'][0]);
    expect(out.tiers['2'][0]).toEqual({ ...DOC.tiers['2'][0], use: 'cite_only' });
    expect(out.any_host[1]).toEqual({ ...DOC.any_host[1], tier: 2 });
    expect(out.do_not_take).toEqual(DOC.do_not_take);
  });

  it('новый источник без проверки robots.txt — фабрика его не примет', () => {
    const e = edit(DOC);
    let fresh = itemOf(newOutlet(), OUTLET_FIELDS);
    expect(
      factProblems({ ...rowsOf(e), tier1: [rowOf(fresh, OUTLET_FIELDS)] }, DOC).tier1[0],
    ).toEqual([
      'Короткое имя — латиница в нижнем регистре, цифры, «-» и «_»',
      'Впишите хотя бы один сайт',
    ]);
    fresh = set(set(fresh, 'id', 'esa'), 'hosts', 'esa.int');
    const row = rowOf(fresh, OUTLET_FIELDS);
    // Сайт вписан — теперь и о проверке robots.txt.
    expect(factProblems({ ...rowsOf(e), tier1: [row] }, DOC).tier1[0]).toEqual([
      'Сайт ещё не проверен на правила для ИИ-ботов — без этой проверки фабрика источник не примет',
    ]);
    expect(row).toEqual({ id: 'esa', hosts: ['esa.int'], use: 'cite_only', major_outlet: false });
  });

  it('проверки словами: сайт дважды, в «Не брать», закрыт для ИИ, препринт-крупное, виды', () => {
    const rows = rowsOf(edit(DOC));
    const bad: Row[] = [
      { ...rows.tier1[0]!, hosts: ['wikipedia.org', 'https://x.org'] },
      { ...rows.tier1[1]!, major_outlet: true, hosts: ['reddit.com'] },
    ];
    const p = factProblems(
      {
        ...rows,
        tier1: bad,
        tier2: [{ ...rows.tier2[0]!, ai_policy: policy('forbidden') }],
        anyHost: [{ tier: 1 }],
        kinds: ['other'],
      },
      DOC,
    );
    expect(p.tier1[0]).toContain(
      'Сайт «https://x.org» — строчными, без https:// и пути, например nasa.gov',
    );
    expect(p.tier1[1]).toEqual([
      'Сайт «reddit.com» — в списке «Не брать никогда»',
      'Сервер препринтов не может быть крупным изданием: эти тексты никто не рецензировал',
    ]);
    expect(p.tier2[0]).toEqual([
      'Сайт «wikipedia.org» уже есть — в основных изданиях, запись 1',
      'Сайт закрыт для ИИ-ботов — его текст читать нельзя, выберите «только ссылаться»',
    ]);
    expect(p.anyHost[0]).toEqual(['Выберите вид источника']);
    expect(p.doc).toEqual([
      'Вид «измерение» убрать нельзя: по нему фабрика подаёт факт как слова его владельца',
    ]);
    const empty = factProblems({ tier1: [], tier2: [], anyHost: [], kinds: [] }, null);
    expect(empty.doc).toEqual([
      'В основных изданиях нужен хотя бы один источник',
      'Нужен хотя бы один вид фактов — иначе фабрика не знает, о чём факты канала',
    ]);
  });

  it('robots.txt закрывает сайт всем — читать текст нельзя', () => {
    const rows = rowsOf(edit(DOC));
    const p = factProblems(
      { ...rows, tier2: [{ ...rows.tier2[0]!, ai_policy: policy('allowed', false) }] },
      DOC,
    );
    expect(p.tier2[0]).toEqual([
      'Сайт закрыт для всех роботов — его текст читать нельзя, выберите «только ссылаться»',
    ]);
  });

  it('пустой документ: ярусы и виды появляются, лишних ключей нет', () => {
    expect(
      factDoc(null, { tier1: [{ id: 'a' }], tier2: [], anyHost: [], kinds: ['other'] }),
    ).toEqual({
      tiers: { '1': [{ id: 'a' }] },
      kinds: ['other'],
    });
  });

  it('строки проверки фабрики — словами, без кодов', () => {
    const name = (id: string) => (id === 'nasa' ? 'nasa.gov' : 'источник');
    expect(
      factLineText(
        'example-science sources.rss.feeds[example.org]: robots.txt closes it to every agent (`*`) - it is not read at all',
        name,
      ),
    ).toBe(
      'Сайт ленты новостей example.org закрыт для всех роботов, а канал её читает — уберите ленту в настройках канала, иначе фабрика не примет список',
    );
    expect(
      factLineText(
        'example-science fact-sources tiers.1[nasa]: `use` read_text but its robots.txt verdict for AI bots is forbidden',
        name,
      ),
    ).toBe(
      'Основные издания, nasa.gov: сайт закрыт для ИИ-ботов — его текст читать нельзя, только ссылаться',
    );
    expect(factLineText("host 'nasa.gov' is listed twice (1 and 2)", name)).toBe(
      'Сайт «nasa.gov» указан дважды',
    );
    expect(factLineText('something new', name)).toBeNull();
  });
});
