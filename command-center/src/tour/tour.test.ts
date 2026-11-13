// Логика тура «Обучение» (CC-0072): шаги, переходы, прогресс, раскладка подсказки.
import { CLOSED, reduceTour, type TourState } from './engine';
import {
  EMPTY_PROGRESS,
  TOUR_STORAGE_KEY,
  allSeen,
  loadProgress,
  markSeen,
  parseProgress,
  restartProgress,
  resumeIndex,
  saveProgress,
  sectionSeen,
  showInvite,
} from './progress';
import {
  MARGIN,
  MIN_CARD,
  PHONE_SHARE,
  SHOW,
  cardWidth,
  overlaps,
  placeCard,
  scrollDelta,
  spotOf,
  type Box,
  type View,
} from './place';
import { SECTIONS, STEPS, onRoute, sectionStart, stepLabel, stepsOf } from './steps';

const DESKTOP: View = { width: 1280, height: 800 };
const PHONE: View = { width: 390, height: 844 };

describe('шаги тура', () => {
  it('у шагов разные имена, каждый — в известном разделе, разделы идут подряд', () => {
    expect(new Set(STEPS.map((s) => s.id)).size).toBe(STEPS.length);
    const order = STEPS.map((s) => s.section).filter((s, i, a) => s !== a[i - 1]);
    expect(order).toEqual(SECTIONS.map((s) => s.id));
    for (const s of SECTIONS) expect(stepsOf(s.id).length).toBeGreaterThan(0);
  });

  it('экраны — в порядке табов: главная, каналы, батчи, ролики, публикация, вопросы', () => {
    const routes = STEPS.filter((s) => s.section !== 'basics')
      .map((s) => s.route)
      .filter((r, i, a) => r !== a[i - 1]);
    expect(routes).toEqual(['/', '/channels', '/batches', '/videos', '/publishing', '/questions']);
  });

  it('общие приёмы — отдельными шагами', () => {
    expect(stepsOf('basics').map((s) => s.id)).toEqual(
      expect.arrayContaining(['read-only', 'confirm', 'more', 'tips', 'theme', 'phone']),
    );
  });

  it('у шага с целью есть слова на случай, когда цели нет, или цель есть всегда', () => {
    const always = new Set(['tabs', 'ask', 'tip-example', 'theme', 'tour-button', 'launch']);
    for (const s of STEPS) {
      if (s.target && !always.has(s.target)) expect(s.missing, s.id).toBeTruthy();
      expect(s.body.length, s.id).toBeGreaterThan(0);
    }
  });

  it('тексты — без номеров задач, путей и слов разработки', () => {
    const all = STEPS.flatMap((s) => [s.title, ...s.body, s.missing ?? '']).join('\n');
    expect(all).not.toMatch(/CC-\d|CF-\d|\/api|\.json|localStorage|data-tour|API\b|JSON/);
  });

  it('номер шага и начало раздела', () => {
    expect(stepLabel(2, 24)).toBe('3 из 24');
    expect(stepLabel(0)).toBe(`1 из ${STEPS.length}`);
    expect(STEPS[sectionStart('videos')]!.section).toBe('videos');
    expect(sectionStart('home')).toBe(0);
  });

  it('экран шага: точный путь, а у «глубоких» — и вложенный', () => {
    const list = STEPS.find((s) => s.id === 'channel-card')!;
    const deep = STEPS.find((s) => s.id === 'channel-settings')!;
    expect(onRoute(list, '/channels')).toBe(true);
    expect(onRoute(list, '/channels/')).toBe(true);
    expect(onRoute(list, '/channels/example-film')).toBe(false);
    expect(onRoute(deep, '/channels/example-film')).toBe(true);
    expect(onRoute(deep, '/channelsx')).toBe(false);
    expect(onRoute(STEPS[0]!, '/')).toBe(true);
    expect(onRoute(STEPS[0]!, '/videos')).toBe(false);
  });
});

describe('переходы тура', () => {
  const step = (index: number): TourState => ({ mode: 'step', index });

  it('дальше, назад, закрыть; после последнего — закрыт', () => {
    expect(reduceTour(CLOSED, { type: 'start', index: 0 })).toEqual(step(0));
    expect(reduceTour(step(0), { type: 'next' }, 3)).toEqual(step(1));
    expect(reduceTour(step(1), { type: 'back' }, 3)).toEqual(step(0));
    expect(reduceTour(step(0), { type: 'back' }, 3)).toEqual(step(0));
    expect(reduceTour(step(2), { type: 'next' }, 3)).toEqual({ mode: 'closed', index: 2 });
    expect(reduceTour(step(1), { type: 'close' }, 3)).toEqual({ mode: 'closed', index: 1 });
    expect(reduceTour(step(1), { type: 'menu' }, 3)).toEqual({ mode: 'menu', index: 1 });
  });

  it('начало за краем прижимается к шагам; «дальше» в оглавлении ничего не делает', () => {
    expect(reduceTour(CLOSED, { type: 'start', index: 99 }, 3)).toEqual(step(2));
    expect(reduceTour(CLOSED, { type: 'start', index: -1 }, 3)).toEqual(step(0));
    const menu: TourState = { mode: 'menu', index: 0 };
    expect(reduceTour(menu, { type: 'next' }, 3)).toBe(menu);
    expect(reduceTour(menu, { type: 'back' }, 3)).toBe(menu);
  });
});

describe('прогресс тура', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it('пустой, испорченный и чужой — пустой прогресс', () => {
    expect(parseProgress(null)).toEqual(EMPTY_PROGRESS);
    expect(parseProgress('{')).toEqual(EMPTY_PROGRESS);
    expect(parseProgress('42')).toEqual(EMPTY_PROGRESS);
    expect(parseProgress('null')).toEqual(EMPTY_PROGRESS);
    expect(
      parseProgress(JSON.stringify({ seen: ['nope', 'tabs', 'tabs', 3], last: 'nope' })),
    ).toEqual({ ...EMPTY_PROGRESS, seen: ['tabs'] });
  });

  it('сохраняется и читается обратно', () => {
    const p = markSeen(markSeen(EMPTY_PROGRESS, 'welcome'), 'tabs');
    saveProgress(p);
    expect(localStorage.getItem(TOUR_STORAGE_KEY)).toContain('tabs');
    expect(loadProgress()).toEqual(p);
    expect(resumeIndex(p)).toBe(1);
  });

  it('без хранилища тур не падает: чтение — пустой прогресс, запись — молча', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    expect(loadProgress()).toEqual(EMPTY_PROGRESS);
    expect(() => saveProgress(markSeen(EMPTY_PROGRESS, 'tabs'))).not.toThrow();
  });

  it('увиденные шаги по разделам; последний шаг — тур пройден', () => {
    let p = EMPTY_PROGRESS;
    expect(showInvite(p)).toBe(true);
    for (const s of stepsOf('home')) p = markSeen(p, s.id);
    expect(showInvite(p)).toBe(false);
    expect(sectionSeen(p, 'home')).toEqual({
      seen: stepsOf('home').length,
      total: stepsOf('home').length,
    });
    expect(sectionSeen(p, 'videos').seen).toBe(0);
    expect(markSeen(p, p.last!)).toBe(p);
    expect(allSeen(p)).toBe(false);
    for (const s of STEPS) p = markSeen(p, s.id);
    expect(p.finished).toBe(true);
    expect(allSeen(p)).toBe(true);
    expect(resumeIndex(p)).toBeNull();
  });

  it('«пройти заново» забывает шаги, а строку на главной больше не показывает', () => {
    const p = restartProgress(markSeen(EMPTY_PROGRESS, 'tabs'));
    expect(p.seen).toEqual([]);
    expect(p.finished).toBe(false);
    expect(showInvite(p)).toBe(false);
    expect(showInvite({ ...EMPTY_PROGRESS, dismissed: true })).toBe(false);
  });
});

describe('раскладка подсказки', () => {
  const box = (top: number, left: number, width: number, height: number): Box => ({
    top,
    left,
    width,
    height,
  });
  const cardBox = (p: ReturnType<typeof placeCard>, h: number): Box =>
    box(p.top, p.left, p.width, h);
  const insideView = (b: Box, v: View) =>
    b.top >= MARGIN - 0.5 &&
    b.left >= MARGIN - 0.5 &&
    b.top + b.height <= v.height - MARGIN + 0.5 &&
    b.left + b.width <= v.width - MARGIN + 0.5;

  it('без цели: на компьютере посередине, на телефоне у низа', () => {
    const d = placeCard(null, 200, DESKTOP);
    expect(d.side).toBe('center');
    expect(d.left).toBe((1280 - 360) / 2);
    const p = placeCard(null, 200, PHONE);
    expect(p.side).toBe('dock-bottom');
    expect(p.width).toBe(390 - 32);
    expect(insideView(cardBox(p, 200), PHONE)).toBe(true);
  });

  it('компьютер: под целью, если влезает; у низа экрана — над ней; у края — сбоку', () => {
    const under = placeCard(box(100, 100, 200, 40), 220, DESKTOP);
    expect(under.side).toBe('bottom');
    expect(under.top).toBe(152);
    const over = placeCard(box(600, 100, 200, 100), 220, DESKTOP);
    expect(over.side).toBe('top');
    const tall = placeCard(box(40, 40, 400, 720), 220, DESKTOP);
    expect(tall.side).toBe('right');
    for (const p of [under, over, tall]) {
      expect(insideView(cardBox(p, 220), DESKTOP)).toBe(true);
      expect(overlaps(cardBox(p, 220), p.spot!)).toBe(false);
    }
  });

  it('компьютер: цель во весь экран — подсказка в углу, подсветка её не залезает под подсказку', () => {
    const p = placeCard(box(20, 20, 1240, 760), 220, DESKTOP);
    expect(p.side).toBe('dock-bottom');
    expect(insideView(cardBox(p, 220), DESKTOP)).toBe(true);
    expect(overlaps(cardBox(p, 220), p.spot!)).toBe(false);
  });

  it('телефон: во всю ширину, не вылезает за экран и не закрывает подсветку', () => {
    const cases = [
      box(80, 10, 370, 60), // у шапки — под целью
      box(700, 10, 370, 80), // у низа — над целью
      box(60, 10, 370, 700), // высокая — к низу, подсветка обрезана
      box(300, 10, 370, 300), // посередине, ни сверху, ни снизу не влезает
      box(75, 10, 370, 1475), // выше экрана (карточка Studio): верх цели виден над подсказкой
      box(520, 10, 370, 300), // в нижней половине — подсказка над ней
    ];
    for (const c of cases) {
      const spot = spotOf(c, PHONE, 59)!;
      const p = placeCard(spot, 320, PHONE);
      const card = box(p.top, p.left, p.width, p.height);
      const at = JSON.stringify(c);
      expect(p.width).toBe(cardWidth(PHONE));
      expect(insideView(card, PHONE), at).toBe(true);
      expect(p.spot, at).not.toBeNull();
      expect(overlaps(card, p.spot!), at).toBe(false);
      // Верх цели (заголовок) не под подсказкой: подсветка начинается там же, где цель.
      if (p.side !== 'dock-top') expect(p.spot!.top, at).toBe(spot.top);
      // И видно не меньше полосы — или цели целиком, если она ниже полосы.
      expect(p.spot!.height, at).toBeGreaterThanOrEqual(Math.min(spot.height, SHOW) - 1);
    }
    const sides = cases.map((c) => placeCard(spotOf(c, PHONE, 59), 320, PHONE).side);
    expect(sides).toEqual(['bottom', 'top', 'dock-bottom', 'dock-bottom', 'dock-bottom', 'top']);
  });

  it('телефон: подсказка не выше доли экрана; прижатая — сжимается, но не до нуля', () => {
    const tall = placeCard(null, 2000, PHONE);
    expect(tall.height).toBe(Math.round(844 * PHONE_SHARE));
    expect(tall.top).toBe(844 - MARGIN - tall.height);
    const squeezed = placeCard(spotOf(box(200, 10, 370, 1400), PHONE, 59), 500, PHONE);
    expect(squeezed.side).toBe('dock-bottom');
    expect(squeezed.height).toBeLessThan(500);
    expect(squeezed.height).toBeGreaterThanOrEqual(MIN_CARD);
    // Цель в нижней половине, высокая подсказка над ней не влезает — сверху, сжатая.
    const low = spotOf(box(460, 10, 370, 384), PHONE, 59)!;
    const over = placeCard(low, 500, PHONE);
    expect(over.side).toBe('dock-top');
    expect(over.height).toBeLessThan(500);
    expect(overlaps(box(over.top, over.left, over.width, over.height), over.spot!)).toBe(false);
    expect(over.spot!.top).toBe(low.top);
  });

  it('компьютер: подсказка выше экрана сжимается до экрана', () => {
    const p = placeCard(null, 2000, DESKTOP);
    expect(p.top).toBe(MARGIN);
    expect(p.height).toBe(800 - 2 * MARGIN);
  });

  it('подсветка не заходит под шапку и за края; невидимая цель — без подсветки', () => {
    expect(spotOf(box(30, -20, 100, 100), DESKTOP, 60)).toEqual(box(60, 0, 88, 78));
    expect(spotOf(box(-300, 0, 100, 100), DESKTOP, 60)).toBeNull();
    expect(spotOf(box(900, 0, 100, 100), DESKTOP, 60)).toBeNull();
    // Цель в липкой шапке (плашка «только смотреть»): рамка не выходит за низ шапки.
    expect(spotOf(box(60, 0, 1280, 40), DESKTOP, 0, 100)).toEqual(box(52, 0, 1280, 48));
  });

  it('прокрутка: видимую не трогаем, невидимую — к середине; на телефоне — к шапке', () => {
    expect(scrollDelta(box(200, 0, 100, 100), DESKTOP, 60, 200)).toBe(0);
    // Ниже экрана: середина цели встаёт в середину видимой области под шапкой.
    expect(scrollDelta(box(1200, 0, 100, 100), DESKTOP, 60, 200)).toBe(1250 - (76 + 708 / 2));
    // Высокая — верхом под шапку.
    expect(scrollDelta(box(1200, 0, 100, 2000), DESKTOP, 60, 200)).toBe(1200 - 76);
    // Телефон: под целью подсказка не влезает — цель поднимается к шапке.
    expect(scrollDelta(box(300, 0, 300, 300), PHONE, 60, 300)).toBe(300 - 76);
    expect(scrollDelta(box(100, 0, 300, 100), PHONE, 60, 300)).toBe(0);
  });
});
