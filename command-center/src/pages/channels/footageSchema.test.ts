// Происхождение футажа по строкам (CC-0130): документ → строки правки → документ без потерь
// (неизвестные поля строки и файла, вложенная `attribution`, прочие способы `found_by`); проверки
// словами по `footage_licence.footage_origin_errors` и правилу `official_channels`, по одной на
// строку; строки фабрики — словами.
import {
  ACCEPTED_FIELDS,
  channelFields,
  footageDoc,
  footageLineText,
  footageProblems,
  footageRowsOf,
  foundByText,
  licenceName,
  newChannel,
  newOrigin,
  officialFields,
  originFields,
  REFUSED_FIELDS,
  withOnScreen,
  type FootageRows,
} from './listSchemas';
import { itemOf, itemsOf, rowOf, type Item, type Row } from './rows';

const CH = 'UCexample000000000000010';

const SCIENCE = {
  _what: 'откуда футаж канала — заметка файла',
  attribution: { where: 'description' },
  licences: {
    accepted: [
      {
        id: 'public_domain',
        what: 'общественное достояние США',
        attribution: 'requested',
        share_alike: false,
        matches: ['public domain', 'pd-usgov'],
      },
      {
        id: 'cc_by',
        attribution: 'required',
        share_alike: false,
        matches: ['cc by'],
        license_url: 'https://creativecommons.org/licenses/by/4.0/',
      },
    ],
    refused: [{ id: 'noncommercial', what: 'NC', tokens: ['nc'] }],
    note: 'ключ блока лицензий',
  },
  footage_origins: [
    {
      id: 'nasa',
      who: 'NASA (штаб-квартира и центры)',
      licence: 'public_domain',
      terms_url: 'https://www.nasa.gov/nasa-brand-center/images-and-media/',
      quote: 'не охраняется авторским правом в США',
      found_by: [
        { how: 'youtube_channels', ref: 'official_channels pattern `nasa`', works_now: true },
        { how: 'archive_api', endpoint: 'https://images-api.nasa.gov/search', works_now: false },
      ],
      attribution: {
        required: false,
        requested: true,
        credit: 'NASA',
        where: 'description',
        on_screen: false,
      },
      caveats: ['Эмблема NASA — не общественное достояние.', 'Без намёка на одобрение NASA.'],
    },
  ],
  official_channels: [
    {
      pattern: 'nasa',
      what: 'космическое агентство США',
      origin: 'nasa',
      owners: ['nasa'],
      seen_as: 'NASA; NASA Science',
      channels: [{ id: CH, title: 'NASA', handle: '@NASA', resolved_by: 'страница канала' }],
    },
  ],
};

/** Как редактор: строки → документ (официальные каналы — с их каналами). */
function roundTrip(doc: Record<string, unknown> | null, edit?: (rows: FootageRows) => void) {
  const start = footageRowsOf(doc);
  const acc = itemsOf(start.accepted, ACCEPTED_FIELDS).map((x) => rowOf(x, ACCEPTED_FIELDS));
  const ref = itemsOf(start.refused, REFUSED_FIELDS).map((x) => rowOf(x, REFUSED_FIELDS));
  const of = originFields(acc);
  const origins = itemsOf(start.origins, of).map((x) => withOnScreen(rowOf(x, of)));
  const ofs = officialFields(start.science, origins);
  const cf = channelFields(start.science);
  const official = itemsOf(start.official, ofs).map((x) => {
    const r = rowOf(x, ofs);
    if (!Array.isArray(x.row.channels)) return r;
    return { ...r, channels: itemsOf(x.row.channels, cf).map((c) => rowOf(c, cf)) };
  });
  const rows: FootageRows = {
    science: start.science,
    official,
    origins,
    accepted: acc,
    refused: ref,
  };
  edit?.(rows);
  return { rows, doc: footageDoc(doc, rows) };
}

describe('происхождение футажа по строкам (CC-0130)', () => {
  it('Science без правки — документ как был: вложенная attribution, found_by, чужие поля', () => {
    expect(roundTrip(SCIENCE).doc).toEqual(SCIENCE);
  });

  it('«как фабрика узнаёт» — варианты через запятую, в файл — через «|» без потерь', () => {
    const ofs = officialFields(true, SCIENCE.footage_origins);
    const row = { pattern: 'european southern observatory|eso', origin: 'nasa', channels: [] };
    const item = itemOf(row, ofs);
    expect(item.text.pattern).toBe('european southern observatory, eso');
    expect(rowOf(item, ofs)).toEqual(row);
    expect(rowOf({ ...item, text: { ...item.text, pattern: 'eso, эсо' } }, ofs)).toEqual({
      ...row,
      pattern: 'eso|эсо',
    });
  });

  it('Reel: только official_channels — другие ключи не появляются; owners целы', () => {
    const reel = {
      _task: 'заметка',
      official_channels: [
        {
          pattern: 'examplestream',
          what: 'стример',
          seen_as: 'ExampleStream; ExampleStream Brasil',
          owners: ['examplestream'],
          channels: [{ id: 'UCexample000000000000030', title: 'ExampleStream', resolved_by: 'x' }],
        },
      ],
    };
    const { rows, doc } = roundTrip(reel);
    expect(rows.science).toBe(false);
    expect(doc).toEqual(reel);
    expect(footageProblems(rows).official).toEqual([[]]);
  });

  it('правка вложенной подписи: соседи в attribution целы; «где» ставит on_screen сам', () => {
    const start = footageRowsOf(SCIENCE);
    const of = originFields(start.accepted as Row[]);
    const item = itemsOf(start.origins, of)[0]!;
    const edited: Item = {
      ...item,
      text: {
        ...item.text,
        'attribution.credit': 'NASA/JPL',
        'attribution.where': 'description+on_screen',
      },
    };
    expect(withOnScreen(rowOf(edited, of))).toEqual({
      ...SCIENCE.footage_origins[0],
      attribution: {
        required: false,
        requested: true,
        credit: 'NASA/JPL',
        where: 'description+on_screen',
        on_screen: true,
      },
    });
  });

  it('новый источник: способ и флажок «работает» — в первом found_by', () => {
    const of = originFields(SCIENCE.licences.accepted);
    const item = itemOf(newOrigin(), of);
    const row = withOnScreen(
      rowOf(
        {
          ...item,
          text: {
            ...item.text,
            who: 'ESO',
            id: 'eso',
            licence: 'cc_by',
            terms_url: 'https://www.eso.org/public/copyright/',
            'found_by.0.how': 'archive_page',
            'found_by.0.works_now': '1',
            'attribution.credit': 'ESO',
          },
        },
        of,
      ),
    );
    expect(row).toEqual({
      who: 'ESO',
      id: 'eso',
      licence: 'cc_by',
      terms_url: 'https://www.eso.org/public/copyright/',
      found_by: [{ how: 'archive_page', works_now: true }],
      attribution: { credit: 'ESO', where: 'description', on_screen: false },
    });
  });

  it('проверки: одна на строку; пустой код канала — «впишите», а не «не тот вид»', () => {
    const { rows } = roundTrip(SCIENCE, (r) => {
      r.official[0]!.channels = [
        { title: 'Пустой', resolved_by: 'x' },
        { id: 'UC123', handle: '@x', resolved_by: 'x' },
        { id: CH, resolved_by: 'x' },
        { ...newChannel(), id: 'UCexample000000000000060', handle: '@NASAJPL' },
      ];
      r.origins.push({ id: 'Плохое имя', licence: 'cc_by_nc' });
      r.accepted.push({ id: 'cc_by', attribution: 'x' });
      r.refused.push({});
    });
    const p = footageProblems(rows);
    expect(p.channels[0]).toEqual([
      ['Впишите код канала'],
      ['Код канала — 24 знака, начинается с UC'],
      ['Впишите @имя канала'],
      [],
    ]);
    expect(p.origins[1]).toEqual(['Короткое имя — латиница в нижнем регистре, цифры, «-» и «_»']);
    expect(p.accepted[2]).toEqual(['Эта лицензия уже есть в списке']);
    expect(p.refused[1]).toEqual(['Впишите, какую лицензию не берём']);
  });

  it('проверки источника по порядку: лицензия, условия, способ, подпись', () => {
    const base = {
      id: 'x',
      licence: 'cc_by',
      terms_url: 'https://x.org',
      attribution: { credit: 'X', where: 'description', on_screen: false },
    };
    const check = (o: Row) =>
      footageProblems({
        science: true,
        official: [],
        origins: [o],
        accepted: SCIENCE.licences.accepted,
        refused: [],
      }).origins[0];
    expect(check({ ...base, licence: 'press_kit', found_by: [] })).toEqual([
      'Этой лицензии нет среди тех, что канал берёт',
    ]);
    expect(check({ ...base, terms_url: 'http://x.org' })).toEqual([
      'Страница с условиями — полностью, с https://',
    ]);
    expect(check({ ...base, found_by: [{ works_now: false }] })).toEqual([
      'Выберите, как фабрика находит футаж',
    ]);
    expect(
      check({ ...base, licence: 'per_file', found_by: [{ how: 'drawn', works_now: true }] }),
    ).toEqual(['«Рисует сама» — способ только своей графики, и у неё он единственный']);
    expect(
      check({ ...base, found_by: [{ how: 'archive_api', works_now: true }], attribution: {} }),
    ).toEqual(['Впишите, как подписывать автора']);
    expect(
      check({
        ...base,
        licence: 'youtube_upload',
        terms_url: null,
        found_by: [{ how: 'youtube_search', works_now: true }],
      }),
    ).toEqual(['Этой лицензии нет среди тех, что канал берёт']);
  });

  it('Science без лицензий и источников — словами про список целиком', () => {
    const p = footageProblems({
      science: true,
      official: [],
      origins: [],
      accepted: [],
      refused: [],
    });
    expect(p.doc).toEqual([
      'Нужна хотя бы одна лицензия, которую канал берёт',
      'Нужен хотя бы один источник футажа',
    ]);
  });

  it('названия лицензий по-русски; код остаётся значением', () => {
    expect(licenceName('cc_by')).toBe('CC BY (с указанием автора)');
    expect(licenceName('public_domain')).toBe('общественное достояние');
    expect(licenceName('press', [{ id: 'press', name: 'Пресс-кит' }])).toBe('Пресс-кит');
    expect(licenceName('press', [{ id: 'press' }])).toBe('лицензия 1 из списка «берём»');
    const item = itemOf({ id: 'cc_by_sa', matches: ['cc by-sa'] }, ACCEPTED_FIELDS);
    expect(item.text.id).toBe('CC BY-SA (с указанием автора, под той же лицензией)');
    expect(rowOf(item, ACCEPTED_FIELDS).id).toBe('cc_by_sa');
    expect(foundByText(SCIENCE.footage_origins[0]!)).toBe(
      'Ещё способ: API архива (пока не работает) — он правится в файле.',
    );
  });

  it('строки фабрики словами; незнакомая — null', () => {
    const n = {
      origin: (id: string) => (id === 'nasa' ? 'NASA' : 'источник'),
      licence: (id: string) => licenceName(id),
      official: (p: string) => (p === 'nasa' ? 'NASA' : p),
    };
    const say = (l: string) => footageLineText(l, n);
    expect(
      say(
        "footage_origins[0] (nasa): licence 'press_kit' is neither an accepted licence nor 'per_file'",
      ),
    ).toBe('Источник «NASA»: лицензии нет среди тех, что канал берёт');
    expect(
      say('footage_origins[0] (nasa): no https `terms_url` - the page its licence was read on'),
    ).toBe('Источник «NASA»: нет страницы с условиями (https://…)');
    expect(say('footage_origins[0] (nasa): found_by[1] does not say `works_now`')).toBe(
      'Источник «NASA»: у способа 2 не отмечено, работает ли он',
    );
    expect(say("official_channels[0] (nasa) channels[1]: 'UC1' is not a YouTube channel id")).toBe(
      'Правообладатель «NASA», канал 2: это не код канала YouTube (24 знака, начинается с UC)',
    );
    expect(
      say('official_channels[2] (examplestream): channels[0].id None is not a YouTube channel id'),
    ).toBe(
      'Правообладатель «examplestream», канал 1: это не код канала YouTube (24 знака, начинается с UC)',
    );
    expect(say('official_channels[1] (None): no `pattern`')).toBe(
      'Правообладатель 2: не вписано, как фабрика его узнаёт',
    );
    expect(say(`official_channels[0] (nasa) channels[0]: ${CH} listed twice`)).toBe(
      'Правообладатель «NASA», канал 1: этот канал уже есть в списке',
    );
    expect(
      say("official_channels[0] (nasa): role 'x' is not one of ('footage', 'proof_quote')"),
    ).toBe('Правообладатель «NASA»: роль канала записана не так');
    expect(say("licences.accepted[1]: id 'cc_by' twice")).toBe(
      'Лицензия «CC BY (с указанием автора)» указана дважды',
    );
    expect(say('licences.refused[0]: needs `id` and `what`')).toBe(
      'Отклонённая лицензия 1: нужно, какая и почему не берём',
    );
    expect(say('no `official_channels` list')).toBe('Нет списка официальных каналов');
    expect(say('capture_hosts[0]: something new')).toBeNull();
  });
});
