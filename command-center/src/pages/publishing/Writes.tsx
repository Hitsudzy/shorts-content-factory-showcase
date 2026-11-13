// Общие куски записей экрана «Публикация» (CC-0068): двухшаговое действие — план фабрики с
// токеном и «да» с отсчётом (`useConfirmFlow` → `ConfirmDialog` → `WriteButton`, как пересборка
// в CC-0063), отказы `PublishWriteProblem` словами (`writeProblemText`; строка фабрики — как
// есть, код и технические строки — под «подробнее»), раскрывашка формы и поля ввода.
// `confirm_*`/`check_changed` — план берётся заново сам (токен, отправленный не тому действию,
// сгорел); `busy` и `answer_required` — токен цел, можно нажать ещё раз. Долгая запись
// (загрузка на YouTube, CC-0069) — `long`: окно показывает, сколько уже ждём, и не даёт нажать
// второй раз и закрыться, пока фабрика не ответила.
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import { ActionTimeout } from '@/api/batchActions';
import { BatchError, problemCode } from '@/api/batchProblem';
import { humanDashes } from '@/api/humanText';
import { useAfterPublishWrite, writeProblemText } from '@/api/publishWrites';
import { useWrites } from '@/api/writes';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { WriteGate } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { confirmText } from '@/pages/batches/actions';
import { PlanLife, ReplanButton } from '@/pages/batches/ActionParts';
import { TOKEN_KEPT_CODES, useConfirmFlow } from '@/pages/batches/useConfirmFlow';
import { inputBase } from '@/pages/channels/styles';

import { PlanFailed, usePlanFailed } from './planFailed';

/** «30 секунд», «20 минут». */
function waited(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 120 ? `${s} секунд` : `${Math.round(s / 60)} минут`;
}

/** Сколько уже ждём ответа: «0:42». */
export function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const s = Math.max(0, Math.floor((now - since) / 1000));
  return (
    <span className="font-mono tabular-nums" data-testid="elapsed">
      {Math.floor(s / 60)}:{String(s % 60).padStart(2, '0')}
    </span>
  );
}

/** Отказ записи: заголовок словами по коду, строка фабрики, «подробнее» — код и детали. */
export function WriteRefusal({
  error,
  className,
  text = writeProblemText,
  say = (m: string) => m,
}: {
  error: unknown;
  className?: string;
  /** Отказ словами по коду (свой у записей статистики). */
  text?: (code: string | null | undefined) => string;
  /** Строка фабрики для человека (id каналов и батчей — названиями), CC-0033. */
  say?: (message: string) => string;
}) {
  const problem = error instanceof BatchError ? error.problem : null;
  const timeout = error instanceof ActionTimeout;
  const tech = error instanceof Error ? error.message : String(error);
  return (
    <div
      role="alert"
      data-testid="write-refusal"
      data-code={problem?.code}
      className={cn(
        'grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-3 text-[13px]',
        className,
      )}
    >
      <div className="font-semibold text-danger" data-testid="write-refusal-title">
        {problem
          ? text(problem.code)
          : timeout
            ? `Фабрика не ответила за ${waited(error.ms)} — посмотрите состояние, прежде чем повторять`
            : 'Фабрика не ответила как положено'}
      </div>
      {problem && problem.message !== text(problem.code) ? (
        <p className="m-0 [overflow-wrap:anywhere]" data-testid="write-refusal-message">
          {humanDashes(say(problem.message))}
        </p>
      ) : null}
      <More className="mt-0.5">
        {problem ? <span>код: {problem.code}</span> : null}
        {problem && humanDashes(say(problem.message)) !== problem.message ? (
          <span>{problem.message}</span>
        ) : null}
        {problem ? problem.details.map((d, i) => <span key={i}>{d}</span>) : <span>{tech}</span>}
      </More>
    </div>
  );
}

type Flow = ReturnType<typeof useConfirmFlow<unknown, Planned, unknown>>;
type Planned = {
  ok: boolean;
  why?: string | null;
  confirm?: string | null;
  expires_in_s?: number | null;
};

/** Долгая запись идёт: с какого момента ждём (окно смонтировало это в момент «да»). */
function ActWaiting({ children }: { children: ReactNode }) {
  const [since] = useState(() => Date.now());
  return (
    <div
      role="status"
      data-testid="act-waiting"
      className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--primary)_40%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_6%,var(--card))] p-3 text-[13px]"
    >
      <span className="flex flex-wrap items-center gap-2">
        <span className="size-2 animate-pulse rounded-full bg-primary" aria-hidden />
        <b className="font-semibold">Фабрика работает</b>
        <span className="text-muted-foreground">
          уже <Elapsed since={since} />
        </span>
      </span>
      {children}
    </div>
  );
}

/** Ход плана, переплан, отказ «да», истёкший токен — в окне подтверждения. */
function FlowNotes({
  flow,
  waiting,
  keptNote,
  text = writeProblemText,
  say,
}: {
  flow: Pick<
    Flow,
    'planning' | 'planError' | 'replannedBecause' | 'actError' | 'expired' | 'spent' | 'acting'
  >;
  /** Долгая запись: что показать, пока фабрика не ответила. */
  waiting?: ReactNode;
  /** Токен цел после отказа (`busy`, `answer_required`): что делать дальше. */
  keptNote?: (code: string) => ReactNode;
  text?: (code: string | null | undefined) => string;
  say?: (message: string) => string;
}) {
  const actCode = problemCode(flow.actError);
  // Отказ «да» появляется под планом: подвести его в поле зрения (подвал окна прилипает снизу).
  const errorRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (flow.actError) errorRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [flow.actError]);
  return (
    <>
      {flow.planning ? (
        <p role="status" className="m-0 animate-pulse text-muted-foreground" data-testid="planning">
          Фабрика проверяет…
        </p>
      ) : null}
      {flow.planError ? <WriteRefusal error={flow.planError} text={text} say={say} /> : null}
      {flow.replannedBecause ? (
        <div
          role="status"
          data-testid="replanned"
          data-code={problemCode(flow.replannedBecause) ?? undefined}
          className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] p-3 text-[13px]"
        >
          <b className="font-semibold">Проверил заново — посмотрите план и подтвердите ещё раз</b>
          <span>{text(problemCode(flow.replannedBecause))}.</span>
        </div>
      ) : null}
      {flow.acting && waiting ? <ActWaiting>{waiting}</ActWaiting> : null}
      {flow.actError ? (
        <div
          ref={errorRef}
          data-testid="act-error"
          data-code={actCode ?? undefined}
          className="grid scroll-mb-24 gap-1"
        >
          <WriteRefusal error={flow.actError} text={text} say={say} />
          {actCode && TOKEN_KEPT_CODES.has(actCode) ? (
            <p className="m-0 text-xs text-muted-foreground" data-testid="busy-note">
              {keptNote?.(actCode) ?? 'Подтверждение ещё годно — подождите и нажмите ещё раз.'}
            </p>
          ) : null}
        </div>
      ) : null}
      {flow.expired && !flow.spent ? (
        <p role="status" data-testid="token-expired" className="m-0 text-[13px] text-warning">
          План устарел — запросите заново.
        </p>
      ) : null}
    </>
  );
}

/**
 * Шапка плана: можно ли и почему нет (строка фабрики — как есть). После отказа «да» план не
 * обещает, что можно: «не выполнено» — до нового плана.
 */
export function PlanHead({
  plan,
  yes,
  no,
  partial = null,
}: {
  plan: Planned;
  yes: string;
  no: string;
  /** Часть можно (копилка: «разложить можно 1 из 2») — значок спокойный, не «нельзя». */
  partial?: string | null;
}) {
  const failed = usePlanFailed();
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      data-testid="plan-head"
      data-failed={failed ? '1' : undefined}
    >
      <StatusBadge
        tone={plan.ok && !failed ? 'ok' : partial && !failed ? 'warn' : 'danger'}
        tip={failed ? 'Фабрика отказала — ничего не сделано. Запросите план заново' : undefined}
      >
        {failed ? 'не выполнено' : plan.ok ? yes : (partial ?? no)}
      </StatusBadge>
      {plan.why ? (
        <span data-testid="plan-why" className="[overflow-wrap:anywhere]">
          {humanDashes(plan.why)}
        </span>
      ) : null}
    </div>
  );
}

/** Слово, которое пользователь набирает сам, чтобы «да» стало доступно (`WriteAction yes`). */
const YES_WORD = 'да';

/** Набрано ли «да» (без учёта регистра и пробелов по краям). */
const isYes = (v: string) => v.trim().toLowerCase() === YES_WORD;

/**
 * Свой ответ вместо «да» (`WriteAction yes={…}`): что просить, когда ответ годится и что
 * подсказать, пока не годится. Поле то же — пустое, без вставки, чистится на новом плане.
 */
export type TypedAnswer = {
  label: ReactNode;
  ok: (v: string) => boolean;
  /** Чего не хватает в набранном (null — годится или ещё пусто). */
  hint?: (v: string) => string | null;
};

/**
 * Поле «да» (CC-0115): пустое при каждом новом плане, вставка и перетаскивание не принимаются,
 * подсказки-значения нет — пользователь набирает «да» сам, прочитав план.
 */
export function YesField({
  id,
  value,
  onChange,
  answer,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  /** Свой ответ вместо «да»: подпись и подсказка. */
  answer?: TypedAnswer;
}) {
  const inputId = useId();
  const hint = answer?.hint?.(value) ?? null;
  return (
    <div className="grid gap-1" data-testid={`${id}-yes-field`}>
      <label htmlFor={inputId} className="text-[13px]">
        {answer ? (
          answer.label
        ) : (
          <>
            Прочитали план? Чтобы выполнить, наберите сами: <b className="font-semibold">«да»</b>
          </>
        )}
      </label>
      <input
        id={inputId}
        data-testid={`${id}-yes`}
        value={value}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onPaste={(e) => e.preventDefault()}
        onDrop={(e) => e.preventDefault()}
        className={cn(inputBase, answer ? 'w-full' : 'max-w-40')}
      />
      {hint ? (
        <span className="text-xs text-muted-foreground" data-testid={`${id}-yes-hint`}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

/**
 * Запись в два шага: кнопка открывает окно — фабрика проверяет (`plan(body)`) и показывает план
 * (`view`); «да» с отсчётом жизни токена шлёт только `{confirm}`. `why` — своя причина погасить
 * кнопку (форма не заполнена); вне рабочей фабрики кнопку гасит `ConfirmDialog`.
 */
export function WriteAction<A, P extends Planned, R>({
  id,
  label,
  title,
  description,
  body,
  why,
  tip,
  confirmLabel,
  countdownWord,
  pendingLabel = 'Записываю…',
  danger = false,
  plan,
  act,
  view,
  onDone,
  ready = true,
  onOpen,
  waiting,
  keptNote,
  after,
  problemText,
  problemSay,
  onSettled,
  triggerVariant,
  onOpenChange,
  yes = false,
}: {
  id: string;
  label: string;
  title: string;
  description: ReactNode;
  body: A | null;
  why?: string | null;
  tip: string;
  confirmLabel: string;
  /** Как назвать отсчёт на кнопке «да» словами: «план ещё» → «Разложить · план ещё 1:54». */
  countdownWord?: string;
  pendingLabel?: string;
  danger?: boolean;
  plan: (body: A) => Promise<P>;
  /** «Да»: токен плана и, при `yes`, набранное пользователем — как есть (ответ записи). */
  act: (confirm: string, typed: string) => Promise<R>;
  view: (plan: P) => ReactNode;
  onDone: (result: R) => void;
  /** Своё условие «да» сверх токена (например, фраза набрана); иначе «да» погашено. */
  ready?: boolean;
  /** Окно открылось: сбросить то, что вводится в нём (фраза, ответ). */
  onOpen?: () => void;
  /** Долгая запись: пояснение, пока ждём ответа (с отсчётом, сколько уже ждём). */
  waiting?: ReactNode;
  /** Пояснение под отказом, после которого токен цел. */
  keptNote?: (code: string) => ReactNode;
  /** Отказ «да» — показать под ним ещё что-то (например, строки «внести руками»). */
  after?: (error: unknown) => ReactNode;
  /** Отказ словами по коду; по умолчанию — записи публикации. */
  problemText?: (code: string | null | undefined) => string;
  /** Строка отказа фабрики для человека (id каналов и батчей — названиями). */
  problemSay?: (message: string) => string;
  /** Что перечитать после «да»; по умолчанию — всё про публикацию. */
  onSettled?: () => void;
  /** Вид кнопки, что открывает окно (по умолчанию — как у «да»): тихая кнопка в строке списка. */
  triggerVariant?: 'outline' | 'ghost';
  /** Человек открыл или закрыл окно сам (не «да»): например, свернуть форму под ним (CC-0128). */
  onOpenChange?: (open: boolean) => void;
  /**
   * «Да» — только после того, как пользователь сам набрал «да» под планом (`YesField`); объект —
   * свой ответ вместо «да» (набранное уходит вторым аргументом `act`).
   */
  yes?: boolean | TypedAnswer;
}) {
  const [open, setOpen] = useState(false);
  // Набранное «да» принадлежит плану, под которым набрано: новый план — поле снова пустое.
  const [typed, setTyped] = useState<{ plan: unknown; value: string }>({ plan: null, value: '' });
  const typedRef = useRef('');
  const writes = useWrites();
  const settled = useAfterPublishWrite();
  const flow = useConfirmFlow({
    plan,
    act: (confirm: string) => act(confirm, typedRef.current),
    onDone: (r: R) => {
      setOpen(false);
      onDone(r);
    },
    onSettled: onSettled ?? settled,
  });
  const typedYes = typed.plan !== null && typed.plan === flow.plan ? typed.value : '';
  useEffect(() => {
    typedRef.current = typedYes;
  }, [typedYes]);
  const answer = typeof yes === 'object' ? yes : undefined;
  const typedOk = answer ? answer.ok(typedYes) : isYes(typedYes);
  const askYes = !!yes && !!flow.plan?.ok && !!flow.plan.confirm && !flow.spent;
  const trigger = (
    <Button
      size="sm"
      variant={triggerVariant ?? (danger ? 'destructive' : 'default')}
      data-testid={`${id}-open`}
    >
      {label}
    </Button>
  );
  // Окно уже открыто — не гасим его под ногами: перечитанные после «да» данные могут дать
  // свою причину (удалять стало нечего), а отказ фабрики человек должен дочитать.
  if (!open && writes.allowed && (why || !body))
    return (
      <WriteGate why={why ?? 'Заполните поля'} wide>
        {trigger}
      </WriteGate>
    );
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        onOpenChange?.(v);
        if (v && body) {
          onOpen?.();
          flow.start(body);
        } else flow.reset();
      }}
      tip={tip}
      trigger={trigger}
      title={title}
      description={description}
      confirmLabel={confirmText(confirmLabel, flow, countdownWord)}
      pendingLabel={pendingLabel}
      pending={flow.acting}
      danger={danger}
      confirmDisabled={!flow.canConfirm || !ready || (!!yes && !typedOk)}
      confirmTestId={`${id}-confirm`}
      onConfirm={() => void flow.confirm()}
      extraActions={<ReplanButton flow={flow} onClick={() => flow.replan()} />}
    >
      <div className="grid gap-3 text-[13px]" data-testid={`${id}-plan`}>
        <PlanFailed.Provider value={!!flow.actError && flow.spent}>
          {flow.plan ? view(flow.plan) : null}
        </PlanFailed.Provider>
        {askYes ? (
          <YesField
            id={id}
            value={typedYes}
            onChange={(value) => setTyped({ plan: flow.plan, value })}
            answer={answer}
          />
        ) : null}
        <PlanLife flow={flow} testId={`${id}-plan-life`} />
        <FlowNotes
          flow={flow}
          waiting={waiting}
          keptNote={keptNote}
          text={problemText}
          say={problemSay}
        />
        {flow.actError && after ? after(flow.actError) : null}
      </div>
    </ConfirmDialog>
  );
}

/**
 * Раскрывашка формы записи: кнопка «… ▾» и форма под ней. `open`/`onOpenChange` — снаружи;
 * `keepMounted` — свёрнутая форма прячется, но не размонтируется (её окно записи живёт дальше).
 */
export function Disclosure({
  id,
  label,
  tip,
  children,
  open: openProp,
  onOpenChange,
  keepMounted = false,
}: {
  id: string;
  label: string;
  tip: string;
  children: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  keepMounted?: boolean;
}) {
  const [own, setOwn] = useState(false);
  const open = openProp ?? own;
  const setOpen = (v: boolean) => {
    setOwn(v);
    onOpenChange?.(v);
  };
  const panel = useId();
  return (
    <div className="grid gap-2" data-testid={id}>
      <Tip content={tip} wide>
        <Button
          size="sm"
          variant="outline"
          aria-expanded={open}
          aria-controls={panel}
          data-testid={`${id}-toggle`}
          onClick={() => setOpen(!open)}
          className="w-max"
        >
          {label}
          <span aria-hidden>{open ? '▴' : '▾'}</span>
        </Button>
      </Tip>
      {open || keepMounted ? (
        <div
          id={panel}
          hidden={!open}
          data-testid={`${id}-form`}
          className="grid gap-2.5 rounded-sm border p-3 text-[13px] text-foreground"
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

/** Поле ввода с подписью; `tip` — подсказка к подписи. */
export function Field({
  label,
  value,
  onChange,
  testId,
  placeholder,
  tip,
  rows,
  type = 'text',
  hint,
  invalid,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testId: string;
  placeholder?: string;
  tip?: string;
  rows?: number;
  type?: 'text' | 'date';
  hint?: ReactNode;
  invalid?: boolean;
}) {
  const id = useId();
  const caption = (
    <span
      className={cn(
        'w-fit max-w-full text-xs text-muted-foreground',
        tip && 'underline decoration-dotted underline-offset-4',
      )}
      tabIndex={tip ? 0 : undefined}
    >
      {label}
    </span>
  );
  return (
    <div className="grid gap-1">
      <label htmlFor={id} className="contents">
        {tip ? <Tip content={tip}>{caption}</Tip> : caption}
      </label>
      {rows ? (
        <textarea
          id={id}
          data-testid={testId}
          rows={rows}
          value={value}
          placeholder={placeholder}
          aria-invalid={invalid || undefined}
          onChange={(e) => onChange(e.target.value)}
          className={cn(inputBase, 'h-auto min-h-14 py-2')}
        />
      ) : (
        <input
          id={id}
          type={type}
          data-testid={testId}
          value={value}
          placeholder={placeholder}
          aria-invalid={invalid || undefined}
          onChange={(e) => onChange(e.target.value)}
          className={inputBase}
        />
      )}
      {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
    </div>
  );
}

/** Флажок с подписью; `tip` — подсказка. */
export function Check({
  label,
  checked,
  onChange,
  testId,
  tip,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  testId: string;
  tip?: string;
}) {
  const id = useId();
  const text = (
    <span
      tabIndex={tip ? 0 : undefined}
      className={cn(tip && 'underline decoration-dotted underline-offset-4')}
    >
      {label}
    </span>
  );
  return (
    <div className="flex items-start gap-2">
      <input
        id={id}
        type="checkbox"
        data-testid={testId}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5"
      />
      <label htmlFor={id}>{tip ? <Tip content={tip}>{text}</Tip> : text}</label>
    </div>
  );
}

/** Итог записи на карточке: спокойный или тревожный, с «Скрыть». */
export function Done({
  tone,
  title,
  testId,
  onClose,
  children,
}: {
  tone: 'ok' | 'warn';
  title: string;
  testId: string;
  onClose: () => void;
  children?: ReactNode;
}) {
  const color = tone === 'ok' ? 'var(--success)' : 'var(--warning)';
  return (
    <div
      role="status"
      data-testid={testId}
      style={{
        borderColor: `color-mix(in srgb, ${color} 40%, var(--border))`,
        background: `color-mix(in srgb, ${color} 7%, var(--card))`,
      }}
      className="grid gap-1.5 rounded-sm border p-3 text-[13px] text-foreground"
    >
      <div className="flex items-start justify-between gap-2">
        <b className="font-semibold">{title}</b>
        <Button size="sm" variant="ghost" onClick={onClose} data-testid="done-close">
          Скрыть
        </Button>
      </div>
      {children}
    </div>
  );
}
