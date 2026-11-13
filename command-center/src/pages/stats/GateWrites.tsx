// Подпись цены и решение по правилу воротец (CC-0115 шаг 3 → CC-0114 API): у строки правила на
// «Статистике» — «Подписать цену…» (цена не ниже измеренной и ваша заметка) и «Записать
// решение…» (мерить или предупреждать, номер задачи, заметка). Обе — план фабрики (ничего не
// пишет) → «да», набранное вами, с токеном на 120 с. План получает `ledger_sha256` чтения, которое
// вы смотрели: леджер с тех пор сменился — «Цены изменились, откройте заново». Имя правила, путь
// леджера, отпечатки и строки фабрики — под «подробнее».
import { useId, useState } from 'react';

import {
  GATE_CHANGED,
  gateDecide,
  gateProblemText,
  gateSign,
  planGateDecide,
  planGateSign,
  useAfterGateWrite,
  type GatePriceResult,
  type GateWritePlan,
  type GateWriteResult,
} from '@/api/gatePrices';
import { More } from '@/components/common/More';
import { plural } from '@/pages/batches/format';
import { Disclosure, Done, Field, PlanHead, WriteAction } from '@/pages/publishing/Writes';

import { MODE, ruleText } from './gateWords';

const videos = (n: number) =>
  `${n} ${plural(n, 'готовый ролик', 'готовых ролика', 'готовых роликов')}`;

const TASK = /^CF-\d{4}$/;

/** Цена из поля: целое 0 или больше; иначе null. */
function priceOf(text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  return Number(t);
}

/** Что запишется — словами по блоку плана. */
function BlockText({ plan }: { plan: GateWritePlan | GateWriteResult }) {
  const b = plan.block ?? {};
  if (plan.kind === 'sign') {
    const n = typeof b.price === 'number' ? b.price : null;
    return (
      <span data-testid="gate-write-what">
        {n == null
          ? 'Подпись цены правила'
          : `Подпись: ради этого правила можно терять ${videos(n)} окна — после подписи правило отказывает`}
      </span>
    );
  }
  const mode = typeof b.mode === 'string' ? (MODE[b.mode] ?? b.mode) : null;
  return (
    <span data-testid="gate-write-what">{mode ? `Решение: ${mode}` : 'Решение по правилу'}</span>
  );
}

function GatePlanView({ plan }: { plan: GateWritePlan }) {
  const sign = plan.kind === 'sign';
  const changed = plan.refusals.some((r) => r.code === 'check_changed');
  const b = plan.block ?? {};
  return (
    <>
      <PlanHead
        plan={plan}
        yes={sign ? 'можно подписать' : 'можно записать'}
        no={sign ? 'подписать нельзя' : 'записать нельзя'}
      />
      {changed ? (
        <p
          role="status"
          data-testid="gate-changed"
          className="m-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] p-3 font-semibold"
        >
          {GATE_CHANGED}: закройте окно — цены на карточке обновятся, и проверьте ещё раз.
        </p>
      ) : null}
      {plan.ok ? (
        <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-2 gap-y-1">
          <div className="contents">
            <dt className="text-muted-foreground">Правило:</dt>
            <dd className="m-0 font-semibold">{ruleText(plan.rule)}</dd>
          </div>
          <div className="contents">
            <dt className="text-muted-foreground">Запишется:</dt>
            <dd className="m-0">
              <BlockText plan={plan} />
            </dd>
          </div>
          {typeof b.note === 'string' ? (
            <div className="contents">
              <dt className="text-muted-foreground">Заметка:</dt>
              <dd className="m-0 [overflow-wrap:anywhere]" data-testid="gate-write-note">
                {b.note}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : plan.refusals.length > 1 ? (
        <ul className="m-0 grid list-disc gap-0.5 pl-5" data-testid="gate-write-refusals">
          {plan.refusals.slice(1).map((r) => (
            <li key={r.code}>{r.message}</li>
          ))}
        </ul>
      ) : null}
      <p className="m-0 text-xs text-muted-foreground">
        Запись ставится от вашего имени, из центра; фабрика сама внесёт её в журнал цен.
      </p>
      <More className="mt-0">
        <span>
          {plan.action} · {plan.rule} · by {plan.by} · via {plan.via}
        </span>
        {plan.path ? <span>файл: {plan.path}</span> : null}
        {plan.task ? <span>задача фабрики: {plan.task}</span> : null}
        <span>
          журнал цен: {plan.base_sha256 ?? '—'} → {plan.new_sha256 ?? 'без записи'}
        </span>
        {plan.refusals.map((r) => (
          <span key={r.code}>
            {r.code}: {r.line}
          </span>
        ))}
        {plan.lines.map((l, i) => (
          <span key={i}>{l}</span>
        ))}
      </More>
    </>
  );
}

function GateDone({ result, onClose }: { result: GateWriteResult; onClose: () => void }) {
  return (
    <Done
      tone="ok"
      testId="gate-write-done"
      title={result.kind === 'sign' ? 'Цена подписана' : 'Решение записано'}
      onClose={onClose}
    >
      <BlockText plan={result} />
      <More className="mt-0">
        <span>
          {result.action} · {result.rule}
        </span>
        {result.commit ? <span>запись фабрики: {result.commit}</span> : null}
        <span>журнал цен: {result.sha256}</span>
      </More>
    </Done>
  );
}

function SignForm({
  r,
  base,
  onDone,
}: {
  r: GatePriceResult;
  base: string | null;
  onDone: (res: GateWriteResult) => void;
}) {
  const floor = r.actions.measured_price;
  const min = typeof floor === 'number' ? Math.ceil(floor) : null;
  const [price, setPrice] = useState(min == null ? '' : String(min));
  const [note, setNote] = useState('');
  const after = useAfterGateWrite();
  const n = priceOf(price);
  const clean = note.trim();
  const why =
    n == null
      ? 'Цена — целое число готовых роликов, 0 или больше'
      : min != null && n < min
        ? `Не меньше измеренной: ${videos(min)}`
        : !clean
          ? 'Напишите заметку: почему подписываете эту цену'
          : null;
  return (
    <Disclosure
      id="gate-sign"
      label="Подписать цену…"
      tip="После подписи правило отказывает: вы согласны терять столько готовых роликов ради него. Фабрика сначала покажет план"
    >
      <Field
        label="Цена — сколько готовых роликов можно терять"
        value={price}
        onChange={setPrice}
        testId="gate-sign-price"
        invalid={n == null || (min != null && n < min)}
        hint={min != null ? `Измерено: ${videos(min)} — меньше подписать нельзя` : undefined}
      />
      <Field
        label="Заметка (обязательна)"
        value={note}
        onChange={setNote}
        testId="gate-sign-note"
        rows={2}
        placeholder="Например: решили в чате — пусть отказывает"
        hint="Без ваших слов фабрика подпись не пишет; заметка останется в журнале цен"
      />
      <div>
        <WriteAction
          id="gate-sign"
          label="Показать план…"
          title={`Подписать цену: «${ruleText(r.rule)}»?`}
          description="Фабрика проверила подпись — вот что запишется в журнал цен."
          body={why || n == null ? null : { price: n, note: clean, base_sha256: base }}
          why={why}
          tip="Фабрика покажет план; подпишет — после вашего «да»"
          confirmLabel="Подписать"
          pendingLabel="Подписываю…"
          yes
          plan={(b) => planGateSign(r.rule, b)}
          act={(c) => gateSign(r.rule, c)}
          view={(p) => <GatePlanView plan={p} />}
          problemText={gateProblemText}
          onSettled={after}
          onDone={(res) => {
            setNote('');
            onDone(res);
          }}
        />
      </div>
    </Disclosure>
  );
}

function ModeChoice({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const name = useId();
  const opts = [
    {
      v: 'measure',
      label: 'Только мерить',
      hint: 'правило ничего не останавливает, фабрика считает',
    },
    { v: 'warn', label: 'Предупреждать', hint: 'ролик идёт дальше, вы видите предупреждение' },
  ];
  return (
    <fieldset className="m-0 grid gap-1 border-0 p-0" data-testid="gate-decide-mode">
      <legend className="mb-1 text-xs text-muted-foreground">Как правилу работать</legend>
      {opts.map((o) => (
        <label key={o.v} className="flex items-baseline gap-2">
          <input
            type="radio"
            name={name}
            value={o.v}
            checked={value === o.v}
            onChange={() => onChange(o.v)}
            data-testid={`gate-decide-${o.v}`}
          />
          <span>
            {o.label} <span className="text-xs text-muted-foreground">— {o.hint}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

function DecideForm({
  r,
  base,
  onDone,
}: {
  r: GatePriceResult;
  base: string | null;
  onDone: (res: GateWriteResult) => void;
}) {
  const [mode, setMode] = useState('');
  const [task, setTask] = useState('');
  const [note, setNote] = useState('');
  const after = useAfterGateWrite();
  const t = task.trim().toUpperCase();
  const clean = note.trim();
  const why = !mode
    ? 'Выберите, как правилу работать'
    : !TASK.test(t)
      ? 'Укажите номер задачи фабрики вида CF-0330'
      : !clean
        ? 'Напишите заметку: почему так решили'
        : null;
  return (
    <Disclosure
      id="gate-decide"
      label="Записать решение…"
      tip="Мерить или предупреждать — отказ делает только подпись цены. Фабрика сначала покажет план"
    >
      <ModeChoice value={mode} onChange={setMode} />
      <Field
        label="Задача фабрики, к которой решение"
        value={task}
        onChange={setTask}
        testId="gate-decide-task"
        placeholder="CF-0330"
        tip="Номер задачи, где решали, — фабрика пишет его рядом с решением"
      />
      <Field
        label="Заметка (обязательна)"
        value={note}
        onChange={setNote}
        testId="gate-decide-note"
        rows={2}
        placeholder="Например: пусть пока предупреждает — мало замеров"
      />
      <div>
        <WriteAction
          id="gate-decide"
          label="Показать план…"
          title={`Записать решение: «${ruleText(r.rule)}»?`}
          description="Фабрика проверила решение — вот что запишется в журнал цен."
          body={why ? null : { mode, task: t, note: clean, base_sha256: base }}
          why={why}
          tip="Фабрика покажет план; запишет — после вашего «да»"
          confirmLabel="Записать"
          pendingLabel="Записываю…"
          yes
          plan={(b) => planGateDecide(r.rule, b)}
          act={(c) => gateDecide(r.rule, c)}
          view={(p) => <GatePlanView plan={p} />}
          problemText={gateProblemText}
          onSettled={after}
          onDone={(res) => {
            setNote('');
            setTask('');
            setMode('');
            onDone(res);
          }}
        />
      </div>
    </Disclosure>
  );
}

/** Записи строки правила: подпись и решение — что разрешает `actions` чтения. */
export function GateWrites({ r, base }: { r: GatePriceResult; base: string | null }) {
  const [done, setDone] = useState<GateWriteResult | null>(null);
  if (!r.actions.sign && !r.actions.decide && !done) return null;
  return (
    <div className="mt-1 grid gap-2" data-testid="gate-writes">
      {done ? <GateDone result={done} onClose={() => setDone(null)} /> : null}
      <div className="grid gap-2">
        {r.actions.sign ? <SignForm r={r} base={base} onDone={setDone} /> : null}
        {r.actions.decide ? <DecideForm r={r} base={base} onDone={setDone} /> : null}
      </div>
    </div>
  );
}
