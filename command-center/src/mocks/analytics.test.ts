import { createAnalyticsBackend, routeAnalytics } from './analytics';

const at = (p: string) => new URL(`http://x${p}`);
const get = (b: ReturnType<typeof createAnalyticsBackend>, p: string) =>
  routeAnalytics(b, 'GET', at(p));

describe('подставная статистика', () => {
  it('каналы: у Reel и Tech был сбор, у Science — ни разу', () => {
    const r = get(createAnalyticsBackend(), '/api/analytics');
    expect(r?.status).toBe(200);
    const body = r!.body as { channels: { channel: string; last_run: unknown }[] };
    expect(body.channels.map((c) => [c.channel, !!c.last_run])).toEqual([
      ['example-film', true],
      ['example-tech', true],
      ['example-science', false],
    ]);
  });

  it('окно 7 дней: у Reel собрано, у Tech — collected:false и окон нет', () => {
    const b = createAnalyticsBackend();
    const reel = get(b, '/api/analytics/example-film/metrics?first_days=7')!.body as {
      collected: boolean;
      videos: { window: { complete?: boolean | null; final: boolean } | null }[];
    };
    expect(reel.collected).toBe(true);
    expect(reel.videos).toHaveLength(8);
    expect(reel.videos.filter((v) => v.window === null)).toHaveLength(1);
    expect(reel.videos.filter((v) => v.window && !v.window.final).length).toBeGreaterThan(0);
    const tech = get(b, '/api/analytics/example-tech/metrics?first_days=7')!.body as {
      collected: boolean;
      videos: { window: unknown }[];
    };
    expect(tech.collected).toBe(false);
    expect(tech.videos.every((v) => v.window === null)).toBe(true);
  });

  it('сводка: группы по стилю, мало роликов, пробелы', () => {
    const r = get(createAnalyticsBackend(), '/api/analytics/example-film/summary?first_days=7')!
      .body as {
      aggregates: Record<string, { value: string; videos: number; small_sample: boolean }[]>;
      gaps: Record<string, unknown[]>;
      saved: boolean;
    };
    expect(r.aggregates.pattern!.map((g) => g.value)).toContain('contrast');
    expect(r.aggregates.pattern!.every((g) => g.small_sample)).toBe(true);
    expect(r.gaps.no_profile).toHaveLength(1);
    expect(r.gaps.no_studio!.length).toBeGreaterThan(0);
    expect(r.saved).toBe(true);
  });

  it('отказы: нет канала, нет ролика, нет сохранённой сводки, плохой день, сломанное хранилище', () => {
    const b = createAnalyticsBackend();
    expect(get(b, '/api/analytics/nope/metrics')?.status).toBe(404);
    expect((get(b, '/api/analytics/example-film/videos/zzz')!.body as { code: string }).code).toBe(
      'unknown_video',
    );
    expect(
      (get(b, '/api/analytics/example-film/summary/2026-01-01')!.body as { code: string }).code,
    ).toBe('no_saved_summary');
    expect(get(b, '/api/analytics/example-film/summary/bad')?.status).toBe(422);
    b.state.broken = 'example-film';
    expect(get(b, '/api/analytics/example-film/studio')?.status).toBe(409);
  });

  it('упакованные батчи — только с packed=true; записей нет', () => {
    const b = createAnalyticsBackend();
    const plain = get(b, '/api/analytics/example-film/footage-wanted?packed=false')!.body as {
      rows: unknown[];
      packed_read: boolean;
    };
    const packed = get(b, '/api/analytics/example-film/footage-wanted?packed=true')!.body as {
      rows: unknown[];
      packed_read: boolean;
    };
    expect(packed.rows.length).toBe(plain.rows.length + 1);
    expect([plain.packed_read, packed.packed_read]).toEqual([false, true]);
    expect(routeAnalytics(b, 'POST', at('/api/analytics/example-film/studio'))).toBeNull();
  });

  it('Studio: у Tech не настроено, у Reel пора читать и есть последнее чтение', () => {
    const b = createAnalyticsBackend();
    const tech = get(b, '/api/analytics/example-tech/studio')!.body as {
      settings: unknown;
      settings_error: string | null;
    };
    expect(tech.settings).toBeNull();
    expect(tech.settings_error).toMatch(/studio_read/);
    const reel = get(b, '/api/analytics/example-film/studio')!.body as {
      due: { due: boolean } | null;
      last_videos: unknown[];
      last_visit: unknown;
    };
    expect(reel.due?.due).toBe(true);
    expect(reel.last_videos).toHaveLength(5);
    expect(reel.last_visit).not.toBeNull();
  });
});
