// «Напоминания»: очередь фабрики (что ещё уйдёт и что не дошло; «показать все» — ещё отправленные
// и отменённые) и форма «поставить напоминание» — как записи публикации (`WriteAction`): фабрика
// разбирает время по Москве и показывает, когда и что поставит, «да» с отсчётом ставит. Сейчас
// ничего не отправляется — напоминание уходит в своё время. «Отменить» у ждущего и недошедшего —
// так же, план фабрики (что значит отмена) и «да» (CC-0087, API CC-0081); у отменённого видно,
// кто и откуда отменил («из центра, вами»).
import { useState } from 'react';

import {
  addReminder,
  cancelReminder,
  notifyProblemText,
  planReminderCancel,
  planReminder,
  reminderWhy,
  useAfterReminderWrite,
  useReminders,
  type NotifyCancelPlan,
  type NotifyCancelResult,
  type NotifyReminder,
  type NotifyReminderPlan,
  type NotifyReminderResult,
  type ReminderForm,
} from '@/api/notify';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { whoText } from '@/pages/batches/format';
import { Done, Field, PlanHead, WriteAction } from '@/pages/publishing/Writes';
import { Loaded } from '@/components/common/Loaded';

import {
  attemptsText,
  backendLabel,
  cancelledText,
  REMINDER_STATUS,
  untilText,
  whenText,
} from './format';

const live = (r: NotifyReminder) => r.status !== 'sent' && r.status !== 'cancelled';

function CancelPlanView({ plan }: { plan: NotifyCancelPlan }) {
  const r = plan.reminder;
  const st = REMINDER_STATUS[plan.status];
  return (
    <>
      <PlanHead plan={plan} yes="можно отменить" no="отменить нельзя" />
      <blockquote
        className="m-0 border-l-2 border-primary pl-3 [overflow-wrap:anywhere]"
        data-testid="notify-cancel-text"
      >
        {r.text ?? '—'}
      </blockquote>
      <p className="m-0" data-testid="notify-cancel-when">
        Должно уйти {whenText(r.due) ?? r.due_msk} МСК · сейчас: {st.label}
      </p>
      <p className="m-0" data-testid="notify-cancel-means">
        {plan.means}
      </p>
      <p className="m-0 text-xs text-muted-foreground">
        Отменяет: {whoText(plan.by) ?? plan.by}, из центра — так и запишется у напоминания. Вернуть
        отменённое нельзя — только поставить заново.
      </p>
      <More className="mt-0">
        <span>
          {plan.action} · {plan.id} · by {plan.by} · via {plan.via}
        </span>
        <span>отпечаток {plan.fingerprint}</span>
      </More>
    </>
  );
}

function CancelDone({ result, onClose }: { result: NotifyCancelResult; onClose: () => void }) {
  const r = result.reminder;
  return (
    <Done tone="ok" testId="notify-cancel-done" title="Напоминание отменено" onClose={onClose}>
      <span>
        «{r.text ?? ''}» не уйдёт. {cancelledText(result.cancelled_by, result.cancelled_via)}.
      </span>
      <More className="mt-0">
        <span>
          {r.id} · cancelled {result.cancelled_at} · by {result.cancelled_by} · via{' '}
          {result.cancelled_via}
        </span>
      </More>
    </Done>
  );
}

function ReminderRow({
  r,
  max,
  onCancelled,
}: {
  r: NotifyReminder;
  max: number;
  onCancelled: (res: NotifyCancelResult) => void;
}) {
  const st = REMINDER_STATUS[r.status];
  const after = useAfterReminderWrite();
  const failedOn = Object.entries(r.backends ?? {})
    .filter(([, v]) => String(v).startsWith('error'))
    .map(([b]) => backendLabel(b));
  return (
    <li
      data-testid="notify-reminder"
      data-status={r.status}
      data-id={r.id}
      className="grid gap-1.5 border-b py-2.5 last:border-b-0"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="grid min-w-0 gap-0.5">
          <b className="font-semibold [overflow-wrap:anywhere]">{r.text ?? '—'}</b>
          <span className="text-xs text-muted-foreground" data-testid="notify-reminder-when">
            {whenText(r.due) ?? r.due_msk} МСК
            {r.status === 'sent' && r.sent_at ? ` · ушло ${whenText(r.sent_at)}` : ''}
            {r.status === 'cancelled' && r.cancelled_at
              ? ` · отменено ${whenText(r.cancelled_at)}`
              : ''}
          </span>
          {r.status === 'cancelled' && (r.cancelled_by || r.cancelled_via) ? (
            <span className="text-xs text-muted-foreground" data-testid="notify-reminder-cancelled">
              {cancelledText(r.cancelled_by, r.cancelled_via)}
            </span>
          ) : null}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={st.tone} tip={st.tip}>
            {st.label}
          </StatusBadge>
          {live(r) ? (
            <WriteAction
              id="notify-reminder-cancel"
              label="Отменить…"
              title="Отменить напоминание?"
              description="Фабрика проверила напоминание — вот что значит отмена."
              body={r.id}
              tip="Фабрика покажет, что значит отмена; отменит — после вашего «да»"
              confirmLabel="Отменить напоминание"
              pendingLabel="Отменяю…"
              danger
              triggerVariant="ghost"
              plan={planReminderCancel}
              act={(confirm) => cancelReminder(r.id, confirm)}
              view={(p) => <CancelPlanView plan={p} />}
              problemText={notifyProblemText}
              onSettled={after}
              onDone={onCancelled}
            />
          ) : null}
        </div>
      </div>
      {r.status === 'failed' || r.status === 'exhausted' ? (
        <span className="text-xs text-warning" data-testid="notify-reminder-tries">
          {attemptsText(r.attempts ?? 0, max)}
          {failedOn.length ? ` · не принял: ${failedOn.join(', ')}` : ''}
          {r.last_try ? ` · последняя — ${whenText(r.last_try)}` : ''}
        </span>
      ) : null}
      <More className="mt-0">
        <span>
          {r.id} · due {r.due ?? '—'} · {r.due_msk}
        </span>
        <span>
          created {r.created ?? '—'} · by {r.by ?? '—'} · via {r.via ?? '—'}
        </span>
        {r.status === 'cancelled' ? (
          <span>
            cancelled {r.cancelled_at ?? '—'} · by {r.cancelled_by ?? '—'} · via{' '}
            {r.cancelled_via ?? '—'}
          </span>
        ) : null}
        {r.reason ? <span>{r.reason}</span> : null}
        {Object.entries(r.backends ?? {}).map(([b, v]) => (
          <span key={b}>
            {b}: {String(v)}
          </span>
        ))}
      </More>
    </li>
  );
}

export function ReminderPlan({ plan }: { plan: NotifyReminderPlan }) {
  const until = untilText(plan.due, plan.now);
  return (
    <>
      <PlanHead plan={plan} yes="можно поставить" no="поставить нельзя" />
      <p className="m-0" data-testid="notify-plan-when">
        Напомнит <b className="font-semibold">{whenText(plan.due, plan.now)} МСК</b>
        {until ? <span className="text-muted-foreground"> · {until}</span> : null}
      </p>
      <blockquote
        className="m-0 border-l-2 border-primary pl-3 [overflow-wrap:anywhere]"
        data-testid="notify-plan-text"
      >
        {plan.text}
      </blockquote>
      <p className="m-0 text-xs text-muted-foreground">
        Сейчас ничего не отправится: напоминание уйдёт в своё время на все включённые каналы
        уведомлений. Поставит: {whoText(plan.by) ?? plan.by}.
      </p>
      <More className="mt-0">
        <span>
          at «{plan.at}» → due {plan.due} · {plan.due_msk}
        </span>
        <span>часы фабрики {plan.now}</span>
        <span>
          {plan.action} · by {plan.by} · отпечаток {plan.fingerprint}
        </span>
      </More>
    </>
  );
}

function ReminderDone({ result, onClose }: { result: NotifyReminderResult; onClose: () => void }) {
  const r = result.reminder;
  return (
    <Done
      tone={result.created ? 'ok' : 'warn'}
      testId="notify-reminder-done"
      title={result.created ? 'Напоминание поставлено' : 'Такое напоминание уже стоит'}
      onClose={onClose}
    >
      <span>
        {result.created
          ? `Уйдёт ${whenText(r.due) ?? r.due_msk} МСК: «${r.text ?? ''}».`
          : `На ${whenText(r.due) ?? r.due_msk} МСК уже стоит то же самое — второе не поставлено.`}
      </span>
      <More className="mt-0">
        <span>
          {r.id} · {r.due} · by {result.by}
        </span>
      </More>
    </Done>
  );
}

const EMPTY: ReminderForm = { at: '', text: '' };

function NewReminder() {
  const [form, setForm] = useState<ReminderForm>(EMPTY);
  const [done, setDone] = useState<NotifyReminderResult | null>(null);
  const after = useAfterReminderWrite();
  const why = reminderWhy(form);
  return (
    <div className="mb-3 grid gap-2.5 rounded-sm border p-3" data-testid="notify-new">
      <b className="text-sm font-semibold">Поставить напоминание</b>
      <div className="grid gap-2.5 sm:grid-cols-[10rem_minmax(0,1fr)]">
        <Field
          label="Когда, по Москве"
          value={form.at}
          onChange={(at) => setForm((f) => ({ ...f, at }))}
          testId="notify-new-at"
          placeholder="21:00"
          tip="«21:00» — ближайшие 21:00: сегодня, если ещё не прошло, иначе завтра. Или дата и время: «2026-10-13 09:30». Время — московское"
        />
        <Field
          label="О чём напомнить"
          value={form.text}
          onChange={(text) => setForm((f) => ({ ...f, text }))}
          testId="notify-new-text"
          placeholder="Например, принять ролики Reel"
          tip="Одна строка — переносы фабрика склеит. До 1000 знаков"
        />
      </div>
      <div>
        <WriteAction
          id="notify-new"
          label="Поставить…"
          title="Поставить напоминание?"
          description="Фабрика разобрала время — вот что она поставит в очередь."
          body={why ? null : form}
          why={why}
          tip="Фабрика покажет, когда и что напомнит; в очередь — после вашего «да»"
          confirmLabel="Поставить"
          plan={planReminder}
          act={addReminder}
          view={(p) => <ReminderPlan plan={p} />}
          problemText={notifyProblemText}
          onSettled={after}
          onDone={(r) => {
            setDone(r);
            setForm(EMPTY);
          }}
        />
      </div>
      {done ? <ReminderDone result={done} onClose={() => setDone(null)} /> : null}
    </div>
  );
}

export function Reminders() {
  const [all, setAll] = useState(false);
  const [cancelled, setCancelled] = useState<NotifyCancelResult | null>(null);
  const q = useReminders(all);
  return (
    <Card aria-labelledby="notify-reminders-title" data-testid="notify-reminders">
      <CardHead
        eyebrow="Очередь фабрики · время по Москве"
        title="Напоминания"
        titleId="notify-reminders-title"
        actions={
          <Tip content="Ещё и отправленные и отменённые">
            <Button
              size="sm"
              variant={all ? 'default' : 'ghost'}
              aria-pressed={all}
              data-testid="notify-reminders-all"
              onClick={() => setAll(!all)}
            >
              Показать все
            </Button>
          </Tip>
        }
      />
      <NewReminder />
      {cancelled ? (
        <div className="mb-3">
          <CancelDone result={cancelled} onClose={() => setCancelled(null)} />
        </div>
      ) : null}
      <Loaded q={q} reading="Читаю напоминания…" failed="Напоминания не прочитать">
        {(d) =>
          d.reminders.length ? (
            <>
              <ul
                className={cn('m-0 list-none p-0', q.isPlaceholderData && 'opacity-60')}
                data-testid="notify-reminder-list"
              >
                {d.reminders.map((r) => (
                  <ReminderRow key={r.id} r={r} max={d.max_attempts} onCancelled={setCancelled} />
                ))}
              </ul>
              <p className="m-0 mt-2 text-xs text-muted-foreground">
                Не дошло — фабрика пробует снова, всего до {d.max_attempts} раз.
              </p>
              <More>
                <span>{d.path}</span>
              </More>
            </>
          ) : (
            <EmptyState title={all ? 'Напоминаний ещё не ставили' : 'Ничего не ждёт'}>
              {all
                ? 'Поставьте первое выше — фабрика напомнит в своё время.'
                : 'Все напоминания ушли или отменены. «Показать все» — история.'}
            </EmptyState>
          )
        }
      </Loaded>
    </Card>
  );
}
