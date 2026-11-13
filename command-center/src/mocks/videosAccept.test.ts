// Мок приёмки (CC-0062): проверки фабрики по порядку, журнал или очередь под батчем.
import { PAST } from './batches';
import { createVideosBackend, namesVideo, PAST_REDO, REDO_NOT_YET, routeVideos } from './videos';

const post = (
  b: ReturnType<typeof createVideosBackend>,
  batch: string,
  slug: string,
  body: unknown,
) =>
  routeVideos(
    b,
    'POST',
    new URL(`http://x/api/batches/${batch}/videos/${slug}/acceptance`),
    {},
    body,
  );

describe('мок приёмки', () => {
  it('имя ролика в словах — в любом регистре и с любыми разделителями', () => {
    expect(namesVideo('delver — да', 'delver')).toBe(true);
    expect(namesVideo('Rink Rivals, берём', 'rink-rivals')).toBe(true);
    expect(namesVideo('да, первый', 'delver')).toBe(false);
  });

  it('отказы фабрики: без имени, без причины, без кода, код у «да», повторный вердикт', () => {
    const b = createVideosBackend();
    const code = (body: unknown, slug = 'delver') => {
      const r = post(b, PAST, slug, body);
      return r && 'body' in r && r.status !== 200 ? (r.body as { code: string }).code : r?.status;
    };
    expect(code({ verdict: 'yes', words: 'да' })).toBe('answer_without_name');
    expect(code({ verdict: 'no', words: 'delver — нет' })).toBe('rejection_without_reason');
    expect(
      code({ verdict: 'no', words: 'delver — нет', reason: 'скучно', reason_code: 'Bad' }),
    ).toBe('rejection_without_code');
    expect(code({ verdict: 'yes', words: 'delver — да', reason_code: 'weak_hook' })).toBe(
      'acceptance_with_code',
    );
    expect(code({ verdict: 'yes', words: 'rink-rivals — да' }, 'rink-rivals')).toBe(
      'verdict_already_given',
    );
    expect(b.accepted).toEqual([]);
  });

  it('«да» без идущего батча — коммит; «переделать» под батчем — очередь, queued:false', () => {
    const b = createVideosBackend();
    const yes = post(b, PAST, 'delver', { verdict: 'yes', words: 'delver — берём' });
    expect(yes).toMatchObject({
      status: 200,
      body: {
        committed: true,
        pending: false,
        queued: { code: 'placed', ok: true, publish_path: 'publish/example-film/_queue/delver.mp4' },
      },
    });
    const list = b.list(PAST).body as { videos: { acceptance: unknown }[] };
    expect(list.videos[0]!.acceptance).toMatchObject({
      verdict: 'accepted',
      answer: 'delver — берём',
    });
    b.setGoing([{ dir: 'pipeline/example-film/2026-10-10T0200Z', why: 'батч идёт' }]);
    const redo = post(b, PAST, 'delver', {
      verdict: 'redo',
      words: 'delver — переделать',
      reason: 'хук слабый',
      reason_code: 'weak_hook',
      amend: 'посмотрел ещё раз',
    });
    expect(redo).toMatchObject({
      status: 200,
      body: {
        pending: true,
        committed: false,
        commit: null,
        batches: [{ why: 'батч идёт' }],
        redo: { queued: false, reason: REDO_NOT_YET },
        queued: null,
        acceptance: { pending: true, amended_because: 'посмотрел ещё раз' },
      },
    });
    // Пересборка видна в списке источника — состояние одно на обе копии.
    post(b, PAST_REDO, 'delver', { verdict: 'yes', words: 'delver да', amend: 'новая версия' });
    expect(b.accepted.map((a) => a.batch)).toEqual([PAST, PAST, PAST_REDO]);
  });
});
