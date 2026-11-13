import type { DevRoadmap, DevTaskRow } from '@/api/dev';

import {
  applyFilters,
  compareVersions,
  EMPTY_FILTERS,
  filtersToParams,
  hasFilters,
  optionsOf,
  parseFilters,
  sortRows,
  toggle,
} from './filters';
import { currentMilestone, groupTasks, progressOf } from './groups';
import { dayText, statusWord, tasksWord } from './words';

const row = (id: string, over: Partial<DevTaskRow> = {}): DevTaskRow => ({
  id,
  title: id,
  type: 'task',
  status: 'open',
  milestone: '1.1',
  repo: 'frontend',
  created: '2026-10-10',
  closed: null,
  dod: null,
  blocked_by: [],
  extra: {},
  project: id.startsWith('CC-') ? 'center' : 'factory',
  archived: false,
  archive: null,
  path: `tasks/${id}.md`,
  branch: 'main',
  checklist: { done: 0, total: 0 },
  ...over,
});

describe('фильтры в адресе', () => {
  it('разбор: списки через запятую без повторов и пустых, неизвестная сортировка — по умолчанию', () => {
    const f = parseFilters(
      new URLSearchParams('q=%20вход%20&status=open,,done,open&milestone=1.1&sort=nope&view=x'),
    );
    expect(f).toEqual({
      ...EMPTY_FILTERS,
      q: 'вход',
      status: ['open', 'done'],
      milestone: ['1.1'],
    });
    expect(parseFilters(new URLSearchParams('sort=new')).sort).toBe('new');
  });

  it('обратно в адрес: порядок постоянный, пустое и сортировка по умолчанию не пишутся', () => {
    const f = { ...EMPTY_FILTERS, status: ['open', 'blocked'], q: 'tech', project: ['center'] };
    expect(filtersToParams(f).toString()).toBe('q=tech&project=center&status=open%2Cblocked');
    expect(filtersToParams(EMPTY_FILTERS).toString()).toBe('');
    expect(filtersToParams({ ...EMPTY_FILTERS, sort: 'id' }).toString()).toBe('sort=id');
  });

  it('туда и обратно — то же самое; посторонний `view` сохраняется', () => {
    const p = new URLSearchParams('view=roadmap&q=a%20b&type=bug&repo=-&sort=closed');
    const back = filtersToParams(parseFilters(p), p);
    expect(back.get('view')).toBe('roadmap');
    expect(parseFilters(back)).toEqual(parseFilters(p));
  });

  it('hasFilters и toggle', () => {
    expect(hasFilters(EMPTY_FILTERS)).toBe(false);
    expect(hasFilters({ ...EMPTY_FILTERS, sort: 'id' })).toBe(false);
    const f = toggle(EMPTY_FILTERS, 'status', 'open');
    expect(f.status).toEqual(['open']);
    expect(hasFilters(f)).toBe(true);
    expect(toggle(f, 'status', 'open').status).toEqual([]);
  });

  it('фильтр на месте: точное совпадение, «-» — пустое поле; И между ключами', () => {
    const rows = [
      row('CF-0001', { milestone: '2.9', repo: null }),
      row('CF-0002', { milestone: '2.10', status: 'done' }),
      row('CC-0003', { milestone: null }),
    ];
    const ids = (f: Partial<typeof EMPTY_FILTERS>) =>
      applyFilters(rows, { ...EMPTY_FILTERS, ...f }).map((t) => t.id);
    expect(ids({})).toEqual(['CF-0001', 'CF-0002', 'CC-0003']);
    expect(ids({ milestone: ['2.9'] })).toEqual(['CF-0001']);
    expect(ids({ repo: ['-'] })).toEqual(['CF-0001']);
    expect(ids({ milestone: ['-'] })).toEqual(['CC-0003']);
    expect(ids({ project: ['factory'], status: ['done'] })).toEqual(['CF-0002']);
  });

  it('варианты выбора: вехи по убыванию версии, «без» — в конце, со счётом', () => {
    const rows = [
      row('CF-1', { milestone: '2.9' }),
      row('CF-2', { milestone: '2.10' }),
      row('CF-3', { milestone: '2.9' }),
      row('CF-4', { milestone: null }),
    ];
    expect(optionsOf(rows, 'milestone')).toEqual([
      { value: '2.10', n: 1 },
      { value: '2.9', n: 2 },
      { value: '-', n: 1 },
    ]);
    expect(compareVersions('2.10', '2.9')).toBeGreaterThan(0);
  });

  it('сортировка: по статусу (ждёт вас первой), по номеру, новые, недавно закрытые', () => {
    const rows = [
      row('CF-0010', { status: 'done', closed: '2026-10-12', created: '2026-10-01' }),
      row('CF-0002', { status: 'needs-you', created: '2026-10-15' }),
      row('CF-0003', { status: 'done', closed: '2026-10-16', created: '2026-10-02' }),
    ];
    const ids = (s: Parameters<typeof sortRows>[1]) => sortRows(rows, s).map((t) => t.id);
    expect(ids('status')).toEqual(['CF-0002', 'CF-0003', 'CF-0010']);
    expect(ids('id')).toEqual(['CF-0002', 'CF-0003', 'CF-0010']);
    expect(ids('new')).toEqual(['CF-0002', 'CF-0003', 'CF-0010']);
    expect(ids('closed')).toEqual(['CF-0003', 'CF-0010', 'CF-0002']);
  });
});

describe('группы по вехам и прогресс', () => {
  const roadmaps: DevRoadmap[] = [
    {
      project: 'factory',
      branch: 'main',
      sha: null,
      error: null,
      milestones: [
        { version: '2.8', title: 'Голос', heading: '', done: '2026-10-14', tasks: [], sprints: [] },
        { version: '2.9', title: 'Эфир', heading: '', done: null, tasks: [], sprints: [] },
        { version: '3.0', title: 'Третий', heading: '', done: null, tasks: [], sprints: [] },
      ],
    },
    {
      project: 'center',
      branch: 'main',
      sha: null,
      error: null,
      milestones: [
        { version: '1.0', title: 'Готов', heading: '', done: '2026-10-16', tasks: [], sprints: [] },
        { version: '1.1', title: 'Вход', heading: '', done: null, tasks: [], sprints: [] },
      ],
    },
  ];

  it('прогресс: «не делаем» не в счёт, чеклисты складываются', () => {
    expect(
      progressOf([
        row('CF-1', { status: 'done', checklist: { done: 2, total: 2 } }),
        row('CF-2', { status: 'wontfix' }),
        row('CF-3', { status: 'open', checklist: { done: 1, total: 4 } }),
      ]),
    ).toEqual({ done: 1, total: 2, wontfix: 1, checklist: { done: 3, total: 6 } });
  });

  it('текущие вехи сверху, потом следующие по карте, вне карты, без вехи, сделанные — в конце', () => {
    const rows = [
      row('CF-0001', { milestone: '2.8', status: 'done' }),
      row('CF-0002', { milestone: '3.0' }),
      row('CF-0003', { milestone: '2.9' }),
      row('CF-0004', { milestone: null }),
      row('CF-0005', { milestone: '9.9' }),
      row('CC-0001', { milestone: '1.0', status: 'done' }),
      row('CC-0002', { milestone: '1.1' }),
    ];
    const g = groupTasks(rows, roadmaps, 'status');
    expect(g.map((x) => x.key)).toEqual([
      'factory|2.9',
      'center|1.1',
      'factory|3.0',
      'factory|9.9',
      'factory|',
      'center|1.0',
      'factory|2.8',
    ]);
    expect(g[0]).toMatchObject({ current: true, title: 'Эфир', done: null });
    expect(g[5]).toMatchObject({ current: false, done: '2026-10-16' });
    expect(currentMilestone(roadmaps[1])).toBe('1.1');
  });

  it('карты нет — веха сделана, если закрыты все её задачи', () => {
    const g = groupTasks(
      [
        row('CF-0001', { milestone: '2.8', status: 'done', closed: '2026-10-05' }),
        row('CF-0002', { milestone: '2.8', status: 'wontfix', closed: '2026-10-07' }),
        row('CF-0003', { milestone: '2.9' }),
      ],
      undefined,
      'id',
    );
    expect(g.map((x) => [x.key, x.done])).toEqual([
      ['factory|2.9', null],
      ['factory|2.8', '2026-10-07'],
    ]);
  });
});

describe('слова', () => {
  it('статусы цветом, неизвестный — как есть', () => {
    expect(statusWord('needs-you')).toMatchObject({ label: 'ждёт вас', tone: 'warn' });
    expect(statusWord('blocked').tone).toBe('danger');
    expect(statusWord('in-progress').tone).toBe('live');
    expect(statusWord('done').tone).toBe('ok');
    expect(statusWord('frozen')).toMatchObject({ label: 'frozen', tone: 'idle' });
  });

  it('даты и счёт задач', () => {
    const now = new Date('2026-10-17T12:00:00Z');
    expect(dayText('2026-10-13', now)).toBe('13.10');
    expect(dayText('2025-12-31', now)).toBe('31.12.2025');
    expect(dayText('2026-10-13T21:14:00+03:00', now)).toBe('13.10');
    expect(dayText(null, now)).toBeNull();
    expect([1, 2, 5, 11, 22, 25].map(tasksWord)).toEqual([
      '1 задача',
      '2 задачи',
      '5 задач',
      '11 задач',
      '22 задачи',
      '25 задач',
    ]);
  });
});
