// Подставные банки мемов (CC-0024 фабрики, договор 0.24.0): общий банк по умолчанию (`memes` —
// у ExampleFilm и ExampleScience он один) и свой банк ExampleTech (`memes-example-tech`, 35
// записей на разборе, как в жизни). Описания и метки — по-английски, как у фабрики. Данные
// выдуманные, форма — `index.json` банка и `_desk/decisions.json` стола.

/** Запись `index.json` банка — как её держит фабрика. */
export type IndexEntry = {
  id: string;
  file: string;
  description: string;
  tags: string[];
  source_url?: string;
  notes?: string;
  review?: 'pending';
  cutout?: boolean;
  cutout_asset?: Record<string, unknown>;
  clip?: { start_s: number; end_s: number };
};

/** Отметка черновика стола: `{v, cut, note}` и, если её ставил центр, кто и когда. */
export type DraftMark = {
  v?: 'keep' | 'drop';
  cut?: boolean;
  note?: string;
  marked_by?: string;
  marked_at?: string;
  via?: string;
};

export type BankSeed = {
  folder: string;
  entries: IndexEntry[];
  /** `null` — черновика нет (файла `_desk/decisions.json` нет). */
  draft: Record<string, DraftMark> | null;
  /** Пустые полосы подписи (CF-0534), как их мерит `status`. */
  /** `phrase` — словами фабрики по-английски, `phrase_ru` — по-русски (CF-0762). */
  bands: { id: string; phrase: string; phrase_ru?: string | null }[];
  /** Мем → намерение, образцом которого он служит (такой не убирается). */
  leaders: Record<string, string>;
};

export const REEL_CH = 'example-film';
export const SCIENCE_CH = 'example-science';
export const TECH_CH = 'example-tech';
export const DEFAULT_BANK = 'memes';
export const TECH_BANK = 'memes-example-tech';

/** Каналы и их банки: `insert_layers.meme` из конфигов каналов. */
export const CHANNEL_BANKS: { channel: string; bank: string; layer_enabled: boolean | null }[] = [
  { channel: REEL_CH, bank: DEFAULT_BANK, layer_enabled: true },
  { channel: SCIENCE_CH, bank: DEFAULT_BANK, layer_enabled: null },
  { channel: TECH_CH, bank: TECH_BANK, layer_enabled: false },
];

const img = 'https://i.imgflip.com';

type Row = [id: string, description: string, tags: string[]];

const TECH_ROWS: Row[] = [
  [
    'always-has-been',
    'Two astronauts: one looks at Earth, the other holds a gun behind him.',
    ['realization', 'always was', 'reveal', 'space', 'legacy code', 'it was never fine'],
  ],
  [
    'anakin-padme',
    'A young man smiles, the woman opposite slowly stops smiling.',
    ['right?', 'naive', 'doubt', 'expectation', 'release notes', 'breaking change'],
  ],
  [
    'bell-curve',
    'A bell curve: the simple and the genius ends agree, the middle overthinks.',
    ['overthinking', 'midwit', 'simple answer', 'genius', 'use a spreadsheet'],
  ],
  [
    'bernie-once-again-asking',
    'An old man in mittens says he is once again asking.',
    ['asking again', 'support', 'please', 'donation', 'feature request'],
  ],
  [
    'buff-doge-vs-cheems',
    'A muscular dog towers over a small sad dog: then and now.',
    ['then vs now', 'old hardware', 'decline', 'comparison', 'nostalgia'],
  ],
  [
    'change-my-mind',
    'A man sits at a table with a sign: change my mind.',
    ['opinion', 'debate', 'hot take', 'tabs vs spaces', 'controversy'],
  ],
  [
    'clown-applying-makeup',
    'Four steps of a man putting on clown make-up.',
    ['self-own', 'escalation', 'bad decision', 'deploy on friday', 'clown'],
  ],
  [
    'disaster-girl',
    'A girl smiles at the camera while a house burns behind her.',
    ['disaster', 'chaos', 'smug', 'production down', 'fire'],
  ],
  [
    'distracted-boyfriend',
    'A man turns to look at another woman while his girlfriend glares.',
    ['distracted', 'new framework', 'temptation', 'switching', 'shiny object'],
  ],
  [
    'drake-hotline-bling',
    'A man rejects one thing with his hand and approves the other.',
    ['preference', 'no vs yes', 'choice', 'better option', 'approval'],
  ],
  [
    'evil-kermit',
    'A frog talks to a hooded version of itself.',
    ['temptation', 'inner voice', 'bad idea', 'do it', 'self-control'],
  ],
  [
    'expanding-brain',
    'A brain grows brighter with each sillier idea.',
    ['escalation', 'galaxy brain', 'irony', 'enlightenment', 'over-engineering'],
  ],
  [
    'futurama-fry',
    'A cartoon man squints in suspicion.',
    ['suspicious', 'not sure if', 'doubt', 'squint', 'bug or feature'],
  ],
  [
    'grandma-finds-the-internet',
    'An old woman stares in surprise at a laptop.',
    ['elderly', 'internet', 'surprise', 'new tech', 'boomer'],
  ],
  [
    'grus-plan',
    'A cartoon villain presents a plan on a flipchart and the last step backfires.',
    ['plan', 'backfire', 'wait', 'oops', 'roadmap'],
  ],
  [
    'hide-the-pain-harold',
    'An older man smiles at the camera, the pain shows in his eyes.',
    ['hidden pain', 'fake smile', 'coping', 'its fine', 'on-call'],
  ],
  [
    'is-this-a-pigeon',
    'An anime man points at a butterfly and asks if it is a pigeon.',
    ['misunderstanding', 'wrong label', 'confusion', 'is this ai', 'naming'],
  ],
  [
    'left-exit-12-off-ramp',
    'A car swerves across lanes to the exit at the last second.',
    ['sudden change', 'swerve', 'pivot', 'choice', 'rewrite'],
  ],
  [
    'mocking-spongebob',
    'A cartoon sponge bends over, clucking like a chicken.',
    ['mocking', 'sarcasm', 'repeat', 'taunt', 'you said'],
  ],
  [
    'monkey-puppet',
    'A puppet monkey glances sideways, then looks away.',
    ['awkward', 'side eye', 'guilty', 'avoid', 'silence'],
  ],
  [
    'panik-kalm-panik',
    'A meme man panics, calms down, panics again.',
    ['panic', 'relief', 'twist', 'roller coaster', 'release day'],
  ],
  [
    'roll-safe',
    'A man taps his temple with a knowing grin.',
    ['clever', 'life hack', 'smart', 'cant fail if', 'logic'],
  ],
  [
    'sad-pablo-escobar',
    'A man sits alone, waiting, in three sad shots.',
    ['lonely', 'waiting', 'bored', 'sad', 'empty office'],
  ],
  [
    'scooby-doo-mask-reveal',
    'A cartoon character pulls the mask off the villain.',
    ['reveal', 'unmasking', 'truth', 'it was', 'rebrand'],
  ],
  [
    'something-of-a-scientist',
    'A man in a lab says he is something of a scientist himself.',
    ['scientist', 'expert', 'proud', 'amateur', 'self-taught'],
  ],
  [
    'spirerunner-pointing',
    'Two identical superheroes point at each other.',
    ['same', 'blame', 'duplicate', 'mirror', 'fork'],
  ],
  [
    'surprised-pikachu',
    'A cartoon creature opens its mouth in shock.',
    ['shock', 'surprise', 'obvious result', 'gasp', 'consequences'],
  ],
  [
    'theyre-the-same-picture',
    'A woman holds two pictures and says they are the same.',
    ['same', 'no difference', 'identical', 'corporate', 'rebrand'],
  ],
  [
    'this-is-fine',
    'A cartoon dog sips coffee in a room on fire.',
    ['fine', 'denial', 'fire', 'calm', 'coping'],
  ],
  [
    'trade-offer',
    'A man in a suit presents a trade offer.',
    ['trade', 'deal', 'offer', 'exchange', 'negotiation'],
  ],
  [
    'two-buttons',
    'A sweating man cannot choose between two red buttons.',
    ['dilemma', 'hard choice', 'sweat', 'two options', 'both bad'],
  ],
  [
    'uno-draw-25',
    'A cartoon man holds a card: do this or draw 25.',
    ['refusal', 'stubborn', 'or else', 'card game', 'just read the docs'],
  ],
  [
    'woman-yelling-at-cat',
    'A woman yells and points, a cat at the table looks confused.',
    ['argument', 'yelling', 'confused', 'blame', 'meeting'],
  ],
  [
    'x-x-everywhere',
    'A cartoon spaceman shows his friend that something is everywhere.',
    ['everywhere', 'ubiquitous', 'too much', 'look', 'ai everywhere'],
  ],
  [
    'zero-days-without',
    'A sign: zero days without an accident, reset again.',
    ['reset', 'accident', 'again', 'counter', 'incident'],
  ],
];

const GIFS: Record<string, { start_s: number; end_s: number }> = {
  'surprised-pikachu': { start_s: 12.4, end_s: 14.1 },
  'this-is-fine': { start_s: 3, end_s: 6.2 },
  'mocking-spongebob': { start_s: 41.8, end_s: 44 },
  'panik-kalm-panik': { start_s: 0, end_s: 3.5 },
};

/** Можно вырезать: у двух вырезка готова, у одного — фабрика её не приняла. */
const TECH_CUT: Record<string, Record<string, unknown>> = {
  'drake-hotline-bling': { file: 'drake-hotline-bling.cutout.png', coverage: 0.42 },
  'roll-safe': { file: 'roll-safe.cutout.png', coverage: 0.38 },
  'distracted-boyfriend': {
    refused: 'передний план занимает 81% кадра\u00a0— проверка допускает до 60%',
    refused_en: 'foreground covers 81% of the frame (the check allows up to 60%)',
    coverage: 0.81,
  },
};

function techEntries(): IndexEntry[] {
  return TECH_ROWS.map(([id, description, tags]) => {
    const clip = GIFS[id];
    const cut = TECH_CUT[id];
    const e: IndexEntry = {
      id,
      file: clip ? `${id}.gif` : `${id}.${id.length % 3 ? 'jpg' : 'png'}`,
      description,
      tags,
      source_url: clip
        ? `https://www.youtube.com/watch?v=meme${id.length}`
        : `${img}/${id.slice(0, 6)}.jpg`,
      review: 'pending',
    };
    if (clip) e.clip = clip;
    if (cut) {
      e.cutout = true;
      e.cutout_asset = cut;
    }
    if (id === 'grus-plan') e.notes = 'Подпись сверху у шаблона — пустая белая полоса.';
    return e;
  });
}

function reelEntries(): IndexEntry[] {
  const rows: (Row & { 3?: Partial<IndexEntry> })[] = [
    [
      'ancient-aliens',
      'A wild-haired man in a suit gestures with both palms up, explaining something with total conviction.',
      ['aliens', 'conspiracy', 'explaining', 'wild theory', 'no evidence', 'ancient'],
    ],
    [
      'bugs-bunny-communist',
      'A cartoon rabbit holds up a red flag with a smug expression.',
      ['ours now', 'collective', 'cartoon', 'sharing', 'remake', 'copy'],
    ],
    [
      'charlie-conspiracy',
      'A dishevelled man gestures wildly at a wall of documents joined by red string.',
      ['conspiracy', 'connecting dots', 'fan theory', 'red string', 'rabbit hole'],
    ],
    [
      'disaster-girl',
      'A girl smiles at the camera while a house burns behind her.',
      ['disaster', 'chaos', 'smug', 'fire', 'flop'],
    ],
    [
      'disappointed-cricket-fan',
      'A man in the stands puts his hands on his hips in disappointment.',
      ['disappointed', 'really', 'seriously', 'fan', 'flop'],
    ],
    [
      'distracted-boyfriend',
      'A man turns to look at another woman while his girlfriend glares.',
      ['distracted', 'temptation', 'switching', 'remake', 'reboot'],
    ],
    [
      'epic-handshake',
      'Two muscular arms clasp hands in agreement.',
      ['agreement', 'common ground', 'alliance', 'unity', 'fans'],
    ],
    [
      'frustrated-boromir',
      'A bearded warrior raises a hand: one does not simply walk in.',
      ['one does not simply', 'lord of the rings', 'fantasy', 'hard', 'fed up'],
    ],
    [
      'old-man-yells-at-cloud',
      'A cartoon old man shakes his fist at a cloud.',
      ['elderly', 'angry', 'annoyed', 'again', 'ugh'],
    ],
    [
      'picard-facepalm',
      'A captain buries his face in his hand.',
      ['facepalm', 'exasperated', 'headache', 'mistake', 'cringe'],
    ],
    [
      'gandalf-looking',
      'A wizard looks at something with deep concern.',
      ['concern', 'lord of the rings', 'fantasy', 'worried', 'hmm'],
    ],
    [
      'shrek-reaction',
      'An ogre makes a puzzled face, a GIF from the film.',
      ['puzzled', 'cartoon', 'what', 'confused', 'remake'],
    ],
  ];
  return rows.map(([id, description, tags]) => {
    const e: IndexEntry = {
      id,
      file: `${id}.jpg`,
      description,
      tags,
      source_url: `${img}/${id.slice(0, 5)}.jpg`,
    };
    if (id === 'disappointed-cricket-fan') {
      e.file = `${id}.png`;
      e.cutout = true;
      e.cutout_asset = { file: `${id}.cutout.png`, coverage: 0.35 };
    }
    if (['gandalf-looking', 'shrek-reaction', 'old-man-yells-at-cloud'].includes(id))
      e.review = 'pending';
    if (id === 'shrek-reaction') {
      e.file = `${id}.gif`;
      e.source_url = 'https://www.youtube.com/watch?v=shrek01';
      e.clip = { start_s: 88.2, end_s: 90.6 };
    }
    return e;
  });
}

/** Свежие банки: каждый тест и каждая загрузка тренировки — с чистого листа. */
export function seedBanks(): Record<string, BankSeed> {
  return {
    [DEFAULT_BANK]: {
      folder: 'shared/inserts/memes',
      entries: reelEntries(),
      draft: {
        'picard-facepalm': {
          v: 'drop',
          note: 'Слишком затёрт',
          marked_by: 'user',
          marked_at: '2026-10-10T18:20:00+00:00',
          via: 'center',
        },
        'gandalf-looking': { v: 'keep' },
      },
      bands: [],
      leaders: { 'disaster-girl': 'disaster', 'shrek-reaction': 'confused' },
    },
    [TECH_BANK]: {
      folder: 'shared/inserts/memes-example-tech',
      entries: techEntries(),
      // Отметка мема, которого в банке уже нет: `status.stale`.
      draft: { 'old-sticker': { v: 'drop' }, 'always-has-been': { v: 'keep', cut: false } },
      bands: [
        {
          id: 'grus-plan',
          phrase: 'top 79 white rows (22%)',
          phrase_ru: 'сверху белая полоса, 22% высоты',
        },
        {
          id: 'two-buttons',
          phrase: 'bottom 61 black rows (17%)',
          phrase_ru: 'снизу чёрная полоса, 17% высоты',
        },
      ],
      leaders: {},
    },
  };
}
