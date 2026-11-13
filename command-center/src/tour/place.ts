// Где встать подсказке тура и что подсветить. Чистая геометрия (координаты окна, px):
// так её можно проверить без браузера. Правила:
// - на компьютере подсказка шириной 360px встаёт снизу, сверху, справа или слева от цели —
//   там, где помещается целиком и не закрывает её; не поместилась нигде — в правый нижний угол;
// - на телефоне (уже 640px) подсказка во всю ширину с полями 16px — под целью или над ней,
//   а если места нет, прилипает к низу (верх цели в верхней половине экрана) или к верху и
//   сжимается, чтобы верх цели остался виден; подсветка обрезается так, чтобы подсказка её
//   не закрывала;
// - подсветка не заходит под липкую шапку (`safeTop`) и за края окна.

export type Box = { top: number; left: number; width: number; height: number };
export type View = { width: number; height: number };
export type Side = 'bottom' | 'top' | 'right' | 'left' | 'center' | 'dock-bottom' | 'dock-top';
export type Placement = {
  top: number;
  left: number;
  width: number;
  /** Высота, которую подсказке можно занять; содержимое выше — листается внутри. */
  height: number;
  side: Side;
  spot: Box | null;
};

export const PHONE_MAX = 640;
export const CARD_WIDTH = 360;
export const GAP = 12;
export const MARGIN = 16;
/** Поле подсветки вокруг цели: рамка подсветки рисуется в нём, не задевая элемент. */
export const PAD = 8;

export const isPhone = (view: View): boolean => view.width < PHONE_MAX;

export const cardWidth = (view: View): number =>
  isPhone(view)
    ? Math.max(0, view.width - 2 * MARGIN)
    : Math.min(CARD_WIDTH, view.width - 2 * MARGIN);

const bottomOf = (b: Box) => b.top + b.height;
const rightOf = (b: Box) => b.left + b.width;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, Math.max(lo, hi)));

/** Пересекаются ли два прямоугольника (касание краем — не пересечение). */
export function overlaps(a: Box, b: Box): boolean {
  const w = Math.min(rightOf(a), rightOf(b)) - Math.max(a.left, b.left);
  const h = Math.min(bottomOf(a), bottomOf(b)) - Math.max(a.top, b.top);
  return w > 0.5 && h > 0.5;
}

/**
 * Подсветка: цель с полем, обрезанная видимой полосой окна от `safeTop` до `safeBottom` (для
 * целей в липкой шапке — сама шапка: рамка не вылезает за её нижний край); не видна — null.
 */
export function spotOf(
  target: Box,
  view: View,
  safeTop = 0,
  safeBottom: number = view.height,
): Box | null {
  const top = Math.max(target.top - PAD, safeTop);
  const bottom = Math.min(bottomOf(target) + PAD, view.height, safeBottom);
  const left = Math.max(target.left - PAD, 0);
  const right = Math.min(rightOf(target) + PAD, view.width);
  if (bottom - top < 4 || right - left < 4) return null;
  return { top, left, width: right - left, height: bottom - top };
}

/** Обрезать подсветку, чтобы она не уходила под подсказку (подсказка у верха или низа). */
function clipAway(spot: Box, card: Box, side: 'dock-top' | 'dock-bottom'): Box | null {
  if (!overlaps(spot, card)) return spot;
  const top = side === 'dock-top' ? Math.max(spot.top, bottomOf(card) + GAP / 2) : spot.top;
  const bottom =
    side === 'dock-bottom' ? Math.min(bottomOf(spot), card.top - GAP / 2) : bottomOf(spot);
  if (bottom - top < 4) return null;
  return { ...spot, top, height: bottom - top };
}

/** Подсказка на телефоне не выше этой доли экрана, сжатая — не ниже `MIN_CARD` (листается). */
export const PHONE_SHARE = 0.6;
export const MIN_CARD = 180;
/** Сколько цели оставить видимым рядом с прижатой к краю подсказкой. */
export const SHOW = 160;

/**
 * Место подсказки естественной высоты `cardHeight` у подсветки `spot` (null — посреди экрана).
 * `height` — сколько подсказке можно занять (больше — листается внутри).
 */
export function placeCard(spot: Box | null, cardHeight: number, view: View): Placement {
  const width = cardWidth(view);
  const phone = isPhone(view);
  const cap = phone ? Math.round(view.height * PHONE_SHARE) : view.height - 2 * MARGIN;
  const h = Math.max(0, Math.min(cardHeight, cap, view.height - 2 * MARGIN));
  const at = (top: number, left: number, side: Side, s: Box | null, height = h): Placement => ({
    top,
    left,
    width,
    height,
    side,
    spot: s,
  });
  if (!spot) {
    return phone
      ? at(view.height - MARGIN - h, MARGIN, 'dock-bottom', null)
      : at(
          Math.max(MARGIN, (view.height - h) / 2),
          Math.max(MARGIN, (view.width - width) / 2),
          'center',
          null,
        );
  }
  if (phone) {
    const below = view.height - bottomOf(spot) - MARGIN - GAP;
    const above = spot.top - MARGIN - GAP;
    if (below >= h) return at(bottomOf(spot) + GAP, MARGIN, 'bottom', spot);
    if (above >= h) return at(spot.top - GAP - h, MARGIN, 'top', spot);
    // Ни под, ни над целью не помещается. Верх цели в верхней половине экрана — подсказка
    // прижимается к низу и сжимается так, чтобы над ней остался виден верх цели (её заголовок);
    // иначе — к верху, над целью. Подсветка обрезается по подсказке.
    if (spot.top < view.height / 2) {
      const room = view.height - MARGIN - GAP - (spot.top + Math.min(spot.height, SHOW));
      const height = Math.max(Math.min(h, MIN_CARD), Math.min(h, room));
      const top = view.height - MARGIN - height;
      const card = { top, left: MARGIN, width, height };
      return at(top, MARGIN, 'dock-bottom', clipAway(spot, card, 'dock-bottom'), height);
    }
    const height = Math.max(Math.min(h, MIN_CARD), Math.min(h, above));
    const card = { top: MARGIN, left: MARGIN, width, height };
    return at(MARGIN, MARGIN, 'dock-top', clipAway(spot, card, 'dock-top'), height);
  }
  const xUnder = clamp(spot.left, MARGIN, view.width - MARGIN - width);
  const yBeside = clamp(spot.top, MARGIN, view.height - MARGIN - h);
  const tries: { side: Side; top: number; left: number }[] = [
    { side: 'bottom', top: bottomOf(spot) + GAP, left: xUnder },
    { side: 'top', top: spot.top - GAP - h, left: xUnder },
    { side: 'right', top: yBeside, left: rightOf(spot) + GAP },
    { side: 'left', top: yBeside, left: spot.left - GAP - width },
  ];
  for (const t of tries) {
    const box = { top: t.top, left: t.left, width, height: h };
    const inside =
      box.top >= MARGIN - 0.5 &&
      box.left >= MARGIN - 0.5 &&
      bottomOf(box) <= view.height - MARGIN + 0.5 &&
      rightOf(box) <= view.width - MARGIN + 0.5;
    if (inside && !overlaps(box, spot)) return at(t.top, t.left, t.side, spot);
  }
  const top = view.height - MARGIN - h;
  const left = view.width - MARGIN - width;
  const card = { top, left, width, height: h };
  return at(top, left, 'dock-bottom', clipAway(spot, card, 'dock-bottom'));
}

/**
 * На сколько прокрутить страницу, чтобы цель встала удобно (0 — не надо). Компьютер: цель
 * целиком видна — не трогаем, иначе ставим посередине (высокую — верхом под шапку). Телефон:
 * цель видна и подсказка помещается под ней или над ней — не трогаем, иначе цель — к шапке.
 */
export function scrollDelta(target: Box, view: View, safeTop: number, cardHeight: number): number {
  const visible =
    target.top >= safeTop + MARGIN - 1 && bottomOf(target) <= view.height - MARGIN + 1;
  const room = view.height - safeTop - 2 * MARGIN;
  let delta: number;
  if (isPhone(view)) {
    const h = Math.min(cardHeight, Math.round(view.height * PHONE_SHARE));
    const fits =
      view.height - bottomOf(target) - MARGIN - GAP >= h ||
      target.top - safeTop - MARGIN - GAP >= h;
    if (visible && fits) return 0;
    delta = target.top - (safeTop + MARGIN);
  } else {
    if (visible) return 0;
    delta =
      target.height <= room
        ? target.top + target.height / 2 - (safeTop + MARGIN + room / 2)
        : target.top - (safeTop + MARGIN);
  }
  return Math.abs(delta) < 2 ? 0 : Math.round(delta);
}
