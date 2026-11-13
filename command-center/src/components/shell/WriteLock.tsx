// CC-0084: глобальный прелоадер записи. Пока у фабрики в полёте хоть одна запись (учёт —
// `src/api/writeLock.ts`, его ведёт сам клиент API), весь центр под слоем: клики, клавиши,
// фокус и переходы по маршрутам не проходят, Esc слой не снимает. Слой снимается по ответу
// фабрики — успех или отказ, отказ экран показывает как раньше.
//
// Как замораживаем: слушатели на `window` в фазе перехвата — они первые на пути любого
// события, и `stopImmediatePropagation` не пускает его дальше: ни кнопкам, ни Radix (окна,
// подсказки, их «клик снаружи» и Esc). Фокус — в слое; события фокуса тоже не уходят дальше,
// иначе ловушка фокуса открытого окна Radix тянула бы его обратно.
//
// Блокировка — сразу; видимый слой (затемнение и подпись) проступает через 250 мс, чтобы
// короткая запись не мигала. Прогресса нет: фабрика его не сообщает, а ложный не рисуем.
import { useEffect, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useBlocker } from 'react-router';

import {
  getWritesInFlight,
  upToText,
  useWritesInFlight,
  type WriteInFlight,
} from '@/api/writeLock';

const POINTER_EVENTS = [
  'pointerdown',
  'pointerup',
  'mousedown',
  'mouseup',
  'click',
  'dblclick',
  'auxclick',
  'contextmenu',
  'touchstart',
  'touchend',
  'dragstart',
  'drop',
] as const;
const KEY_EVENTS = ['keydown', 'keyup', 'keypress', 'beforeinput', 'paste', 'cut'] as const;

const isLocked = () => getWritesInFlight().length > 0;

/** Слой записи: вешается один раз, в `Layout` (внутри роутера — ему нужен `useBlocker`). */
export function WriteLock() {
  const writes = useWritesInFlight();
  const current = writes.at(-1) ?? null;
  const long = writes.find((w) => w.upToMs !== undefined) ?? null;

  // Переходы по маршрутам (в том числе «назад» браузера) — нет, пока запись в полёте. Решает
  // сам учёт в момент перехода: после ответа код экрана может перейти сразу (новый канал).
  const blocker = useBlocker(isLocked);
  useEffect(() => {
    if (!current && blocker.state === 'blocked') blocker.reset();
  }, [current, blocker]);

  // Долгая запись: закрыть вкладку можно, но браузер переспросит — запись идёт на фабрике.
  useEffect(() => {
    if (!long) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [long]);

  if (!current || typeof document === 'undefined') return null;
  return createPortal(<Layer current={current} count={writes.length} long={long} />, document.body);
}

function Layer({
  current,
  count,
  long,
}: {
  current: WriteInFlight;
  count: number;
  long: WriteInFlight | null;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const layer = ref.current;
    if (!layer) return;
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    layer.focus({ preventScroll: true });

    const stop = (e: Event) => {
      e.stopImmediatePropagation();
      if (e.cancelable) e.preventDefault();
    };
    const key = (e: KeyboardEvent) => {
      e.stopImmediatePropagation();
      // Сочетания браузера (⌘W, ⌘R, Ctrl+Tab) не трогаем: вкладку закрыть можно.
      if ((e.metaKey || e.ctrlKey) && e.type !== 'beforeinput') return;
      if (e.cancelable) e.preventDefault();
    };
    const focus = (e: FocusEvent) => {
      e.stopImmediatePropagation();
      if (e.type === 'focusin' && e.target !== layer) layer.focus({ preventScroll: true });
    };
    const opts = { capture: true, passive: false } as const;
    for (const t of POINTER_EVENTS) window.addEventListener(t, stop, opts);
    for (const t of KEY_EVENTS) window.addEventListener(t, key as EventListener, opts);
    window.addEventListener('focusin', focus, opts);
    window.addEventListener('focusout', focus, opts);
    return () => {
      for (const t of POINTER_EVENTS) window.removeEventListener(t, stop, opts);
      for (const t of KEY_EVENTS) window.removeEventListener(t, key as EventListener, opts);
      window.removeEventListener('focusin', focus, opts);
      window.removeEventListener('focusout', focus, opts);
      // Фокус — туда, где был, если код экрана за это время не увёл его сам (окно закрылось).
      const now = document.activeElement;
      if (before?.isConnected && (!now || now === document.body || now === layer)) {
        before.focus({ preventScroll: true });
      }
    };
  }, []);

  const plan = current.kind === 'plan';
  return (
    <div
      ref={ref}
      data-testid="write-lock"
      data-kind={current.kind}
      role="dialog"
      aria-modal="true"
      aria-busy="true"
      aria-labelledby="write-lock-title"
      aria-describedby="write-lock-note"
      tabIndex={-1}
      // Окно Radix (модальное) гасит `pointer-events` у body — слой их возвращает себе, иначе
      // клик прошёл бы сквозь него в окно. Строкой стиля: так видит и jsdom.
      style={{ pointerEvents: 'auto' }}
      className="fixed inset-0 z-[100] grid cursor-progress place-items-center px-4 outline-none"
    >
      <div
        aria-hidden
        className="write-lock-in absolute inset-0 bg-background/70 backdrop-blur-[2px]"
      />
      <div className="write-lock-in relative w-full max-w-[420px] rounded-lg border bg-card p-card text-card-foreground shadow-lg">
        <div className="flex items-start gap-3">
          {/* Дуга — `primary-text`, а не `primary`: в светлой теме жёлтый на белой карточке
              почти не виден (1,4:1), тёмно-жёлтый — 6,0:1 (CC-0093). В тёмной оба токена
              одного цвета, там ничего не меняется. */}
          <span
            aria-hidden
            data-testid="write-lock-spinner"
            className="write-lock-spin mt-0.5 inline-block size-5 shrink-0 rounded-full border-2 border-muted-foreground/30 border-t-primary-text"
          />
          <div className="min-w-0">
            <p
              id="write-lock-title"
              data-testid="write-lock-title"
              className="m-0 text-[15px] font-semibold"
            >
              {current.title}
            </p>
            <p id="write-lock-note" className="m-0 mt-1 text-[13px] text-muted-foreground">
              {plan
                ? 'Фабрика проверяет, что будет сделано; пока ничего не записано.'
                : 'Ждём ответа фабрики. Интерфейс вернётся, как только она ответит.'}
            </p>
            {long ? (
              <p data-testid="write-lock-long" className="m-0 mt-2 text-[13px]">
                Это может занять {upToText(long.upToMs!)}. Вкладку можно закрыть — запись
                продолжится на фабрике.
              </p>
            ) : null}
            {count > 1 ? (
              <p className="m-0 mt-2 text-[12px] text-muted-foreground">
                Записей в работе: {count}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
