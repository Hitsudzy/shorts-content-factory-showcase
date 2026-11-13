// Пауза канала (CC-0068, API CC-0065): поставить — причина обязательна, срок — день (00:00 МСК)
// или без срока («до снятия»); если пауза уже стоит — заменить её (`replace`). Снять — с
// заметкой. Обе — план фабрики и «да» с отсчётом (./Writes). Фабрика помечает причину и заметку
// «(из центра)»; номер паузы и реестр — под «подробнее».
import { useState } from 'react';

import type { ChannelPause } from '@/api/publish';
import {
  pauseClear,
  pauseSet,
  planPauseClear,
  planPauseSet,
  type PausePlan,
  type PauseWriteResult,
} from '@/api/publishWrites';
import { More } from '@/components/common/More';
import { dateTimeMsk } from '@/pages/batches/format';

import { Disclosure, Done, Field, PlanHead, WriteAction } from './Writes';

const untilText = (u: unknown) =>
  typeof u === 'string' && u ? `до ${dateTimeMsk(u) ?? u}` : 'без срока — до снятия';

function SetPlan({ plan }: { plan: PausePlan }) {
  const row = (plan.row ?? {}) as { reason?: string; until?: string | null };
  const replaces = (plan as { replaces?: { reason?: string } | null }).replaces;
  return (
    <>
      <PlanHead plan={plan} yes="можно поставить" no="поставить нельзя" />
      <dl className="m-0 grid gap-1">
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted-foreground">Причина:</dt>
          <dd className="m-0" data-testid="pause-plan-reason">
            {row.reason ?? '—'}
          </dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted-foreground">Срок:</dt>
          <dd className="m-0" data-testid="pause-plan-until">
            {untilText(row.until)}
          </dd>
        </div>
        {replaces ? (
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted-foreground">Заменит паузу:</dt>
            <dd className="m-0" data-testid="pause-plan-replaces">
              {replaces.reason}
            </dd>
          </div>
        ) : null}
      </dl>
      <p className="m-0 text-muted-foreground">
        Пока пауза стоит, фабрика не ставит ролики в слоты, а завтрашний слот остаётся пустым.
      </p>
      <More className="mt-0">
        <span>{plan.line}</span>
        {plan.open_row ? <span>стоит: {plan.open_row.pause_id}</span> : null}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function ClearPlan({ plan }: { plan: PausePlan }) {
  const row = (plan.row ?? {}) as { clear_note?: string };
  return (
    <>
      <PlanHead plan={plan} yes="можно снять" no="снять нельзя" />
      {plan.open_row ? (
        <dl className="m-0 grid gap-1">
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted-foreground">Снимет паузу:</dt>
            <dd className="m-0" data-testid="pause-plan-reason">
              {plan.open_row.reason}
            </dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-muted-foreground">Заметка:</dt>
            <dd className="m-0" data-testid="pause-plan-note">
              {row.clear_note ?? '—'}
            </dd>
          </div>
        </dl>
      ) : null}
      <p className="m-0 text-muted-foreground">
        Строка паузы в реестре остаётся — с отметкой, кто и когда снял.
      </p>
      <More className="mt-0">
        <span>{plan.line}</span>
        {plan.open_row ? <span>пауза: {plan.open_row.pause_id}</span> : null}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

export function PauseWrites({ channel, pause }: { channel: string; pause: ChannelPause }) {
  const paused = pause.state === 'paused';
  const [reason, setReason] = useState('');
  const [until, setUntil] = useState('');
  const [note, setNote] = useState('');
  const [done, setDone] = useState<PauseWriteResult | null>(null);
  return (
    <div className="mt-2 grid gap-2" data-testid="pause-writes">
      <div className="flex flex-wrap items-start gap-2">
        <Disclosure
          id="pause-set"
          label={paused ? 'Заменить паузу' : 'Поставить на паузу'}
          tip={
            paused
              ? 'Снять нынешнюю паузу и поставить другую — с новой причиной и сроком'
              : 'Остановить выкладку роликов канала в слоты — с причиной и, если нужно, сроком'
          }
        >
          <Field
            label="Причина"
            value={reason}
            onChange={setReason}
            testId="pause-reason"
            placeholder="Например: проверка — смотрим вкладку «Авторские права»"
            tip="Фабрика требует причину; в реестр она уйдёт с пометкой «из центра»"
          />
          <Field
            label="До какого дня"
            type="date"
            value={until}
            onChange={setUntil}
            testId="pause-until"
            tip="Пауза кончится в 00:00 МСК этого дня; пусто — до снятия"
            hint={until ? undefined : 'Пусто — пауза стоит, пока её не снимут.'}
          />
          {paused ? (
            <p className="m-0 text-xs text-muted-foreground" data-testid="pause-replace-note">
              Нынешняя пауза снимется, вместо неё встанет эта.
            </p>
          ) : null}
          <WriteAction
            id="pause-set"
            label={paused ? 'Проверить и заменить…' : 'Проверить и поставить…'}
            title={paused ? 'Заменить паузу канала?' : 'Поставить канал на паузу?'}
            description="Фабрика проверила, что будет записано в реестр пауз."
            body={
              reason.trim()
                ? { reason: reason.trim(), until: until || null, replace: paused }
                : null
            }
            why={reason.trim() ? null : 'Напишите причину паузы'}
            tip="Фабрика проверит паузу и покажет план; запись — после вашего «да»"
            confirmLabel={paused ? 'Заменить' : 'Поставить'}
            plan={(b) => planPauseSet(channel, b)}
            act={(c) => pauseSet(channel, c)}
            view={(p) => <SetPlan plan={p} />}
            onDone={(r) => {
              setDone(r);
              setReason('');
              setUntil('');
            }}
          />
        </Disclosure>
        {paused ? (
          <Disclosure id="pause-clear" label="Снять паузу" tip="Вернуть выкладку роликов в слоты">
            <Field
              label="Заметка"
              value={note}
              onChange={setNote}
              testId="pause-note"
              placeholder="Например: проверка пройдена"
              tip="Необязательно; в реестр уйдёт с пометкой «из центра»"
            />
            <WriteAction
              id="pause-clear"
              label="Проверить и снять…"
              title="Снять паузу канала?"
              description="Фабрика проверила, какую паузу снимет."
              body={{ note: note.trim() || null }}
              tip="Фабрика проверит и покажет, какую паузу снимет; запись — после вашего «да»"
              confirmLabel="Снять"
              plan={(b) => planPauseClear(channel, b)}
              act={(c) => pauseClear(channel, c)}
              view={(p) => <ClearPlan plan={p} />}
              onDone={(r) => {
                setDone(r);
                setNote('');
              }}
            />
          </Disclosure>
        ) : null}
      </div>
      {done ? (
        <Done
          tone="ok"
          testId="pause-done"
          title={done.action === 'pause_set' ? 'Пауза поставлена' : 'Пауза снята'}
          onClose={() => setDone(null)}
        >
          <span>
            {done.action === 'pause_set'
              ? `${done.row.reason} · ${untilText(done.row.until)}`
              : 'Ролики снова встают в слоты.'}
          </span>
          <More className="mt-0">
            <span>пауза: {done.row.pause_id}</span>
          </More>
        </Done>
      ) : null}
    </div>
  );
}
