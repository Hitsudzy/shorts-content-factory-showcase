import type { components } from '@/api/schema.gen';

import { createDevBackend, routeDev } from './dev';

type S = components['schemas'];

const get = (path: string) => routeDev(createDevBackend(), 'GET', new URL(`http://x${path}`));

describe('подставная «Разработка» — как API CC-0124', () => {
  it('список: фабрика первой, потом по id; все статусы; счёт и источники', () => {
    const r = get('/api/dev/tasks');
    expect(r?.status).toBe(200);
    const b = r!.body as S['DevTasks'];
    expect(b.count).toBe(b.total);
    expect(b.tasks[0]!.project).toBe('factory');
    const center = b.tasks.findIndex((t) => t.project === 'center');
    expect(b.tasks.slice(center).every((t) => t.project === 'center')).toBe(true);
    expect(new Set(b.tasks.map((t) => t.status))).toEqual(
      new Set(['open', 'in-progress', 'blocked', 'needs-you', 'done', 'wontfix']),
    );
    expect(b.tasks.some((t) => t.archived)).toBe(true);
    expect(b.sources.map((s) => s.project)).toEqual(['factory', 'center']);
    expect(b.tasks[0]).not.toHaveProperty('body');
  });

  it('фильтры — списки через запятую; q — каждое слово, без регистра, и в теле', () => {
    const b = get('/api/dev/tasks?status=blocked,needs-you&project=center')!.body as S['DevTasks'];
    expect(b.tasks.map((t) => t.id)).toEqual(['CC-0150', 'CC-0151']);
    const q = get('/api/dev/tasks?q=TECH%20расписанию')!.body as S['DevTasks'];
    expect(q.tasks.map((t) => t.id)).toContain('CF-0618');
    const body = get('/api/dev/tasks?q=связка')!.body as S['DevTasks'];
    expect(body.tasks.map((t) => t.id)).toEqual(['CC-0150']);
  });

  it('неизвестный проект — 422 bad_project, неизвестная задача — 404 unknown_task', () => {
    expect(get('/api/dev/tasks?project=moon')).toMatchObject({
      status: 422,
      body: { code: 'bad_project' },
    });
    expect(get('/api/dev/tasks/CF-9999')).toMatchObject({
      status: 404,
      body: { code: 'unknown_task' },
    });
  });

  it('задача: тело, чеклист, связи с названиями, коммиты новые сверху', () => {
    const t = get('/api/dev/tasks/CC-0124')!.body as S['DevTask'];
    expect(t.checklist).toEqual({ done: 2, total: 4 });
    expect(t.items[0]).toEqual({ text: 'API: список, карточка, дорожная карта', done: true });
    expect(t.related.map((r) => r.id)).toEqual(['CC-0037', 'CF-0626']);
    expect(t.related[1]).toMatchObject({ project: 'factory', status: 'done' });
    expect(t.commits[0]!.subject).toMatch(/^WIP CC-0124/);
  });

  it('дорожные карты: вехи по порядку, сделанные — с датой; фильтр проекта', () => {
    const b = get('/api/dev/roadmap?project=center')!.body as S['DevRoadmaps'];
    expect(b.roadmaps).toHaveLength(1);
    const ms = b.roadmaps[0]!.milestones;
    expect(ms.map((m) => [m.version, m.done])).toEqual([
      ['1.0', '2026-10-16'],
      ['1.1', null],
      ['1.2', null],
    ]);
    expect(ms[1]!.sprints[1]!.tasks[0]).toBe('CC-0124');
  });

  it('ошибка чтения центра — задач центра нет, у источника error', () => {
    const be = createDevBackend();
    be.state.sourceError = true;
    const b = routeDev(be, 'GET', new URL('http://x/api/dev/tasks'))!.body as S['DevTasks'];
    expect(b.tasks.every((t) => t.project === 'factory')).toBe(true);
    expect(b.sources[1]!.error).toBeTruthy();
  });
});
