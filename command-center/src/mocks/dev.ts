// Подставная «Разработка» (`GET /api/dev/tasks`, `/api/dev/tasks/{id}`, `/api/dev/roadmap` —
// CC-0124, договор 0.66.0). Общий для Vitest (MSW, src/mocks/handlers.ts), Playwright
// (tests/e2e/fixtures.ts) и тренировки (src/training/demo.ts). Импорты — относительные.
//
// Две дорожные карты, как у живых репо 17.10: фабрика — веха 2.8 сделана (её задачи в архиве
// `v2.8`), текущая 2.9 (спринт 2.9.1 сделан, 2.9.2 идёт), впереди 3.0; центр — 1.0 сделана
// (архив `1.0`), текущая 1.1 (два спринта), впереди 1.2. Задачи всех статусов, у CC-0124 и
// CF-0618 — чеклисты, в текстах — ссылки CF ↔ CC, у сделанных и идущих — коммиты.
// Фильтры — как у API: списки через запятую, точное совпадение; `q` — каждое слово в id,
// заголовке или теле, без регистра; неизвестный проект — 422 `bad_project`.
// Ручки теста (`state`): `refuse` (500 на всё), `sourceError` (ошибка чтения центра — его задач
// нет, в `sources` — `error`), `calls` (пути запросов).
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export type DevReply =
  | { status: 200; body: S['DevTasks'] | S['DevTask'] | S['DevRoadmaps'] }
  | { status: 404 | 422; body: S['DevProblem'] }
  | { status: 500; body: { detail: string } };

export const FACTORY_SHA = '9c41e07b2d5a8f13c6e0b74d2a19f5e3c8b06d71';
export const CENTER_SHA = 'd7ab21734e9c0f5a1b8d26e4c3f07a95b1e2d468';

type Project = 'factory' | 'center';

/** Строка таблицы задач: [id, заголовок, тип, статус, веха, репо, заведена, закрыта]. */
type Seed = [string, string, string, string, string | null, string | null, string, string | null];

const FACTORY: Seed[] = [
  [
    'CF-0601',
    'Пересборка ролика с этапа — без повторного поиска футажа',
    'task',
    'done',
    '2.8',
    'agents/video-editor',
    '2026-09-28',
    '2026-10-06',
  ],
  [
    'CF-0603',
    'Журнал загрузок: одна запись на слот',
    'task',
    'done',
    '2.8',
    'shared',
    '2026-09-29',
    '2026-10-08',
  ],
  [
    'CF-0605',
    'Голос диктора: паузы по знакам препинания',
    'task',
    'done',
    '2.8',
    'agents/video-editor',
    '2026-09-30',
    '2026-10-10',
  ],
  [
    'CF-0607',
    'Порог остановки канала — свой на канал',
    'task',
    'wontfix',
    '2.8',
    'shared',
    '2026-10-01',
    '2026-10-12',
  ],
  [
    'CF-0609',
    'Тесты без сети и без живых данных',
    'chore',
    'done',
    '2.8',
    null,
    '2026-10-02',
    '2026-10-13',
  ],
  [
    'CF-0612',
    'Батч Science: темы из трёх источников вместо одного',
    'task',
    'done',
    '2.9',
    'agents/trend-hunter',
    '2026-10-09',
    '2026-10-14',
  ],
  [
    'CF-0614',
    'Футаж: не брать один и тот же клип дважды за неделю',
    'bug',
    'done',
    '2.9',
    'agents/footage-indexer',
    '2026-10-10',
    '2026-10-15',
  ],
  [
    'CF-0615',
    'Расход токенов по стадиям в сводке батча',
    'task',
    'done',
    '2.9',
    'api',
    '2026-10-10',
    '2026-10-15',
  ],
  [
    'CF-0618',
    'Публикация Tech по расписанию с 17.10, 01:00 МСК',
    'task',
    'in-progress',
    '2.9',
    'shared',
    '2026-10-12',
    null,
  ],
  [
    'CF-0620',
    'Обложки: крупный текст читается на телефоне',
    'task',
    'open',
    '2.9',
    'agents/video-editor',
    '2026-10-13',
    null,
  ],
  [
    'CF-0621',
    'Публикация Science после 19.10',
    'task',
    'blocked',
    '2.9',
    'shared',
    '2026-10-13',
    null,
  ],
  [
    'CF-0623',
    'Ключ YouTube API для второго проекта',
    'task',
    'needs-you',
    '2.9',
    'api',
    '2026-10-14',
    null,
  ],
  [
    'CF-0624',
    'Проверка фактов: ссылка на источник у каждой цифры',
    'task',
    'open',
    '2.9',
    'agents/compliance-checker',
    '2026-10-14',
    null,
  ],
  [
    'CF-0626',
    'Командный центр: задачи CC-0001…0037 и дорожная карта',
    'task',
    'done',
    '2.9',
    null,
    '2026-10-09',
    '2026-10-09',
  ],
  [
    'CF-0627',
    'Субтитры съезжают на роликах длиннее 50 с',
    'bug',
    'open',
    '2.9',
    'agents/video-editor',
    '2026-10-15',
    null,
  ],
  ['CF-0630', 'Третий канал: ExampleHistory', 'task', 'open', '3.0', null, '2026-10-15', null],
  [
    'CF-0631',
    'Аналитик: выводы по удержанию раз в неделю',
    'research',
    'open',
    '3.0',
    'agents/content-researcher',
    '2026-10-16',
    null,
  ],
  [
    'CF-0633',
    'Переезд API на отдельный порт и пользователя',
    'task',
    'open',
    '3.0',
    'api',
    '2026-10-16',
    null,
  ],
  [
    'CF-0635',
    'Идея: озвучка вторым голосом для диалогов',
    'research',
    'open',
    null,
    null,
    '2026-10-16',
    null,
  ],
];

const CENTER: Seed[] = [
  [
    'CC-0141',
    'Публикация: подписи слотов без технических слов',
    'task',
    'done',
    '1.0',
    'frontend',
    '2026-10-14',
    '2026-10-15',
  ],
  [
    'CC-0142',
    'Лента слотов — «пустых дней за 2 недели» и «журнала загрузок нет»',
    'task',
    'done',
    '1.0',
    'frontend',
    '2026-10-14',
    '2026-10-16',
  ],
  [
    'CC-0144',
    'Главная: что ждёт вас — одной строкой',
    'task',
    'done',
    '1.0',
    'frontend',
    '2026-10-15',
    '2026-10-16',
  ],
  [
    'CC-0145',
    'Договор 0.64.0: типы и проверка снимка',
    'chore',
    'done',
    '1.0',
    'frontend',
    '2026-10-15',
    '2026-10-16',
  ],
  [
    'CC-0146',
    'План недели: слова про день без батча',
    'task',
    'done',
    '1.0',
    'frontend',
    '2026-10-15',
    '2026-10-16',
  ],
  [
    'CC-0148',
    '«Журнала загрузок нет» — одной строкой про фабрику',
    'bug',
    'done',
    '1.0',
    'frontend',
    '2026-10-16',
    '2026-10-16',
  ],
  [
    'CC-0036',
    'Вход по паролю из домашней сети: API',
    'task',
    'done',
    '1.1',
    'cc/api',
    '2026-10-09',
    '2026-10-17',
  ],
  ['CC-0037', 'Экран входа и выхода', 'task', 'in-progress', '1.1', 'frontend', '2026-10-09', null],
  [
    'CC-0124',
    'Вкладка «Разработка»: задачи фабрики и центра — версии, поиск, фильтры, карточка задачи',
    'task',
    'in-progress',
    '1.1',
    null,
    '2026-10-13',
    null,
  ],
  [
    'CC-0147',
    'Ролики: сравнение двух версий рядом на телефоне',
    'task',
    'open',
    '1.1',
    'frontend',
    '2026-10-16',
    null,
  ],
  [
    'CC-0149',
    'Обслуживание: архив старых батчей одной кнопкой',
    'task',
    'open',
    '1.1',
    'cc/api',
    '2026-10-16',
    null,
  ],
  [
    'CC-0150',
    'Пароль центра: где его хранить на Mac',
    'task',
    'needs-you',
    '1.1',
    'cc/api',
    '2026-10-16',
    null,
  ],
  [
    'CC-0151',
    'Токены: ключ второго проекта в разрешениях',
    'task',
    'blocked',
    '1.1',
    'frontend',
    '2026-10-16',
    null,
  ],
  [
    'CC-0152',
    'Тёмная тема по расписанию',
    'task',
    'wontfix',
    '1.1',
    'frontend',
    '2026-10-16',
    '2026-10-17',
  ],
  [
    'CC-0160',
    'Уведомления в Telegram прямо из центра',
    'task',
    'open',
    '1.2',
    'cc/api',
    '2026-10-17',
    null,
  ],
  [
    'CC-0161',
    'Статистика: сравнение каналов за месяц',
    'task',
    'open',
    '1.2',
    'frontend',
    '2026-10-17',
    null,
  ],
];

/** Тела задач (markdown): у остальных — короткое описание из заголовка. */
const BODIES: Record<string, string> = {
  'CF-0618': `## Описание
Tech публикуется по расписанию каждый день с **17.10, 01:00 МСК**. Слоты — из \`channels/tech/schedule.json\`, загрузка — через журнал (CF-0603).

Центр показывает ленту слотов (CC-0142) — проверить там, что первые три дня стоят.

## Чеклист
- [x] Расписание Tech в \`schedule.json\`
- [x] Журнал загрузок пишет одну запись на слот
- [ ] Первая загрузка 17.10 прошла
- [ ] Вторая и третья — без ручного запуска
- [ ] Отчёт за неделю

## Блокер
Нет.`,
  'CF-0621': `## Описание
Science идёт после **19.10** — когда Tech отработает три дня подряд.

## Блокер
Ждёт CF-0618: сначала Tech по расписанию.`,
  'CF-0623': `## Описание
Для второго проекта нужен свой ключ YouTube API: квота первого уходит на Tech.

## Нужно от вас
Создать ключ в Google Cloud и положить его в \`.env\` фабрики — центр ключи не трогает. После этого — CC-0151.`,
  'CF-0626': `## Описание
Гриль про командный центр: заведены задачи CC-0001…CC-0037 и дорожная карта 0.1–1.1.

## Сделано
- задачи центра в \`tasks/\`
- ROADMAP центра
- вход по паролю — CC-0036 и CC-0037`,
  // Не попадает в скриншоты: проверка, что сырой HTML в теле остаётся текстом.
  'CF-0635': `## Описание
Короткая заметка из гриля: <script>alert(1)</script> и <img src=x onerror=alert(2)> — как текст.
Ссылка [javascript:alert(3)](javascript:alert(3)) — тоже текст.`,
  'CF-0607': `## Описание
Порог остановки на канал.

## Почему не делаем
Один общий порог проще, а каналов пока два. Вернуться, если появится третий (CF-0630).`,
  'CC-0124': `## Описание
Просьба пользователя 13.10: вкладка с задачами на разработку — с **версией**, *поиском* и фильтрами.

Источники (только чтение):
- фабрика: \`tasks/CF-*.md\` и \`tasks/archive/v*/\`;
- центр: \`tasks/CC-*.md\` и \`tasks/archive/\`;
- \`ROADMAP.md\` обоих.

### Экран
1. Список с группами по вехам.
2. Поиск и фильтры — в адресе.
3. Карточка задачи — тело как markdown.

Связано: CF-0626 (гриль центра), CC-0037 (вход).

\`\`\`
GET /api/dev/tasks?project=&milestone=&status=&q=
curl -s 'http://127.0.0.1:8787/api/dev/tasks?project=factory,center&milestone=2.9,1.1&status=open,in-progress,needs-you&q=расписание' | jq '.tasks[] | {id, status, milestone}'
\`\`\`

Подробнее — в [дизайне центра](https://example.org/design).

## Чеклист
- [x] API: список, карточка, дорожная карта
- [x] Типы договора 0.66.0
- [ ] Экран «Разработка»
- [ ] e2e и скриншоты`,
  'CC-0037': `## Описание
Экран входа: пароль из домашней сети, с Mac — без пароля. API — CC-0036.

## Чеклист
- [x] Состояние входа и 401 в клиенте
- [x] Подставной вход в тестах
- [ ] Ревью экранов`,
  'CC-0151': `## Описание
Показать ключ второго проекта на «Токенах».

## Блокер
Ждёт CF-0623 — ключа ещё нет.`,
  'CC-0150': `## Описание
Где хранить хэш пароля центра на Mac.

## Нужно от вас
Решить: связка ключей или файл \`.env\` центра. Рекомендация — связка ключей.`,
};

const blurb = (title: string) => `## Описание\n${title}.\n`;

type Full = S['DevTask'];

function itemsOf(body: string): S['DevChecklistItem'][] {
  return [...body.matchAll(/^- \[([ xX])\] (.+)$/gm)].map((m) => ({
    text: m[2]!,
    done: m[1] !== ' ',
  }));
}

const shaOf = (seed: string) => {
  let h = 0;
  for (const c of seed) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return (h.toString(16).padStart(8, '0') + FACTORY_SHA).slice(0, 40);
};

function build(project: Project, seed: Seed): Full {
  const [id, title, type, status, milestone, repo, created, closed] = seed;
  const body = BODIES[id] ?? blurb(title);
  const items = itemsOf(body);
  const doneMilestone = project === 'factory' ? milestone === '2.8' : milestone === '1.0';
  const archive = doneMilestone ? (project === 'factory' ? 'v2.8' : '1.0') : null;
  const blocked_by = id === 'CF-0621' ? ['CF-0618'] : id === 'CC-0151' ? ['CF-0623'] : [];
  return {
    id,
    title,
    type,
    status,
    milestone,
    repo,
    created,
    closed,
    dod: project === 'factory' ? 'тесты зелёные, отчёт в задаче' : null,
    blocked_by,
    extra: {},
    project,
    archived: !!archive,
    archive,
    path: archive ? `tasks/archive/${archive}/${id}.md` : `tasks/${id}.md`,
    branch: 'main',
    checklist: { done: items.filter((i) => i.done).length, total: items.length },
    body,
    items,
    related: [],
    commits: [],
  };
}

/** Коммиты задачи: «заведена» и по одному на шаг — новые сверху. */
function commitsOf(t: Full): S['DevCommit'][] {
  const out: S['DevCommit'][] = [
    {
      sha: shaOf(`${t.id}-filed`),
      date: `${t.created}T21:14:00+03:00`,
      subject: `${t.id} filed`,
      project: t.project,
    },
  ];
  if (t.status === 'in-progress' || t.status === 'done')
    out.unshift({
      sha: shaOf(`${t.id}-wip`),
      date: `${t.closed ?? '2026-10-17'}T08:05:00+03:00`,
      subject: `WIP ${t.id}: ${t.title}`,
      project: t.project,
    });
  if (t.status === 'done')
    out.unshift({
      sha: shaOf(`${t.id}-done`),
      date: `${t.closed}T18:40:00+03:00`,
      subject: `${t.id} done`,
      project: t.project,
    });
  return out;
}

type MilestoneSeed = {
  version: string;
  title: string;
  done: string | null;
  sprints: { version: string; title: string; done: string | null; tasks: string[] }[];
  tasks: string[];
};

const ROADMAPS: Record<Project, MilestoneSeed[]> = {
  factory: [
    {
      version: '2.8',
      title: 'Пересборка и голос',
      done: '2026-10-14',
      sprints: [],
      tasks: ['CF-0601', 'CF-0603', 'CF-0605', 'CF-0607', 'CF-0609'],
    },
    {
      version: '2.9',
      title: 'Публикация по расписанию',
      done: null,
      sprints: [
        {
          version: '2.9.1',
          title: 'Темы и футаж',
          done: '2026-10-15',
          tasks: ['CF-0612', 'CF-0614', 'CF-0615', 'CF-0626'],
        },
        {
          version: '2.9.2',
          title: 'Tech и Science в эфир',
          done: null,
          tasks: ['CF-0618', 'CF-0621', 'CF-0623', 'CF-0620', 'CF-0624', 'CF-0627'],
        },
      ],
      tasks: [],
    },
    {
      version: '3.0',
      title: 'Третий канал',
      done: null,
      sprints: [],
      tasks: ['CF-0630', 'CF-0631', 'CF-0633'],
    },
  ],
  center: [
    {
      version: '1.0',
      title: 'Центр готов',
      done: '2026-10-16',
      sprints: [],
      tasks: ['CC-0141', 'CC-0142', 'CC-0144', 'CC-0145', 'CC-0146', 'CC-0148'],
    },
    {
      version: '1.1',
      title: 'Вход и разработка',
      done: null,
      sprints: [
        {
          version: '1.1.1',
          title: 'Вход по паролю',
          done: null,
          tasks: ['CC-0036', 'CC-0037', 'CC-0150'],
        },
        {
          version: '1.1.2',
          title: 'Вкладка «Разработка»',
          done: null,
          tasks: ['CC-0124', 'CC-0147', 'CC-0149', 'CC-0151', 'CC-0152'],
        },
      ],
      tasks: [],
    },
    {
      version: '1.2',
      title: 'Уведомления и сравнения',
      done: null,
      sprints: [],
      tasks: ['CC-0160', 'CC-0161'],
    },
  ],
};

const ID_RE = /\b(?:CF|CC)-\d{4}\b/g;

function createWorld(): Full[] {
  const all = [
    ...FACTORY.map((s) => build('factory', s)),
    ...CENTER.map((s) => build('center', s)),
  ].sort((a, b) =>
    a.project === b.project ? a.id.localeCompare(b.id) : a.project === 'factory' ? -1 : 1,
  );
  const byId = new Map(all.map((t) => [t.id, t]));
  for (const t of all) {
    const ids = new Set([...t.body.matchAll(ID_RE)].map((m) => m[0]));
    for (const b of t.blocked_by) ids.add(b);
    ids.delete(t.id);
    t.related = [...ids].sort().map((id) => {
      const r = byId.get(id);
      return {
        id,
        project: id.startsWith('CC-') ? 'center' : 'factory',
        title: r?.title ?? null,
        status: r?.status ?? null,
      };
    });
    t.commits = commitsOf(t);
  }
  return all;
}

export type DevState = {
  refuse: boolean;
  /** Ошибка чтения репо центра: его задач и дорожной карты нет, в `sources` — `error`. */
  sourceError: boolean;
  calls: string[];
};

export function createDevBackend() {
  const state: DevState = { refuse: false, sourceError: false, calls: [] };
  const tasks = createWorld();
  return { state, tasks };
}

export type DevBackend = ReturnType<typeof createDevBackend>;

const PROJECTS = new Set<string>(['factory', 'center']);
const problem = (status: 404 | 422, code: S['DevProblem']['code'], message: string): DevReply => ({
  status,
  body: { message, code, details: [] },
});

const list = (v: string | null) =>
  v
    ? v
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean)
    : [];

function row(t: Full): S['DevTaskRow'] {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { body, items, related, commits, ...rest } = t;
  return rest;
}

function sources(b: DevBackend): S['DevSource'][] {
  return [
    { project: 'factory', repo: '.', branch: 'main', sha: FACTORY_SHA, error: null },
    b.state.sourceError
      ? {
          project: 'center',
          repo: '.worktrees/cc-frontend',
          branch: 'main',
          sha: null,
          error: 'git show main:tasks — fatal: not a git repository',
        }
      : {
          project: 'center',
          repo: '.worktrees/cc-frontend',
          branch: 'main',
          sha: CENTER_SHA,
          error: null,
        },
  ];
}

export function routeDev(b: DevBackend, method: string, url: URL): DevReply | null {
  const m = /\/api\/dev\/(tasks|roadmap)(?:\/([^/]+))?$/.exec(url.pathname);
  if (method !== 'GET' || !m) return null;
  b.state.calls.push(`${url.pathname}${url.search}`);
  if (b.state.refuse) return { status: 500, body: { detail: 'Internal Server Error' } };
  const p = url.searchParams;
  const project = p.get('project');
  if (project && !PROJECTS.has(project))
    return problem(422, 'bad_project', `unknown project ${project}: factory or center`);
  const visible = b.tasks.filter(
    (t) => !(b.state.sourceError && t.project === 'center') && (!project || t.project === project),
  );

  if (m[1] === 'roadmap') {
    if (m[2]) return null;
    const projects = (['factory', 'center'] as const).filter((x) => !project || x === project);
    return {
      status: 200,
      body: {
        roadmaps: projects.map((x) =>
          b.state.sourceError && x === 'center'
            ? {
                project: x,
                branch: 'main',
                sha: null,
                error: 'ROADMAP.md не прочитан',
                milestones: [],
              }
            : {
                project: x,
                branch: 'main',
                sha: x === 'factory' ? FACTORY_SHA : CENTER_SHA,
                error: null,
                milestones: ROADMAPS[x].map((ms) => ({
                  version: ms.version,
                  title: ms.title,
                  heading: `${ms.version} — ${ms.title}${ms.done ? ` (DONE ${ms.done})` : ''}`,
                  done: ms.done,
                  tasks: ms.tasks,
                  sprints: ms.sprints.map((sp) => ({
                    ...sp,
                    heading: `Спринт ${sp.version} — ${sp.title}${sp.done ? ` (DONE ${sp.done})` : ''}`,
                  })),
                })),
              },
        ),
      },
    };
  }

  if (m[2]) {
    const id = decodeURIComponent(m[2]);
    const t = visible.find((x) => x.id === id);
    return t ? { status: 200, body: t } : problem(404, 'unknown_task', `unknown task ${id}`);
  }

  const want = {
    milestone: list(p.get('milestone')),
    status: list(p.get('status')),
    type: list(p.get('type')),
    repo: list(p.get('repo')),
  };
  const words = (p.get('q') ?? '').toLowerCase().split(/\s+/).filter(Boolean);
  const hit = visible.filter((t) => {
    for (const [k, vs] of Object.entries(want) as [keyof typeof want, string[]][])
      if (vs.length && !vs.includes(t[k] ?? '')) return false;
    const hay = `${t.id}\n${t.title ?? ''}\n${t.body}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
  return {
    status: 200,
    body: {
      tasks: hit.map(row),
      count: hit.length,
      total: visible.length,
      sources: sources(b).filter((s) => !project || s.project === project),
    },
  };
}
