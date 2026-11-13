// Мок отказанных после монтажа роликов (CC-0116): Science 2001Z — sophie-adenot с mp4 и ролик
// без файла в `videos[]` с `refused`, `refused` в режимах и плане пересборки, 409 `video_refused`.
import { describe, expect, it } from 'vitest';

import { ADENOT_SCORE_LINE, createVideosBackend, routeVideos, SCIENCE } from './videos';

const url = (p: string) => new URL(`http://127.0.0.1/api/batches/${SCIENCE}${p}`);
type V = {
  slug: string;
  refused?: { gate: string | null; score_line: string | null; reason_code: string | null } | null;
  mp4: { exists: boolean };
};

describe('мок: отказанные после монтажа', () => {
  it('в списке батча — с `refused`; у одного mp4 есть, у другого — нет', () => {
    const b = createVideosBackend();
    const list = (routeVideos(b, 'GET', url('/videos')) as { body: { videos: V[] } }).body;
    const by = new Map(list.videos.map((v) => [v.slug, v]));
    expect(by.get('mars-sample-return')?.refused).toBeUndefined();
    expect(by.get('sophie-adenot')).toMatchObject({
      refused: { gate: 'score_below_threshold', score_line: ADENOT_SCORE_LINE },
      mp4: { exists: true },
    });
    expect(by.get('jwst-little-red-dots')).toMatchObject({
      refused: { reason_code: 'no_second_source', gate: null },
      mp4: { exists: false },
    });
    expect(routeVideos(b, 'GET', url('/videos/sophie-adenot/mp4'))).toMatchObject({
      status: 200,
      file: 'clip.mp4',
    });
  });

  it('вердикт отказанному — 409 `video_refused`, в журнал ничего', () => {
    const b = createVideosBackend();
    const r = routeVideos(
      b,
      'POST',
      url('/videos/sophie-adenot/acceptance'),
      {},
      { verdict: 'yes', words: 'sophie-adenot — да' },
    );
    expect(r).toMatchObject({ status: 409, body: { code: 'video_refused' } });
    expect(b.accepted).toEqual([]);
  });

  it('режимы и план пересборки несут `refused`; без плана монтажа перемонтаж отказан', () => {
    const b = createVideosBackend();
    const modes = routeVideos(b, 'GET', url('/rebuild/modes')) as {
      body: { videos: { slug: string; refused: string | null; plan: boolean }[] };
    };
    expect(modes.body.videos).toEqual([
      expect.objectContaining({ slug: 'mars-sample-return', refused: null, plan: true }),
      expect.objectContaining({
        slug: 'sophie-adenot',
        refused: 'score_below_threshold',
        plan: true,
      }),
      expect.objectContaining({
        slug: 'jwst-little-red-dots',
        refused: 'no_second_source',
        plan: false,
      }),
    ]);
    const plan = (videos: string[], mode: string) =>
      (
        routeVideos(b, 'POST', url('/rebuild/plan'), {}, { videos, mode }) as {
          body: { ok: boolean; reason: string; videos: { refused: string | null }[] };
        }
      ).body;
    const ok = plan(['sophie-adenot'], 'reedit');
    expect(ok).toMatchObject({ ok: true, videos: [{ refused: 'score_below_threshold' }] });
    expect(plan(['jwst-little-red-dots'], 'reedit')).toMatchObject({
      ok: false,
      reason: expect.stringContaining('нет плана монтажа'),
    });
    expect(plan(['jwst-little-red-dots'], 'rewrite')).toMatchObject({
      ok: true,
      videos: [{ refused: 'no_second_source' }],
    });
  });
});
