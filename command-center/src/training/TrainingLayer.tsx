// Тренировка (CC-0073): плашка «Тренировка — это демо, фабрика не трогается» под шапкой на
// каждом экране и панель заданий. Кусок ленивый — вместе с демо-сервером, только в тренировке.
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router';

import { CheckIcon } from '@/components/common/icons';
import { useToast } from '@/components/common/useToast';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { localStore, TASKS, type TaskId } from './checklist';
import { checklist, demoStore } from './demo';
import { exitTraining } from './mode';
import { BANNER_TEXT } from './TrainingSlot';

export const PANEL_STORAGE_KEY = 'cc-training-panel';

/** Свёрнута ли панель — как оставили; впервые — открыта на компьютере, свёрнута на телефоне. */
function loadOpen(): boolean {
  let saved: string | null;
  try {
    saved = localStore()?.getItem(PANEL_STORAGE_KEY) ?? null;
  } catch {
    saved = null;
  }
  if (saved === 'open') return true;
  if (saved === 'closed') return false;
  try {
    return window.matchMedia('(min-width: 640px)').matches;
  } catch {
    return true;
  }
}

function saveOpen(open: boolean): void {
  try {
    localStore()?.setItem(PANEL_STORAGE_KEY, open ? 'open' : 'closed');
  } catch {
    // Не запомнили — панель просто откроется в следующий раз.
  }
}

const titleOf = (id: TaskId) => TASKS.find((t) => t.id === id)!.title;

const PHONE = '(max-width: 639.98px)';

/**
 * На телефоне панель и свёрнутая полоса лежат внизу во всю ширину: тосты поднимаются над ними
 * (`--toast-offset`, его читает Toast). На компьютере панель справа — тостам не мешает.
 */
function useToastOffset(el: HTMLElement | null) {
  useEffect(() => {
    const root = document.documentElement;
    if (!el) return undefined;
    const measure = () => {
      let phone: boolean;
      try {
        phone = window.matchMedia(PHONE).matches;
      } catch {
        phone = false;
      }
      if (!phone) {
        root.style.removeProperty('--toast-offset');
        return;
      }
      const top = el.getBoundingClientRect().top;
      root.style.setProperty('--toast-offset', `${Math.max(0, window.innerHeight - top) + 8}px`);
    };
    measure();
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    ro?.observe(el);
    window.addEventListener('resize', measure);
    return () => {
      ro?.disconnect();
      window.removeEventListener('resize', measure);
      root.style.removeProperty('--toast-offset');
    };
  }, [el]);
}

export default function TrainingLayer({ className }: { className?: string }) {
  const done = useSyncExternalStore(checklist.subscribe, checklist.get);
  const demo = useSyncExternalStore(demoStore.subscribe, demoStore.get);
  const [open, setOpen] = useState(loadOpen);
  const [leaving, setLeaving] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const panelId = useId();
  const [bottom, setBottom] = useState<HTMLElement | null>(null);
  useToastOffset(bottom);

  // Только что выполненное — строкой в плашке (панель могла быть свёрнута; тост занят экраном).
  const [fresh, setFresh] = useState<TaskId[]>([]);
  useEffect(() => {
    let prev = checklist.get();
    return checklist.subscribe(() => {
      const now = checklist.get();
      setFresh(now.filter((id) => !prev.includes(id)));
      prev = now;
    });
  }, []);

  const toggle = () => {
    setOpen((o) => {
      saveOpen(!o);
      return !o;
    });
  };

  const leave = () => {
    setLeaving(true);
    // Живые и демо-данные не смешиваются: кэш пуст, дальше — перезагрузка живым центром.
    qc.clear();
    void exitTraining();
  };

  const restart = () => {
    demoStore.reset();
    void qc.resetQueries();
    toast('Тренировка начата заново: демо-данные свежие, отметки сняты');
  };

  const total = TASKS.length;
  const count = `${done.length} из ${total}`;

  return (
    <>
      <div
        role="region"
        aria-label="Тренировка"
        data-testid="training-banner"
        className="border-t border-[color-mix(in_srgb,var(--primary)_45%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_12%,var(--background))]"
      >
        {/* Телефон: строка текста во всю ширину, кнопки — второй строкой; компьютер — в ряд. */}
        <div className={cn('grid gap-1.5 py-2 sm:flex sm:items-center sm:gap-3', className)}>
          <p className="m-0 min-w-0 text-[13px] sm:flex-1">
            <b className="font-semibold" data-testid="training-banner-text">
              {BANNER_TEXT}
            </b>
            <span className="hidden text-muted-foreground sm:inline">
              {' '}
              — данные учебные, записи уходят в демо-фабрику этой вкладки.
            </span>
            <span role="status" data-testid="training-last" className="block truncate text-success">
              {fresh.length ? `Задание выполнено: ${fresh.map(titleOf).join(', ')}` : null}
            </span>
          </p>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              className="flex-1 sm:flex-none"
              aria-expanded={open}
              aria-controls={panelId}
              data-testid="training-tasks-toggle"
              onClick={toggle}
            >
              Задания · {count}
            </Button>
            <Button
              size="sm"
              variant="default"
              className="flex-1 sm:flex-none"
              data-testid="training-exit"
              disabled={leaving}
              onClick={leave}
            >
              {leaving ? 'Выхожу…' : 'Выйти из тренировки'}
            </Button>
          </div>
        </div>
      </div>
      {createPortal(
        open ? (
          <section
            ref={setBottom}
            id={panelId}
            aria-labelledby={`${panelId}-title`}
            data-testid="training-panel"
            className="fixed inset-x-0 bottom-0 z-40 flex max-h-[min(60dvh,560px)] flex-col overflow-hidden rounded-t-lg border-t border-primary bg-card sm:rounded-lg sm:border text-card-foreground shadow-2xl sm:inset-x-auto sm:right-4 sm:bottom-4 sm:max-h-[calc(100dvh-180px)] sm:w-[360px]"
          >
            <div className="flex shrink-0 items-start gap-2 border-b px-3.5 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="eyebrow">Тренировка</div>
                <h2
                  id={`${panelId}-title`}
                  className="m-0 font-display text-base font-semibold tracking-[.02em] uppercase"
                >
                  Задания
                </h2>
              </div>
              <span
                className="pt-1 font-mono text-xs text-muted-foreground"
                data-testid="training-count"
              >
                {count}
              </span>
              <Button size="sm" variant="ghost" data-testid="training-collapse" onClick={toggle}>
                Свернуть
              </Button>
            </div>
            <div
              className="h-1 shrink-0 bg-muted"
              role="progressbar"
              aria-label="Выполнено заданий"
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={done.length}
            >
              <div
                className="h-full bg-primary"
                style={{ width: `${(done.length / total) * 100}%` }}
              />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3.5 py-2.5">
              {done.length === total ? (
                <p
                  role="status"
                  data-testid="training-all-done"
                  className="m-0 mb-2 rounded-sm border border-[color-mix(in_srgb,var(--success)_40%,var(--border))] p-2 text-[13px]"
                >
                  Все задания выполнены. Теперь вы знаете, как центр пишет в фабрику. Выйдите из
                  тренировки — вернутся живые данные.
                </p>
              ) : null}
              <ol className="m-0 grid list-none gap-1.5 p-0" aria-label="Задания тренировки">
                {TASKS.map((t) => {
                  const isDone = done.includes(t.id);
                  return (
                    <li
                      key={t.id}
                      data-testid="training-task"
                      data-task={t.id}
                      data-done={isDone ? 'yes' : 'no'}
                      className="grid grid-cols-[18px_1fr_auto] items-start gap-x-2 rounded-sm border px-2.5 py-2"
                    >
                      <span
                        aria-hidden
                        className={cn(
                          'mt-0.5 grid size-[18px] place-items-center rounded-full border',
                          isDone
                            ? 'border-success bg-success text-background'
                            : 'border-muted-foreground',
                        )}
                      >
                        {isDone ? <CheckIcon className="size-3" /> : null}
                      </span>
                      <span className="min-w-0">
                        <span className="text-[13px] font-semibold">
                          {t.title}
                          <span className="sr-only">
                            {isDone ? ' — выполнено' : ' — не выполнено'}
                          </span>
                        </span>
                        {t.demoOnly ? (
                          <span className="ml-1.5 rounded-sm border px-1 text-[11px] whitespace-nowrap text-muted-foreground">
                            только демо
                          </span>
                        ) : null}
                        <span className="block text-xs text-muted-foreground">{t.hint}</span>
                      </span>
                      {t.to ? (
                        <Link
                          to={t.to}
                          data-testid="training-task-go"
                          className="pt-0.5 text-xs text-primary-text underline-offset-4 hover:underline"
                        >
                          Открыть
                        </Link>
                      ) : (
                        <span />
                      )}
                    </li>
                  );
                })}
              </ol>
              <div className="mt-3 grid gap-2 border-t pt-2.5" data-testid="training-levers">
                <div className="eyebrow">Что будет, если…</div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    data-testid="training-expire"
                    aria-pressed={demo.levers.expireNext}
                    disabled={demo.levers.expireNext}
                    onClick={demoStore.expireNext}
                  >
                    Промотать время
                  </Button>
                  <span className="min-w-0 flex-1 text-xs text-muted-foreground">
                    {demo.levers.expireNext
                      ? 'Следующее «да» опоздает: фабрика скажет, что план устарел.'
                      : 'Как будто окно простояло больше двух минут.'}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    data-testid="training-refuse"
                    aria-pressed={demo.refuseNext}
                    disabled={demo.refuseNext}
                    onClick={demoStore.refuseNext}
                  >
                    Следующее «да» — отказ
                  </Button>
                  <span className="min-w-0 flex-1 text-xs text-muted-foreground">
                    {demo.refuseNext
                      ? 'Ждёт: следующее «да» на «Публикации» получит отказ фабрики.'
                      : 'Фабрика откажет в записи — так выглядит её отказ.'}
                  </span>
                </div>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-t px-3.5 pt-2.5 pb-[calc(12px+env(safe-area-inset-bottom))] sm:pb-2.5">
              <Button size="sm" variant="ghost" data-testid="training-reset" onClick={restart}>
                Начать заново
              </Button>
              <Button
                size="sm"
                variant="default"
                className="ml-auto"
                data-testid="training-exit-panel"
                disabled={leaving}
                onClick={leave}
              >
                Выйти из тренировки
              </Button>
            </div>
          </section>
        ) : (
          // Телефон: свёрнутая панель — полоса внизу, её видно с первого входа.
          <button
            ref={setBottom}
            type="button"
            data-testid="training-handle"
            data-training-handle=""
            aria-expanded={false}
            aria-controls={panelId}
            onClick={toggle}
            className="fixed inset-x-0 bottom-0 z-40 flex cursor-pointer items-center justify-between gap-3 border-t border-primary bg-card px-4 pt-2.5 pb-[calc(10px+env(safe-area-inset-bottom))] text-left text-[13px] font-semibold text-card-foreground shadow-2xl sm:hidden"
          >
            <span>Задания · {count}</span>
            <span aria-hidden className="text-primary-text">
              ▴ открыть
            </span>
          </button>
        ),
        document.body,
      )}
    </>
  );
}
