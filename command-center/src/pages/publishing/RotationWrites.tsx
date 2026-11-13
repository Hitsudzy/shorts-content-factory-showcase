// Ротация паттернов (CC-0068, API CC-0065): назначить пары сценариям батча (`rotate.assign`:
// уже стоящая пара возвращается как есть, тема, что ждёт материала, пропускается — если только
// вы не посмотрели перепись и не согласны), отклонить пару (в плане — вердикт
// `rotate.rule_on_rejection`: отказ примут и дадут замену или отклонят по правилу R1–R8) и
// отказаться за нехваткой материала (файл дефицита планировщика под `pipeline/`: назначение
// закрывается без замены). Номера сценариев, пары и строки фабрики — под «подробнее».
import { useState } from 'react';

import {
  deficitWhy,
  idsOf,
  MIN_REASON_CHARS,
  planRotationAssign,
  planRotationRefuse,
  planRotationReject,
  rotationAssign,
  rotationRefuse,
  rotationReject,
  type AssignScript,
  type RotationPlan,
  type RotationResult,
  type Ruling,
} from '@/api/publishWrites';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';

import { Check, Disclosure, Done, Field, PlanHead, WriteAction } from './Writes';

/** Правила `rule_on_rejection` словами (почему отказ отклонят). */
const RULE_TEXT: Record<string, string> = {
  R1: 'у сценария нет стоящего назначения',
  R2: 'причина слишком короткая',
  R3: 'от пары этого сценария уже отказывались — один отказ на сценарий',
  R4: 'эту пару уже отклоняли в нынешнем окне — это вопрос к паттерну, решает человек',
  R5: 'отступать некуда: другой исполнимой пары сейчас нет',
  R6: 'отказ сломал бы окно без повторов или ровное распределение у уже стоящих назначений',
  R7: 'у канала нет пары без этого ритма',
  R8: 'замена перекосила бы окно распределения',
};

const ordinal = (i: number) => `${i + 1}-й`;

const STATE_TEXT: Record<string, string> = {
  standing: 'пара уже стоит — вернётся как есть',
  held: 'тема ждёт пополнения пула — пропускается',
  fresh: 'пару вытянет ротация',
};

function reasonWhy(reason: string): string | null {
  const n = reason.trim().length;
  return n < MIN_REASON_CHARS
    ? `Причина — не короче ${MIN_REASON_CHARS} знаков (сейчас ${n}): она остаётся в журнале ротации`
    : null;
}

function AssignPlan({ plan }: { plan: RotationPlan }) {
  const scripts = (plan.scripts ?? []) as AssignScript[];
  return (
    <>
      <PlanHead plan={plan} yes="можно назначить" no="назначить нельзя" />
      <ul className="m-0 grid list-none gap-1 p-0" data-testid="assign-scripts">
        {scripts.map((s, i) => (
          <li key={s.script_id} data-testid="assign-script" data-state={s.state}>
            Сценарий {ordinal(i)}: {STATE_TEXT[s.state] ?? s.state}
            {s.state === 'held' && s.retry_when ? ` (${s.retry_when})` : ''}
          </li>
        ))}
      </ul>
      <More className="mt-0">
        {scripts.map((s) => (
          <span key={s.script_id}>
            {s.script_id}: {s.state}
            {s.pattern_id ? ` ${s.pattern_id}/${s.rhythm_id} seq ${s.seq}` : ''}
          </span>
        ))}
        <span>исполнимые пары: {((plan.eligible_pairs ?? []) as string[]).join(', ') || '—'}</span>
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function RejectPlan({ plan }: { plan: RotationPlan }) {
  const ruling = (plan.ruling ?? null) as Ruling | null;
  const upheld = ruling?.verdict === 'upheld';
  return (
    <>
      <PlanHead plan={plan} yes="можно записать" no="отклонить нельзя" />
      {ruling ? (
        <div className="grid gap-1" data-testid="ruling" data-verdict={ruling.verdict}>
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge
              tone={upheld ? 'ok' : 'warn'}
              tip="Решение страж ротации выносит заранее: план ничего не пишет"
            >
              {upheld ? 'отказ примут' : 'отказ отклонят'}
            </StatusBadge>
            <span data-testid="ruling-text">
              {upheld
                ? ruling.excluded_rhythm
                  ? 'Вместо этой пары ротация даст другую — без отклонённого ритма.'
                  : 'Вместо этой пары ротация даст следующую по кругу.'
                : `Назначение остаётся: ${(ruling.rule && RULE_TEXT[ruling.rule]) || 'так решил страж ротации'}.`}
            </span>
          </span>
          <span className="text-muted-foreground">
            {upheld
              ? 'В журнал запишется принятый отказ и новая строка с заменой.'
              : 'В журнал запишется отклонённый отказ — пара сценария не меняется.'}
          </span>
        </div>
      ) : null}
      <More className="mt-0">
        {ruling?.rule ? <span>правило {ruling.rule}</span> : null}
        {ruling?.replacement ? <span>замена: {ruling.replacement.join('/')}</span> : null}
        {ruling?.excluded_rhythm ? <span>без ритма: {ruling.excluded_rhythm}</span> : null}
        {ruling?.explanation ? <span>{ruling.explanation}</span> : null}
        {plan.script_id ? <span>сценарий: {String(plan.script_id)}</span> : null}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function RefusePlan({ plan }: { plan: RotationPlan }) {
  const anchors = (plan.anchors ?? []) as unknown[];
  return (
    <>
      <PlanHead plan={plan} yes="можно отказаться" no="отказаться нельзя" />
      {plan.ok ? (
        <p className="m-0" data-testid="refuse-what">
          Назначение закроется без замены, а тема будет ждать, пока в пуле не появится нужный
          материал{anchors.length ? ` (не хватает: ${anchors.length})` : ''}.
        </p>
      ) : null}
      <More className="mt-0">
        {plan.deficit ? <span>дефицит: {String(plan.deficit)}</span> : null}
        {anchors.map((a, i) => (
          <span key={i}>{JSON.stringify(a)}</span>
        ))}
        {plan.script_id ? <span>сценарий: {String(plan.script_id)}</span> : null}
        <span>отпечаток проверки {plan.fingerprint}</span>
      </More>
    </>
  );
}

function RotationDone({ r, onClose }: { r: RotationResult; onClose: () => void }) {
  const res = r.result as Record<string, unknown> | unknown[] | null;
  const verdict = !Array.isArray(res) ? (res?.verdict as string | undefined) : undefined;
  const title =
    r.action === 'rotation_assign'
      ? 'Пары назначены'
      : r.action === 'rotation_reject'
        ? verdict === 'upheld'
          ? 'Отказ принят — пара заменена'
          : 'Отказ отклонён и записан — назначение остаётся'
        : 'Отказ записан — тема ждёт материала';
  const assigned = Array.isArray(res)
    ? res.filter((x) => (x as { state?: string }).state !== 'standing').length
    : null;
  return (
    <Done
      tone={r.action === 'rotation_reject' && verdict !== 'upheld' ? 'warn' : 'ok'}
      title={title}
      testId="rotation-done"
      onClose={onClose}
    >
      {assigned != null ? <span>Новых назначений: {assigned}.</span> : null}
      <More className="mt-0">
        {(Array.isArray(res) ? res : [res]).map((x, i) => (
          <span key={i}>{JSON.stringify(x)}</span>
        ))}
      </More>
    </Done>
  );
}

export function RotationWrites({ channel }: { channel: string }) {
  const [batch, setBatch] = useState('');
  const [ids, setIds] = useState('');
  const [despite, setDespite] = useState(false);
  const [rej, setRej] = useState({ script: '', batch: '', reason: '', rhythm: false });
  const [ref, setRef] = useState({ script: '', batch: '', reason: '', deficit: '' });
  const [done, setDone] = useState<RotationResult | null>(null);

  const scriptIds = idsOf(ids);
  const whyAssign = !batch.trim()
    ? 'Укажите батч'
    : !scriptIds.length
      ? 'Укажите сценарии батча'
      : null;
  const whyReject = !rej.script.trim() ? 'Укажите сценарий' : reasonWhy(rej.reason);
  const whyRefuse = !ref.script.trim()
    ? 'Укажите сценарий'
    : (reasonWhy(ref.reason) ?? deficitWhy(ref.deficit));

  return (
    <div className="mt-2 grid gap-2" data-testid="rotation-writes">
      <div className="flex flex-wrap items-start gap-2">
        <Disclosure
          id="rot-assign"
          label="Назначить пары"
          tip="Дать сценариям батча пары паттернов по кругу ротации"
        >
          <Field
            label="Батч"
            value={batch}
            onChange={setBatch}
            testId="assign-batch"
            placeholder="2026-10-09T0200Z"
          />
          <Field
            label="Сценарии"
            rows={2}
            value={ids}
            onChange={setIds}
            testId="assign-ids"
            tip="Через пробел, запятую или с новой строки"
          />
          <Check
            label="Назначить и темам, что ждут материала"
            checked={despite}
            onChange={setDespite}
            testId="assign-despite"
            tip="Вы посмотрели перепись пула и не согласны, что материала не хватает"
          />
          <WriteAction
            id="rot-assign"
            label="Проверить и назначить…"
            title="Назначить пары паттернов?"
            description="Фабрика проверила, какие пары получат сценарии."
            body={
              whyAssign
                ? null
                : { batch_id: batch.trim(), script_ids: scriptIds, despite_shortage: despite }
            }
            why={whyAssign}
            tip="Фабрика покажет, что получит каждый сценарий; запись — после вашего «да»"
            confirmLabel="Назначить"
            plan={(b) => planRotationAssign(channel, b)}
            act={(c) => rotationAssign(channel, c)}
            view={(p) => <AssignPlan plan={p} />}
            onDone={setDone}
          />
        </Disclosure>
        <Disclosure
          id="rot-reject"
          label="Отклонить пару"
          tip="Отказаться от пары, назначенной сценарию: страж ротации решит, примут ли отказ"
        >
          <Field
            label="Сценарий"
            value={rej.script}
            onChange={(v) => setRej((x) => ({ ...x, script: v }))}
            testId="reject-script"
          />
          <Field
            label="Батч"
            value={rej.batch}
            onChange={(v) => setRej((x) => ({ ...x, batch: v }))}
            testId="reject-batch"
            tip="Нужен, если у сценария назначения в нескольких батчах"
            hint="Необязательно."
          />
          <Field
            label="Причина"
            rows={2}
            value={rej.reason}
            onChange={(v) => setRej((x) => ({ ...x, reason: v }))}
            testId="reject-reason"
            tip={`Что не так с парой именно для этого ролика — не короче ${MIN_REASON_CHARS} знаков`}
            hint={`${rej.reason.trim().length} из ${MIN_REASON_CHARS} знаков`}
          />
          <Check
            label="Отказ от ритма, а не только от пары"
            checked={rej.rhythm}
            onChange={(v) => setRej((x) => ({ ...x, rhythm: v }))}
            testId="reject-rhythm"
            tip="Замена не возьмёт ни одной пары с этим ритмом"
          />
          <WriteAction
            id="rot-reject"
            label="Проверить и отклонить…"
            title="Отклонить пару сценария?"
            description="Страж ротации вынес решение по отказу — план ничего не пишет."
            body={
              whyReject
                ? null
                : {
                    script_id: rej.script.trim(),
                    reason: rej.reason.trim(),
                    rejects_rhythm: rej.rhythm,
                    batch_id: rej.batch.trim() || null,
                  }
            }
            why={whyReject}
            tip="Фабрика покажет вердикт стража ротации; запись — после вашего «да»"
            confirmLabel="Записать отказ"
            plan={(b) => planRotationReject(channel, b)}
            act={(c) => rotationReject(channel, c)}
            view={(p) => <RejectPlan plan={p} />}
            onDone={setDone}
          />
        </Disclosure>
        <Disclosure
          id="rot-refuse"
          label="Отказаться: нет материала"
          tip="Закрыть назначение без замены: для ролика не хватает материала в пуле"
        >
          <Field
            label="Сценарий"
            value={ref.script}
            onChange={(v) => setRef((x) => ({ ...x, script: v }))}
            testId="refuse-script"
          />
          <Field
            label="Батч"
            value={ref.batch}
            onChange={(v) => setRef((x) => ({ ...x, batch: v }))}
            testId="refuse-batch"
            hint="Необязательно."
          />
          <Field
            label="Причина"
            rows={2}
            value={ref.reason}
            onChange={(v) => setRef((x) => ({ ...x, reason: v }))}
            testId="refuse-reason"
            hint={`${ref.reason.trim().length} из ${MIN_REASON_CHARS} знаков`}
          />
          <Field
            label="Файл дефицита"
            value={ref.deficit}
            onChange={(v) => setRef((x) => ({ ...x, deficit: v }))}
            testId="refuse-deficit"
            placeholder="pipeline/…/plan.assetless-rung.json"
            tip="Что планировщик не нашёл в пуле — его файл в батче, путь от корня фабрики"
            invalid={!!ref.deficit && !!deficitWhy(ref.deficit)}
          />
          <WriteAction
            id="rot-refuse"
            label="Проверить и отказаться…"
            title="Отказаться от назначения за нехваткой материала?"
            description="Фабрика проверила дефицит и назначение."
            body={
              whyRefuse
                ? null
                : {
                    script_id: ref.script.trim(),
                    reason: ref.reason.trim(),
                    deficit: ref.deficit.trim(),
                    batch_id: ref.batch.trim() || null,
                  }
            }
            why={whyRefuse}
            tip="Фабрика покажет, что закроется; запись — после вашего «да»"
            confirmLabel="Отказаться"
            plan={(b) => planRotationRefuse(channel, b)}
            act={(c) => rotationRefuse(channel, c)}
            view={(p) => <RefusePlan plan={p} />}
            onDone={setDone}
          />
        </Disclosure>
      </div>
      {done ? <RotationDone r={done} onClose={() => setDone(null)} /> : null}
    </div>
  );
}
