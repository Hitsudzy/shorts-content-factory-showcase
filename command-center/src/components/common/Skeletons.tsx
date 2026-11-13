// Скелетоны вместо «Читаю…» (CC-0121): пока запрос идёт, на месте блока стоит заготовка той же
// формы и высоты — когда приходят данные, страница не прыгает.
//
// Как пользоваться: в ветке `q.isPending` поставить пресет нужной формы, сказав `label` — то, что
// раньше было текстом «Читаю …»: он остаётся для читалки (sr-only), глазами видна только форма.
//
//   {q.isPending ? <SkeletonRows rows={3} height={64} label="Читаю копилку…" /> : …}
//
// Высоту подбирать под настоящий блок: строки текста — `SkeletonText` (строка 21 px, как у текста
// 14/1.5), строки списка — `SkeletonRows` с высотой настоящей строки, таблица — `SkeletonTable`,
// карточка целиком — `SkeletonCard`, кинолента — `SkeletonFilmStrip` (те же классы, что у ленты),
// значок — `SkeletonBadge`. Своя форма — `Pending` с полосками `Skeleton` внутри.
// Ошибки и пустые состояния скелетоном не заменяются.
import type { ComponentProps, CSSProperties, ReactNode } from 'react';

import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

/** Текст для читалки по умолчанию. */
export const PENDING_LABEL = 'Загружаю…';

type PendingProps = Omit<ComponentProps<'div'>, 'children'> & {
  /** Что читается — для читалки; глазами не видно. */
  label?: string;
  /**
   * Часть другого скелетона: без своего `role="status"` и текста для читалки — их даёт внешний
   * (один статус на блок).
   */
  bare?: boolean;
  children?: ReactNode;
};

/**
 * Обёртка скелетона: `role="status"`, `aria-busy`, скрытое «Загружаю…» (или `label`). Внутри —
 * полоски `Skeleton` любой формы; сама обёртка ничего не рисует.
 */
export function Pending({
  label = PENDING_LABEL,
  bare = false,
  className,
  children,
  ...props
}: PendingProps) {
  if (bare)
    return (
      <div data-slot="pending-part" className={cn('grid min-w-0 gap-2', className)} {...props}>
        {children}
      </div>
    );
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      data-slot="pending"
      className={cn('grid min-w-0 gap-2', className)}
      {...props}
    >
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

type Width = string | number;
const widthStyle = (w: Width): CSSProperties => ({ width: typeof w === 'number' ? `${w}%` : w });

/** Ширины строк по кругу: последняя строка абзаца короче — так скелетон похож на текст. */
const LINE_WIDTHS: number[] = [92, 78, 85, 64];

/** Одна строка текста высотой `lineHeight` (по умолчанию 21 px — текст 14/1.5). */
function Line({
  width,
  lineHeight = 21,
  bar = 12,
}: {
  width: Width;
  lineHeight?: number;
  bar?: number;
}) {
  return (
    <span className="flex items-center" style={{ height: lineHeight }}>
      <Skeleton style={{ ...widthStyle(width), height: bar }} />
    </span>
  );
}

/**
 * Строки текста. `lines` — сколько строк у настоящего текста; `lineHeight` — высота строки (px);
 * `widths` — ширины строк (проценты или CSS), иначе — по кругу из «текстовых».
 */
export function SkeletonText({
  lines = 1,
  lineHeight = 21,
  widths,
  label,
  className,
  ...props
}: PendingProps & { lines?: number; lineHeight?: number; widths?: Width[] }) {
  return (
    <Pending label={label} className={cn('gap-0', className)} data-skeleton="text" {...props}>
      {Array.from({ length: lines }, (_, i) => (
        <Line
          key={i}
          lineHeight={lineHeight}
          bar={Math.max(8, Math.round(lineHeight * 0.55))}
          width={
            widths?.[i] ??
            (lines > 1 && i === lines - 1 ? 52 : LINE_WIDTHS[i % LINE_WIDTHS.length]!)
          }
        />
      ))}
    </Pending>
  );
}

/** «Подробнее» под списком (`More`): отступ 12 и строка `text-xs` (16 px). */
export function SkeletonMore({ className }: { className?: string }) {
  return (
    <span className={cn('mt-3 flex h-4 items-center', className)}>
      <Skeleton className="h-2.5 w-20" />
    </span>
  );
}

/** Шапка карточки как у `CardHead`: подпись капителью (18 px), заголовок (2 + 25,5 px), отступ 14. */
function HeadBars() {
  return (
    <span className="mb-3.5 block">
      <Line width="22%" lineHeight={18} bar={10} />
      <span className="mt-0.5 flex h-[25.5px] items-center">
        <Skeleton className="h-4 w-[46%]" />
      </span>
    </span>
  );
}

/** Рамка карточки и её строки — без обёртки `Pending` (общая для `SkeletonCard` и `SkeletonPage`). */
function CardBars({
  rows,
  head,
  more = false,
  className,
  children,
}: {
  rows: number;
  head: boolean;
  more?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <span className={cn('block rounded-lg border bg-card p-card', className)}>
      {head ? <HeadBars /> : null}
      {Array.from({ length: rows }, (_, i) => (
        <Line
          key={i}
          width={rows > 1 && i === rows - 1 ? 52 : LINE_WIDTHS[i % LINE_WIDTHS.length]!}
        />
      ))}
      {children}
      {more ? <SkeletonMore /> : null}
    </span>
  );
}

/**
 * Карточка целиком (`Card` + `CardHead`): рамка, шапка и `rows` строк текста. Для блоков, которые
 * до ответа не рисуют даже своей карточки. `children` — что ещё внутри карточки после строк
 * (другие пресеты с `bare`).
 */
export function SkeletonCard({
  rows = 3,
  head = true,
  more = false,
  label,
  className,
  children,
  ...props
}: PendingProps & { rows?: number; head?: boolean; more?: boolean }) {
  return (
    <Pending label={label} className="gap-0" data-skeleton="card" {...props}>
      <CardBars rows={rows} head={head} more={more} className={className}>
        {children}
      </CardBars>
    </Pending>
  );
}

/**
 * Строки списка: `rows` рамок высотой `height` (px) через `gap` (px) — под настоящие строки
 * (карточки роликов, вопросы, события). `bordered={false}` — строки без рамки (лента событий).
 */
export function SkeletonRows({
  rows = 3,
  height = 56,
  gap = 8,
  bordered = true,
  label,
  className,
  style,
  ...props
}: PendingProps & { rows?: number; height?: number; gap?: number; bordered?: boolean }) {
  return (
    <Pending
      label={label}
      className={className}
      style={{ gap, ...style }}
      data-skeleton="rows"
      {...props}
    >
      {Array.from({ length: rows }, (_, i) => (
        <span
          key={i}
          className={cn('flex min-w-0 items-center gap-3', bordered && 'rounded-sm border px-3')}
          style={{ height }}
        >
          <span className="grid min-w-0 flex-1 gap-1.5">
            <Skeleton
              className="h-3.5"
              style={widthStyle(LINE_WIDTHS[i % LINE_WIDTHS.length]! - 30)}
            />
            {height >= 44 ? <Skeleton className="h-3 w-1/4" /> : null}
          </span>
          <Skeleton className="h-5 w-14 shrink-0 rounded-full" />
        </span>
      ))}
    </Pending>
  );
}

/**
 * Список карточки (`.list` макета: строки через черту, `py-[11px]`, у первой сверху без отступа)
 * — каналы и агенты главной, факты «Фабрики». `avatar` — кружок 34 px слева; `sub` — сколько
 * строк мелкого текста (`text-xs`, 16 px) под основной у каждой строки (число или по строкам); `badge` —
 * значок справа; `more` — «подробнее» под списком.
 */
export function SkeletonList({
  rows = 3,
  avatar = false,
  sub = 0,
  badge = true,
  more = false,
  label,
  className,
  ...props
}: PendingProps & {
  rows?: number;
  avatar?: boolean;
  sub?: number | number[];
  badge?: boolean;
  more?: boolean;
}) {
  return (
    <Pending label={label} className={cn('gap-0', className)} data-skeleton="list" {...props}>
      <span className="grid">
        {Array.from({ length: rows }, (_, i) => {
          const n = Array.isArray(sub) ? (sub[i] ?? 0) : sub;
          return (
            <span
              key={i}
              className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-t py-[11px] first:border-t-0 first:pt-0"
            >
              {avatar ? (
                <Skeleton className="size-[34px] rounded-full" />
              ) : (
                <span className="w-0" />
              )}
              <span className="grid min-w-0">
                <Line width={LINE_WIDTHS[i % LINE_WIDTHS.length]! - 40} />
                {Array.from({ length: n }, (_, j) => (
                  <Line key={j} width={j ? 40 : 70} lineHeight={16} bar={9} />
                ))}
              </span>
              {badge ? (
                <Skeleton className="h-[23px] w-[4.5rem] rounded-full" />
              ) : (
                <span className="w-0" />
              )}
            </span>
          );
        })}
      </span>
      {more ? <SkeletonMore /> : null}
    </Pending>
  );
}

/**
 * Плитки с картинкой (обложки роликов 9:16, мемы 4:3): `count` плиток в сетке `className`
 * (колонки — как у настоящей сетки), под картинкой `lines` строк подписи (13/1.35) и значок.
 */
export function SkeletonTiles({
  count = 6,
  aspect = '9 / 16',
  lines = 1,
  badge = true,
  label,
  className,
  ...props
}: PendingProps & { count?: number; aspect?: string; lines?: number; badge?: boolean }) {
  return (
    <Pending label={label} className={cn('gap-3', className)} data-skeleton="tiles" {...props}>
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className="grid min-w-0 content-start gap-2 p-1">
          <Skeleton className="w-full" style={{ aspectRatio: aspect }} />
          <span className="grid gap-1">
            {Array.from({ length: lines }, (_, j) => (
              <Line key={j} width={j ? 50 : 85} lineHeight={17.5} bar={10} />
            ))}
            {badge ? <Skeleton className="h-[22px] w-20 rounded-sm" /> : null}
          </span>
        </span>
      ))}
    </Pending>
  );
}

/**
 * Таблица: строка заголовка (`header`, 33 px) и `rows` строк высотой `rowHeight` (px, по
 * умолчанию 37 — ячейка 13/1.5 с отступами 8) на `cols` колонок.
 */
export function SkeletonTable({
  rows = 5,
  cols = 4,
  rowHeight = 37,
  header = true,
  label,
  className,
  ...props
}: PendingProps & { rows?: number; cols?: number; rowHeight?: number; header?: boolean }) {
  const line = (key: string, h: number, bar: string, head = false) => (
    <span
      key={key}
      className={cn('grid items-center gap-4 border-b', head && 'border-border')}
      style={{ height: h, gridTemplateColumns: `2fr repeat(${Math.max(cols - 1, 0)}, 1fr)` }}
    >
      {Array.from({ length: cols }, (_, c) => (
        <Skeleton key={c} className={bar} style={widthStyle(c === 0 ? 70 : 50)} />
      ))}
    </span>
  );
  return (
    <Pending label={label} className={cn('gap-0', className)} data-skeleton="table" {...props}>
      {header ? line('head', 33, 'h-2.5', true) : null}
      {Array.from({ length: rows }, (_, i) => line(String(i), rowHeight, 'h-3'))}
    </Pending>
  );
}

/**
 * Кинолента из `frames` кадров — те же классы рамки и кадра, что у `FilmStrip`
 * (src/pages/batches/FilmStrip.tsx): высота ленты та же, пока стадии читаются.
 */
export function SkeletonFilmStrip({
  frames = 6,
  label,
  className,
  ...props
}: PendingProps & { frames?: number }) {
  return (
    <Pending label={label} className="gap-0" data-skeleton="film" {...props}>
      <span
        style={{ '--film-cols': `repeat(${frames}, minmax(0, 1fr))` } as CSSProperties}
        className={cn(
          'film-strip grid grid-cols-1 gap-2 rounded-sm px-4 py-2.5 lg:grid-cols-(--film-cols) lg:px-2.5 lg:py-[18px]',
          className,
        )}
      >
        {Array.from({ length: frames }, (_, i) => (
          <span
            key={i}
            className="film-frame grid grid-cols-[40px_1fr] gap-x-2 rounded-[3px] px-2.5 py-2 lg:flex lg:min-h-[98px] lg:flex-col lg:gap-[3px] lg:p-2.5"
          >
            <span className="flex h-[16px] items-center">
              <Skeleton className="h-2.5 w-5 bg-[#2a2a38]" />
            </span>
            <span className="flex h-[19.5px] items-center">
              <Skeleton className="h-3 w-4/5 bg-[#2a2a38]" />
            </span>
          </span>
        ))}
      </span>
    </Pending>
  );
}

/** Значок-пилюля (как `StatusBadge`) в строке: `width` — CSS-ширина, по умолчанию 4.5rem. */
export function SkeletonBadge({
  width = '4.5rem',
  label = PENDING_LABEL,
  className,
}: {
  width?: Width;
  label?: string;
  className?: string;
}) {
  return (
    <span
      role="status"
      aria-busy="true"
      data-slot="pending"
      data-skeleton="badge"
      className={cn('inline-flex align-middle', className)}
    >
      <span className="sr-only">{label}</span>
      <Skeleton className="h-[22px] rounded-full" style={widthStyle(width)} />
    </span>
  );
}

/**
 * Страница целиком, пока грузится её кусок кода: шапка и две карточки — чтобы оболочка не
 * мигала пустотой и строкой «Загружаю…».
 */
export function SkeletonPage({ label = PENDING_LABEL }: { label?: string }) {
  return (
    <Pending label={label} className="gap-(--space-gap) p-(--space-gutter)" data-skeleton="page">
      <span className="grid gap-1.5">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-6 w-64 max-w-full" />
      </span>
      <CardBars rows={3} head />
      <CardBars rows={4} head />
    </Pending>
  );
}
