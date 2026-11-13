// Переключатель API-загрузки канала (CC-0069, API CC-0066): включить — только с заметкой (где и
// когда решили, после аудита YouTube API) и только если в окне подтверждения пользователь сам
// набрал фразу «аудит подтверждаю» (`audit_phrase` плана): центр её не подставляет, без неё
// фабрика откажет `audit_unconfirmed`, а токен сгорит. План показывает, что ещё не готово
// (`warnings`) — это не отказ, решение пользователя. Выключить — без фразы, заметка по желанию.
// Файл переключателя — под «подробнее».
import { useId, useState } from 'react';

import type { ApiSwitchState } from '@/api/publish';
import { apiSwitch, planApiSwitch, type SwitchPlan, type SwitchResult } from '@/api/publishWrites';
import { More } from '@/components/common/More';
import { inputBase } from '@/pages/channels/styles';

import { apiWarningText } from './format';
import { Disclosure, Done, Field, PlanHead, WriteAction } from './Writes';

function Warnings({ list, testId }: { list: string[]; testId: string }) {
  if (!list.length) return null;
  return (
    <div className="grid gap-1" data-testid={testId}>
      <span className="font-medium">Ещё не готово — фабрика предупреждает, но не запрещает:</span>
      <ul className="m-0 grid list-disc gap-0.5 pl-5">
        {list.map((w) => (
          <li key={w} className="text-warning [overflow-wrap:anywhere]">
            {apiWarningText(w)}
          </li>
        ))}
      </ul>
      <More className="mt-0">
        {list.map((w) => (
          <span key={`raw-${w}`}>{w}</span>
        ))}
      </More>
    </div>
  );
}

/** Поле фразы аудита: пусто при каждом открытии окна, без подсказки-вставки. */
function AuditPhrase({
  phrase,
  value,
  onChange,
}: {
  phrase: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const id = useId();
  return (
    <div className="grid gap-1" data-testid="switch-audit-field">
      <label htmlFor={id} className="text-[13px]">
        Чтобы включить, наберите сами: <b className="font-semibold">«{phrase}»</b>
      </label>
      <input
        id={id}
        data-testid="switch-audit"
        value={value}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onPaste={(e) => e.preventDefault()}
        className={inputBase}
      />
      <span className="text-xs text-muted-foreground">
        Фраза — ваше подтверждение, что аудит YouTube API пройден. Не та фраза — фабрика ничего не
        тронет, а план придётся проверить заново.
      </span>
    </div>
  );
}

function SwitchPlanView({
  plan,
  audit,
  setAudit,
}: {
  plan: SwitchPlan;
  audit: string;
  setAudit: (v: string) => void;
}) {
  const row = (plan.row ?? {}) as { note?: string };
  return (
    <>
      <PlanHead
        plan={plan}
        yes={plan.on ? 'можно включить' : 'можно выключить'}
        no={plan.on ? 'включить нельзя' : 'выключить нельзя'}
      />
      <p className="m-0" data-testid="switch-plan-what">
        {plan.on
          ? 'После включения ролики канала грузит программа — после вашего «да» на каждый ролик.'
          : 'После выключения ролики канала снова грузите вы через Studio.'}
      </p>
      {row.note ? (
        <div className="flex flex-wrap gap-x-2">
          <span className="text-muted-foreground">Заметка:</span>
          <span data-testid="switch-plan-note">{row.note}</span>
        </div>
      ) : null}
      <Warnings list={plan.warnings ?? []} testId="switch-plan-warnings" />
      {plan.ok && plan.audit_phrase ? (
        <AuditPhrase phrase={plan.audit_phrase} value={audit} onChange={setAudit} />
      ) : null}
      <More className="mt-0">
        <span>{plan.line}</span>
        <span>файл: {plan.path}</span>
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

export function SwitchWrites({ channel, state }: { channel: string; state: ApiSwitchState }) {
  const [note, setNote] = useState('');
  const [audit, setAudit] = useState('');
  const [done, setDone] = useState<SwitchResult | null>(null);
  const on = state.on;
  const finish = (r: SwitchResult) => {
    setDone(r);
    setNote('');
    setAudit('');
  };
  return (
    <div className="mt-2 grid gap-2" data-testid="switch-writes">
      {on ? (
        <Disclosure
          id="switch-off"
          label="Выключить API-загрузку"
          tip="Вернуть загрузку роликов канала вам — через Studio"
        >
          <Field
            label="Заметка"
            value={note}
            onChange={setNote}
            testId="switch-note"
            placeholder="Например: квота кончилась — грузим через Studio"
            tip="Необязательно; уйдёт в историю переключателя с пометкой «из центра»"
          />
          <WriteAction
            id="switch-off"
            label="Проверить и выключить…"
            title="Выключить API-загрузку канала?"
            description="Фабрика проверила, что запишет в переключатель."
            body={{ on: false, note: note.trim() || null }}
            tip="Фабрика проверит и покажет план; запись — после вашего «да»"
            confirmLabel="Выключить"
            plan={(b) => planApiSwitch(channel, b)}
            act={(c) => apiSwitch(channel, c, null)}
            view={(p) => <SwitchPlanView plan={p} audit="" setAudit={() => undefined} />}
            onDone={finish}
          />
        </Disclosure>
      ) : (
        <Disclosure
          id="switch-on"
          label="Включить API-загрузку"
          tip="Только после аудита YouTube API: ролики канала будет грузить программа"
        >
          <Field
            label="Заметка"
            rows={2}
            value={note}
            onChange={setNote}
            testId="switch-note"
            placeholder="Где и когда решили: например, «аудит пройден 11.10, письмо Google»"
            tip="Фабрика требует заметку: где и когда вы так решили. В историю уйдёт с пометкой «из центра»"
          />
          <WriteAction
            id="switch-on"
            label="Проверить и включить…"
            title="Включить API-загрузку канала?"
            description="Фабрика проверила, что запишет в переключатель и что ещё не готово."
            body={note.trim() ? { on: true, note: note.trim() } : null}
            why={note.trim() ? null : 'Напишите, где и когда решили включить'}
            tip="Фабрика проверит и покажет план и предупреждения; включение — после фразы и «да»"
            confirmLabel="Включить"
            ready={!!audit.trim()}
            onOpen={() => setAudit('')}
            plan={(b) => planApiSwitch(channel, b)}
            act={(c) => apiSwitch(channel, c, audit)}
            view={(p) => <SwitchPlanView plan={p} audit={audit} setAudit={setAudit} />}
            onDone={finish}
          />
        </Disclosure>
      )}
      {done ? (
        <Done
          tone={done.on && done.warnings.length ? 'warn' : 'ok'}
          testId="switch-done"
          title={done.on ? 'API-загрузка включена' : 'API-загрузка выключена'}
          onClose={() => setDone(null)}
        >
          <span>
            {done.on
              ? 'Ролики канала грузит программа — после вашего «да» на каждый.'
              : 'Ролики канала снова грузите вы через Studio.'}
          </span>
          {done.on ? <Warnings list={done.warnings} testId="switch-done-warnings" /> : null}
          <More className="mt-0">
            <span>{done.state.line}</span>
          </More>
        </Done>
      ) : null}
    </div>
  );
}
