// «Пора прочитать Studio» в шапке (CC-0151): вместо полосы под шапкой — кнопка рядом с темой
// и обучением с меткой «пора»; по нажатию — окошко под кнопкой, как панель аккаунта Google:
// скруглённая карточка у правого края, крестик, внутри плитки — почему пора (строка фабрики уже
// говорит, когда читали) и повод, кнопка чтения (её «да» — прежнее окно подтверждения). Окошко плавает над страницей, страница
// не сдвигается; закрывается по Esc, клику вне и крестику, фокус возвращается на кнопку.
// Кнопка видна при том же условии, что и полоса раньше (`useStudioDueState`).
import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';

import { StudioIcon } from '@/components/common/icons';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';

import { StudioDueAction } from './StudioRead';
import { hookWordOf, useStudioDueState } from './studioDue';

const HOOK = 'center-first-open-of-day';
/** Ширина окошка на компьютере; на телефоне (уже 640px) — на всю ширину с полями 16px. */
const WIDTH = 380;
const GUTTER = 16;
const PHONE = 640;

/** Место окошка под кнопкой: правый край — по кнопке, высота — до низа экрана. */
function place(btn: HTMLElement): CSSProperties {
  const r = btn.getBoundingClientRect();
  const vw = document.documentElement.clientWidth || window.innerWidth;
  const top = Math.round(r.bottom + 8);
  const box: CSSProperties = { top, maxHeight: `calc(100dvh - ${top + GUTTER}px)` };
  if (vw < PHONE) return { ...box, left: GUTTER, right: GUTTER };
  const right = Math.max(GUTTER, Math.round(vw - r.right));
  return { ...box, right, width: Math.min(WIDTH, vw - right - GUTTER) };
}

/** Открыто окно подтверждения поверх окошка: Esc и клики — его, окошко не закрываем. */
const modalUp = () => !!document.querySelector('[role="alertdialog"]');

export function StudioHeaderButton() {
  const state = useStudioDueState(HOOK);
  const due = state.due;
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<CSSProperties>({});
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const popId = useId();
  const titleId = useId();
  // Блок погас (итог скрыт, «пора» прошло) — окошко закрыто и при следующем «пора».
  if (!due && open) setOpen(false);

  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      if (btn.current) setStyle(place(btn.current));
    };
    update();
    pop.current?.focus({ preventScroll: true });
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (refocus: boolean) => {
      setOpen(false);
      if (refocus) btn.current?.focus();
    };
    // Захват на window — раньше подсказок Radix: Esc закрывает окошко, а не только подсказку.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || modalUp()) return;
      close(true);
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target;
      if (!(t instanceof Node) || modalUp()) return;
      if (pop.current?.contains(t) || btn.current?.contains(t)) return;
      // Клик по другой кнопке или полю — фокус остаётся там; по пустому месту — на кнопку,
      // после того как браузер сам уведёт фокус с окошка (mousedown идёт следом за pointerdown).
      const el = t instanceof Element ? t : t.parentElement;
      close(false);
      if (!el?.closest('a,button,input,select,textarea,summary,label,[tabindex]'))
        window.setTimeout(() => btn.current?.focus(), 0);
    };
    window.addEventListener('keydown', onKey, true);
    document.addEventListener('pointerdown', onDown, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      document.removeEventListener('pointerdown', onDown, true);
    };
  }, [open]);

  if (!due) return null;
  const label = due.due ? 'Пора прочитать Studio' : 'Чтение Studio';
  const hookWord = hookWordOf(due);
  const shut = () => {
    setOpen(false);
    btn.current?.focus();
  };

  return (
    <>
      <Tip
        side="left"
        content={
          due.due
            ? 'Пора прочитать Studio — почему пора и кнопка чтения'
            : 'Чтение Studio — ход и итог'
        }
      >
        <Button
          ref={btn}
          aria-label={label}
          aria-expanded={open}
          aria-controls={popId}
          aria-haspopup="dialog"
          data-testid="studio-pop-open"
          data-due={due.due || undefined}
          className="relative"
          onClick={() => (open ? shut() : setOpen(true))}
        >
          <StudioIcon className="size-[17px]" />
          <span className="hidden md:inline">Studio</span>
          {due.due ? (
            <span
              aria-hidden
              data-testid="studio-pop-mark"
              className="absolute -top-[3px] -right-[3px] size-2.5 rounded-full bg-primary-text ring-2 ring-background"
            />
          ) : null}
        </Button>
      </Tip>
      {open ? (
        <div
          ref={pop}
          id={popId}
          role="dialog"
          aria-labelledby={titleId}
          tabIndex={-1}
          data-testid="studio-pop"
          style={style}
          className="fixed z-30 grid content-start gap-2 overflow-y-auto overscroll-contain rounded-[24px] border bg-muted p-2.5 text-[13px] text-foreground shadow-[0_12px_40px_#0000004d] outline-none dark:border-[color-mix(in_srgb,var(--foreground)_16%,var(--border))] dark:shadow-[0_16px_48px_#000c]"
        >
          <div className="flex items-center gap-2 py-0.5 pr-0.5 pl-3.5">
            <h2 id={titleId} className="m-0 min-w-0 flex-1 text-[15px] font-semibold">
              {label}
            </h2>
            <Button
              size="icon"
              variant="ghost"
              aria-label="Закрыть"
              data-testid="studio-pop-close"
              className="rounded-full border-transparent bg-transparent text-[20px] leading-none font-normal hover:bg-card"
              onClick={shut}
            >
              <span aria-hidden>×</span>
            </Button>
          </div>
          <div
            data-testid="studio-due"
            data-hook={HOOK}
            data-due={due.due || undefined}
            className="grid gap-1.5"
          >
            {due.due ? (
              <section
                aria-label="Почему пора"
                className="grid gap-1 rounded-[16px] bg-card px-4 py-3.5"
              >
                <p className="m-0" data-testid="studio-why">
                  {due.why}
                </p>
                {/* Возраст чтения уже в строке фабрики («Studio не читали 30 ч») — не повторяем. */}
                {hookWord ? (
                  <p className="m-0 text-muted-foreground" data-testid="studio-hook">
                    Повод: {hookWord}
                  </p>
                ) : null}
              </section>
            ) : null}
            {/* На светлой погашенная жёлтая «Прочитать Studio» при opacity 50% почти не читается —
                здесь чуть плотнее; общий вид погашенных кнопок не трогаем. */}
            <section
              aria-label="Чтение"
              className="rounded-[16px] bg-card px-4 py-3.5 light:[&_[data-testid=studio-read-open]:disabled]:opacity-70"
            >
              <StudioDueAction due={due} state={state} />
            </section>
          </div>
        </div>
      ) : null}
    </>
  );
}
