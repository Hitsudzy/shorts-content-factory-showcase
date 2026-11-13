// Экран входа (CC-0037): один пароль, «Войти», ошибки простыми словами. Показывается вместо
// центра, пока этому браузеру нужен вход (домашняя сеть). Сам не ходит ни в какие ручки, кроме
// `/api/auth/login`: до входа остальное API закрыто (401).
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

import { login, type LoginOutcome } from '@/api/auth';
import { EyeIcon, EyeOffIcon } from '@/components/common/icons';
import { Tip } from '@/components/common/Tip';
import { ThemeToggle } from '@/components/shell/ThemeToggle';
import { Button } from '@/components/ui/button';
import { TooltipProvider } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

import { clock, lockedText } from './lockText';
import type { LoginReason } from './store';

const FIELD =
  'h-[40px] w-full min-w-0 rounded-sm border border-input bg-background py-2 pr-11 pl-3 text-sm text-foreground outline-none focus-visible:border-ring aria-invalid:border-danger disabled:cursor-not-allowed disabled:border-border disabled:bg-muted disabled:text-muted-foreground';

/**
 * Выключенная «Войти» (блокировка, вход в пути): не прозрачностью, как у общей кнопки, а
 * приглушённым фоном — подпись читается (контраст ≈ 5:1 в обеих темах).
 */
const SUBMIT_OFF =
  'disabled:border-border disabled:bg-muted disabled:font-medium disabled:text-muted-foreground disabled:opacity-100 dark:disabled:opacity-100';

type Problem = Exclude<LoginOutcome, { ok: true }>;

type Lock = { until: number; seconds: number };

/**
 * Секунды до конца блокировки, раз в секунду; null — блокировки нет, 0 — кончилась. Первый кадр
 * после отказа считает от `seconds`: часы `now` ещё с прошлого тика.
 */
function useLockLeft(lock: Lock | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (lock === null) return;
    const id = setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t >= lock.until) clearInterval(id);
    }, 1000);
    return () => clearInterval(id);
  }, [lock]);
  if (lock === null) return null;
  return Math.max(0, Math.min(lock.seconds, (lock.until - now) / 1000));
}

const NOTE: Record<LoginReason, string | null> = {
  boot: null,
  expired: 'Вход истёк. Введите пароль — центр откроется на той же странице',
  logout: 'Вы вышли из центра на этом устройстве',
};

export function LoginScreen({ reason }: { reason: LoginReason | null }) {
  const fieldId = useId();
  const errorId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState('');
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [lock, setLock] = useState<Lock | null>(null);
  const left = useLockLeft(lock);
  const locked = left !== null && left > 0;
  // Блокировка кончилась — её отказ больше не показываем.
  const shownProblem = problem?.kind === 'locked' && !locked ? null : problem;

  // Блокировка кончилась — поле снова включено: курсор в него.
  const wasLocked = useRef(false);
  useEffect(() => {
    if (wasLocked.current && !locked) input.current?.focus();
    wasLocked.current = locked;
  }, [locked]);

  useEffect(() => {
    document.title = 'Вход · Командный центр Example';
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || locked) return;
    if (!password.trim()) {
      setProblem({ ok: false, kind: 'empty', message: 'Введите пароль' });
      input.current?.focus();
      return;
    }
    setBusy(true);
    const out = await login(password);
    setBusy(false);
    if (out.ok) return;
    setProblem(out);
    if (out.kind === 'locked')
      setLock({ until: Date.now() + out.retryAfter * 1000, seconds: out.retryAfter });
    input.current?.focus();
    if (out.kind === 'wrong') input.current?.select();
  }

  const message =
    shownProblem?.kind === 'locked' && left !== null
      ? lockedText(left)
      : (shownProblem?.message ?? null);
  const note = reason ? NOTE[reason] : null;

  return (
    <TooltipProvider>
      <div
        data-testid="login-screen"
        className="relative grid min-h-screen place-items-center bg-background px-gutter py-10"
      >
        <div className="absolute top-3 right-[var(--space-gutter)]">
          <ThemeToggle />
        </div>
        <main className="w-full max-w-[380px]">
          <section className="rounded-lg border bg-card p-6 text-card-foreground sm:p-7">
            <div className="mb-5 flex items-center gap-3">
              <img
                src={`${import.meta.env.BASE_URL}favicon.svg`}
                alt=""
                width={44}
                height={44}
                className="size-11 shrink-0 rounded-[10px]"
              />
              <div className="min-w-0">
                <div className="eyebrow">Вход</div>
                <h1 className="mt-0.5 text-[19px] leading-tight font-semibold text-balance">
                  Командный центр Example
                </h1>
              </div>
            </div>

            {note ? (
              <p
                data-testid="login-note"
                className="mb-4 rounded-sm border bg-background px-3 py-2 text-[13px] text-muted-foreground"
              >
                {note}
              </p>
            ) : null}

            <form noValidate onSubmit={(e) => void submit(e)} className="grid gap-3">
              <label htmlFor={fieldId} className="text-[13px] font-medium">
                Пароль
              </label>
              <div className="relative -mt-1.5">
                <input
                  ref={input}
                  id={fieldId}
                  name="password"
                  type={shown ? 'text' : 'password'}
                  autoComplete="current-password"
                  autoCapitalize="none"
                  spellCheck={false}
                  autoFocus
                  disabled={locked}
                  value={password}
                  aria-invalid={shownProblem && shownProblem.kind !== 'locked' ? true : undefined}
                  aria-describedby={message ? errorId : undefined}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (shownProblem && !locked) setProblem(null);
                  }}
                  className={FIELD}
                />
                <Tip content={shown ? 'Скрыть пароль' : 'Показать пароль'}>
                  <button
                    type="button"
                    aria-label={shown ? 'Скрыть пароль' : 'Показать пароль'}
                    aria-pressed={shown}
                    data-testid="password-toggle"
                    disabled={locked}
                    onClick={() => setShown((v) => !v)}
                    className="absolute inset-y-0 right-0 grid w-10 place-items-center rounded-r-sm text-muted-foreground outline-none hover:text-foreground focus-visible:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {shown ? (
                      <EyeOffIcon className="size-[18px]" />
                    ) : (
                      <EyeIcon className="size-[18px]" />
                    )}
                  </button>
                </Tip>
              </div>

              {/* Место под строку ошибки — всегда: карточка не прыгает, когда ошибка появляется. */}
              <div className="min-h-[38px]" data-testid="login-error-slot">
                {message ? (
                  <div
                    id={errorId}
                    role="alert"
                    data-testid="login-error"
                    data-kind={shownProblem?.kind}
                    className={cn(
                      'rounded-sm border px-3 py-2 text-[13px]',
                      shownProblem?.kind === 'locked' || shownProblem?.kind === 'off'
                        ? 'border-[color-mix(in_srgb,var(--warning)_45%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_10%,var(--background))]'
                        : 'border-[color-mix(in_srgb,var(--danger)_45%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_8%,var(--background))] text-danger',
                    )}
                  >
                    {message}
                    {shownProblem?.kind === 'locked' && left !== null ? (
                      <span
                        data-testid="lock-timer"
                        className="mt-0.5 block font-mono text-xs text-muted-foreground tabular-nums"
                      >
                        Осталось {clock(left)}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>

              <Button
                type="submit"
                variant="default"
                className={cn('h-[40px] w-full text-sm', SUBMIT_OFF)}
                disabled={busy || locked}
              >
                {busy ? 'Вход…' : 'Войти'}
              </Button>
            </form>
          </section>
          <p className="mt-4 px-1 text-center text-xs text-pretty text-muted-foreground">
            Вход нужен только из домашней сети; на Mac центр открывается без пароля
          </p>
        </main>
      </div>
    </TooltipProvider>
  );
}
