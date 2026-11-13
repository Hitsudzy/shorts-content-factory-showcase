// «Принять в банк…» (CC-0115 шаг 3 → CC-0114 API, `…/candidates/accept[/plan]`): кандидаты,
// которых «да» возьмёт сейчас (`accept.ready`), — галочка у каждого и ваш текст записи банка
// (описание, теги, заметки; пусто — фабрика возьмёт текст кандидата и попросит переписать на
// столе). План фабрики ничего не пишет: кого возьмёт и кого нет; «да» вы набираете сами — оно
// уходит фабрике как ваш ответ. Новые записи ждут разбора на столе. Id шаблонов — под «подробнее».
import { useState } from 'react';

import {
  memeAccept,
  memeAcceptProblemText,
  planMemeAccept,
  useAfterMemeAccept,
  type MemeAcceptPlan,
  type MemeAcceptResult,
  type MemeCandidates,
} from '@/api/memeCandidates';
import { listOf } from '@/api/publishWrites';
import { More } from '@/components/common/More';
import { plural } from '@/pages/batches/format';
import { Check, Disclosure, Done, Field, PlanHead, WriteAction } from '@/pages/publishing/Writes';

type Text = { description: string; tags: string; notes: string };
const EMPTY: Text = { description: '', tags: '', notes: '' };

const templates = (n: number) => `${n} ${plural(n, 'шаблон', 'шаблона', 'шаблонов')}`;

function AcceptPlanView({ plan, names }: { plan: MemeAcceptPlan; names: Map<string, string> }) {
  const name = (id: string) => names.get(id) ?? 'шаблон без имени';
  return (
    <>
      <PlanHead plan={plan} yes="можно принять" no="принять некого" />
      {plan.accept.length ? (
        <div className="grid gap-1" data-testid="accept-plan-take">
          <span className="text-muted-foreground">
            Возьмёт в банк ({templates(plan.accept.length)}):
          </span>
          <ul className="m-0 grid list-disc gap-0.5 pl-5">
            {plan.accept.map((id) => (
              <li key={id}>{name(id)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {plan.refused.length ? (
        <div className="grid gap-1" data-testid="accept-plan-refused">
          <span className="text-muted-foreground">Не возьмёт:</span>
          <ul className="m-0 grid list-disc gap-0.5 pl-5">
            {plan.refused.map((r) => (
              <li key={r.id}>
                {name(r.id)} — {r.text}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="m-0 text-xs text-muted-foreground">
        Ничего не скачивается: записи банка появятся сразу и будут ждать вашего разбора на столе.
      </p>
      <More className="mt-0">
        <span>
          {plan.action} · {plan.bank} · by {plan.by} · via {plan.via}
        </span>
        <span>возьмёт: {plan.accept.join(', ') || '—'}</span>
        {plan.answer.prompt ? <span>вопрос фабрики: {plan.answer.prompt}</span> : null}
        {plan.refused.map((r) => (
          <span key={r.id}>
            {r.id}: {r.reason}
          </span>
        ))}
        <span>список: {plan.fingerprint}</span>
        <span>отпечаток плана {plan.plan_fingerprint}</span>
      </More>
    </>
  );
}

export function AcceptCandidates({ d }: { d: MemeCandidates }) {
  const ready = d.accept.ready;
  const names = new Map(
    d.candidates.filter((c) => c.id).map((c) => [c.id!, c.name ?? 'шаблон без имени']),
  );
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [text, setText] = useState<Record<string, Text>>({});
  const [done, setDone] = useState<MemeAcceptResult | null>(null);
  const after = useAfterMemeAccept(d.channel);
  const ids = ready.filter((id) => picked[id] !== false);
  const details = Object.fromEntries(
    ids
      .map((id) => [id, text[id] ?? EMPTY] as const)
      .filter(([, t]) => t.description.trim() || t.tags.trim() || t.notes.trim())
      .map(([id, t]) => [
        id,
        {
          description: t.description.trim() || null,
          tags: t.tags.trim() ? listOf(t.tags) : null,
          notes: t.notes.trim() || null,
        },
      ]),
  );
  const set = (id: string, k: keyof Text, v: string) =>
    setText((s) => ({ ...s, [id]: { ...(s[id] ?? EMPTY), [k]: v } }));
  if (!ready.length && !done) return null;
  return (
    <div className="grid gap-2" data-testid="meme-accept">
      {done ? (
        <Done
          tone="ok"
          testId="meme-accept-done"
          title={`Принято в банк: ${templates(done.accepted.length)}`}
          onClose={() => setDone(null)}
        >
          <span>Записи ждут вашего разбора на столе мемов.</span>
          <More className="mt-0">
            <span>{done.accepted.join(', ')}</span>
            {done.embedding && typeof done.embedding.line === 'string' ? (
              <span>{done.embedding.line}</span>
            ) : null}
          </More>
        </Done>
      ) : null}
      {ready.length ? (
        <Disclosure
          id="meme-accept"
          label="Принять в банк…"
          tip="Фабрика сначала покажет, кого возьмёт; примет — после вашего «да»"
        >
          <ul className="m-0 grid list-none gap-3 p-0">
            {ready.map((id) => {
              const on = picked[id] !== false;
              const t = text[id] ?? EMPTY;
              return (
                <li key={id} className="grid gap-1.5" data-testid="meme-accept-item" data-id={id}>
                  <Check
                    label={names.get(id) ?? 'шаблон без имени'}
                    checked={on}
                    onChange={(v) => setPicked((s) => ({ ...s, [id]: v }))}
                    testId="meme-accept-pick"
                  />
                  {on ? (
                    <div className="grid gap-1.5 pl-6">
                      <Field
                        label="Описание (по желанию)"
                        value={t.description}
                        onChange={(v) => set(id, 'description', v)}
                        testId="meme-accept-description"
                        placeholder="Что значит мем, когда он к месту"
                      />
                      <Field
                        label="Теги через запятую, по-английски (по желанию)"
                        value={t.tags}
                        onChange={(v) => set(id, 'tags', v)}
                        testId="meme-accept-tags"
                        placeholder="calm, disaster, irony"
                      />
                      <Field
                        label="Заметки (по желанию)"
                        value={t.notes}
                        onChange={(v) => set(id, 'notes', v)}
                        testId="meme-accept-notes"
                      />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
          <div>
            <WriteAction
              id="meme-accept"
              label="Показать план…"
              title="Принять кандидатов в банк мемов?"
              description="Фабрика проверила, кого возьмёт в банк."
              body={
                ids.length ? { ids, details: Object.keys(details).length ? details : null } : null
              }
              why={ids.length ? null : 'Отметьте хотя бы один шаблон'}
              tip="Фабрика покажет план; примет — после вашего «да»"
              confirmLabel="Принять"
              pendingLabel="Принимаю…"
              yes
              plan={(b) => planMemeAccept(d.channel, b)}
              act={(c, typed) => memeAccept(d.channel, c, typed)}
              view={(p) => <AcceptPlanView plan={p} names={names} />}
              problemText={memeAcceptProblemText}
              onSettled={after}
              onDone={(r) => {
                setPicked({});
                setText({});
                setDone(r);
              }}
            />
          </div>
        </Disclosure>
      ) : null}
    </div>
  );
}
