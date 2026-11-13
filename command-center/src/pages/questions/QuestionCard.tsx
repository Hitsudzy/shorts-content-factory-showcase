// Карточка вопроса (CC-0017): кто и когда спросил, текст, ответ прямо в карточке («Отправить» —
// прямая запись, без плана) и «Решено…» — подтверждение в один шаг. Отказ — словами в карточке
// (или в окне «решено»), строка фабрики — под «подробнее». Вне рабочей фабрики обе кнопки
// погашены причиной (`WriteButton`/`ConfirmDialog`). После любой записи списки вопросов, таб и
// главная перечитываются (`useAnswer`/`useResolve`).
// CC-0086: предложенный ответ — плейсхолдером в поле; «Принять предложение» отправляет его одним
// нажатием (прямая запись, как «Отправить»; API читает предложение заново и откажет, если оно
// сменилось), «Вставить и поправить» переносит текст в поле. У ответа — пометка «принято
// предложение» / «свой ответ». Подтверждения записей («да», фраза аудита) сюда не относятся.
import { useId, useRef, useState, type ReactNode } from 'react';

import {
  QuestionError,
  questionErrorText,
  useAccept,
  useAnswer,
  useResolve,
  type Question,
} from '@/api/questions';
import { useWrites } from '@/api/writes';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { useToast } from '@/components/common/useToast';
import { WriteButton } from '@/components/common/WriteButton';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { dateTimeMsk, whoText } from '@/pages/batches/format';
import { inputBase } from '@/pages/channels/styles';

import { answerKind, sourceName, sourceTip, STATUS, suggesterName, viaName } from './format';

function Refusal({ e, action }: { e: unknown; action: 'answer' | 'resolve' }) {
  const t = questionErrorText(e, action);
  return (
    <div
      role="alert"
      data-testid={`${action}-error`}
      className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-2.5"
    >
      <div className="font-semibold text-danger">{t.title}</div>
      <p className="m-0 text-muted-foreground">{t.text}</p>
      {t.detail ? (
        <More className="mt-0">
          <span>{t.detail}</span>
        </More>
      ) : null}
    </div>
  );
}

/**
 * Вопроса больше нет в открытых (решён с другой стороны или пропал из журнала): список сейчас
 * перечитается и карточка уйдёт вместе с отказом — поэтому он ещё и тостом.
 */
function gone(
  e: unknown,
  action: 'answer' | 'resolve',
  toast: (t: string, tone: 'danger') => void,
) {
  if (e instanceof QuestionError && (e.kind === 'missing' || e.kind === 'resolved'))
    toast(questionErrorText(e, action).title, 'danger');
}

function Who({ q, channelName }: { q: Question; channelName: (id: string) => string }) {
  return (
    <span className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
      <Tip content={sourceTip(q.source)}>
        <span tabIndex={0} data-testid="question-source" className="font-medium text-foreground">
          {sourceName(q.source)}
        </span>
      </Tip>
      {q.channel ? (
        <>
          <span aria-hidden>·</span>
          <span data-testid="question-channel">{channelName(q.channel)}</span>
        </>
      ) : null}
      {q.created ? (
        <>
          <span aria-hidden>·</span>
          <span>{dateTimeMsk(q.created)}</span>
        </>
      ) : null}
    </span>
  );
}

export function Said({
  label,
  by,
  at,
  children,
}: {
  label: string;
  by?: string | null;
  at?: string | null;
  children: ReactNode;
}) {
  const who = whoText(by);
  const when = dateTimeMsk(at);
  return (
    <div className="grid gap-0.5 rounded-sm border-l-2 border-primary bg-[color-mix(in_srgb,var(--primary)_6%,transparent)] px-2.5 py-1.5">
      <span className="text-xs text-muted-foreground">
        {[label, who && who !== 'вы' ? who : null, when].filter(Boolean).join(' · ')}
      </span>
      <span className="[overflow-wrap:anywhere] whitespace-pre-wrap">{children}</span>
    </div>
  );
}

/** Пометка у ответа: «принято предложение» или «свой ответ» (CC-0086). */
export function AnswerKind({ q }: { q: Question }) {
  const k = answerKind(q);
  if (!k) return null;
  return (
    <Tip content={k.tip}>
      <span
        tabIndex={0}
        data-testid="answer-kind"
        data-accepted={q.accepted_suggestion ? 'true' : 'false'}
        className={cn(
          'w-fit rounded-sm border px-1.5 py-px text-xs',
          q.accepted_suggestion
            ? 'border-[color-mix(in_srgb,var(--success)_45%,var(--border))] text-success'
            : 'text-muted-foreground',
        )}
      >
        {k.label}
      </span>
    </Tip>
  );
}

/**
 * Кто и когда предложил, «почему» — тултипом (CC-0086). Разделитель «·» держится со словом перед
 * ним (неразрывный пробел внутри одного куска): при переносе строка не начинается с «·».
 */
function SuggestionLine({ q }: { q: Question }) {
  const parts = ['Предложение', suggesterName(q.suggested_by), dateTimeMsk(q.suggested_at)].filter(
    (p): p is string => !!p,
  );
  const why = q.suggestion_why;
  return (
    <span
      className="flex flex-wrap items-center gap-x-1 text-xs text-muted-foreground"
      data-testid="suggestion-line"
    >
      {parts.map((p, i) => (
        <span key={i} data-slot="suggestion-part">
          {p}
          {i < parts.length - 1 || why ? '\u00a0· ' : ''}
        </span>
      ))}
      {why ? (
        <Tip
          content={
            <span className="grid gap-1">
              <span>{why}</span>
              <span className="opacity-80">
                Предложение — серым в поле ответа: примите его одним нажатием или вставьте и
                поправьте.
              </span>
            </span>
          }
          wide
        >
          <button
            type="button"
            data-testid="suggestion-why"
            className="cursor-help border-0 bg-transparent p-0 text-xs text-muted-foreground underline decoration-dotted underline-offset-2"
          >
            почему
          </button>
        </Tip>
      ) : null}
    </span>
  );
}

function AnswerForm({ q, onDone }: { q: Question; onDone?: () => void }) {
  const toast = useToast();
  const answer = useAnswer();
  const accept = useAccept();
  const writes = useWrites();
  const field = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState(q.status === 'answered' ? (q.answer ?? '') : '');
  const empty = !text.trim();
  const suggestion = q.suggestion?.trim() ? q.suggestion : null;
  const pending = answer.isPending || accept.isPending;
  const failed = answer.isError ? answer.error : accept.isError ? accept.error : null;
  const clearErrors = () => {
    if (answer.isError) answer.reset();
    if (accept.isError) accept.reset();
  };
  const take = () => {
    if (!suggestion || !empty || pending || !writes.allowed) return;
    clearErrors();
    accept.mutate(
      { qid: q.id, suggestedAt: q.suggested_at ?? null },
      {
        onSuccess: () => {
          setText('');
          toast('Предложение принято — ответ отправлен фабрике');
          onDone?.();
        },
        onError: (e) => gone(e, 'answer', toast),
      },
    );
  };
  const paste = () => {
    if (!suggestion) return;
    clearErrors();
    setText(suggestion);
    requestAnimationFrame(() => {
      const el = field.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  };
  const send = () => {
    if (empty || pending || !writes.allowed) return;
    clearErrors();
    answer.mutate(
      { qid: q.id, text: text.trim() },
      {
        onSuccess: () => {
          setText('');
          toast('Ответ отправлен фабрике');
          onDone?.();
        },
        onError: (e) => gone(e, 'answer', toast),
      },
    );
  };
  return (
    <form
      className="grid gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
    >
      {suggestion ? <SuggestionLine q={q} /> : null}
      <textarea
        ref={field}
        aria-label="Ваш ответ"
        data-testid="answer-text"
        rows={suggestion ? 3 : 2}
        value={text}
        placeholder={suggestion ?? 'Ваш ответ — словами'}
        data-suggested={suggestion ? 'true' : undefined}
        onChange={(e) => {
          setText(e.target.value);
          clearErrors();
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            send();
          }
        }}
        className={cn(inputBase, 'h-auto min-h-14 resize-y py-2 text-sm')}
      />
      {failed ? <Refusal e={failed} action="answer" /> : null}
      <div className="flex flex-wrap items-center gap-2">
        {suggestion ? (
          <WriteButton
            type="button"
            variant={empty ? 'default' : 'outline'}
            size="sm"
            data-testid="suggestion-accept"
            aria-busy={accept.isPending || undefined}
            disabled={pending}
            onClick={take}
            why={
              empty
                ? undefined
                : 'В поле уже ваш текст — отправьте его или очистите поле, чтобы принять предложение'
            }
            tip="Отправить предложенное решение как ваш ответ — одним нажатием, как «Отправить»"
          >
            {accept.isPending ? 'Принимаю…' : 'Принять предложение'}
          </WriteButton>
        ) : null}
        <WriteButton
          type="submit"
          variant={suggestion && empty ? 'outline' : 'default'}
          size="sm"
          data-testid="answer-send"
          aria-busy={answer.isPending || undefined}
          disabled={pending}
          why={
            empty
              ? suggestion
                ? 'Сначала напишите ответ — или примите предложение'
                : 'Сначала напишите ответ'
              : undefined
          }
          tip="Ответ уйдёт в журнал фабрики — его прочтёт тот, кто спросил. Ctrl+Enter — тоже отправить"
        >
          {answer.isPending ? 'Отправляю…' : 'Отправить'}
        </WriteButton>
        {suggestion ? (
          <Tip content="Перенести предложенный текст в поле, чтобы поправить его перед отправкой">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              data-testid="suggestion-paste"
              onClick={paste}
              disabled={pending}
            >
              Вставить и поправить
            </Button>
          </Tip>
        ) : null}
        {onDone ? (
          <Button size="sm" variant="ghost" onClick={onDone} disabled={pending}>
            Отмена
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function ResolveButton({ q }: { q: Question }) {
  const id = useId();
  const toast = useToast();
  const resolve = useResolve();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) {
          resolve.reset();
          setNote('');
        }
      }}
      trigger={
        <Button size="sm" data-testid="resolve-open" data-tour="resolve">
          Решено…
        </Button>
      }
      tip="Закрыть вопрос: он уйдёт в историю. Спросит одно подтверждение"
      title="Отметить вопрос решённым?"
      description={<span className="[overflow-wrap:anywhere]">«{q.text}»</span>}
      error={resolve.isError ? <Refusal e={resolve.error} action="resolve" /> : null}
      confirmLabel="Решено"
      pendingLabel="Записываю…"
      pending={resolve.isPending}
      confirmTestId="resolve-confirm"
      onConfirm={() =>
        resolve.mutate(
          { qid: q.id, note },
          {
            onSuccess: () => {
              setOpen(false);
              setNote('');
              toast('Вопрос отмечен решённым');
            },
            onError: (e) => gone(e, 'resolve', toast),
          },
        )
      }
    >
      <label htmlFor={id} className="grid gap-1 text-[13px]">
        <span className="text-muted-foreground">Как решилось — необязательно</span>
        <input
          id={id}
          data-testid="resolve-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="например: переразрешил доступ в терминале"
          className={inputBase}
        />
      </label>
    </ConfirmDialog>
  );
}

/** Открытый или отвеченный вопрос — с ответом в карточке и «решено». */
export function QuestionCard({
  q,
  channelName,
}: {
  q: Question;
  channelName: (id: string) => string;
}) {
  const [again, setAgain] = useState(false);
  const st = STATUS[q.status];
  return (
    <section
      aria-label={`Вопрос: ${q.text.slice(0, 60)}`}
      data-testid="question"
      data-tour="question"
      data-status={q.status}
      data-qid={q.id}
      className={cn(
        'grid min-w-0 content-start gap-2.5 rounded-lg border bg-card p-card',
        q.status === 'open' && 'border-[color-mix(in_srgb,var(--warning)_35%,var(--border))]',
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <Who q={q} channelName={channelName} />
        <StatusBadge tone={st.tone} tip={st.tip}>
          {st.label}
        </StatusBadge>
      </div>
      <p
        className="m-0 text-[15px] leading-[1.45] [overflow-wrap:anywhere]"
        data-testid="question-text"
      >
        {q.text}
      </p>
      {q.status === 'answered' && q.answer && !again ? (
        <div className="grid gap-1">
          <Said label="Ваш ответ" by={q.answered_by} at={q.answered_at}>
            <span data-testid="question-answer">{q.answer}</span>
          </Said>
          <AnswerKind q={q} />
        </div>
      ) : null}
      {q.status === 'open' || again ? (
        <AnswerForm q={q} onDone={again ? () => setAgain(false) : undefined} />
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {q.status === 'answered' && !again ? (
          <Button
            size="sm"
            variant="ghost"
            data-testid="answer-again"
            onClick={() => setAgain(true)}
          >
            Изменить ответ
          </Button>
        ) : null}
        <ResolveButton q={q} />
      </div>
      <QuestionMore q={q} />
    </section>
  );
}

/** Номер, ключ события, скрипт, канал и ссылка — только здесь. */
export function QuestionMore({ q }: { q: Question }) {
  return (
    <More className="mt-0">
      <span>вопрос: {q.id}</span>
      <span>событие: {q.key}</span>
      <span>
        спросил: {q.source}
        {q.created_by && q.created_by !== q.source ? ` (${q.created_by})` : ''}
      </span>
      {q.channel ? <span>канал: {q.channel}</span> : null}
      {q.link ? <span>ссылка: {q.link}</span> : null}
      {q.created ? <span>создан: {q.created}</span> : null}
      {q.updated ? <span>изменён: {q.updated}</span> : null}
      {q.answered_by ? <span>ответил: {q.answered_by}</span> : null}
      {q.answered_via ? <span>ответ пришёл: {viaName(q.answered_via)}</span> : null}
      {q.suggestion ? <span>предложение: {q.suggestion}</span> : null}
      {q.suggestion_why ? <span>почему: {q.suggestion_why}</span> : null}
      {q.suggested_by ? <span>предложил: {q.suggested_by}</span> : null}
      {q.suggested_at ? <span>предложено: {q.suggested_at}</span> : null}
      {q.resolved_by ? <span>решил: {q.resolved_by}</span> : null}
    </More>
  );
}

/** Решённый вопрос в истории: вопрос, ответ, кто и когда закрыл, как решилось. */
export function HistoryItem({
  q,
  channelName,
}: {
  q: Question;
  channelName: (id: string) => string;
}) {
  const who = whoText(q.resolved_by);
  return (
    <li
      data-testid="history-item"
      data-qid={q.id}
      className="grid min-w-0 gap-2 border-t py-3 first:border-t-0 first:pt-0"
    >
      <Who q={q} channelName={channelName} />
      <p className="m-0 [overflow-wrap:anywhere]">{q.text}</p>
      {q.answer ? (
        <div className="grid gap-1">
          <Said label="Ответ" by={q.answered_by} at={q.answered_at}>
            {q.answer}
          </Said>
          <AnswerKind q={q} />
        </div>
      ) : null}
      <span className="text-xs text-muted-foreground" data-testid="history-resolved">
        Решён{q.resolved_at ? ` ${dateTimeMsk(q.resolved_at)}` : ''}
        {who ? ` · ${who === 'вы' ? 'вами' : sourceName(who)}` : ''}
        {q.note ? ` · ${q.note}` : ''}
      </span>
      <QuestionMore q={q} />
    </li>
  );
}
