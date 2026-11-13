// Рубильник расписания (`POST /api/schedule/switch {on, note}`): включить — только с
// заметкой, где и когда вы сказали «включай» (фабрика без неё отказывает 422 `note_required`,
// её сообщение — как есть); выключить — заметка по желанию. Оба — через подтверждение.
import { useId, useState } from 'react';

import { useSetSwitch, type SchedulePlan } from '@/api/schedule';
import { Card, CardHead } from '@/components/common/Card';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { More } from '@/components/common/More';
import { StatusBadge, StatusPill } from '@/components/common/Status';
import { Button } from '@/components/ui/button';
import { inputBase } from '@/pages/channels/styles';

import { dateTimeMsk, noteText, switchState, timerState, whoText } from './format';
import { Refusal, Row } from './parts';

export function SwitchCard({ plan }: { plan: SchedulePlan }) {
  const sw = plan.switch;
  const state = switchState(sw);
  const timer = timerState(plan.timer);
  const set = useSetSwitch();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const noteId = useId();
  const turnOn = !sw.on;
  const since = dateTimeMsk(sw.since);
  const who = whoText(sw.by);
  const lastNote = noteText(sw.note);
  const last = sw.history.at(-1);

  const onOpenChange = (v: boolean) => {
    setOpen(v);
    if (v) {
      setNote('');
      set.reset();
    }
  };
  const confirm = () =>
    set.mutate({ on: turnOn, note: note.trim() || null }, { onSuccess: () => setOpen(false) });

  return (
    <Card
      aria-labelledby="switch-title"
      data-testid="switch-card"
      data-tour="switch"
      className="grid content-start gap-3"
    >
      <CardHead
        eyebrow="Рубильник расписания"
        title={sw.on ? 'Расписание включено' : 'Расписание выключено'}
        titleId="switch-title"
        actions={
          <StatusPill
            tone={state.tone === 'ok' ? 'live' : state.tone}
            tip="Рубильник: включён — фабрика по расписанию сама запускает батч дня по плану; выключен — только запуск вручную"
            data-testid="switch-state"
          >
            {state.label}
          </StatusPill>
        }
      />
      <p className="m-0 text-muted-foreground">{state.text}</p>
      <ul className="m-0 grid list-none p-0">
        <Row
          label="Последнее изменение"
          tip="Когда и кто последним переключил рубильник (время московское)"
          testId="switch-since"
        >
          {since ? (
            <span>
              {since}
              {who ? <span className="text-muted-foreground"> · {who}</span> : null}
            </span>
          ) : (
            <span className="text-muted-foreground">не переключали</span>
          )}
        </Row>
        {lastNote ? (
          <Row label="Заметка" tip="Что было сказано при переключении" testId="switch-note">
            <span className="[overflow-wrap:anywhere]">{lastNote}</span>
          </Row>
        ) : null}
        <Row
          label="Таймер расписания"
          tip="Таймер расписания проверяет план раз в 15 минут. Без него батчи по расписанию не стартуют даже при включённом рубильнике"
          testId="switch-timer"
        >
          <StatusBadge tone={timer.tone}>{timer.label}</StatusBadge>
        </Row>
      </ul>
      <div className="flex flex-wrap gap-2">
        <ConfirmDialog
          open={open}
          onOpenChange={onOpenChange}
          trigger={
            <Button variant={turnOn ? 'default' : 'destructive'} data-testid="switch-toggle">
              {turnOn ? 'Включить расписание…' : 'Выключить расписание…'}
            </Button>
          }
          title={turnOn ? 'Включить расписание?' : 'Выключить расписание?'}
          description={
            turnOn
              ? 'Фабрика начнёт сама запускать батч дня по плану, в окне канала. Нужна заметка: где и когда вы сказали «включай» — она останется в журнале рубильника.'
              : 'Батчи по расписанию перестанут запускаться; идущий батч это не остановит. Запустить батч можно будет вручную.'
          }
          confirmLabel={turnOn ? 'Включить' : 'Выключить'}
          pendingLabel={turnOn ? 'Включаю…' : 'Выключаю…'}
          pending={set.isPending}
          danger={!turnOn}
          onConfirm={confirm}
          error={set.isError ? <Refusal error={set.error} title="Фабрика не переключила" /> : null}
        >
          <label htmlFor={noteId} className="grid gap-1 text-[13px]">
            <span className="font-semibold">
              {turnOn ? 'Заметка — обязательно' : 'Заметка — по желанию'}
            </span>
            <textarea
              id={noteId}
              data-testid="switch-note-input"
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={
                turnOn ? 'например: «в чате 10.10 вечером сказал включай»' : 'почему выключаете'
              }
              className={inputBase}
            />
          </label>
        </ConfirmDialog>
      </div>
      <More className="mt-0">
        <span>рубильник: {sw.line}</span>
        <span>таймер: {plan.timer}</span>
        {sw.error ? <span>ошибка: {sw.error}</span> : null}
        {last?.task ? <span>задача: {last.task}</span> : null}
        {sw.history
          .slice(-5)
          .reverse()
          .map((h, i) => (
            <span key={i}>
              {h.at} ·{' '}
              {h.action === 'enable' ? 'включил' : h.action === 'disable' ? 'выключил' : '—'}{' '}
              {h.by ?? ''}
              {h.note ? ` · ${h.note}` : ''}
            </span>
          ))}
      </More>
    </Card>
  );
}
