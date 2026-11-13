// «Правил в Studio» и отмена (CC-0115 шаг 3 → CC-0106 API, `…/studio/edited[/plan]`,
// `…/edited/undo[/plan]`): вы поправили поле ролика в Studio руками — отметка на строке журнала
// загрузок, серия «без ручных правок» начинается заново; отметка ошиблась — снять её. План —
// сухой прогон фабрики (строка до и после, серия после); «да» вы набираете сами. Какой ролик —
// последний из серии или по ссылке из Studio; slug и id ролика — под «подробнее».
import { useState } from 'react';

import type { StudioStreak } from '@/api/publish';
import {
  editedWhy,
  planStudioEdited,
  studioEdited,
  videoIdOf,
  type StudioEditedPlan,
  type StudioEditedPlanIn,
  type StudioEditedResult,
} from '@/api/publishWrites';
import { readableSlug } from '@/api/videos';
import { More } from '@/components/common/More';
import { dateTimeMsk } from '@/pages/batches/format';

import { Disclosure, Done, Field, PlanHead, WriteAction } from './Writes';

type Which = 'last' | 'link';

const titleOf = (row: Record<string, unknown> | null | undefined): string | null => {
  const t = row?.title;
  return typeof t === 'string' && t.trim() ? t.trim() : null;
};

function EditedPlanView({ plan }: { plan: StudioEditedPlan }) {
  // Строка журнала загрузок названия не хранит: без него — имя ролика словами (как `videoTitle`).
  const title =
    titleOf(plan.before) ?? titleOf(plan.row) ?? (plan.slug ? readableSlug(plan.slug) : null);
  const when = plan.before?.publish_at;
  return (
    <>
      <PlanHead
        plan={{ ...plan, why: editedWhy(plan.why) }}
        yes={plan.edited ? 'можно отметить' : 'можно снять'}
        no={plan.edited ? 'отметить нельзя' : 'снять нельзя'}
      />
      {plan.ok ? (
        <p className="m-0" data-testid="edited-plan-video">
          {title ? `Ролик: «${title}»` : 'Запись журнала: ролик, загруженный через Studio'}
          {typeof when === 'string' && dateTimeMsk(when) ? `, публикация ${dateTimeMsk(when)}` : ''}
        </p>
      ) : null}
      {plan.ok && plan.note ? (
        <p className="m-0" data-testid="edited-plan-note">
          Заметка: {plan.note}
        </p>
      ) : null}
      {plan.streak ? (
        <p className="m-0" data-testid="edited-plan-streak">
          Подряд без правок станет: {plan.streak.streak} из {plan.streak.goal}
        </p>
      ) : null}
      <p className="m-0 text-xs text-muted-foreground">
        {plan.edited
          ? 'Серия роликов без ручных правок начнётся заново — с роликов, загруженных после этого.'
          : 'Отметка о ручной правке снимется, заметка к ней — тоже; серия пересчитается.'}
      </p>
      <More className="mt-0">
        <span>
          {plan.action} · by {plan.by} · via {plan.via}
        </span>
        <span>
          ролик: {plan.slug ?? '—'} ({plan.video_id ?? '—'})
        </span>
        {plan.why && editedWhy(plan.why) !== plan.why ? <span>{plan.why}</span> : null}
        <span>журнал: {plan.journal}</span>
        <span>отпечаток плана {plan.fingerprint}</span>
      </More>
    </>
  );
}

const PLAN_TEXT = {
  description: 'Фабрика проверила, какую строку журнала загрузок это изменит.',
  tip: 'Фабрика покажет план; запишет — после вашего «да»',
};

export function StudioEdited({ channel, streak }: { channel: string; streak: StudioStreak }) {
  const last = streak.run.at(-1) ?? null;
  const [pick, setPick] = useState<Which>(last ? 'last' : 'link');
  const [link, setLink] = useState('');
  const [note, setNote] = useState('');
  const [done, setDone] = useState<StudioEditedResult | null>(null);
  const choice: Which = last ? pick : 'link';
  const vid = videoIdOf(link);
  const note_ = note.trim() || null;
  const body: StudioEditedPlanIn | null =
    choice === 'last' && last
      ? { slug: last, note: note_ }
      : vid
        ? { video_id: vid, note: note_ }
        : null;
  const why =
    body || choice === 'last'
      ? null
      : link.trim()
        ? 'Ссылка не похожа на ролик YouTube — вставьте её из Studio'
        : 'Вставьте ссылку на ролик из Studio';
  const le = streak.last_edited;
  const leVid = typeof le?.video_id === 'string' ? le.video_id : null;
  const leSlug = typeof le?.slug === 'string' ? le.slug : null;
  const undoBody: StudioEditedPlanIn | null = leVid
    ? { video_id: leVid }
    : leSlug
      ? { slug: leSlug }
      : null;
  return (
    <div className="grid gap-2" data-testid="studio-edited">
      {done ? (
        <Done
          tone="ok"
          testId="studio-edited-done"
          title={done.edited ? 'Правка в Studio отмечена' : 'Отметка о правке снята'}
          onClose={() => setDone(null)}
        >
          <span>
            Подряд без правок: {done.streak.streak} из {done.streak.goal}
          </span>
        </Done>
      ) : null}
      <div className="flex flex-wrap items-start gap-2">
        <Disclosure
          id="studio-edited"
          label="Я правил ролик в Studio…"
          tip="Если вы поправили название, описание или теги в Studio руками — отметьте это: серия без правок начнётся заново"
        >
          {last ? (
            <fieldset className="m-0 grid gap-1 border-0 p-0" data-testid="studio-edited-pick">
              <legend className="mb-1 text-xs text-muted-foreground">Какой ролик</legend>
              <label className="flex items-baseline gap-2">
                <input
                  type="radio"
                  name={`studio-edited-${channel}`}
                  checked={choice === 'last'}
                  onChange={() => setPick('last')}
                  data-testid="studio-edited-last"
                />
                <span>Последний загруженный через Studio</span>
              </label>
              <label className="flex items-baseline gap-2">
                <input
                  type="radio"
                  name={`studio-edited-${channel}`}
                  checked={choice === 'link'}
                  onChange={() => setPick('link')}
                  data-testid="studio-edited-other"
                />
                <span>Другой — по ссылке из Studio</span>
              </label>
            </fieldset>
          ) : null}
          {choice === 'link' ? (
            <Field
              label="Ссылка на ролик или его id в Studio"
              value={link}
              onChange={setLink}
              testId="studio-edited-link"
              placeholder="https://youtube.com/shorts/…"
              invalid={!!link.trim() && !vid}
            />
          ) : null}
          <Field
            label="Что поправили (по желанию)"
            value={note}
            onChange={setNote}
            testId="studio-edited-note"
            placeholder="Например: поправил тег"
          />
          <div>
            <WriteAction
              id="studio-edited"
              label="Показать план…"
              title="Отметить ручную правку в Studio?"
              description={PLAN_TEXT.description}
              body={body}
              why={why}
              tip={PLAN_TEXT.tip}
              confirmLabel="Отметить"
              pendingLabel="Записываю…"
              yes
              plan={(b) => planStudioEdited(channel, b)}
              act={(c) => studioEdited(channel, c)}
              view={(p) => <EditedPlanView plan={p} />}
              onDone={(r) => {
                setLink('');
                setNote('');
                setDone(r);
              }}
            />
          </div>
        </Disclosure>
        {undoBody ? (
          <WriteAction
            id="studio-unedit"
            label="Снять отметку…"
            title="Снять отметку о ручной правке?"
            description={PLAN_TEXT.description}
            body={undoBody}
            tip="Если отметка о правке ошибочна — снимите её; фабрика сначала покажет план"
            confirmLabel="Снять отметку"
            pendingLabel="Снимаю…"
            triggerVariant="outline"
            yes
            plan={(b) => planStudioEdited(channel, b, true)}
            act={(c) => studioEdited(channel, c, true)}
            view={(p) => <EditedPlanView plan={p} />}
            onDone={setDone}
          />
        ) : null}
      </div>
    </div>
  );
}
