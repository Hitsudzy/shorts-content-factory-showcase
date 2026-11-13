// Подставные «Версии и агенты» (CC-0031): как у живой фабрики — выпуск v2.3.4, в работе 2.4, пять
// агентов из `agents.lock.json`; ручки расхождения, «ничего в работе», ошибки лока и отказа;
// сохранённый ответ и `?fresh=true`.
import { createVersionsBackend, PINS, routeVersions, VERSIONS_CHECKED_AT } from './versions';

const get = (b: ReturnType<typeof createVersionsBackend>, q = '') => {
  const r = routeVersions(b, 'GET', new URL(`http://x/api/versions${q}`));
  if (!r) throw new Error('не наш путь');
  return r;
};
const ok = (b: ReturnType<typeof createVersionsBackend>, q = '') => {
  const r = get(b, q);
  if (r.status !== 200) throw new Error(`ответ ${r.status}`);
  return r.body;
};

describe('подставные версии', () => {
  it('по умолчанию — расхождение у двух агентов, в работе 2.4, проверка с кодом 1', () => {
    const v = ok(createVersionsBackend());
    expect(v.factory.release_tag).toBe('v2.3.4');
    expect(v.factory.versions_in_work).toEqual(['release/2.4']);
    expect(v.agents.map((a) => a.agent)).toEqual(PINS.map(([a]) => a));
    expect(v.agents.filter((a) => !a.ok).map((a) => a.agent)).toEqual([
      'content-researcher',
      'video-editor',
    ]);
    expect(v.status.exit_code).toBe(1);
    expect(v.agents.every((a) => a.line?.split(/\s+/)[1] === a.path)).toBe(true);
    expect(v.center.version).toBe('0.3.1');
    expect(v.modules[0]!.ok).toBe(true);
    expect(v.checked_at).toBe(VERSIONS_CHECKED_AT);
    expect(v.cached).toBe(false);
  });

  it('второй запрос — сохранённый ответ, ?fresh=true — новая проверка позже', () => {
    const b = createVersionsBackend();
    ok(b);
    const kept = ok(b);
    const fresh = ok(b, '?fresh=true');
    expect(kept.cached).toBe(true);
    expect(kept.checked_at).toBe(VERSIONS_CHECKED_AT);
    expect(fresh.cached).toBe(false);
    expect(Date.parse(fresh.checked_at)).toBeGreaterThan(Date.parse(VERSIONS_CHECKED_AT));
    expect(b.state.calls).toEqual(['/api/versions', '/api/versions', '/api/versions?fresh=true']);
  });

  it('всё на пинах и ничего в работе — код 0, пустой список', () => {
    const b = createVersionsBackend();
    b.clean();
    b.state.inWork = [];
    const v = ok(b);
    expect(v.agents.every((a) => a.ok)).toBe(true);
    expect(v.status).toMatchObject({ exit_code: 0, ok: true });
    expect(v.factory.versions_in_work).toEqual([]);
  });

  it('лок не прочитан — строк нет, код 2; отказ — 500; чужой путь — не наш', () => {
    const b = createVersionsBackend();
    b.state.lockError = 'no agents.lock.json';
    const v = ok(b);
    expect(v.agents).toEqual([]);
    expect(v.status.exit_code).toBe(2);
    b.state.refuse = true;
    expect(get(b).status).toBe(500);
    expect(routeVersions(b, 'GET', new URL('http://x/api/version'))).toBeNull();
    expect(routeVersions(b, 'POST', new URL('http://x/api/versions'))).toBeNull();
  });

  it('замечание вне агентов — строка root с DIFF', () => {
    const b = createVersionsBackend();
    b.clean();
    b.state.rootLines = true;
    const v = ok(b);
    expect(v.status.lines.filter((l) => l.of === 'root')).toHaveLength(1);
    expect(v.status.exit_code).toBe(1);
  });
});
