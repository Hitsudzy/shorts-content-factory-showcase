// Подставные тёзки (`publish.namesakes`, CC-0183): голое имя — 409 `namesakes` на заметке, загрузке,
// записи из Studio и карточке, с батчем — нужный ролик; `~` только в именах файлов; `slug` простое.
import { BatchError, problemCode } from '@/api/batchProblem';
import { getCardInfo } from '@/api/cards';
import { getNote, getQueue } from '@/api/publish';
import { confirmMove, planMove } from '@/api/publishMove';
import { planStudioRecord, planUpload } from '@/api/publishWrites';
import { getStash, planStashAuto, planStashPlace } from '@/api/stash';

import { publish } from './handlers';
import { PLACED, REEL } from './publish';
import {
  STASH_RESERVE,
  TWIN,
  TWIN_NEW,
  TWIN_OF_PLACED,
  TWIN_OLD,
  TWIN_RESERVE,
  TWIN_RESERVE_NEW_ID,
  TWIN_TITLES,
} from './stash';

const refused = async (p: Promise<unknown>) => {
  const e = await p.then(
    () => null,
    (x: unknown) => x,
  );
  expect(e).toBeInstanceOf(BatchError);
  return { code: problemCode(e), status: (e as BatchError).status, error: e as BatchError };
};

describe('подставные тёзки', () => {
  it('без `namesakes` тёзок нет и голое имя отвечает как раньше', async () => {
    publish.feedPolicy();
    const { videos, not_queued } = await getStash(REEL);
    const slugs = [...videos, ...not_queued].map((v) => v.slug);
    expect(slugs).not.toContain(TWIN);
    await expect(getNote(REEL, STASH_RESERVE, '_reserve')).resolves.toMatchObject({
      slug: STASH_RESERVE,
    });
  });

  it('копилка: два ролика одного имени; `~` в файле, имя простое, батч свой', async () => {
    publish.namesakes();
    const { videos } = await getStash(REEL);
    const twins = videos.filter((v) => v.slug === TWIN);
    expect(twins.map((v) => v.batch_id).sort()).toEqual([TWIN_OLD, TWIN_NEW]);
    expect(twins[0]!.mp4).toContain(`${TWIN}~`);
    expect(videos.filter((v) => v.slug === TWIN_RESERVE)).toHaveLength(2);
    expect(videos.find((v) => v.slug === PLACED)?.batch_id).toBe(TWIN_OF_PLACED);
  });

  it('заметка: голое имя — 409 `namesakes` с батчами; с батчем — свой ролик', async () => {
    publish.namesakes();
    const no = await refused(getNote(REEL, TWIN, '_queue'));
    expect(no.status).toBe(409);
    expect(no.code).toBe('namesakes');
    expect(no.error.message).toContain(TWIN_OLD);
    expect(no.error.message).toContain(TWIN_NEW);
    const note = await getNote(REEL, TWIN, '_queue', undefined, TWIN_NEW);
    expect(note.title).toBe(TWIN_TITLES[`${TWIN_NEW}/${TWIN}`]);
    const reserve = await getNote(REEL, TWIN_RESERVE, '_reserve', undefined, TWIN_OLD);
    expect(reserve.title).toBe(TWIN_TITLES[`${TWIN_OLD}/${TWIN_RESERVE}`]);
  });

  it('загрузка и запись из Studio: голое имя — `namesakes`; с батчем проходит мимо него', async () => {
    publish.namesakes();
    const upload = await refused(
      planUpload(REEL, { slug: TWIN_RESERVE, day: '_reserve', entry: null }),
    );
    expect(upload.code).toBe('namesakes');
    const record = await refused(
      planStudioRecord(REEL, {
        slug: TWIN_RESERVE,
        day: '_reserve',
        video_id: 'abcdefghijk',
        read: {},
        replaces: null,
      }),
    );
    expect(record.code).toBe('namesakes');
    const named = await planUpload(REEL, {
      slug: TWIN_RESERVE,
      batch_id: TWIN_NEW,
      day: '_reserve',
      entry: null,
    }).then(
      () => null,
      (e: unknown) => problemCode(e),
    );
    expect(named).not.toBe('namesakes');
  });

  it('карточка: голое имя — `namesakes`; у каждого батча свой ответ', async () => {
    publish.namesakes();
    const no = await refused(getCardInfo(REEL, TWIN, null));
    expect(no.code).toBe('namesakes');
    const old = await getCardInfo(REEL, TWIN, TWIN_OLD);
    const young = await getCardInfo(REEL, TWIN, TWIN_NEW);
    expect(old.batch_id).toBe(TWIN_OLD);
    expect(young.batch_id).toBe(TWIN_NEW);
    expect(young.state).not.toBe(old.state);
  });

  it('размещение: `<батч>/<имя>` ставит своего, голое имя — отказ с батчами', async () => {
    publish.namesakes();
    const bare = await planStashPlace(REEL, [TWIN]);
    expect(bare.confirm).toBeNull();
    const plan = await planStashPlace(REEL, [`${TWIN_NEW}/${TWIN}`]);
    expect(plan.items.map((i) => [i.slug, i.batch_id])).toEqual([[TWIN, TWIN_NEW]]);
    expect(plan.confirm).toBeTruthy();
  });

  it('авто-раскладка: `slug` пропущенных простое, у каждого свой `batch_id`', async () => {
    publish.namesakes();
    const plan = await planStashAuto(REEL, false);
    for (const s of plan.skipped ?? []) {
      expect(s.slug).not.toContain('/');
      expect(s.batch_id).toBeTruthy();
    }
  });

  it('перенос: голое имя двух роликов запаса — `ambiguous`; с батчем уходит только свой', async () => {
    publish.namesakes();
    const day = '2026-10-13';
    const bare = await planMove(REEL, { moves: [{ slug: TWIN_RESERVE, day }], unplace: [] });
    expect(bare.ok).toBe(false);
    expect(bare.items[0]!.refusals[0]!.code).toBe('ambiguous');
    expect(bare.items[0]!.refusals[0]!.message).toContain(TWIN_OLD);
    const plan = await planMove(REEL, {
      moves: [{ slug: TWIN_RESERVE, batch_id: TWIN_NEW, day }],
      unplace: [],
    });
    expect(plan.ok).toBe(true);
    expect(plan.items[0]).toMatchObject({
      slug: TWIN_RESERVE,
      batch_id: TWIN_NEW,
      video_id: TWIN_RESERVE_NEW_ID,
    });
    await confirmMove(REEL, plan.confirm!, plan.base_sha256);
    const { videos } = await getStash(REEL);
    expect(videos.filter((v) => v.slug === TWIN_RESERVE).map((v) => v.batch_id)).toEqual([
      TWIN_OLD,
    ]);
  });

  it('снятие: `<батч>/<имя>` снимает ролик ленты; тёзка в копилке не тронут', async () => {
    publish.namesakes();
    const day = (await getQueue(REEL, 14)).slots.find((s) => s.taken_by === PLACED)!.day;
    const note = await getNote(REEL, PLACED, day);
    const batch = note.batch!.batch_id!;
    const plan = await planMove(REEL, { moves: [], unplace: [], withdraw: [`${batch}/${PLACED}`] });
    expect(plan.ok).toBe(true);
    await confirmMove(REEL, plan.confirm!, plan.base_sha256);
    const { videos } = await getStash(REEL);
    const twins = videos.filter((v) => v.slug === PLACED);
    expect(twins.find((v) => v.batch_id === TWIN_OF_PLACED)).toBeDefined();
    expect(twins).toHaveLength(2);
  });
});
