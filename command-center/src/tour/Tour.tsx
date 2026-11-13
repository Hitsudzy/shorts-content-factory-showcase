// Тур «Обучение» (CC-0072): подсказки поверх интерфейса с подсветкой элемента.
//
// Тур только показывает: поверх страницы лежит прозрачный слой, который ловит клики, — под
// туром ничего не нажать, а сам тур нажимает только ссылки перехода (открыть канал или ролик,
// `open` у шага). Записей тур не шлёт.
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';
import { useLocation, useNavigate } from 'react-router';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { enterTraining, exitTraining, isTraining } from '@/training/mode';

import { CLOSED, reduceModel, tourTiming } from './engine';
import { MARGIN, placeCard, scrollDelta, spotOf, type Box, type View } from './place';
import {
  loadProgress,
  resumeIndex,
  saveProgress,
  sectionSeen,
  type TourProgress,
} from './progress';
import {
  SECTIONS,
  STEPS,
  onRoute,
  sectionOf,
  sectionStart,
  stepLabel,
  type TourStep,
} from './steps';
import { TourContext, type TourApi } from './useTour';

type Status = 'none' | 'pending' | 'found' | 'missing';

/**
 * Рамка подсветки: тёмная линия внутри и снаружи жёлтой рамки (видна и на светлой, и на тёмной
 * странице), мягкое свечение акцентом и затемнение остального экрана.
 */
const SPOT_SHADOW = [
  'inset 0 0 0 1.5px rgb(5 5 10 / 0.85)',
  '0 0 0 2px rgb(5 5 10 / 0.9)',
  '0 0 22px 4px color-mix(in srgb, var(--primary) 55%, transparent)',
  '0 0 0 200vmax rgb(5 5 10 / 0.62)',
].join(', ');

/** Естественная высота подсказки: содержимое + поля и рамка самой подсказки. */
function naturalHeight(card: HTMLElement | null, inner: HTMLElement | null): number {
  if (!card || !inner) return 240;
  const st = getComputedStyle(card);
  const frame =
    parseFloat(st.paddingTop) +
    parseFloat(st.paddingBottom) +
    parseFloat(st.borderTopWidth) +
    parseFloat(st.borderBottomWidth);
  return Math.ceil(inner.offsetHeight + (Number.isFinite(frame) ? frame : 0));
}

/** Первый видимый элемент с меткой `data-tour`. */
function findTarget(name: string): HTMLElement | null {
  for (const el of document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`)) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return el;
  }
  return null;
}

/** Ссылка перехода шага: сама метка на `<a>` или первая ссылка внутри неё. */
function findLink(name: string): HTMLAnchorElement | null {
  const el = findTarget(name);
  if (!el) return null;
  return el instanceof HTMLAnchorElement ? el : el.querySelector<HTMLAnchorElement>('a[href]');
}

const boxOf = (r: DOMRect): Box => ({
  top: r.top,
  left: r.left,
  width: r.width,
  height: r.height,
});
const sameBox = (a: Box | null, b: Box | null) =>
  a === b ||
  (!!a &&
    !!b &&
    Math.abs(a.top - b.top) < 0.5 &&
    Math.abs(a.left - b.left) < 0.5 &&
    Math.abs(a.width - b.width) < 0.5 &&
    Math.abs(a.height - b.height) < 0.5);

const viewNow = (): View => ({
  width: document.documentElement.clientWidth || window.innerWidth,
  height: window.innerHeight,
});

/**
 * Полоса окна, где можно рисовать подсветку: под липкой шапкой; у целей в самой шапке — сама
 * шапка (рамка не выходит за её нижний край на страницу).
 */
function bandOf(el: HTMLElement): { top: number; bottom: number } {
  const header = document.querySelector('header');
  const edge = header ? Math.max(0, header.getBoundingClientRect().bottom) : 0;
  return el.closest('header') ? { top: 0, bottom: edge } : { top: edge, bottom: Infinity };
}

/**
 * Ищет цель шага, докручивает к ней страницу и следит за её местом каждый кадр. Нет цели —
 * сначала переход по ссылке `open`, потом ждём до `tourTiming.waitMs` и честно говорим «нет».
 */
function useStepTarget(step: TourStep, ready: boolean, cardHeight: () => number) {
  const [status, setStatus] = useState<Status>(step.target ? 'pending' : 'none');
  const [rect, setRect] = useState<Box | null>(null);
  const [band, setBand] = useState({ top: 0, bottom: Infinity });

  // Подсказка пересоздаётся на каждый шаг (key), поэтому начальное состояние — уже этого шага.
  useEffect(() => {
    if (!step.target || !ready) return;
    const target = step.target;
    let started = performance.now();
    let opened = false;
    let scrolledAt = 0;
    let foundAt = 0;
    let scrolls = 0;
    let lastLook = 0;
    let el: HTMLElement | null = null;
    let state: Status = 'pending';
    let box: Box | null = null;
    let frame = 0;
    const set = (s: Status) => {
      if (s !== state) setStatus((state = s));
    };
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      if (!el?.isConnected || el.getClientRects().length === 0) {
        el = null;
        // Не нашли — ищем часто, пока ждём, и изредка потом (данные могут прийти позже).
        if (state === 'missing' && now - lastLook < 500) return;
        lastLook = now;
        el = findTarget(target);
        if (!el) {
          if (box) setRect((box = null));
          if (step.open && !opened) {
            const link = findLink(step.open);
            if (link) {
              opened = true;
              started = now;
              link.click();
              return;
            }
          }
          if (now - started > tourTiming.waitMs) set('missing');
          return;
        }
      }
      set('found');
      if (!foundAt) foundAt = now;
      const view = viewNow();
      const b = bandOf(el);
      const top = b.top;
      let r = boxOf(el.getBoundingClientRect());
      // Докрутить к цели: сразу и ещё несколько раз в первые секунды — пока догружаются данные
      // выше цели и сдвигают её; потом — только если цель совсем ушла с экрана.
      const settling = now - foundAt < 3000 && scrolls < 6;
      if (scrolledAt === 0 || (now - scrolledAt > 300 && (settling || !spotOf(r, view, top)))) {
        scrolledAt = now;
        const dy = scrollDelta(r, view, top, cardHeight());
        if (dy) {
          const y = window.scrollY;
          window.scrollBy({ top: dy, behavior: 'instant' });
          // Страница дальше не листается — не повторять попусту.
          scrolls = window.scrollY === y ? 6 : scrolls + 1;
          r = boxOf(el.getBoundingClientRect());
        }
      }
      if (!sameBox(box, r)) setRect((box = r));
      setBand((o) =>
        Math.abs(o.top - b.top) < 0.5 &&
        (o.bottom === b.bottom || Math.abs(o.bottom - b.bottom) < 0.5)
          ? o
          : b,
      );
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [step, ready, cardHeight]);

  return { status, rect, band };
}

function StepCard({
  index,
  onNext,
  onBack,
  onClose,
  onMenu,
}: {
  index: number;
  onNext: () => void;
  onBack: () => void;
  onClose: () => void;
  onMenu: () => void;
}) {
  const step = STEPS[index]!;
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const ready = onRoute(step, pathname);
  const cardRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const [cardH, setCardH] = useState(240);
  const [view, setView] = useState<View>(viewNow);
  // Естественная высота подсказки — по содержимому: сжатая подсказка листается внутри, и
  // её собственная высота уже не говорит, сколько ей нужно.
  const cardHeight = useCallback(() => naturalHeight(cardRef.current, innerRef.current), []);
  const { status, rect, band } = useStepTarget(step, ready, cardHeight);
  const titleId = useId();
  const bodyId = useId();

  // Не на экране шага — перейти (тур сам ходит между экранами).
  useEffect(() => {
    if (!ready) void navigate(step.route);
  }, [ready, step, navigate]);

  // Фокус — на подсказку, при каждом шаге.
  useEffect(() => {
    cardRef.current?.focus({ preventScroll: true });
  }, [index]);

  useLayoutEffect(() => {
    const inner = innerRef.current;
    if (!inner) return;
    const measure = () => {
      setCardH(cardHeight());
      setView(viewNow());
    };
    measure();
    // jsdom (Vitest) без ResizeObserver — там хватает изменения окна.
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    ro?.observe(inner);
    window.addEventListener('resize', measure);
    return () => {
      ro?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [cardHeight]);

  const spot = rect ? spotOf(rect, view, band.top, band.bottom) : null;
  const place = placeCard(spot, cardH, view);
  const section = sectionOf(step.section);
  const last = index === STEPS.length - 1;

  return (
    <>
      {place.spot ? (
        <div
          aria-hidden
          data-testid="tour-spot"
          className="pointer-events-none fixed z-[71] rounded-[10px] border-[3px] border-primary motion-safe:transition-[top,left,width,height] motion-safe:duration-150"
          style={{
            top: place.spot.top,
            left: place.spot.left,
            width: place.spot.width,
            height: place.spot.height,
            boxShadow: SPOT_SHADOW,
          }}
        />
      ) : (
        <div
          aria-hidden
          className="pointer-events-none fixed inset-0 z-[71] bg-[rgb(5_5_10/0.62)]"
        />
      )}
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        data-testid="tour-card"
        data-step={step.id}
        data-section={step.section}
        data-target={status}
        data-side={place.side}
        className="fixed z-[72] overflow-y-auto overscroll-contain rounded-lg border border-primary bg-card p-4 text-card-foreground shadow-2xl outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-5"
        style={{
          top: place.top,
          left: place.left,
          width: place.width,
          maxHeight: place.height,
        }}
      >
        <div ref={innerRef} className="grid gap-3">
          <div className="flex items-center justify-between gap-2">
            <span className="eyebrow">{section.title}</span>
            <span className="font-mono text-xs text-muted-foreground" data-testid="tour-count">
              {stepLabel(index)}
            </span>
          </div>
          <div
            className="h-1 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-label="Пройдено шагов"
            aria-valuemin={1}
            aria-valuemax={STEPS.length}
            aria-valuenow={index + 1}
          >
            <div
              className="h-full bg-primary"
              style={{ width: `${((index + 1) / STEPS.length) * 100}%` }}
            />
          </div>
          <h2 id={titleId} className="m-0 font-display text-lg font-semibold tracking-[.02em]">
            {step.title}
          </h2>
          <div id={bodyId} className="grid gap-2 text-[13px] leading-[1.5]">
            {step.body.map((p) => (
              <p key={p} className="m-0">
                {p}
              </p>
            ))}
            {status === 'pending' ? (
              <p role="status" className="m-0 animate-pulse text-muted-foreground">
                Ищу это на экране…
              </p>
            ) : status === 'missing' ? (
              <p
                role="status"
                data-testid="tour-missing"
                className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] p-2 text-muted-foreground"
              >
                {step.missing ?? 'Сейчас этого на экране нет.'}
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="default" data-testid="tour-next" onClick={onNext}>
              {last ? 'Готово' : 'Дальше'}
            </Button>
            {last && !isTraining() ? (
              <Button data-testid="tour-practice-start" onClick={() => enterTraining()}>
                Начать тренировку
              </Button>
            ) : null}
            <Button data-testid="tour-back" disabled={index === 0} onClick={onBack}>
              Назад
            </Button>
            <Button variant="ghost" data-testid="tour-skip" className="ml-auto" onClick={onClose}>
              Пропустить
            </Button>
          </div>
          <button
            type="button"
            data-testid="tour-menu"
            className="w-max cursor-pointer text-xs text-primary-text underline-offset-4 hover:underline"
            onClick={onMenu}
          >
            Оглавление обучения
          </button>
        </div>
      </div>
    </>
  );
}

/**
 * Тренировка (CC-0073) в оглавлении: центр перезагрузится на демо-данных. Уже в ней — выход.
 */
function PracticeEntry() {
  const on = isTraining();
  return (
    <button
      type="button"
      data-testid="tour-practice"
      data-training={on ? 'on' : 'off'}
      onClick={() => (on ? void exitTraining() : enterTraining())}
      className="grid w-full cursor-pointer grid-cols-[1fr_auto] items-center gap-x-3 rounded-sm border border-dashed border-primary bg-transparent px-3 py-2 text-left hover:border-solid"
    >
      <span className="text-sm font-semibold">Тренировка</span>
      <span className="text-xs text-primary-text">
        {on ? 'Выйти из тренировки' : 'Начать тренировку'}
      </span>
      <span className="col-span-2 text-xs text-muted-foreground">
        {on
          ? 'Вы в тренировке: задания — в панели, фабрика не трогается.'
          : 'Попробовать кнопки самому на учебных данных: центр перезагрузится на демо, фабрика не трогается.'}
      </span>
    </button>
  );
}

function Menu({
  progress,
  onStart,
  onRestart,
  onClose,
}: {
  progress: TourProgress;
  onStart: (index: number) => void;
  onRestart: () => void;
  onClose: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const resume = resumeIndex(progress);
  const started = progress.seen.length > 0;
  const [frame, setFrame] = useState<{ top: number; maxHeight: number } | null>(null);
  useEffect(() => {
    cardRef.current?.focus({ preventScroll: true });
  }, []);
  // Оглавление — посередине, но не выше низа шапки с полем: шапку и её плашки не закрывает.
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    const measure = () => {
      const header = document.querySelector('header')?.getBoundingClientRect().bottom ?? 0;
      const vh = window.innerHeight;
      const maxHeight = Math.max(200, vh - Math.max(0, header) - 2 * MARGIN);
      const h = Math.min(card.offsetHeight, maxHeight);
      setFrame({ top: Math.max(Math.max(0, header) + MARGIN, (vh - h) / 2), maxHeight });
    };
    measure();
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    ro?.observe(card);
    window.addEventListener('resize', measure);
    return () => {
      ro?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, []);
  return (
    <div
      ref={cardRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
      data-testid="tour-contents"
      style={frame ?? undefined}
      className="fixed top-1/2 left-1/2 z-[72] flex max-h-[calc(100dvh-32px)] w-[min(520px,calc(100vw-32px))] -translate-x-1/2 flex-col overflow-hidden rounded-lg border bg-card text-card-foreground shadow-2xl outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {/* Шапка и низ с кнопками стоят на месте, листается только список разделов: «Закрыть»
          всегда на экране — и на компьютере, и на телефоне. */}
      <div className="grid shrink-0 gap-2 px-4 pt-4 sm:px-5 sm:pt-5">
        <div>
          <div className="eyebrow">Обучение</div>
          <h2 id={titleId} className="m-0 mt-0.5 font-display text-xl font-semibold uppercase">
            Как пользоваться центром
          </h2>
        </div>
        <p className="m-0 text-[13px] leading-[1.5] text-muted-foreground">
          Короткий тур: подсказки поверх экрана покажут, где что лежит и как этим пользоваться. Тур
          только показывает — сам ничего не нажимает и в фабрике ничего не меняет. Можно начать с
          любого раздела.
        </p>
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-3 sm:px-5"
        data-testid="tour-contents-list"
      >
        <ol className="m-0 grid list-none gap-1.5 p-0" aria-label="Разделы обучения">
          {SECTIONS.map((s) => {
            const r = sectionSeen(progress, s.id);
            const done = r.seen === r.total;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  data-testid="tour-section"
                  data-section={s.id}
                  data-done={done ? 'yes' : 'no'}
                  onClick={() => onStart(sectionStart(s.id))}
                  className="grid w-full cursor-pointer grid-cols-[1fr_auto] items-center gap-x-3 rounded-sm border bg-transparent px-3 py-2 text-left hover:border-muted-foreground"
                >
                  <span className="text-sm font-semibold">{s.title}</span>
                  <span
                    className={cn('text-xs', done ? 'text-success' : 'text-muted-foreground')}
                    data-testid="tour-section-state"
                  >
                    {done ? 'пройдено' : r.seen ? `${r.seen} из ${r.total}` : `шагов: ${r.total}`}
                  </span>
                  <span className="col-span-2 text-xs text-muted-foreground">{s.about}</span>
                </button>
              </li>
            );
          })}
          <li>
            <PracticeEntry />
          </li>
        </ol>
      </div>
      <div
        className="flex shrink-0 flex-wrap items-center gap-2 border-t px-4 py-3 sm:px-5"
        data-testid="tour-contents-footer"
      >
        {resume !== null ? (
          <Button
            variant="default"
            data-testid="tour-resume"
            className="h-auto min-h-[34px] py-1.5 whitespace-normal"
            onClick={() => onStart(resume)}
          >
            Продолжить: {sectionOf(STEPS[resume]!.section).title}, шаг {stepLabel(resume)}
          </Button>
        ) : null}
        <Button
          variant={resume === null ? 'default' : 'outline'}
          data-testid="tour-restart"
          onClick={onRestart}
        >
          {started ? 'Пройти заново' : 'Начать с начала'}
        </Button>
        <Button data-testid="tour-contents-close" className="ml-auto" onClick={onClose}>
          Закрыть
        </Button>
      </div>
    </div>
  );
}

const FOCUSABLE = 'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

export function TourProvider({ children }: { children: ReactNode }) {
  const [model, dispatch] = useReducer(reduceModel, undefined, () => ({
    tour: CLOSED,
    progress: loadProgress(),
  }));
  const { tour: state, progress } = model;
  const layerRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const open = state.mode !== 'closed';

  useEffect(() => saveProgress(progress), [progress]);

  const api = useMemo<TourApi>(() => {
    // Запомнить, откуда открыли: туда вернётся фокус, когда тур закроют.
    const remember = () => {
      const el = document.activeElement;
      if (!layerRef.current?.contains(el)) opener.current = el instanceof HTMLElement ? el : null;
    };
    return {
      openMenu: () => {
        remember();
        dispatch({ type: 'menu' });
      },
      start: (index) => {
        remember();
        dispatch({ type: 'start', index });
      },
      dismissInvite: () => dispatch({ type: 'dismiss' }),
      progress,
    };
  }, [progress]);

  // Закрылся — фокус туда, откуда открывали.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) {
      const el = opener.current;
      if (el?.isConnected) el.focus({ preventScroll: true });
      opener.current = null;
    }
    wasOpen.current = open;
  }, [open]);

  // Клавиатура: Esc закрывает, стрелки листают; фокус не уходит из подсказки.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        dispatch({ type: 'close' });
        return;
      }
      if (state.mode !== 'step' || e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        dispatch({ type: 'next' });
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        dispatch({ type: 'back' });
      }
    };
    const onFocus = (e: FocusEvent) => {
      const layer = layerRef.current;
      if (layer && e.target instanceof Node && !layer.contains(e.target))
        layer.querySelector<HTMLElement>('[role="dialog"]')?.focus({ preventScroll: true });
    };
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('focusin', onFocus);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('focusin', onFocus);
    };
  }, [open, state.mode]);

  // Tab по кругу внутри подсказки.
  const trapTab = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab') return;
    const items = [...(layerRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    if (!items.length) return;
    const first = items[0]!;
    const lastItem = items[items.length - 1]!;
    const active = document.activeElement;
    if (e.shiftKey && (active === first || !items.includes(active as HTMLElement))) {
      e.preventDefault();
      lastItem.focus();
    } else if (!e.shiftKey && (active === lastItem || !items.includes(active as HTMLElement))) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <TourContext.Provider value={api}>
      {children}
      {open ? (
        <div ref={layerRef} data-testid="tour" data-mode={state.mode} onKeyDown={trapTab}>
          {/* Слой поверх страницы: ловит клики, чтобы под туром ничего не нажималось. */}
          <div
            aria-hidden
            data-testid="tour-blocker"
            className={cn('fixed inset-0 z-[70]', state.mode === 'menu' && 'bg-[rgb(5_5_10/0.62)]')}
            onMouseDown={(e) => e.preventDefault()}
          />
          {state.mode === 'menu' ? (
            <Menu
              progress={progress}
              onStart={(index) => dispatch({ type: 'start', index })}
              onRestart={() => dispatch({ type: 'restart' })}
              onClose={() => dispatch({ type: 'close' })}
            />
          ) : (
            <StepCard
              key={state.index}
              index={state.index}
              onNext={() => dispatch({ type: 'next' })}
              onBack={() => dispatch({ type: 'back' })}
              onClose={() => dispatch({ type: 'close' })}
              onMenu={() => dispatch({ type: 'menu' })}
            />
          )}
        </div>
      ) : null}
    </TourContext.Provider>
  );
}
