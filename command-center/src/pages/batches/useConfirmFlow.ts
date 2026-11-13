// Двухшаговое действие с токеном подтверждения (CC-0046/0047): план → «да» с токеном.
// План берётся при открытии окна и заново по просьбе; «да» доступно, только когда план
// `ok`, токен есть и не истёк (`expires_in_s` с момента ответа — отсчёт на кнопке). Отказ
// `confirm_*`/`check_changed` — план берётся заново сам, а причина показывается; `busy` и
// `answer_required` — токен цел, нажать можно ещё раз; прочие отказы (`refused`, сеть, таймаут) — токен считаем
// потраченным, нужен новый план.
import { useCallback, useEffect, useRef, useState } from 'react';

import { BatchError, problemCode, type BatchProblem } from '@/api/batchProblem';
import { needsReplan } from '@/api/batchActions';
import { NOT_WORKING_FACTORY } from '@/api/client';
import { useWrites } from '@/api/writes';

import { secondsLeft } from './actions';

/** Отказ «только смотреть» без похода в API: планы тоже под защитой записи (CC-0058/0059). */
function readOnlyError(reason: string) {
  const message = `Только смотреть: ${reason}`;
  const problem = { code: NOT_WORKING_FACTORY, message, details: [reason] };
  return new BatchError(409, message, problem as unknown as BatchProblem);
}

/**
 * Отказы «да», после которых токен цел и нажать можно ещё раз: `busy` (запись занята) и
 * `answer_required` (загрузка: ответ не «да» — фабрика проверяет его до траты токена).
 */
export const TOKEN_KEPT_CODES: ReadonlySet<string> = new Set(['busy', 'answer_required']);

type Planned = { ok: boolean; confirm?: string | null; expires_in_s?: number | null };

type Plan<P, A> = { plan: P; args: A; deadline: number | null; spent: boolean };

export function useConfirmFlow<A, P extends Planned, R>({
  plan: planFn,
  act: actFn,
  onDone,
  onSettled,
}: {
  plan: (args: A) => Promise<P>;
  act: (confirm: string, args: A) => Promise<R>;
  /** Фабрика ответила на «да» (200): окно можно закрывать. */
  onDone: (result: R, args: A) => void;
  /** После любого ответа на «да» (и отказа): перечитать состояние. */
  onSettled?: () => void;
}) {
  const [planned, setPlanned] = useState<Plan<P, A> | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<unknown>(null);
  const [acting, setActing] = useState(false);
  const [actError, setActError] = useState<unknown>(null);
  const [replannedBecause, setReplannedBecause] = useState<unknown>(null);
  const [now, setNow] = useState(() => Date.now());
  const ask = useRef(0);
  /** Тело последнего плана — и упавшего: «Проверить заново» без аргументов берёт его. */
  const lastArgs = useRef<{ args: A } | null>(null);
  const writes = useWrites();
  const readOnly = useRef<string | null>(null);
  useEffect(() => {
    readOnly.current = writes.allowed ? null : writes.reason;
  }, [writes.allowed, writes.reason]);

  const runPlan = useCallback(
    async (args: A) => {
      const n = ++ask.current;
      lastArgs.current = { args };
      if (readOnly.current !== null) {
        // Вне рабочей фабрики план не спрашиваем: его маршрут тоже пишет (токен) и откажет.
        setPlanned(null);
        setPlanning(false);
        setPlanError(readOnlyError(readOnly.current));
        return;
      }
      setPlanning(true);
      setPlanError(null);
      try {
        const p = await planFn(args);
        if (n !== ask.current) return;
        const t = Date.now();
        setNow(t);
        setPlanned({
          plan: p,
          args,
          deadline: p.confirm && p.expires_in_s != null ? t + p.expires_in_s * 1000 : null,
          spent: false,
        });
      } catch (e) {
        if (n !== ask.current) return;
        setPlanned(null);
        setPlanError(e);
      } finally {
        if (n === ask.current) setPlanning(false);
      }
    },
    [planFn],
  );

  /** Окно открыто: всё сначала и план. */
  const start = useCallback(
    (args: A) => {
      setPlanned(null);
      setActError(null);
      setReplannedBecause(null);
      void runPlan(args);
    },
    [runPlan],
  );

  /**
   * План заново (по кнопке или с другими условиями — например, «и шаг»). Без аргументов — с
   * телом последнего плана, даже если тот упал (плана нет, а «Проверить заново» есть).
   */
  const replan = useCallback(
    (...given: [] | [A]) => {
      setActError(null);
      setReplannedBecause(null);
      const last = given.length ? { args: given[0] } : lastArgs.current;
      if (last) void runPlan(last.args);
    },
    [runPlan],
  );

  /** Закрыть: опоздавшие ответы плана больше ничего не трогают. */
  const reset = useCallback(() => {
    ask.current++;
    lastArgs.current = null;
    setPlanned(null);
    setPlanning(false);
    setPlanError(null);
    setActError(null);
    setReplannedBecause(null);
  }, []);

  const left = planned ? secondsLeft(planned.deadline, now) : null;
  const expired = left === 0;
  const canConfirm =
    !!planned?.plan.ok &&
    !!planned.plan.confirm &&
    !planned.spent &&
    !expired &&
    !planning &&
    !acting;

  // Отсчёт идёт, пока токен жив.
  useEffect(() => {
    if (!planned?.deadline || planned.spent) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [planned]);

  const confirm = useCallback(async () => {
    if (!planned?.plan.confirm || !canConfirm) return;
    const { args } = planned;
    setActing(true);
    setActError(null);
    setReplannedBecause(null);
    try {
      const r = await actFn(planned.plan.confirm, args);
      setPlanned((p) => (p ? { ...p, spent: true } : p));
      onDone(r, args);
    } catch (e) {
      if (needsReplan(e)) {
        setReplannedBecause(e);
        void runPlan(args);
      } else {
        setActError(e);
        if (!TOKEN_KEPT_CODES.has(problemCode(e) ?? ''))
          setPlanned((p) => (p ? { ...p, spent: true } : p));
      }
    } finally {
      setActing(false);
      onSettled?.();
    }
  }, [planned, canConfirm, actFn, onDone, onSettled, runPlan]);

  return {
    planned,
    plan: planned?.plan ?? null,
    planning,
    planError,
    acting,
    actError,
    replannedBecause,
    left,
    expired,
    spent: !!planned?.spent,
    canConfirm,
    start,
    replan,
    reset,
    confirm,
  };
}
