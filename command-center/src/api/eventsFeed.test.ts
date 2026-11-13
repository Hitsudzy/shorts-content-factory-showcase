import { applyPage, feedDelay, pullFeed, type BatchEvents } from './eventsFeed';

const ev = (offset: number) => ({ offset, event: { kind: 'step', n: offset }, text: null });

function page(offsets: number[], over: Partial<BatchEvents> = {}): BatchEvents {
  const last = offsets.at(-1);
  return {
    batch: 'example-film/2026-10-10T0700Z',
    events: offsets.map(ev),
    next: last == null ? 0 : last + 10,
    size: 1000,
    more: false,
    reset: false,
    poll_s: 3,
    ...over,
  };
}

describe('лента событий по курсору', () => {
  it('первый опрос — без after (хвост), следующий — с next прошлого', async () => {
    const asked: (number | null)[] = [];
    const replies = [page([0, 10, 20]), page([30])];
    const fetch = (after: number | null) => {
      asked.push(after);
      return Promise.resolve(replies.shift()!);
    };
    const first = await pullFeed(undefined, fetch);
    expect(first.lines.map((l) => l.offset)).toEqual([0, 10, 20]);
    expect(first.next).toBe(30);
    const second = await pullFeed(first, fetch);
    expect(asked).toEqual([null, 30]);
    expect(second.lines.map((l) => l.offset)).toEqual([0, 10, 20, 30]);
    expect(feedDelay(second)).toBe(3000);
  });

  it('more — переспрашивает сразу, в пределах одного опроса', async () => {
    const asked: (number | null)[] = [];
    const replies = [page([0], { more: true }), page([10], { more: true }), page([20])];
    const feed = await pullFeed(undefined, (after) => {
      asked.push(after);
      return Promise.resolve(replies.shift()!);
    });
    expect(asked).toEqual([null, 10, 20]);
    expect(feed.lines).toHaveLength(3);
    expect(feed.more).toBe(false);
  });

  it('more дольше maxPages — остаток следующим опросом, почти сразу', async () => {
    let n = 0;
    const feed = await pullFeed(
      undefined,
      () => Promise.resolve(page([n++ * 10], { more: true })),
      2,
    );
    expect(n).toBe(2);
    expect(feed.more).toBe(true);
    expect(feedDelay(feed)).toBe(250);
  });

  it('reset — прежнее выброшено, лента начинается с хвоста ответа', () => {
    const before = applyPage(undefined, page([0, 10, 20, 30]));
    const after = applyPage(before, page([0, 10], { reset: true, size: 20 }));
    expect(after.lines.map((l) => l.offset)).toEqual([0, 10]);
    expect(after.next).toBe(20);
    expect(after.resets).toBe(1);
    expect(after.dropped).toBe(4);
  });

  it('в памяти — не больше keep последних строк', () => {
    let feed = applyPage(undefined, page([0, 10, 20]), 4);
    feed = applyPage(feed, page([30, 40, 50]), 4);
    expect(feed.lines.map((l) => l.offset)).toEqual([20, 30, 40, 50]);
    expect(feed.dropped).toBe(2);
  });

  it('пустой ответ — курсор фабрики, строки прежние', () => {
    const feed = applyPage(applyPage(undefined, page([0])), page([], { next: 10 }));
    expect(feed.lines).toHaveLength(1);
    expect(feed.next).toBe(10);
  });
});
