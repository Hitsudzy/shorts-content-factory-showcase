import { useLayoutEffect, useRef } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router';

import { useToken } from '@/api/oauth';
import { useWriteLocked } from '@/api/writeLock';
import { useOpenCount } from '@/api/questions';
import { useAnsweredCount } from '@/api/requests';
import { CountBadge } from '@/components/common/CountBadge';
import { AskHeaderButton, AskProvider } from '@/components/ask/AskDialog';
import { BellIcon } from '@/components/common/icons';
import { Tip } from '@/components/common/Tip';
import { ApiStatus } from '@/components/shell/ApiStatus';
import { LogoutButton } from '@/components/shell/LogoutButton';
import { ThemeToggle } from '@/components/shell/ThemeToggle';
import { ToastProvider } from '@/components/common/Toast';
import { DevWritesBadge, ReadOnlyBanner } from '@/components/shell/Writes';
import { StudioHeaderButton } from '@/components/studio/StudioHeaderButton';
import { WriteLock } from '@/components/shell/WriteLock';
import { Button } from '@/components/ui/button';
import { TooltipProvider } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { TourProvider } from '@/tour/Tour';
import { TourButton } from '@/tour/TourButtons';
import { TrainingSlot } from '@/training/TrainingSlot';

import { activeAreaPath, AREAS } from './areas';

/** Внутренняя ширина: на компьютере поле --space-gutter, на телефоне 16px, не шире 1280. */
const INNER = 'mx-auto w-full max-w-[1280px] px-gutter';

function Header() {
  return (
    <header className="sticky top-0 z-10 border-b bg-background">
      <div className={cn(INNER, 'flex items-center gap-2.5 py-3 sm:gap-4 sm:py-3.5')}>
        {/* CC-0085: знак — ссылка на главную; вид прежний, кольцо фокуса и лёгкий ховер. */}
        <Link
          to="/"
          aria-label="На главную"
          className="rounded-sm font-display text-[22px] font-semibold tracking-[.06em] whitespace-nowrap uppercase transition-opacity hover:opacity-80 motion-reduce:transition-none"
        >
          Example<em className="text-primary-text not-italic">Co</em>
          <small className="ml-2 hidden font-sans text-xs font-medium tracking-[.08em] text-muted-foreground sm:inline">
            КОМАНДНЫЙ ЦЕНТР
          </small>
        </Link>
        <div className="hidden flex-wrap gap-2 sm:flex">
          <ApiStatus />
        </div>
        <DevWritesBadge />
        <div className="ml-auto flex items-center gap-2">
          {/* CC-0151: «Пора прочитать Studio» — кнопка с окошком вместо полосы под шапкой. */}
          <StudioHeaderButton />
          <ThemeToggle />
          <Tip content="Уведомления и напоминания: что фабрика вам отправила и что напомнит">
            <Button asChild size="icon" data-tour="tip-example">
              <NavLink to="/notifications" aria-label="Уведомления и напоминания">
                <BellIcon className="size-[17px]" />
              </NavLink>
            </Button>
          </Tip>
          <TourButton />
          <AskHeaderButton />
          <LogoutButton />
        </div>
      </div>
      <ReadOnlyBanner className={INNER} />
      <TrainingSlot className={INNER} />
    </header>
  );
}

function questionsTip(tip: string, asked: number | null, answered: number | null): string {
  const parts = [tip];
  if (asked) parts.push(`Ждут ответа: ${asked}`);
  if (answered) parts.push(`Ответ на просьбы: ${answered}`);
  return parts.join('. ');
}

/** Точка у «Токены» (как в макете): токен скоро истечёт или не действует; «ok» — без точки. */
function useTokenMark(): { tone: 'warn' | 'danger'; tip: string } | null {
  const q = useToken();
  const kind = q.data?.kind;
  if (!kind || kind === 'ok') return null;
  const soon = kind === 'expires-soon' || kind === 'unknown-expiry';
  return {
    tone: soon ? 'warn' : 'danger',
    tip:
      kind === 'expires-soon'
        ? 'Токен YouTube скоро истечёт — переразрешите заранее'
        : kind === 'unknown-expiry'
          ? 'Срок токена YouTube неизвестен — переразрешите'
          : 'Токен YouTube не действует — загрузка и метрики стоят',
  };
}

/**
 * Полоса табов. Активный таб считается здесь (`activeAreaPath`), а не `NavLink`-функцией в
 * `className`: таб обёрнут в `Tip` (Radix `asChild`), и Slot склеивает `className` строкой —
 * функция `NavLink` превращалась в свой исходный текст, и активного вида не было (CC-0085).
 */
function Tabs() {
  const asked = useOpenCount();
  const answered = useAnsweredCount();
  const token = useTokenMark();
  const { pathname } = useLocation();
  const active = activeAreaPath(pathname);
  const strip = useRef<HTMLDivElement>(null);

  // На телефоне полоса прокручивается вбок: активный таб — в видимую область (по центру,
  // только если он за краем). Прокручиваем саму полосу, не страницу. Табы меняют ширину и
  // после первого кадра (пришёл счётчик «Вопросы», точка «Токены», догрузился шрифт) —
  // поэтому ещё раз, когда меняется размер табов.
  useLayoutEffect(() => {
    const box = strip.current;
    if (!box) return;
    const reveal = () => {
      const el = box.querySelector<HTMLElement>('[aria-current="page"]');
      if (!el) return;
      const left = el.offsetLeft;
      const right = left + el.offsetWidth;
      if (left >= box.scrollLeft && right <= box.scrollLeft + box.clientWidth) return;
      box.scrollLeft = Math.max(0, left - (box.clientWidth - el.offsetWidth) / 2);
    };
    reveal();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(reveal);
    for (const el of box.children) ro.observe(el);
    return () => ro.disconnect();
  }, [active]);

  return (
    <nav aria-label="Разделы" className="border-b" data-tour="tabs">
      <div
        ref={strip}
        data-testid="tabs-strip"
        className="no-scrollbar relative mx-auto flex max-w-[1280px] gap-0.5 overflow-x-auto px-1.5 sm:px-[calc(var(--space-gutter)-10px)]"
      >
        {AREAS.map((area) => {
          const isActive = area.path === active;
          return (
            <Tip
              key={area.path}
              content={
                area.path === 'questions'
                  ? questionsTip(area.tip, asked, answered)
                  : area.path === 'tokens' && token
                    ? `${area.tip}. ${token.tip}`
                    : area.tip
              }
            >
              <Link
                to={`/${area.path}`}
                aria-current={isActive ? 'page' : undefined}
                data-active={isActive || undefined}
                className={cn(
                  'inline-flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 pt-3 pb-[11px] text-[13px] whitespace-nowrap',
                  isActive
                    ? 'border-primary-text font-semibold text-foreground'
                    : // CC-0085: ховер — подпись `--foreground` и намёк на подчёркивание
                      // приглушённым тоном (не акцентом: акцент — только у активного). Tailwind
                      // `hover:` — под `@media (hover: hover)`, на касании не залипает.
                      'border-transparent text-muted-foreground transition-colors hover:border-muted-foreground/50 hover:text-foreground motion-reduce:transition-none',
                )}
              >
                {area.short}
                {area.path === 'questions' ? (
                  <CountBadge n={asked} label="ждут ответа" small decorative />
                ) : null}
                {area.path === 'tokens' && token ? (
                  <span
                    aria-hidden
                    data-testid="tab-token-mark"
                    data-tone={token.tone}
                    className={cn(
                      'inline-block size-1.5 shrink-0 rounded-full',
                      token.tone === 'warn' ? 'bg-warning' : 'bg-danger',
                    )}
                  />
                ) : null}
              </Link>
            </Tip>
          );
        })}
      </div>
    </nav>
  );
}

export function Layout() {
  // CC-0084: пока запись в полёте — центр под слоем `WriteLock`, страница помечена занятой.
  const locked = useWriteLocked();
  return (
    <TooltipProvider>
      <ToastProvider>
        <AskProvider>
          <TourProvider>
            <WriteLock />
            <div className="min-h-screen" aria-busy={locked || undefined}>
              <Header />
              <Tabs />
              <main className={cn(INNER, 'grid gap-gap py-gutter')}>
                <Outlet />
              </main>
            </div>
          </TourProvider>
        </AskProvider>
      </ToastProvider>
    </TooltipProvider>
  );
}
